from __future__ import annotations

import io
from typing import Optional

import pytest
from rich.console import Console

from tallyman.aggregator import aggregate
from tallyman.counter import FileCount
from tallyman.display import BAR_WIDTH, BLOCK_CHAR, display_results
from tallyman.languages import EXTENSION_MAP, as_spec
from tallyman.walker import WalkStats


def _render(directory: str) -> str:
    out = io.StringIO()
    tally = aggregate([(EXTENSION_MAP['.py'], FileCount(total_lines=1, code_lines=1))])
    display_results(tally, directory, console=Console(file=out, no_color=True, width=100))
    return out.getvalue()


class TestHeader:
    def test_directory_name_is_printed_literally(self):
        """H9: '[bold]' in a name was read as markup and vanished."""
        assert '\nmy[bold]proj\n' in _render('my[bold]proj')
        assert '\nproj[/red]\n' in _render('proj[/red]')

    def test_emoji_codes_are_not_substituted(self):
        assert '\nproj:rocket:\n' in _render('proj:rocket:')

    def test_control_characters_are_replaced(self):
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
    def test_no_files(self):
        out = io.StringIO()
        display_results(aggregate([]), 'proj', console=Console(file=out, no_color=True, width=100))
        assert 'No recognized source files found.' in out.getvalue()

    def test_wording_depends_on_comment_detection(self):
        out = _render_tally(
            [
                ('.py', FileCount(total_lines=3, code_lines=1, comment_lines=1, blank_lines=1)),
                ('.json', FileCount(total_lines=2, code_lines=1, blank_lines=1)),
            ]
        )
        assert _section(out, 'Python') == ['3 lines of code', '1 excluding comments and blank lines']  # has '#'
        assert _section(out, 'JSON') == ['2 lines', '1 excluding blank lines']  # no comment marker

    def test_same_language_in_two_categories_is_labelled(self):
        md = EXTENSION_MAP['.md']
        out = io.StringIO()
        tally = aggregate(
            [(md, FileCount(total_lines=2, code_lines=2)), (as_spec(md), FileCount(total_lines=3, code_lines=3))]
        )
        display_results(tally, 'proj', console=Console(file=out, no_color=True, width=100))
        assert 'Markdown (docs)' in out.getvalue()
        assert 'Markdown (specs)' in out.getvalue()

    def test_more_than_three_languages_in_a_category_ends_with_etc(self):
        entries = [(ext, FileCount(total_lines=10, code_lines=10)) for ext in ('.py', '.rs', '.go', '.java')]
        assert '(Python + Rust + Go, etc)' in _render_tally(entries)  # the first three, by size

    def test_with_spaces_switches_categories_combined_and_bar(self):
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
    def test_bar_is_exactly_bar_width(self, sizes: list[int]):
        exts = ['.py', '.rs', '.go', '.java', '.c', '.cpp', '.cs', '.rb', '.lua', '.php', '.swift', '.kt', '.dart']
        exts += ['.scala', '.zig', '.hs', '.erl']
        entries = [(exts[i], FileCount(total_lines=n, code_lines=n)) for i, n in enumerate(sizes)]
        bar_lines = [line for line in _render_tally(entries).splitlines() if BLOCK_CHAR in line]
        assert len(bar_lines) == 1
        assert bar_lines[0].strip().count(BLOCK_CHAR) == BAR_WIDTH

    def test_small_languages_are_grouped_as_other(self):
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


def _render_with_stats(stats: Optional[WalkStats], files: bool = True) -> str:
    out = io.StringIO()
    entries = [(EXTENSION_MAP['.py'], FileCount(total_lines=1, code_lines=1))] if files else []
    display_results(aggregate(entries), 'proj', console=Console(file=out, no_color=True, width=100), stats=stats)
    return out.getvalue()


class TestPatternNote:
    @pytest.mark.parametrize('stats', [None, WalkStats()])
    def test_nothing_removed_prints_nothing(self, stats: Optional[WalkStats]):
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
    def test_wording(self, stats: WalkStats, line: str):
        """The literal '[exclude]' must survive: printed as markup, Rich would swallow it."""
        out = _render_with_stats(stats)
        assert f'\n  {line}\n' in out
        assert out.rstrip().endswith(line)  # the last line of the report

    def test_printed_even_when_nothing_was_counted(self):
        out = _render_with_stats(WalkStats(3, 0), files=False)
        assert 'No recognized source files found.' in out
        assert 'Excluded by [exclude] patterns: 3 files' in out
