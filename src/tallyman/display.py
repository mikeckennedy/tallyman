"""Rich-based colored terminal output for tallyman results."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from tallyman import __version__
from tallyman.aggregator import TallyResult, language_percentages

BAR_WIDTH = 60
SMALL_LANGUAGE_THRESHOLD = 2.0  # Percentage below which languages are grouped as "Other"


def display_results(result: TallyResult, directory: str, no_color: bool = False) -> None:
    """Render the full tallyman output to the terminal."""
    console = Console(no_color=no_color, highlight=False)

    _display_report_header(console, directory)

    if not result.by_language:
        console.print('[dim]No recognized source files found.[/dim]')
        return

    _display_languages(console, result)
    _display_separator(console)
    _display_category_totals(console, result)
    _display_percentage_bar(console, result)


SECTION_WIDTH = 58


def _display_report_header(console: Console, directory: str) -> None:
    console.print(f'[dim]{"─" * SECTION_WIDTH}[/dim]')
    console.print(f'[bold]Tallyman [dim]v{__version__} created by Michael Kennedy[/dim][/bold]')
    console.print(f'Report for {directory}')
    console.print('')


def _language_header(name: str, color: str) -> str:
    """Build a centered header like: ────────────  Python  ────────────"""
    label = f'  {name}  '
    remaining = SECTION_WIDTH - len(label)
    left = remaining // 2
    right = remaining - left
    return f'[{color}]{"─" * left}{label}{"─" * right}[/{color}]'


def _display_languages(console: Console, result: TallyResult) -> None:
    for stats in result.by_language:
        lang = stats.language

        console.print(_language_header(lang.name, lang.color))

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
    console.print(f'[dim]{"─" * SECTION_WIDTH}[/dim]')


def _display_category_totals(console: Console, result: TallyResult) -> None:
    active_categories = [c for c in result.by_category if c.total_lines > 0]
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


def _display_percentage_bar(console: Console, result: TallyResult) -> None:
    if result.grand_total_lines == 0:
        return

    console.print()

    percentages = language_percentages(result)

    # Group small languages into "Other"
    main_langs = [(name, color, pct) for name, color, pct in percentages if pct >= SMALL_LANGUAGE_THRESHOLD]
    other_pct = sum(pct for _, _, pct in percentages if pct < SMALL_LANGUAGE_THRESHOLD)
    if other_pct > 0:
        main_langs.append(('Other', 'grey50', other_pct))

    # Build the colored bar
    bar = Text()
    chars_used = 0
    for i, (_name, color, pct) in enumerate(main_langs):
        if i == len(main_langs) - 1:
            segment_width = BAR_WIDTH - chars_used
        else:
            segment_width = max(1, round(pct / 100 * BAR_WIDTH))
            segment_width = min(segment_width, BAR_WIDTH - chars_used)
        if segment_width > 0:
            bar.append('█' * segment_width, style=color)
            chars_used += segment_width

    console.print('  ', end='')
    console.print(bar)

    # Legend line
    legend_parts = []
    for name, color, pct in main_langs:
        legend_parts.append(f'[{color}]{name}[/{color}] {pct:.0f}%')
    legend = '  ·  '.join(legend_parts)
    console.print(f'  {legend}')
