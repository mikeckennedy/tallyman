"""Rich-based colored terminal output for tallyman results."""

from __future__ import annotations

import sys
from typing import Optional

from rich.console import Console
from rich.text import Text

from tallyman import __version__
from tallyman.aggregator import (
    BarSegment,
    TallyResult,
    active_categories,
    bar_segments,
    language_display_names,
    percent_label,
    segment_widths,
)
from tallyman.languages import Language
from tallyman.walker import WalkStats


def _can_encode_unicode() -> bool:
    """Check whether stdout can encode every non-ASCII character the report draws: rule, bar block and legend dot.

    On Windows with Git Bash (cp1252 encoding), the box-drawing and block
    characters cause UnicodeEncodeError. Fall back to ASCII for all of them in
    that case, so the report never mixes the two.
    """
    encoding = getattr(sys.stdout, 'encoding', None) or 'ascii'
    try:
        '─█·'.encode(encoding)
        return True
    except UnicodeEncodeError, LookupError:
        return False


_USE_UNICODE = _can_encode_unicode()
HORIZONTAL_RULE = '─' if _USE_UNICODE else '-'
BLOCK_CHAR = '█' if _USE_UNICODE else '#'

BAR_WIDTH = 60
LEGEND_SEPARATOR = '  ·  ' if _USE_UNICODE else '  |  '


def display_results(
    result: TallyResult,
    directory: str,
    no_color: bool = False,
    with_spaces: bool = False,
    console: Optional[Console] = None,
    stats: Optional[WalkStats] = None,
) -> None:
    """Render the full tallyman output to the terminal, or to *console* when given (tests pass one).

    *no_color* applies only to the console created here; a passed-in console keeps its own setting.
    *stats*, when given, adds a closing line saying what ``[exclude] patterns`` removed.
    """
    if console is None:
        console = Console(no_color=no_color, highlight=False)

    _display_report_header(console, directory)

    if not result.by_language:
        console.print('[dim]No recognized source files found.[/dim]')
        # A too-broad pattern is one way to get here, so say what the patterns removed
        _display_pattern_note(console, stats)
        return

    _display_languages(console, result, language_display_names(result))
    _display_separator(console)
    _display_category_totals(console, result, with_spaces=with_spaces)
    _display_percentage_bar(console, result, with_spaces=with_spaces)
    _display_pattern_note(console, stats)


SECTION_WIDTH = 58


def _plural(count: int, singular: str, plural: str) -> str:
    return f'{count:,} {singular if count == 1 else plural}'


def _pattern_note(stats: Optional[WalkStats]) -> Optional[str]:
    """The report's closing line about ``[exclude] patterns``, or None when they removed nothing."""
    if stats is None:
        return None
    parts = []
    if stats.pattern_files:
        parts.append(_plural(stats.pattern_files, 'file', 'files'))
    if stats.pattern_dirs:
        parts.append(_plural(stats.pattern_dirs, 'directory', 'directories'))
    if not parts:
        return None
    return 'Excluded by [exclude] patterns: ' + ', '.join(parts)


def _display_pattern_note(console: Console, stats: Optional[WalkStats]) -> None:
    note = _pattern_note(stats)
    if note is not None:
        console.print()
        console.print(Text(f'  {note}', style='dim'))  # Text, not markup: '[exclude]' would be read as a tag


def _display_report_header(console: Console, directory: str) -> None:
    console.print(f'[dim]{HORIZONTAL_RULE * SECTION_WIDTH}[/dim]')
    console.print(f'[bold]Tallyman [dim]v{__version__} created by Michael Kennedy[/dim][/bold]')
    # A directory name is printed as-is: no markup ([bold]), no emoji codes (:rocket:), no control characters
    console.print(Text(''.join(ch if ch.isprintable() else '?' for ch in directory)))
    console.print('')


def _language_header(name: str, color: str) -> str:
    """Build a centered header like: ────────────  Python  ────────────"""
    label = f'  {name}  '
    remaining = SECTION_WIDTH - len(label)
    left = remaining // 2
    right = remaining - left
    return f'[{color}]{HORIZONTAL_RULE * left}{label}{HORIZONTAL_RULE * right}[/{color}]'


def _display_languages(console: Console, result: TallyResult, display_names: dict[Language, str]) -> None:
    for stats in result.by_language:
        lang = stats.language
        name = display_names[lang]

        console.print(_language_header(name, lang.color))

        total_str = f'{stats.total_lines:,}'
        effective_str = f'{stats.effective_lines:,}'

        if lang.single_line_comment is not None:
            console.print(f'  {total_str:>10} lines of code')
            console.print(f'  {effective_str:>10} excluding comments and blank lines')
        else:
            console.print(f'  {total_str:>10} lines')
            console.print(f'  {effective_str:>10} excluding blank lines')


def _display_separator(console: Console) -> None:
    console.print(f'[dim]{HORIZONTAL_RULE * SECTION_WIDTH}[/dim]')


def _display_category_totals(console: Console, result: TallyResult, *, with_spaces: bool = False) -> None:
    categories = active_categories(result, with_spaces=with_spaces)
    if not categories:
        return

    console.print('  [bold]Totals:[/bold]')

    max_name_len = max(max(len(c.name) for c in categories), len('Combined'))

    for cat in categories:
        # Build the parenthetical language list
        if len(cat.languages) <= 3:
            lang_list = ' + '.join(cat.languages)
        else:
            lang_list = ' + '.join(cat.languages[:3]) + ', etc'

        lines = cat.shown_lines(with_spaces=with_spaces)
        padded_name = f'{cat.name}:'
        console.print(f'  {padded_name:<{max_name_len + 1}} {lines:>10,} lines ({lang_list})')

    combined = sum(c.shown_lines(with_spaces=with_spaces) for c in categories)
    console.print(f'  [bold]{"Combined:":<{max_name_len + 1}} {combined:>10,} lines[/bold]')


def _display_percentage_bar(console: Console, result: TallyResult, *, with_spaces: bool = False) -> None:
    segments = bar_segments(result, with_spaces=with_spaces)
    if not segments:  # nothing to share out (no effective lines): no blank line, bar or legend
        return

    console.print()
    console.print('  ', end='')
    console.print(_bar_text(segments))
    console.print(f'  {_legend_text(segments)}')


def _bar_text(segments: list[BarSegment]) -> Text:
    """The coloured bar, BAR_WIDTH cells wide, with at least one cell for every segment."""
    bar = Text()
    widths = segment_widths([s.percent for s in segments], BAR_WIDTH, 1)
    for segment, width in zip(segments, widths):
        bar.append(BLOCK_CHAR * width, style=segment.color)
    return bar


def _legend_text(segments: list[BarSegment]) -> str:
    """The legend under the bar, as Rich markup: each segment's coloured label and its percentage."""
    return LEGEND_SEPARATOR.join(f'[{s.color}]{s.label}[/{s.color}] {percent_label(s.percent)}' for s in segments)
