from __future__ import annotations

import io

from rich.console import Console

from tallyman.aggregator import aggregate
from tallyman.counter import FileCount
from tallyman.display import display_results
from tallyman.languages import EXTENSION_MAP


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
