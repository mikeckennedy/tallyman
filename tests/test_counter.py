from pathlib import Path

from tallyman.counter import FileCount, count_lines
from tallyman.languages import Language


def _lang(comment: str | None = '#') -> Language:
    """Helper to build a test language."""
    return Language('Test', 'code', 'white', comment, ('.test',))


class TestCountLines:
    def test_python_style_comments(self, tmp_path: Path):
        f = tmp_path / 'example.py'
        f.write_text('# comment\ncode = 1\n\nmore_code = 2\n# another comment\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 5
        assert result.comment_lines == 2
        assert result.blank_lines == 1
        assert result.code_lines == 2

    def test_slash_comments(self, tmp_path: Path):
        f = tmp_path / 'example.js'
        f.write_text('// comment\nlet x = 1;\n\n// another\n')
        result = count_lines(f, _lang('//'))
        assert result.total_lines == 4
        assert result.comment_lines == 2
        assert result.blank_lines == 1
        assert result.code_lines == 1

    def test_dash_comments(self, tmp_path: Path):
        f = tmp_path / 'example.lua'
        f.write_text('-- comment\nprint("hi")\n')
        result = count_lines(f, _lang('--'))
        assert result.total_lines == 2
        assert result.comment_lines == 1
        assert result.code_lines == 1

    def test_no_comment_detection(self, tmp_path: Path):
        f = tmp_path / 'example.html'
        f.write_text('<!-- comment -->\n<p>text</p>\n\n')
        result = count_lines(f, _lang(None))
        assert result.total_lines == 3
        assert result.comment_lines == 0  # No detection for this language
        assert result.blank_lines == 1
        assert result.code_lines == 2

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / 'empty.py'
        f.write_text('')
        result = count_lines(f, _lang('#'))
        assert result == FileCount(0, 0, 0, 0)

    def test_only_blank_lines(self, tmp_path: Path):
        f = tmp_path / 'blanks.py'
        f.write_text('\n\n\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 3
        assert result.blank_lines == 3
        assert result.code_lines == 0

    def test_indented_comment(self, tmp_path: Path):
        f = tmp_path / 'indented.py'
        f.write_text('    # indented comment\n    code()\n')
        result = count_lines(f, _lang('#'))
        assert result.comment_lines == 1
        assert result.code_lines == 1

    def test_nonexistent_file(self, tmp_path: Path):
        f = tmp_path / 'nope.py'
        result = count_lines(f, _lang('#'))
        assert result == FileCount(0, 0, 0, 0)

    def test_encoding_errors_handled(self, tmp_path: Path):
        f = tmp_path / 'bad.py'
        f.write_bytes(b'hello\nworld\xff\n')
        result = count_lines(f, _lang('#'))
        assert result.total_lines == 2
        assert result.code_lines == 2
