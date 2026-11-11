# Plan 009 - Spec Colours

One phase, so one file (`plans/planning-rules.md`). It comes from the architect review of 2026-11-10, "Spec variants share their docs colour" under Design concerns, and its test gap "Colour test doesn't cover as_spec() variants".

## Context

`as_spec()` turns a docs language found in a spec directory into a `specs` variant. The variant copies the docs language's colour, so Markdown (specs) and Markdown (docs) are drawn in the same colour. Spec directories are usually the bulk of a repo's Markdown, and the bar is sorted by size, so the two segments often sit side by side. They then read as one block.

**Confirmed on this repo (main @ 75dd0fd, 2026-11-10).** The bar is Python 59%, Markdown (specs) 34%, Markdown (docs) 6%, Other 1%. ANSI codes of the bar runs, from `FORCE_COLOR=1 tallyman .`:

| Terminal | Python | Markdown (specs) | Markdown (docs) | Other |
|---|---|---|---|---|
| truecolor (`COLORTERM=truecolor`) | `33` | `37` | `37` | `38;5;244` |
| 256-colour (`TERM=xterm-256color`) | `33` | `37` | `37` | `38;5;244` |
| 16-colour (`TERM=xterm`) | `33` | `37` | `37` | `37` |

That makes one 40% white block (41% in 16-colour mode). `white` is a standard colour, so even truecolor terminals print the palette's `37`. The PNG card shows the same thing: one `#c0c0c0` block, with only the 2 px segment gap between specs and docs.

**A second collision, found while checking this.** The bar's "Other" segment is hard-coded `grey50`, which is also TOML's colour. When TOML is the smallest language above the 2% cut-off, it sits next to Other, and Rich merges the two runs because the style is identical. A scratch project with Python 93%, TOML 6% and JSON 1% gives a bar with only two colour runs, `33` then one `38;5;244` run covering both TOML and Other. In 16-colour mode, `grey50` also drops to `37`, the same as Markdown (docs) and reStructuredText.

## The code today

- `src/tallyman/languages.py:12-18`: `Language(frozen=True, slots=True)` with `name, category, color, single_line_comment, extensions`.
- `languages.py:66-67`: the two docs languages, Markdown (`white`) and reStructuredText (`grey70`). These are the only languages `as_spec()` accepts.
- `languages.py:142-159`: `as_spec()` is `@functools.cache`d and returns `Language(lang.name, 'specs', lang.color, ...)`. The walker (`walker.py:224`) is its only caller in `src/`.
- `src/tallyman/display.py:206` and `:223`: the bar and legend colour Other `'grey50'`. `src/tallyman/image.py:245` does the same on the card. Plan 008 moves the segment selection into a shared `aggregator.bar_segments()`, but the colours stay in the renderers.
- `image._rich_color_to_rgb()` turns a Rich colour name into the card's RGB with `Color.get_truecolor(None, True)`, Rich's default palette. So `white` is `#c0c0c0` on the card.
- `tests/test_languages.py:174` asserts `spec_md.color == md.color`, which locks in the bug. `test_no_new_shared_colours` (`:240`) compares colour *names* in `LANGUAGES` only, so it misses spec variants, Other, and two names for one colour (`grey50` and `gray50`).
- The setup TUI doesn't use language colours.

## Decisions (recommended; see Open questions)

1. **Each docs language names its spec colour in the registry.** `Language` gets a keyword-only field `spec_color: Optional[str] = None`, and the two docs rows set it. `as_spec()` builds the variant with `color=lang.spec_color`. The colour is fixed when the variant is created, and you can see it next to the docs colour in the registry table.
   - Not derived. A computed shade such as "docs colour, lighter" can't be guaranteed to stay distinct once Rich drops it to 256 or 16 colours. For `white`, the docs colour today, any lighter or darker grey falls back to `37` again in 16-colour mode. Two names picked by hand are easier to check than a rule.
   - Not a separate `SPEC_COLOURS` dict keyed by name: a field keeps the colour on the row that a new docs language has to add anyway, and tests can ask every docs row for it.
2. **The colours** (values checked against Rich 14, the registry, and both card themes):

   | Variant | Rich name | Hex (card) | 256 | 16-colour | vs dark card `#1e1e2e` | vs light card `#ffffff` | Nearest registry colour (CIE76 ΔE) |
   |---|---|---|---|---|---|---|---|
   | Markdown (specs) | `violet` | `#d787ff` | 177 | 13, SGR `95` (bright magenta) | 6.9 : 1 | 2.4 : 1 | PHP `medium_purple3`, 22 |
   | reStructuredText (specs) | `dark_sea_green4` | `#5faf5f` | 71 | 10, SGR `92` (bright green) | 6.1 : 1 | 2.7 : 1 | Dart `cyan3`, 31 |
   | Other (bar, legend) | `grey37` | `#5f5f5f` | 59 | 8, SGR `90` (bright black) | 2.6 : 1 | 6.4 : 1 | TOML `grey50`, 13 |

   For reference, the docs colours they sit next to: Markdown `white` `#c0c0c0`, 16-colour `37`. reStructuredText `grey70` `#b2b2b2`, 16-colour `37`. Their ΔE to the spec colours is 70 and 54. Both docs colours and all three new colours are distinct as card RGB and as 256-colour index from each other and from every registry colour. The only shared pair is still C and C/C++ Header, checked by script.

   How they were picked: all ~250 Rich colour names were screened. Kept were names that don't drop to `37`, `97`, `90`, `30` or `33` in 16-colour mode, have at least 4 : 1 contrast on the dark card and 2.3 : 1 on the light one, and are far from every existing colour. The space is crowded: the best candidate is only ΔE 35 from its nearest neighbour (`deep_pink2`). `violet` (ΔE 22) was picked over it because a 34% segment in hot pink is loud. A soft violet reads as "planning" next to silver docs Markdown, and it's a bright, unused colour in 16-colour mode.
3. **"Other" gets its own colour, `grey37`, defined once.** It drops to SGR `90`, the one 16-colour code no language uses, so Other can't merge with any neighbour on any terminal. It's darker than the greys used for data languages (TOML `grey50`, XML `grey58`, Perl `grey62`), so the leftover segment fades back, which suits it. This fixes the TOML/Other merge and the 16-colour `37` collapse the review noted.
4. **The 16-colour check is limited to what can be guaranteed.** With 16 codes and 44 languages, no rule can keep *every* pair of neighbours apart in 16-colour mode. Two neighbours are structural and can be kept apart:
   - a docs language and its own spec variant, which appear together whenever specs exist;
   - Other, which can follow any language.

   Tests check both. A general "all neighbours differ in 16 colours" check is not planned.

## Phase

| Phase | Covers |
|-------|--------|
| 1 | Decisions 1-4: spec colours, Other colour, colour tests, docs, before/after check |

Lands after plan 008. It assumes 008's `aggregator.bar_segments()` exists and that `display.py` and `image.py` both draw from it.

## Workflow

- All plans 008-012 land on one feature branch, `architect-review-fixes`. Claude commits after each phase. **Never push** (unlike plan 007, there is no push permission), never commit to `main`, and leave merging to Michael.
- After the phase, an architect review runs via the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Address its valid findings, then commit.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- New or changed annotations use `Optional[X]`, not `X | None`. Don't convert untouched code: that sweep is plan 012. `Language.single_line_comment: str | None` stays as it is here.
- Each behaviour change lands with a test that fails before the change and passes after.
- Finish with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean.
- Changelog entries go under the existing `0.4.3 - UNRELEASED` heading in `change-log.md`. No version bump.
- Update README and `CLAUDE.md` where they describe colours, `Language`, or test counts.
- Images written while testing go to the scratchpad, never `~/Desktop` (see the before/after check).

## Phase 1 - Spec and Other colours

### `src/tallyman/languages.py`

- `Language` gets a last field, `spec_color: Optional[str] = field(default=None, kw_only=True)`. Keyword-only, so every positional `Language(...)` call in `src/` and `tests/` (the `_lang()` helpers in `test_aggregator.py`, `test_image.py` and `test_counter.py`) keeps working unchanged. Comment: `# docs languages only: the colour of their as_spec() variant`.
- The two docs rows (keep the `# fmt: off` alignment as far as it goes):
  ```python
  (Language('Markdown', 'docs', 'white', None, ('.md', '.mdx'), spec_color='violet'),)
  (Language('reStructuredText', 'docs', 'grey70', None, ('.rst',), spec_color='dark_sea_green4'),)
  ```
- `as_spec()`:
  - Keep the category check and `@functools.cache`.
  - If `lang.spec_color is None`, raise `ValueError(f'{lang.name} has no spec_color')`. Every registry docs language has one, so this only catches a new docs row added without one, or a test-built `Language`.
  - Return `dataclasses.replace(lang, category='specs', color=lang.spec_color, spec_color=None)`. The variant has no `spec_color` of its own; it isn't a docs language.
  - Docstring: "identical to *lang* except category `'specs'` and colour `lang.spec_color`, so specs and docs never draw as one bar segment."
- `OTHER_COLOR = 'grey37'` near `LANGUAGES`, with a comment: the bar's and legend's "Other" segment; drops to ANSI 90 on 16-colour terminals, which no language uses. `languages.py` is where the colours live and is already imported by both renderers. If plan 008 named a constant for the Other colour somewhere else, move it here, or point that one at this, so there's one definition.

### `src/tallyman/display.py` and `src/tallyman/image.py`

Replace the `'grey50'` literals for Other with `OTHER_COLOR`: display's bar segment and its legend markup (`f'[{OTHER_COLOR}]Other[/{OTHER_COLOR}]'`), and image's bar segment. Line numbers will have moved after 008; grep for `grey50`. Nothing else changes. Both already take colours from `lang.color`, so spec variants pick up their colour through the walker → aggregator → `bar_segments()` path without further edits.

### Tests

`tests/test_languages.py`:

- `TestAsSpec.test_creates_spec_category` (replaces the assertion at `:174`): `spec_md.color == md.spec_color == 'violet'`, `spec_md.color != md.color`, `spec_md.spec_color is None`. Name and extensions are still equal.
- `TestAsSpec.test_rst`: also `as_spec(rst).color == 'dark_sea_green4'`.
- `TestAsSpec.test_docs_language_without_spec_colour_is_rejected`: `as_spec(Language('Doc', 'docs', 'white', None, ('.doc',)))` raises `ValueError` matching `spec_color`.
- `test_every_docs_language_has_a_spec_colour` / `test_only_docs_languages_have_spec_colours`: in `LANGUAGES`, `spec_color is not None` exactly when `category == 'docs'`.
- A helper `_bar_colours() -> list[tuple[str, str]]`: `(lang.name, lang.color)` for every language, `(f'{lang.name} (specs)', as_spec(lang).color)` for every docs language, and `('Other', OTHER_COLOR)`. These are all the colours a bar segment can have.
- `test_every_colour_is_a_valid_rich_colour`: loop over `_bar_colours()` instead of `LANGUAGES`.
- `test_no_new_shared_colours`: group `_bar_colours()` by **resolved** colour, not name. Do it twice: once by `Color.parse(c).get_truecolor(None, True)` (what the card draws) and once by `Color.parse(c).downgrade(ColorSystem.EIGHT_BIT).number` (what a 256-colour terminal draws). In both, the only shared group allowed is `{'C', 'C/C++ Header'}` (`_SHARED_COLOURS`, unchanged). This catches the spec variants, Other vs TOML, and aliases such as `gray50`.
- `test_spec_variant_differs_from_its_docs_language_in_16_colours`, parametrized over the docs languages: the `downgrade(ColorSystem.STANDARD).number` of `lang.color` and `as_spec(lang).color` differ (Markdown: 7 vs 13; reStructuredText: 7 vs 10).
- `test_other_is_unique_in_16_colours`: `OTHER_COLOR`'s standard number (8) differs from every other entry in `_bar_colours()`.

`tests/test_display.py`, rendering the bar through a real colour console so the escape codes are checked:

- Helper `_bar_runs(tally, color_system) -> list[str]`: `display_results(tally, 'proj', console=Console(file=out, force_terminal=True, color_system=color_system, no_color=False, width=100))`. Take the one line containing `BLOCK_CHAR` and return the SGR codes of its runs with `re.findall(r'\x1b\[([0-9;]+)m' + re.escape(BLOCK_CHAR), line)`. Rich merges neighbouring runs with the same style, so a collision shows up either as fewer runs than segments or as two equal codes side by side.
- `test_spec_and_docs_segments_stay_apart`, parametrized over `'standard'`, `'256'`, `'truecolor'`: `aggregate()` Markdown 50 lines plus `as_spec(md)` 40 lines. Expect 2 runs with different codes. Before the fix every mode gives `['37', '37']`.
- `test_other_stays_apart_from_its_neighbour`, same parametrization: Python 93, TOML 6, JSON 1 (JSON falls into Other). Expect 3 runs, each different from the one before it. Before the fix there are 2 runs.
- `test_same_language_in_two_categories_is_labelled` already covers the legend labels; add that the `Markdown (specs)` legend entry carries the spec colour when rendered with colour (the `95`/`38;5;177` code precedes it).

`tests/test_image.py`: no new test. The card colours come from `_rich_color_to_rgb(lang.color)`, and the truecolor-triplet check above is exactly what the card draws. If plan 008 adds a terminal/image agreement test over one `TallyResult`, check that it covers a spec-plus-docs result. If it doesn't, add one there.

### Docs

- `CLAUDE.md`:
  - Core Data Structures: `Language(frozen=True)  # name, category, color, single_line_comment, extensions; spec_color (docs only)`.
  - Key Design Decision 2: `as_spec()` also swaps in `spec_color`, so specs and docs never share a bar colour.
  - "When Adding a New Language": a new docs language must set `spec_color`, a colour no other entry uses, that differs from its docs colour in 16-colour mode. "Pick a colour no other language uses": the test now compares resolved colours across languages, spec variants and Other.
  - Test Structure: recount `test_languages.py` and `test_display.py`. The table's text for `test_languages.py` becomes "valid and unshared colours (languages, spec variants, Other)". Update "all N tests" in Quick Reference.
- `README.md`: nothing describes individual colours, so no change. The hosted screenshots predate this; leave them.
- `change-log.md`, under `0.4.3 - UNRELEASED` → `### Fixed`:
  - Spec and docs Markdown no longer merge into one block in the composition bar. Spec variants of docs languages now have their own colour (Markdown violet, reStructuredText dark sea green), in every terminal colour mode and on the image card.
  - The bar's "Other" segment is now dark grey (`grey37`). It no longer merges with TOML, or with Markdown on 16-colour terminals.
  - `Files:` `src/tallyman/languages.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `tests/test_languages.py`, `tests/test_display.py`, `CLAUDE.md`
  - `Plan:` `plans/009-spec-colours.plan.md`

### Before/after check on this repo

Run it once before the first code change and once after, and paste both into the architect review prompt. `S` is the session scratchpad. `HOME` points the image's Desktop lookup there, so nothing is written to `~/Desktop`:

```bash
S=<scratchpad>/p009; mkdir -p $S/before/Desktop $S/after/Desktop
bar() { FORCE_COLOR=1 COLORTERM=$1 TERM=$2 tallyman . </dev/null | tail -2 | head -1 \
        | sed 's/\x1b/ESC/g' | grep -o 'ESC\[[0-9;]*m' | grep -v 'ESC\[0m' | tr '\n' ' '; echo; }
bar truecolor xterm-256color; bar '' xterm-256color; bar '' xterm
HOME=$S/before tallyman . --image </dev/null; HOME=$S/before tallyman . --image-light </dev/null
# after the change: the same, with HOME=$S/after
```

Expected after (Python, Markdown (specs), Markdown (docs), Other):

| Terminal | Bar codes |
|---|---|
| truecolor | `33  38;5;177  37  38;5;59` |
| 256-colour | `33  38;5;177  37  38;5;59` |
| 16-colour | `33  95  37  90` |

On both PNGs (open them with Read), the 34% specs segment is violet and the 6% docs segment light grey. This was simulated in the scratchpad without touching the repo: the dark card's specs segment drew `#d787ff`, clearly apart from the docs segment's `#c0c0c0`.

### Done when

- On this repo, the before/after check shows four different codes in all three terminal modes, and both cards show violet specs next to grey docs.
- `test_languages.py:174` no longer asserts a shared colour; the new tests above fail on the old code and pass on the new.
- `CLAUDE.md` and `change-log.md` are updated; all checks in "Rules for every phase" are clean.
- Architect review done, valid findings addressed, one commit on `architect-review-fixes`.

## Open questions (Michael's call; defaults let implementation go ahead)

**Confirmed with Michael, 2026-11-10: every default below was chosen.** Implement them as written.


1. **The exact spec colours.** Default `violet` (`#d787ff`) for Markdown (specs) and `dark_sea_green4` (`#5faf5f`) for reStructuredText (specs). If violet is too close to PHP's purple for taste, the most distinct alternative is `deep_pink2` (`#ff005f`, ΔE 35 from Indian red, 16-colour `91`), but it's loud on a large segment.
2. **Recolour Other too (decision 3)?** Default yes, to `grey37`. Leaving `grey50` keeps the TOML/Other merge and the 16-colour `37` collapse. Caveat: SGR `90` (bright black) is nearly invisible on a few themes such as Solarized Dark. That only matters on true 16-colour terminals, and only for the smallest segment.
3. **Field or table?** Default: a `spec_color` field on `Language`. The alternative is a `SPEC_COLOURS = {'Markdown': ..., ...}` dict in `languages.py`, which leaves the dataclass alone but keys colours by name.

## Overlaps with other plans

- **008 (lands first):** `bar_segments()` decides which segments exist. This plan only changes colours, so it doesn't touch segment selection or rounding. Two contact points: wherever 008 leaves the Other colour (use `OTHER_COLOR`), and 008's `BLOCK_CHAR`/encoding changes, which the `_bar_runs()` test helper depends on. Rebase the helper on whatever 008 exports. If 008 adds a terminal/image agreement test, make sure it has a spec-plus-docs case.
- **012 (runs last):** the `Optional[X]` sweep converts `Language.single_line_comment: str | None`. This plan doesn't touch it. 012's doc-drift pass recounts the `CLAUDE.md` test table after every plan; this plan updates the counts it changes anyway.
- **010, 011:** no overlap. The setup TUI doesn't use language colours.

## Noticed, not planned

- On the card, standard Rich colours resolve through Rich's default palette, so Python's `yellow` draws olive `#808000` and `red` (Ruby) `#800000`. In the terminal they follow the user's theme. That's a separate decision about the card palette.
- The card's legend is plain dimmed text with no colour swatches, so segments are matched to names only by order.
- In 16-colour mode the spec colours share a code with one language each: Markdown (specs) and SCSS both drop to 95, reStructuredText (specs) and Shell to 92. They merge only when those happen to sit next to each other in the bar. Decision 4 limits the 16-colour guarantee to docs/spec pairs and Other, so this is accepted (noted in the architect review).
