# Phase 4: Output & Display

## Goal

Replace the plain-text output from Phase 2 with rich, colorful terminal output that matches the sketch. This includes per-language stats with dual line counts, sorted by usage, category totals, and a GitHub-style colored percentage bar. After this phase, Tallyman is feature-complete for v0.1.

## Output Structure

The display has four sections, top to bottom:

```
1. Per-language breakdown (sorted most → least lines)
2. Separator line
3. Category totals (Code, Design, Docs, Data)
4. GitHub-style language percentage bar
```

### Section 1: Per-Language Breakdown

Each language block shows the language name in its assigned color, then indented stats. The exact format depends on whether the language has comment detection:

**Languages with comment detection (Python, Rust, JS, etc.):**
```
  Python:
          10,213 lines of code
           9,100 excluding comments and blank lines
```

**Languages without comment detection (Markdown, JSON, HTML, CSS):**
```
  Markdown:
           2,102 lines
           1,932 excluding blank lines
```

The difference: "lines of code" vs "lines", and "excluding comments and blank lines" vs "excluding blank lines." This reflects the reality that we aren't detecting comments for these languages yet.

Blank line between each language block. Sorted by `total_lines` descending.

### Section 2: Separator

```
  ----------------------------------------------------------
```

A simple dashed line to separate per-language stats from totals.

### Section 3: Category Totals

```
  Totals:
  Code:   11,413 lines (Python + Rust + JS, etc)
  Design:  9,302 (CSS + HTML)
  Docs:    2,102 lines (markdown)
```

Each category line shows:
- Category name, right-padded and aligned.
- Total lines for that category.
- Parenthetical listing the languages that contributed, joined with " + ". If more than 3 languages, show top 3 and add ", etc".

Only show categories that have at least one language with lines.

### Section 4: GitHub-Style Language Bar

A horizontal bar made of colored block characters (`█`), where each segment is proportional to that language's share of total lines. Below the bar, a legend showing each language's name and percentage.

```
  ██████████████████████░░░░░░░░░░░░░░░░░░░
  Python 43%  ·  HTML 22%  ·  CSS 10%  ·  Rust 8%  ·  JS 7%  ·  Other 10%
```

Implementation details:
- Bar width: 60 characters.
- Each language gets `round(percentage / 100 * 60)` blocks in its color.
- Languages under 2% are grouped into "Other" (gray).
- The legend below shows names and percentages separated by ` · `. Each language name is printed in its color.
- If the terminal is narrower than 60 chars, scale down proportionally.

## Steps

### 4.1 — Display Module (`display.py`)

Use Rich's `Console` for all output. This gives us:
- Color support with automatic fallback.
- Respect for `NO_COLOR` environment variable.
- Respect for `--no-color` flag (pass `no_color=True` to `Console`).

```python
from rich.console import Console
from rich.text import Text


def display_results(result: TallyResult, no_color: bool = False) -> None:
    """Render the full tallyman output to the terminal."""
    console = Console(no_color=no_color, highlight=False)

    _display_languages(console, result)
    _display_separator(console)
    _display_category_totals(console, result)
    _display_percentage_bar(console, result)
```

### 4.2 — Per-Language Display

```python
def _display_languages(console: Console, result: TallyResult) -> None:
    for stats in result.by_language:
        lang = stats.language
        console.print()

        # Language name in its color
        console.print(f'  [bold {lang.color}]{lang.name}:[/bold {lang.color}]')

        # Line counts, right-aligned numbers
        total_str = f'{stats.total_lines:,}'

        if lang.single_line_comment is not None:
            # Has comment detection
            effective = stats.non_blank_non_comment
            effective_str = f'{effective:,}'
            console.print(f'          {total_str:>10} lines of code')
            console.print(f'          {effective_str:>10} excluding comments and blank lines')
        else:
            # No comment detection
            non_blank = stats.non_blank
            non_blank_str = f'{non_blank:,}'
            console.print(f'          {total_str:>10} lines')
            console.print(f'          {non_blank_str:>10} excluding blank lines')
```

Note: Right-aligning the numbers so they form a clean column, matching the sketch.

### 4.3 — Separator

```python
def _display_separator(console: Console) -> None:
    console.print()
    console.print(f'  {"—" * 58}')
```

### 4.4 — Category Totals

```python
CATEGORY_DISPLAY_ORDER = ['Code', 'Design', 'Docs', 'Data']

def _display_category_totals(console: Console, result: TallyResult) -> None:
    console.print('  [bold]Totals:[/bold]')

    # Find max category name length for alignment
    max_name_len = max(len(c.name) for c in result.by_category if c.total_lines > 0)

    for cat in result.by_category:
        if cat.total_lines == 0:
            continue

        # Build the parenthetical language list
        if len(cat.languages) <= 3:
            lang_list = ' + '.join(cat.languages)
        else:
            lang_list = ' + '.join(cat.languages[:3]) + ', etc'

        padded_name = f'{cat.name}:'
        console.print(
            f'  {padded_name:<{max_name_len + 1}} {cat.total_lines:>7,} lines ({lang_list})'
        )
```

### 4.5 — GitHub-Style Percentage Bar

```python
def _display_percentage_bar(console: Console, result: TallyResult) -> None:
    if result.grand_total_lines == 0:
        return

    console.print()

    BAR_WIDTH = 60
    percentages = language_percentages(result)

    # Group small languages into "Other"
    THRESHOLD = 2.0
    main_langs = [(name, color, pct) for name, color, pct in percentages if pct >= THRESHOLD]
    other_pct = sum(pct for _, _, pct in percentages if pct < THRESHOLD)
    if other_pct > 0:
        main_langs.append(('Other', 'grey50', other_pct))

    # Build the bar
    bar = Text()
    chars_used = 0
    for i, (name, color, pct) in enumerate(main_langs):
        # Last segment gets remaining chars to avoid rounding gaps
        if i == len(main_langs) - 1:
            segment_width = BAR_WIDTH - chars_used
        else:
            segment_width = max(1, round(pct / 100 * BAR_WIDTH))
            segment_width = min(segment_width, BAR_WIDTH - chars_used)
        bar.append('█' * segment_width, style=color)
        chars_used += segment_width

    console.print(f'  ', end='')
    console.print(bar)

    # Legend line
    legend_parts = []
    for name, color, pct in main_langs:
        legend_parts.append(f'[{color}]{name}[/{color}] {pct:.0f}%')
    legend = '  ·  '.join(legend_parts)
    console.print(f'  {legend}')
```

### 4.6 — Wire into `cli.py`

Replace the temporary `print` loop with:

```python
from tallyman.display import display_results

# After aggregation:
no_color = args.no_color or os.environ.get('NO_COLOR') is not None
display_results(result, no_color=no_color)
```

### 4.7 — Handle Empty Projects

If no files are found:

```python
if not result.by_language:
    console.print('[dim]No recognized source files found.[/dim]')
    sys.exit(0)
```

### 4.8 — Final `cli.py` Main Flow

The complete main function after all phases:

```python
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.path).resolve()

    if not root.is_dir():
        console = Console(stderr=True)
        console.print(f'[red]Error:[/red] {root} is not a directory')
        sys.exit(1)

    # Gitignore
    gitignore_spec = load_gitignore(root)

    # Config
    config_path = root / CONFIG_FILENAME
    existing_config = find_config(root)

    if existing_config and not args.setup:
        excluded_dirs = load_config(existing_config)
    else:
        existing_exclusions = load_config(existing_config) if existing_config else set()
        result = run_setup(root, gitignore_spec, existing_exclusions)
        if result is None:
            sys.exit(0)
        excluded_dirs = result
        save_config(config_path, excluded_dirs)

    # Count
    file_results = []
    for file_path, language in walk_project(root, excluded_dirs):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    tally = aggregate(iter(file_results))

    # Display
    no_color = args.no_color or os.environ.get('NO_COLOR') is not None
    display_results(tally, no_color=no_color)
```

### 4.9 — Tests

**`test_display.py`:**

Testing Rich output can be done by capturing to a string buffer:

```python
from io import StringIO
from rich.console import Console

def test_display_produces_output():
    """display_results writes to the console without errors."""
    # Build a TallyResult with known data
    # Create a Console with file=StringIO() and no_color=True
    # Call display functions
    # Assert the output string contains expected text
```

Test cases:
- Single language → correct output format.
- Multiple languages → sorted by total lines descending.
- Language with comments → shows "excluding comments and blank lines".
- Language without comments → shows "excluding blank lines".
- Category totals appear for each non-empty category.
- Percentage bar characters sum to BAR_WIDTH.
- `--no-color` produces output without ANSI escape codes.
- Empty project → "No recognized source files found."

## Acceptance Criteria

- [ ] Output matches the sketch format: per-language blocks with dual line counts
- [ ] Each language name appears in its assigned color
- [ ] Languages are sorted by total lines, most to least
- [ ] Separator line appears between language blocks and totals
- [ ] Category totals show Code, Design, Docs (and Data if present)
- [ ] Category totals include parenthetical language lists
- [ ] GitHub-style percentage bar renders with colored segments
- [ ] Percentage legend appears below the bar
- [ ] Languages under 2% are grouped as "Other"
- [ ] `--no-color` disables all color output
- [ ] `NO_COLOR` environment variable is respected
- [ ] Empty projects show a clean message instead of crashing
- [ ] Numbers are comma-formatted and right-aligned
- [ ] All tests pass
- [ ] Ruff passes with no errors
