# Phase 1 - Shared Report Model, Then the Bar Fixes

Covers decisions 1-6 and open questions 1-2 from `00-plan-introduction.plan.md`, plus rule 16.

## Goal

The terminal report and the image card get their categories, totals, bar segments, legend labels and segment widths from one set of functions in `aggregator.py`. Then bugs 6 and 7, and the image crash on a tiny "Other", are fixed once in that shared code. A test proves the two outputs agree.

Do it in two steps. **Step A changes no output**, so the existing display and image tests pass unchanged and show the move was faithful. **Step B** is the behaviour change.

## Step A - Move the logic (no output change)

### `aggregator.py`

- `LanguageStats`:
  - Add a property `effective_lines -> int`: `code_lines` when `language.single_line_comment is not None`, else `total_lines - blank_lines`. The docstring says this is the one definition, and both outputs and `--with-spaces` rely on it.
  - Add a method `shown_lines(self, *, with_spaces: bool) -> int`: `total_lines if with_spaces else effective_lines`.
  - Remove `non_blank_non_comment` and `non_blank`. `aggregate()`, `language_percentages()` and `display._display_languages()` are their only callers, and ty/pyrefly will flag any left.
- `CategoryStats`: add the same `shown_lines(*, with_spaces)` method. `aggregate()` fills `effective_lines` from `stats.effective_lines`.
- `language_percentages()`: replace the inner `_effective` with `s.shown_lines(with_spaces=...)`. Keep the signature and behaviour; `tests/test_aggregator.py` uses it.
- Move these here from `display.py` and `image.py` (both define the threshold today):
  - `SMALL_LANGUAGE_THRESHOLD = 2.0`
  - `OTHER_LABEL = 'Other'`
- Add `OTHER_COLOR = 'grey50'` to **`languages.py`**, next to `LANGUAGES`, since that is where the colours live. Add a comment that it is the colour of the bar's and legend's "Other" segment. It is the only definition: `bar_segments()` reads it, and neither renderer has a `'grey50'` literal any more (grep for one when the phase is done). Plan 009 changes this one value to `grey37` (coordinated with 009).
- Move `display._language_display_names()` here as public `language_display_names(result) -> dict[Language, str]`, unchanged. This fixes rule 16.
- Add `active_categories(result, *, with_spaces: bool = False) -> list[CategoryStats]`: categories with `total_lines > 0`, sorted by `shown_lines` descending. The sort is stable, so ties keep `CATEGORY_ORDER`. This is the code at display.py:157-161 and image.py:156-160.
- Add:

  ```python
  @dataclass(frozen=True, slots=True)
  class BarSegment:
      language: Optional[Language]  # None for the Other segment
      label: str                    # display name, e.g. 'Markdown (specs)', or OTHER_LABEL
      color: str                    # a Rich colour name: language.color, or OTHER_COLOR
      percent: float
  ```

- Add `bar_segments(result, *, with_spaces: bool = False) -> list[BarSegment]`:
  - one segment per language at or above `SMALL_LANGUAGE_THRESHOLD`, in `language_percentages()` order;
  - then one Other segment for the rest, when their sum is above zero.

  Labels come from `language_display_names()`. The result is empty when `language_percentages()` is.

### `display.py`

- Import `active_categories`, `bar_segments` and `language_display_names` from `aggregator`. Delete `_language_display_names` and the local `SMALL_LANGUAGE_THRESHOLD`.
- `_display_languages()`: the second number is `stats.effective_lines` in both branches. Keep the branch on `single_line_comment`; it chooses the wording.
- `_display_category_totals()`: use `active_categories()` and `shown_lines()`.
- `_display_percentage_bar(console, result, *, with_spaces)`: drop the `display_names` parameter, since the segments carry labels. Split it into:
  - `_bar_text(segments: list[BarSegment]) -> Text`, which keeps today's width arithmetic in step A;
  - `_legend_text(segments) -> str`, which builds the legend from `segment.label`, `segment.color` and `f'{segment.percent:.0f}%'`, joined by a module constant `LEGEND_SEPARATOR = '  ·  '`.

  This removes the `Language | None` annotation.

### `image.py`

- Import `active_categories`, `bar_segments` and `language_display_names` (if still needed) from `aggregator`. Drop the `display` import and the local `SMALL_LANGUAGE_THRESHOLD`.
- `generate_image()`: use `active_categories()`, `shown_lines()` and `bar_segments()`.
- `_cap_legend()` takes `list[BarSegment]` and keeps today's folding. Segment colour is `_rich_color_to_rgb(segment.color)`.
- This removes the `Language | None` at image.py:114.

### Checkpoint

The existing tests pass with only import changes. Also run a scratch script, in the session scratchpad and not the repo, that saves `tallyman` terminal output (`--no-color`, with and without `--with-spaces`) and `generate_image()` PNGs for this repo, once before step A and once after. The terminal text must be byte-identical. The PNGs must be pixel-identical: `PIL.ImageChops.difference(a, b).getbbox() is None`.

## Step B - Fix the bar

### Bug 6: no bar when there is nothing to share

- `display._display_percentage_bar()`: compute `segments` first. If it is empty, return before the `console.print()` that adds the blank line. Drop the `grand_total_lines == 0` guard, which the empty list already covers.
- `image.generate_image()`: `has_bar = bool(segments)`, used for both the height (`bar_section`) and drawing. So a card with only comment lines has no blank band.

### Bug 7 and the image crash: one width allocator

Add to `aggregator.py`:

```python
def segment_widths(percents: Sequence[float], total: int, minimum: int) -> list[int]:
    """Split *total* cells (or pixels) between segments in proportion to *percents*.

    Every segment gets at least *minimum* (lowered to total // len(percents) if there isn't room),
    the widths add up to *total* exactly, and spare cells go to the largest remainders, earliest first on ties.
    """
```

Algorithm:

1. Compute `ideal[i] = percents[i] / sum(percents) * total`. Divide by the sum, not 100, so floating-point error can't leak.
2. Set `w[i] = max(minimum, floor(ideal[i]))`.
3. While `sum(w) < total`, add 1 to the segment with the largest `ideal[i] - w[i]`, the earlier index on ties.
4. While `sum(w) > total` (the minimum took cells), take 1 from the segment with the largest `w[i] - ideal[i]` among those still above `minimum`, the earlier index on ties.

Return `[]` for an empty input or a zero sum. The segment count is at most 51, so the loops are trivial.

- **Terminal:** `_bar_text()` uses `segment_widths([s.percent for s in segments], BAR_WIDTH, 1)`. Python 496, Rust 496, Go 8 then gives `[30, 29, 1]`.
- **Image:** add `MIN_SEGMENT_PX = 4`, with a comment that it must stay above `BAR_GAP`. Segment *i* spans `x0 = bar_left + sum(widths[:i])` to `x0 + widths[i]`, drawn as `(x0, top, x0 + widths[i] - BAR_GAP, bottom)`. No segment can then be narrower than the gap, which fixes the `ValueError` on a 1 px "Other". The `pct <= 0` and `seg_right <= x` skips go.

### Open question 1 (default: fold the image bar too)

- `bar_segments()` gains `max_languages: Optional[int] = None`. Named segments past the first `max_languages` are merged with the existing Other segment into one Other whose `percent` is their sum. Other stays last.
- The image calls it with `max_languages=MAX_LEGEND_ITEMS`, draws those segments, and builds the legend straight from them. Delete `_cap_legend()`.
- The terminal passes nothing and is unchanged.

### Open question 2 (default: `<1%` and `>99%`)

Add `percent_label(percent: float) -> str` to `aggregator.py`:

- `f'{percent:.0f}%'`;
- but `'<1%'` when that text is `'0%'` and `percent > 0`;
- and `'>99%'` when it is `'100%'` and `percent < 100`.

Both legends use it.

## Tests

`tests/test_aggregator.py`:

- `TestEffectiveLines`:
  - with a comment marker, `effective_lines == code_lines`;
  - without one (Markdown), it is `total_lines - blank_lines`;
  - `CategoryStats.effective_lines` is the sum of its languages';
  - `shown_lines(with_spaces=True)` is `total_lines`.
- `TestActiveCategories`:
  - sorted by effective lines by default and by total lines with `with_spaces`;
  - categories with no lines are left out;
  - equal counts keep `CATEGORY_ORDER`.
- `TestBarSegments`:
  - 97/1/2 gives `[Python, Other]`, with Other at 3%;
  - no Other segment when nothing is under the threshold;
  - empty for no files, and for a comment-only file (bug 6);
  - non-empty for the comment-only file with `with_spaces=True`;
  - labels read `Markdown (docs)` / `Markdown (specs)` when both exist (use `as_spec`), and colours are `language.color` and `languages.OTHER_COLOR`;
  - `max_languages=2` on seven languages gives three segments, the last an Other holding the remaining percentages.
- `TestSegmentWidths`:
  - `[49.6, 49.6, 0.8]`, 60, 1 gives `[30, 29, 1]`;
  - parametrized over the size lists in `test_display.py::test_bar_is_exactly_bar_width` plus `[99.95, 0.05]` at 1080 px / minimum 4: the sum equals `total`, every width is at least `minimum`, and with no minimum bump every width is within 1 of ideal;
  - a minimum too large for the segment count is lowered and the sum still equals `total`;
  - empty input gives `[]`.
- `TestPercentLabel`: `0.3 -> '<1%'`, `0 -> '0%'`, `0.6 -> '1%'`, `49.6 -> '50%'`, `99.7 -> '>99%'`, `100 -> '100%'`.

`tests/test_display.py`:

- `test_no_effective_lines_prints_no_bar` (bug 6): a `.py` file that is all comments. The output has no `BLOCK_CHAR`, and the `Combined:` line is the last non-empty line, with no whitespace-only lines after it. This fails today, since the output ends `'\n  \n  \n'`.
- `test_with_spaces_draws_the_bar_when_no_lines_are_effective`: the same file with `with_spaces=True` has one bar line.
- `test_every_segment_gets_a_cell` (bug 7): for Python 496 / Rust 496 / Go 8, `_bar_text(bar_segments(tally))` has one span per segment, each at least 1 character, with styles equal to the segment colours, and total length `BAR_WIDTH`. Today's code gives the Other segment no span.
- `test_tiny_other_reads_under_one_percent`: 2,000 / 1 lines, and the legend ends with `Other <1%`.
- The existing `test_bar_is_exactly_bar_width` and `test_small_languages_are_grouped_as_other` stay as they are.

`tests/test_image.py`:

- Add a helper `_record_drawing(monkeypatch) -> dict[str, list]`. It wraps `PIL.ImageDraw.ImageDraw.text` and `.rectangle` and records the text drawn and the rectangle coordinates, then calls the originals. Only bar segments are rectangles.
- `test_tiny_other_segment_does_not_crash`: Python 2,000 + Go 1 renders a PNG, and every rectangle has `x1 >= x0`. Today this raises `ValueError`.
- `test_no_effective_lines_draws_no_bar` (bug 6): no rectangles. The image is shorter than the same result rendered with `with_spaces=True`.
- `test_bar_and_legend_match`: one rectangle per legend entry.
- `TestMatchesTerminal`, the agreement test from the review's test gaps:
  - Build one `TallyResult` from:
    - Python 496, Rust 496, Go 8 (code);
    - the **specs-plus-docs case**: a docs Markdown file (40) and a Markdown file from a `plans/` directory (30). Build it by walking a `tmp_path` tree with `README.md` and `plans/design.md` through `walk_project` + `count_lines` + `aggregate`, so the spec variant is the real `as_spec()` object the walker yields, not one made by hand. Keep the tree in a module-level helper (`_specs_and_docs_tree(tmp_path)`) so plan 009's colour tests can reuse it;
    - YAML 20 (devops/data);
    - JSON 10, which has no comment marker;
    - comment and blank lines mixed in, so `with_spaces` changes the numbers.
  - Parametrize over `with_spaces`.
  - Render it with `display_results` (no colour, wide console) and with `generate_image` (recording).
  - Parse each category line with `r'^\s*(\w+):\s+([\d,]+) lines(?: \((.*)\))?$'`. Assert:
    - the same categories in the same order, with the same line counts and language lists;
    - the terminal's `Combined:` equals the image's `Total:`;
    - the legend entries are identical (split each legend on its own module's separator).
  - A second case with seven languages each above 2%: the image's legend is the terminal's first five entries plus `Other {percent_label(sum of the rest)}`, and it has six rectangles.

## Docs

- `CLAUDE.md`:
  - Module map, `aggregator.py` row: add "and the report model both outputs draw: `active_categories()`, `bar_segments()`, `segment_widths()`, `percent_label()`, `language_display_names()`".
  - `display.py` and `image.py` rows: "draws the shared report model".
  - Core Data Structures: add `BarSegment(frozen=True)` and `LanguageStats.effective_lines`.
  - Test counts.
- `change-log.md`, under `0.4.3 - UNRELEASED`:
  - `### Fixed`: a project with no effective lines no longer prints a blank bar and legend, and the image no longer leaves a gap for it; a small "Other" always gets at least one cell of the bar; `--image` no longer crashes when "Other" is under about 0.1%.
  - `### Changed`: the image's bar now folds languages past the fifth into Other, as its legend already did; a non-zero share that rounds to 0% reads `<1%`.
  - `Files:` and `Plan:` lines.

## Done when

- Step A's checkpoint showed identical output, and step B's tests failed before step B and pass after.
- `display.py` and `image.py` hold no selection, threshold or width logic of their own, and `image.py` imports nothing from `display.py`.
- All checks in the introduction's rules are clean, and the architect review's valid findings are addressed and committed.
