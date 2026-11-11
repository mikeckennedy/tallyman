from __future__ import annotations

import codecs
from pathlib import Path
from typing import Optional

import pytest

from tallyman.counter import FileCount, count_lines
from tallyman.languages import RUST, Language, identify_language


def _lang(comment: Optional[str] = '#') -> Language:
    """Helper to build a test language."""
    return Language('Test', 'code', 'white', comment, ('.test',))


class TestCountLines:
    def test_python_style_comments(self, tmp_path: Path) -> None:
        f = tmp_path / 'example.py'
        f.write_text('# comment\ncode = 1\n\nmore_code = 2\n# another comment\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 5
        assert result.comment_lines == 2
        assert result.blank_lines == 1
        assert result.code_lines == 2

    def test_slash_comments(self, tmp_path: Path) -> None:
        f = tmp_path / 'example.js'
        f.write_text('// comment\nlet x = 1;\n\n// another\n')
        result = count_lines(f, _lang('//'))
        assert result.total_lines == 4
        assert result.comment_lines == 2
        assert result.blank_lines == 1
        assert result.code_lines == 1

    def test_solidity_style_comments(self, tmp_path: Path) -> None:
        f = tmp_path / 'Token.sol'
        f.write_text('// SPDX-License-Identifier: MIT\ncontract Token {\n    // storage\n    uint256 totalSupply;\n}\n')
        result = count_lines(f, _lang('//'))
        assert result.total_lines == 5
        assert result.comment_lines == 2
        assert result.blank_lines == 0
        assert result.code_lines == 3

    def test_dash_comments(self, tmp_path: Path) -> None:
        f = tmp_path / 'example.lua'
        f.write_text('-- comment\nprint("hi")\n')
        result = count_lines(f, _lang('--'))
        assert result.total_lines == 2
        assert result.comment_lines == 1
        assert result.code_lines == 1

    def test_no_comment_detection(self, tmp_path: Path) -> None:
        f = tmp_path / 'example.html'
        f.write_text('<!-- comment -->\n<p>text</p>\n\n')
        result = count_lines(f, _lang(None))
        assert result.total_lines == 3
        assert result.comment_lines == 0  # No detection for this language
        assert result.blank_lines == 1
        assert result.code_lines == 2

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / 'empty.py'
        f.write_text('')
        result = count_lines(f, _lang('#'))
        assert result == FileCount(0, 0, 0, 0)

    def test_only_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / 'blanks.py'
        f.write_text('\n\n\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 3
        assert result.blank_lines == 3
        assert result.code_lines == 0

    def test_indented_comment(self, tmp_path: Path) -> None:
        f = tmp_path / 'indented.py'
        f.write_text('    # indented comment\n    code()\n')
        result = count_lines(f, _lang('#'))
        assert result.comment_lines == 1
        assert result.code_lines == 1

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / 'nope.py'
        result = count_lines(f, _lang('#'))
        assert result == FileCount(0, 0, 0, 0)

    def test_encoding_errors_handled(self, tmp_path: Path) -> None:
        f = tmp_path / 'bad.py'
        f.write_bytes(b'hello\nworld\xff\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 2
        assert result.code_lines == 2


class TestLineEndingsAndEncodings:
    @pytest.mark.parametrize(
        ('data', 'total', 'blank'),
        [
            (b'', 0, 0),
            (b'\n', 1, 1),
            (b'a = 1', 1, 0),  # a last line without a newline still counts
            (b'a = 1\nb = 2\n', 2, 0),
            (b'a = 1\r\nb = 2\r\n', 2, 0),
            (b'a = 1\rb = 2\r', 2, 0),  # old Mac line endings
            (b'a = 1\n\x0c\nb = 2\n', 3, 1),  # a form feed is not a line break (wc -l says 3)
            (b'a = 1\x0bb = 2\x1cc\n', 1, 0),  # nor are vertical tab and file separator
            (b'a = 1\n\xe2\x80\xa8b\n', 2, 0),  # nor U+2028 LINE SEPARATOR
            (b'a\r\nb\rc\nd', 4, 0),  # mixed endings, last line unterminated
            (b'a\r\r\nb\n', 3, 1),  # CR then CRLF: an empty line between, as editors show it
            (b'\xef\xbb\xbf', 0, 0),  # a BOM and nothing else
            (b'caf\xe9 = 1\n', 1, 0),  # Latin-1 bytes are replaced, not fatal
            (b'\xff\xfea\x00\n\x00b', 2, 0),  # UTF-16 with an odd byte count
        ],
    )
    def test_only_real_line_breaks_split_lines(self, tmp_path: Path, data: bytes, total: int, blank: int) -> None:
        f = tmp_path / 'x.py'
        f.write_bytes(data)
        result = count_lines(f, _lang('#'))
        assert (result.total_lines, result.blank_lines) == (total, blank)

    def test_utf8_bom_does_not_hide_a_first_line_comment(self, tmp_path: Path) -> None:
        f = tmp_path / 'bom.py'
        f.write_bytes(b'\xef\xbb\xbf# comment\nx = 1\n')
        assert count_lines(f, _lang('#')) == FileCount(total_lines=2, code_lines=1, comment_lines=1)

    @pytest.mark.parametrize('encoding', ['utf-16', 'utf-16-be', 'utf-32', 'utf-32-be'])
    def test_wide_encodings_with_a_bom(self, tmp_path: Path, encoding: str) -> None:
        f = tmp_path / 'wide.sql'
        text = '-- comment\nselect 1;\n\n'
        data = text.encode(encoding)
        if encoding.endswith('-be'):
            data = (b'\xfe\xff' if encoding == 'utf-16-be' else b'\x00\x00\xfe\xff') + data  # -be codecs write no BOM
        f.write_bytes(data)
        assert count_lines(f, _lang('--')) == FileCount(total_lines=3, code_lines=1, comment_lines=1, blank_lines=1)


# RUST_LIB: 4 lines of code and a blank, then a 7-line test module
RUST_LIB = (
    'pub fn a() -> u8 {\n'
    '    1\n'
    '}\n'
    '\n'
    '#[cfg(test)]\n'
    'mod tests {\n'
    '    #[test]\n'
    '    fn t() {\n'
    '        assert_eq!(super::a(), 1);\n'
    '    }\n'
    '}\n'
)


class TestRustTestCode:
    """[rust] exclude_test_modules (issue #8)."""

    def test_flag_leaves_the_test_module_out(self, tmp_path: Path) -> None:
        f = tmp_path / 'lib.rs'
        f.write_text(RUST_LIB)
        result = count_lines(f, RUST, exclude_rust_tests=True)
        assert result == FileCount(total_lines=4, code_lines=3, comment_lines=0, blank_lines=1, test_lines=7)

    def test_without_the_flag_nothing_changes(self, tmp_path: Path) -> None:
        f = tmp_path / 'lib.rs'
        f.write_text(RUST_LIB)
        assert count_lines(f, RUST) == FileCount(total_lines=11, code_lines=10, comment_lines=0, blank_lines=1)

    @pytest.mark.parametrize('newline', ['\r\n', '\r'])
    def test_line_endings(self, tmp_path: Path, newline: str) -> None:
        f = tmp_path / 'lib.rs'
        f.write_bytes(RUST_LIB.replace('\n', newline).encode())
        result = count_lines(f, RUST, exclude_rust_tests=True)
        assert result == FileCount(total_lines=4, code_lines=3, comment_lines=0, blank_lines=1, test_lines=7)

    def test_byte_order_mark(self, tmp_path: Path) -> None:
        f = tmp_path / 'lib.rs'
        f.write_bytes(codecs.BOM_UTF8 + b'#![cfg(test)]\nfn t() {}\n')
        assert count_lines(f, RUST, exclude_rust_tests=True) == FileCount(test_lines=2)

    def test_only_rust_is_scanned(self, tmp_path: Path) -> None:
        f = tmp_path / 'lib.go'  # another '//' language, holding the same text
        f.write_text(RUST_LIB)
        go = identify_language(f)
        assert go is not None and go.name == 'Go'
        assert count_lines(f, go, exclude_rust_tests=True).test_lines == 0
