"""Rich-based colored terminal output for tallyman results."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.text import Text

from tallyman import __version__
from tallyman.aggregator import CATEGORY_DISPLAY_NAMES, TallyResult, language_percentages
from tallyman.languages import Language


def _can_encode_unicode() -> bool:
    """Check whether stdout can handle Unicode box-drawing characters.

    On Windows with Git Bash (cp1252 encoding), the box-drawing and block
    characters cause UnicodeEncodeError.  Fall back to ASCII in that case.
    """
    encoding = getattr(sys.stdout, 'encoding', None) or 'ascii'
    try:
        '─█'.encode(encoding)
        return True
    except UnicodeEncodeError, LookupError:
        return False


_USE_UNICODE = _can_encode_unicode()
HORIZONTAL_RULE = '─' if _USE_UNICODE else '-'
BLOCK_CHAR = '█' if _USE_UNICODE else '#'

BAR_WIDTH = 60
SMALL_LANGUAGE_THRESHOLD = 2.0  # Percentage below which languages are grouped as "Other"


def display_results(result: TallyResult, directory: str, no_color: bool = False) -> None:
    """Render the full tallyman output to the terminal."""
    console = Console(no_color=no_color, highlight=False)

    _display_report_header(console, directory)

    if not result.by_language:
        console.print('[dim]No recognized source files found.[/dim]')
        return

    display_names = _language_display_names(result)

    _display_languages(console, result, display_names)
    _display_separator(console)
    _display_category_totals(console, result)
    _display_percentage_bar(console, result, display_names)


SECTION_WIDTH = 58


def _display_report_header(console: Console, directory: str) -> None:
    console.print(f'[dim]{HORIZONTAL_RULE * SECTION_WIDTH}[/dim]')
    console.print(f'[bold]Tallyman [dim]v{__version__} created by Michael Kennedy[/dim][/bold]')
    console.print(f'{directory}')
    console.print('')


def _language_header(name: str, color: str) -> str:
    """Build a centered header like: ────────────  Python  ────────────"""
    label = f'  {name}  '
    remaining = SECTION_WIDTH - len(label)
    left = remaining // 2
    right = remaining - left
    return f'[{color}]{HORIZONTAL_RULE * left}{label}{HORIZONTAL_RULE * right}[/{color}]'


def _language_display_names(result: TallyResult) -> dict[Language, str]:
    """Build display names, appending category when a language name appears in multiple categories."""
    name_categories: dict[str, set[str]] = {}
    for stats in result.by_language:
        name_categories.setdefault(stats.language.name, set()).add(stats.language.category)

    display_names: dict[Language, str] = {}
    for stats in result.by_language:
        if len(name_categories[stats.language.name]) > 1:
            cat_label = CATEGORY_DISPLAY_NAMES.get(stats.language.category, stats.language.category)
            display_names[stats.language] = f'{stats.language.name} ({cat_label.lower()})'
        else:
            display_names[stats.language] = stats.language.name
    return display_names


def _display_languages(console: Console, result: TallyResult, display_names: dict[Language, str]) -> None:
    for stats in result.by_language:
        lang = stats.language
        name = display_names[lang]

        console.print(_language_header(name, lang.color))

        total_str = f'{stats.total_lines:,}'

        if lang.single_line_comment is not None:
            effective_str = f'{stats.non_blank_non_comment:,}'
            console.print(f'  {total_str:>10} lines of code')
            console.print(f'  {effective_str:>10} excluding comments and blank lines')
        else:
            non_blank_str = f'{stats.non_blank:,}'
            console.print(f'  {total_str:>10} lines')
            console.print(f'  {non_blank_str:>10} excluding blank lines')


def _display_separator(console: Console) -> None:
    console.print(f'[dim]{HORIZONTAL_RULE * SECTION_WIDTH}[/dim]')


def _display_category_totals(console: Console, result: TallyResult) -> None:
    active_categories = sorted(
        (c for c in result.by_category if c.total_lines > 0),
        key=lambda c: c.effective_lines,
        reverse=True,
    )
    if not active_categories:
        return

    console.print('  [bold]Totals:[/bold]')

    max_name_len = max(max(len(c.name) for c in active_categories), len('Combined'))

    for cat in active_categories:
        # Build the parenthetical language list
        if len(cat.languages) <= 3:
            lang_list = ' + '.join(cat.languages)
        else:
            lang_list = ' + '.join(cat.languages[:3]) + ', etc'

        padded_name = f'{cat.name}:'
        console.print(f'  {padded_name:<{max_name_len + 1}} {cat.effective_lines:>10,} lines ({lang_list})')

    combined = sum(c.effective_lines for c in active_categories)
    console.print(f'  [bold]{"Combined:":<{max_name_len + 1}} {combined:>10,} lines[/bold]')


def _display_percentage_bar(console: Console, result: TallyResult, display_names: dict[Language, str]) -> None:
    if result.grand_total_lines == 0:
        return

    console.print()

    percentages = language_percentages(result)

    # Group small languages into "Other"
    main_langs: list[tuple[Language | None, float]] = [
        (lang, pct) for lang, pct in percentages if pct >= SMALL_LANGUAGE_THRESHOLD
    ]
    other_pct = sum(pct for _, pct in percentages if pct < SMALL_LANGUAGE_THRESHOLD)
    if other_pct > 0:
        main_langs.append((None, other_pct))

    # Build the colored bar
    bar = Text()
    chars_used = 0
    for i, (lang, pct) in enumerate(main_langs):
        color = lang.color if lang else 'grey50'
        if i == len(main_langs) - 1:
            segment_width = BAR_WIDTH - chars_used
        else:
            segment_width = max(1, round(pct / 100 * BAR_WIDTH))
            segment_width = min(segment_width, BAR_WIDTH - chars_used)
        if segment_width > 0:
            bar.append(BLOCK_CHAR * segment_width, style=color)
            chars_used += segment_width

    console.print('  ', end='')
    console.print(bar)

    # Legend line
    legend_parts = []
    for lang, pct in main_langs:
        if lang is None:
            legend_parts.append(f'[grey50]Other[/grey50] {pct:.0f}%')
        else:
            name = display_names.get(lang, lang.name)
            legend_parts.append(f'[{lang.color}]{name}[/{lang.color}] {pct:.0f}%')
    legend = '  ·  '.join(legend_parts)
    console.print(f'  {legend}')
