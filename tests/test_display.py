from __future__ import annotations

import io
import re
import sys
from types import SimpleNamespace
from typing import Literal, Optional

import pytest
from rich.console import Console

from tallyman.aggregator import TallyResult, aggregate, bar_segments
from tallyman.counter import FileCount
from tallyman.display import BAR_WIDTH, BLOCK_CHAR, _bar_text, _can_encode_unicode, display_results
from tallyman.languages import EXTENSION_MAP, as_spec
from tallyman.walker import WalkStats


def _render(directory: str) -> str:
    out = io.StringIO()
    tally = aggregate([(EXTENSION_MAP['.py'], FileCount(total_lines=1, code_lines=1))])
    display_results(tally, directory, console=Console(file=out, no_color=True, width=100))
    return out.getvalue()


class TestHeader:
    def test_directory_name_is_printed_literally(self) -> None:
        """H9: '[bold]' in a name was read as markup and vanished."""
        assert '\nmy[bold]proj\n' in _render('my[bold]proj')
        assert '\nproj[/red]\n' in _render('proj[/red]')

    def test_emoji_codes_are_not_substituted(self) -> None:
        assert '\nproj:rocket:\n' in _render('proj:rocket:')

    def test_control_characters_are_replaced(self) -> None:
        out = _render('a\x1b[31mb\nc')
        assert '\x1b' not in out
        assert '\na?[31mb?c\n' in out


def _render_tally(entries: list[tuple[str, FileCount]], with_spaces: bool = False) -> str:
    out = io.StringIO()
    tally = aggregate([(EXTENSION_MAP[ext], counts) for ext, counts in entries])
    display_results(tally, 'proj', with_spaces=with_spaces, console=Console(file=out, no_color=True, width=100))
    return out.getvalue()


def _section(out: str, language: str) -> list[str]:
    """The two count lines under a language's header, with alignment spaces collapsed."""
    lines = out.splitlines()
    header = next(i for i, line in enumerate(lines) if f'  {language}  ' in line)
    return [' '.join(line.split()) for line in lines[header + 1 : header + 3]]


class TestBody:
    def test_no_files(self) -> None:
        out = io.StringIO()
        display_results(aggregate([]), 'proj', console=Console(file=out, no_color=True, width=100))
        assert 'No recognized source files found.' in out.getvalue()

    def test_wording_depends_on_comment_detection(self) -> None:
        out = _render_tally(
            [
                ('.py', FileCount(total_lines=3, code_lines=1, comment_lines=1, blank_lines=1)),
                ('.json', FileCount(total_lines=2, code_lines=1, blank_lines=1)),
            ]
        )
        assert _section(out, 'Python') == ['3 lines of code', '1 excluding comments and blank lines']  # has '#'
        assert _section(out, 'JSON') == ['2 lines', '1 excluding blank lines']  # no comment marker

    def test_same_language_in_two_categories_is_labelled(self) -> None:
        md = EXTENSION_MAP['.md']
        out = io.StringIO()
        tally = aggregate(
            [(md, FileCount(total_lines=2, code_lines=2)), (as_spec(md), FileCount(total_lines=3, code_lines=3))]
        )
        display_results(tally, 'proj', console=Console(file=out, no_color=True, width=100))
        assert 'Markdown (docs)' in out.getvalue()
        assert 'Markdown (specs)' in out.getvalue()
        coloured = _render_coloured(tally, '256')
        assert '\x1b[38;5;177mMarkdown (specs)' in coloured  # the spec colour, violet
        assert '\x1b[37mMarkdown (docs)' in coloured

    def test_more_than_three_languages_in_a_category_ends_with_etc(self) -> None:
        entries = [(ext, FileCount(total_lines=10, code_lines=10)) for ext in ('.py', '.rs', '.go', '.java')]
        assert '(Python + Rust + Go, etc)' in _render_tally(entries)  # the first three, by size

    def test_with_spaces_switches_categories_combined_and_bar(self) -> None:
        entries = [
            ('.py', FileCount(total_lines=10, code_lines=4, comment_lines=3, blank_lines=3)),
            ('.json', FileCount(total_lines=10, code_lines=10)),
        ]
        effective, total = _render_tally(entries), _render_tally(entries, with_spaces=True)
        flat_effective, flat_total = ' '.join(effective.split()), ' '.join(total.split())
        assert 'Code: 4 lines (Python)' in flat_effective
        assert 'Code: 10 lines (Python)' in flat_total
        assert 'Combined: 14 lines' in flat_effective
        assert 'Combined: 20 lines' in flat_total
        assert 'JSON 71%' in effective.splitlines()[-1]  # 10 of 14 effective lines
        assert 'JSON 50%' in total.splitlines()[-1]  # 10 of 20 total lines


class TestPercentageBar:
    @pytest.mark.parametrize(
        'sizes',
        [
            [100],
            [50, 50],
            [70, 20, 10],
            [97, 1, 1, 1],  # three tiny languages grouped as Other
            [34, 33, 33],
            [10] * 10,
            [16, 14, 14, 14, 14, 14, 14],  # rounding gives 58 cells: the last segment takes the remainder
            [1] * 17,  # each rounds up to 4 cells, so the first 16 already need 64: segments must be clamped
        ],
    )
    def test_bar_is_exactly_bar_width(self, sizes: list[int]) -> None:
        exts = ['.py', '.rs', '.go', '.java', '.c', '.cpp', '.cs', '.rb', '.lua', '.php', '.swift', '.kt', '.dart']
        exts += ['.scala', '.zig', '.hs', '.erl']
        entries = [(exts[i], FileCount(total_lines=n, code_lines=n)) for i, n in enumerate(sizes)]
        bar_lines = [line for line in _render_tally(entries).splitlines() if BLOCK_CHAR in line]
        assert len(bar_lines) == 1
        assert bar_lines[0].strip().count(BLOCK_CHAR) == BAR_WIDTH

    def test_small_languages_are_grouped_as_other(self) -> None:
        entries = [
            ('.py', FileCount(total_lines=97, code_lines=97)),
            ('.rs', FileCount(total_lines=1, code_lines=1)),
            ('.go', FileCount(total_lines=2, code_lines=1)),
        ]
        out = _render_tally(entries)
        legend = out.splitlines()[-1]
        assert 'Other' in legend
        assert 'Rust' not in legend
        assert 'Go' not in legend

    def test_no_effective_lines_prints_no_bar(self) -> None:
        """Bug 6: a file that is all comments printed a blank line, an empty bar and an empty legend."""
        out = _render_tally([('.py', FileCount(total_lines=3, comment_lines=3))])
        assert BLOCK_CHAR not in out
        lines = out.splitlines()
        combined = next(i for i, line in enumerate(lines) if 'Combined:' in line)
        assert ' '.join(lines[combined].split()) == 'Combined: 0 lines'
        assert lines[combined + 1 :] == []
        assert out.endswith('lines\n')

    def test_with_spaces_draws_the_bar_when_no_lines_are_effective(self) -> None:
        out = _render_tally([('.py', FileCount(total_lines=3, comment_lines=3))], with_spaces=True)
        assert len([line for line in out.splitlines() if BLOCK_CHAR in line]) == 1
        assert out.splitlines()[-1].strip() == 'Python 100%'

    def test_every_segment_gets_a_cell(self) -> None:
        """Bug 7: Go's 0.8% rounded the first two segments to 30 cells each and left Other none."""
        tally = aggregate(
            [
                (EXTENSION_MAP['.py'], FileCount(total_lines=496, code_lines=496)),
                (EXTENSION_MAP['.rs'], FileCount(total_lines=496, code_lines=496)),
                (EXTENSION_MAP['.go'], FileCount(total_lines=8, code_lines=8)),
            ]
        )
        segments = bar_segments(tally)
        bar = _bar_text(segments)
        assert len(bar) == BAR_WIDTH
        assert len(bar.spans) == len(segments) == 3
        assert all(span.end - span.start >= 1 for span in bar.spans)
        assert [span.style for span in bar.spans] == [s.color for s in segments]
        assert [span.end - span.start for span in bar.spans] == [30, 29, 1]

    def test_tiny_other_reads_under_one_percent(self) -> None:
        entries = [
            ('.py', FileCount(total_lines=2000, code_lines=2000)),
            ('.go', FileCount(total_lines=1, code_lines=1)),
        ]
        assert _render_tally(entries).splitlines()[-1].endswith('Other <1%')


_ColorSystem = Literal['standard', '256', 'truecolor']
_COLOR_SYSTEMS: list[_ColorSystem] = ['standard', '256', 'truecolor']


def _render_coloured(tally: TallyResult, color_system: _ColorSystem) -> str:
    """Render to a colour terminal, with display.py's own highlight=False."""
    out = io.StringIO()
    console = Console(
        file=out, force_terminal=True, color_system=color_system, no_color=False, highlight=False, width=100
    )
    display_results(tally, 'proj', console=console)
    return out.getvalue()


def _bar_runs(tally: TallyResult, color_system: _ColorSystem) -> list[str]:
    """The SGR code of each colour run in the bar. Rich merges neighbouring runs with the same style,
    so two segments in one colour show up as one run."""
    (line,) = [line for line in _render_coloured(tally, color_system).splitlines() if BLOCK_CHAR in line]
    return re.findall(r'\x1b\[([0-9;]+)m' + re.escape(BLOCK_CHAR), line)


class TestBarColours:
    @pytest.mark.parametrize('color_system', _COLOR_SYSTEMS)
    def test_spec_and_docs_segments_stay_apart(self, color_system: _ColorSystem) -> None:
        """Markdown (specs) copied the docs colour, so the two drew as one white block."""
        md = EXTENSION_MAP['.md']
        tally = aggregate(
            [(md, FileCount(total_lines=50, code_lines=50)), (as_spec(md), FileCount(total_lines=40, code_lines=40))]
        )
        runs = _bar_runs(tally, color_system)
        assert len(runs) == 2
        assert runs[0] != runs[1]

    @pytest.mark.parametrize('color_system', _COLOR_SYSTEMS)
    def test_other_stays_apart_from_its_neighbour(self, color_system: _ColorSystem) -> None:
        """Other was grey50, TOML's colour, so a TOML segment and Other merged into one run."""
        entries = [
            (EXTENSION_MAP['.py'], FileCount(total_lines=93, code_lines=93)),
            (EXTENSION_MAP['.toml'], FileCount(total_lines=6, code_lines=6)),
            (EXTENSION_MAP['.json'], FileCount(total_lines=1, code_lines=1)),  # under the cut-off: Other
        ]
        runs = _bar_runs(aggregate(entries), color_system)
        assert len(runs) == 3
        assert all(a != b for a, b in zip(runs, runs[1:]))


def _render_with_stats(stats: Optional[WalkStats], files: bool = True) -> str:
    out = io.StringIO()
    entries = [(EXTENSION_MAP['.py'], FileCount(total_lines=1, code_lines=1))] if files else []
    display_results(aggregate(entries), 'proj', console=Console(file=out, no_color=True, width=100), stats=stats)
    return out.getvalue()


class TestPatternNote:
    @pytest.mark.parametrize('stats', [None, WalkStats()])
    def test_nothing_removed_prints_nothing(self, stats: Optional[WalkStats]) -> None:
        assert 'Excluded by' not in _render_with_stats(stats)

    @pytest.mark.parametrize(
        ('stats', 'line'),
        [
            (WalkStats(12, 1), 'Excluded by [exclude] patterns: 12 files, 1 directory'),
            (WalkStats(1, 0), 'Excluded by [exclude] patterns: 1 file'),
            (WalkStats(0, 2), 'Excluded by [exclude] patterns: 2 directories'),
            (WalkStats(1234, 0), 'Excluded by [exclude] patterns: 1,234 files'),
        ],
    )
    def test_wording(self, stats: WalkStats, line: str) -> None:
        """The literal '[exclude]' must survive: printed as markup, Rich would swallow it."""
        out = _render_with_stats(stats)
        assert f'\n  {line}\n' in out
        assert out.rstrip().endswith(line)  # the last line of the report

    def test_printed_even_when_nothing_was_counted(self) -> None:
        out = _render_with_stats(WalkStats(3, 0), files=False)
        assert 'No recognized source files found.' in out
        assert 'Excluded by [exclude] patterns: 3 files' in out


def _render_rust(test_lines: int, test_files: int, stats: Optional[WalkStats] = None, files: bool = True) -> str:
    out = io.StringIO()
    entries = [(EXTENSION_MAP['.rs'], FileCount(total_lines=4, code_lines=4))] if files else []
    tally = aggregate(entries)
    tally.rust_test_lines, tally.rust_test_files = test_lines, test_files
    display_results(tally, 'proj', console=Console(file=out, no_color=True, width=100), stats=stats)
    return out.getvalue()


class TestRustTestNote:
    """[rust] exclude_test_modules (issue #8): what the report says it left out."""

    def test_nothing_left_out_prints_nothing(self) -> None:
        assert 'Rust test code' not in _render_rust(0, 0)

    @pytest.mark.parametrize(
        ('lines', 'files', 'line'),
        [
            (1, 1, 'Excluded Rust test code: 1 line in 1 file'),
            (2412, 37, 'Excluded Rust test code: 2,412 lines in 37 files'),
            (7, 1, 'Excluded Rust test code: 7 lines in 1 file'),
        ],
    )
    def test_wording(self, lines: int, files: int, line: str) -> None:
        out = _render_rust(lines, files)
        assert f'\n\n  {line}\n' in out  # one blank line above it
        assert out.rstrip().endswith(line)

    def test_after_the_pattern_note_under_one_blank_line(self) -> None:
        out = _render_rust(7, 1, stats=WalkStats(12, 1))
        expected = (
            '\n\n  Excluded by [exclude] patterns: 12 files, 1 directory\n'
            '  Excluded Rust test code: 7 lines in 1 file\n'
        )
        assert out.endswith(expected)

    def test_printed_even_when_nothing_was_counted(self) -> None:
        """A crate of only #![cfg(test)] files counts nothing; the note says why."""
        out = _render_rust(5, 1, files=False)
        assert 'No recognized source files found.' in out
        assert out.rstrip().endswith('Excluded Rust test code: 5 lines in 1 file')


class TestUnicodeProbe:
    @pytest.mark.parametrize(
        ('encoding', 'expected'),
        [('utf-8', True), ('cp1252', False), ('ascii', False), ('cp852', False)],
        ids=['utf-8', 'cp1252 has no box drawing', 'ascii', 'cp852 has no middle dot'],
    )
    def test_unicode_probe(self, monkeypatch: pytest.MonkeyPatch, encoding: str, expected: bool) -> None:
        """Every non-ASCII character the report prints must encode, or the whole report goes ASCII."""
        monkeypatch.setattr(sys, 'stdout', SimpleNamespace(encoding=encoding))
        assert _can_encode_unicode() is expected
