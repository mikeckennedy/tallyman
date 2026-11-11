# Plan 008 - Output and File Hardening - Introduction

## Context

The architect review of main @ 75dd0fd (2026-11-10) found a batch of issues. This plan takes the ones about **what tallyman reads and what it prints**:

- Bug 1: a FIFO (named pipe) with a known extension hangs the walk forever.
- Bug 2: characters the stdout encoding can't represent (cp1252, ascii) crash the run with a traceback.
- Bug 6: when nothing has effective lines, the terminal prints a blank bar and an empty legend, while the image leaves a blank band.
- Bug 7: a small "Other" segment gets 0 cells in the terminal bar but still shows in the legend.
- Bug 8: a `.tally-config.toml` saved with a UTF-8 byte-order mark is rejected with "Invalid statement (at line 1, column 1)".
- Design: the bar and legend selection (main languages, the 2% threshold, "Other") is written twice, in `display.py` and `image.py`, and the "effective lines" rule three times.
- Rule 16: `image.py` imports the private `display._language_display_names`.
- The matching test gaps, including "nothing checks that the terminal and the image agree".

Plans 009-012 come from the same review and land after this one, on the same branch.

### What checking the findings turned up

Every finding above reproduces on main. Checking them turned up three more things this plan also fixes:

- **A FIFO named `.gitignore` hangs too** (`sub/.gitignore` as a FIFO: verified). `GitIgnoreSpec._add_file()` calls `read_bytes()` on it. The same path reads `.git/info/exclude`. Bug 1 is really "tallyman opens files that aren't regular files", and `gitignore.py` is one of those places. Configs are safe because `find_configs()` and the walker test `is_file()` first.
- **`--image` crashes when "Other" is tiny.** In `image.py`, the last segment takes whatever pixels are left. When "Other" is under about 0.1% (a 2,000-line Python project with one 1-line Go file), that leaves 1 px, and `draw.rectangle((x, ..., x + 1 - BAR_GAP, ...))` raises `ValueError: x1 must be greater than or equal to x0` (Pillow 12.1.1: verified). The width fix for bug 7 fixes this as well, so both outputs get one allocator.
- **Bug 2 is narrower than the review says, in one respect.** cp1252 *can* encode the legend's `·` (0xB7). The `·` crash is for ascii-like encodings. Under cp1252, the crash comes from names and paths (`日本`). `sys.stderr` already uses `errors='backslashreplace'`, so only stdout needs reconfiguring.

One more correction: the review's "sums to 101%" under bug 7 comes from rounding each legend entry on its own. That isn't the bug. The bug is the segment with zero width (see decision 6).

## The code today (main @ 75dd0fd)

- `walker.walk_project()` skips symlinked files with `file_path.is_symlink()` (walker.py:206). It then opens matched files in `_is_binary()`: once for the pattern-stats count (walker.py:211) and once for real files (walker.py:219). `counter.count_lines()` only ever sees files the walker yields.
- `display._display_percentage_bar()` (display.py:184-228) and `image.generate_image()` (image.py:156-176, 225-253) each:
  - sort the active categories;
  - call `language_percentages()`;
  - split off languages under `SMALL_LANGUAGE_THRESHOLD` (defined in both modules) into a `(None, pct)` "Other" entry;
  - compute segment widths their own way. The terminal rounds, takes at least 1 cell, and gives the last segment the remainder, which can be 0. The image truncates, takes at least 4 px, and gives the last segment the remainder, which can be 1 px and then crash.
- The image caps its legend at `MAX_LEGEND_ITEMS = 5` and folds the rest into "Other" (`_cap_legend`), but still draws every segment in the bar. So with seven languages, the card shows seven coloured blocks and only five named ones.
- "Effective lines" (`code_lines` with a comment marker, else `total - blank`) is written at aggregator.py:87-90, aggregator.py:123-126 and display.py:142-149.
- `display._can_encode_unicode()` checks only `'─█'`, once, at import time, and picks `-` and `#` when that fails. The legend separator `'  ·  '` is not part of the fallback.
- `config.load_config()` calls `tomllib.load()` on the open file. tomllib rejects a BOM. `gitignore._add_file()` and `counter` both strip one.

## Decisions

Michael's open calls are under "Open questions" below. These follow from the review or from how the code already works:

1. **One shared report model in `aggregator.py`.** Which categories show and in what order, which lines count, which bar segments exist with what label, colour and percentage, and how wide each one is: all of this is computed once there, and `display.py` and `image.py` only draw it. It goes in `aggregator.py`, not in a new module: it is arithmetic on `TallyResult`, and the review suggested that home. The one exception is the "Other" colour, `OTHER_COLOR`, which goes in `languages.py` with the other colours (coordinated with plan 009).
2. **`LanguageStats.effective_lines`** is the single definition of "effective lines". `CategoryStats.effective_lines` stays a field and is filled from it. The aliases `non_blank_non_comment` and `non_blank` go, since nothing else will use them.
3. **`language_display_names()` becomes public, in `aggregator.py`.** It already depends only on `TallyResult` and `CATEGORY_DISPLAY_NAMES`. This fixes rule 16.
4. **Refactor first, fix second.** Phase 1 step A moves the logic with no change to the output. Step B then fixes bugs 6 and 7 once, in the shared code.
5. **No bar when there is nothing to share.** If the bar has no segments (no effective lines, or no lines at all with `--with-spaces`), the terminal prints no blank line, bar or legend. The image draws no bar and doesn't reserve its height. The category totals still print and still say `0 lines`. That is accurate, and a scan with only comments should say so.
6. **Every segment gets width; legend rounding is unchanged.** Widths come from a largest-remainder allocation with a minimum per segment: 1 cell in the terminal, 4 px in the image (more than `BAR_GAP`). The widths always add up to the bar width exactly. Each legend percentage is still rounded on its own, so the legend can add up to 99% or 101%, the way most charts do.
7. **Count only regular files.** One `lstat()` with `stat.S_ISREG` replaces `is_symlink()` and also rules out FIFOs, sockets and devices. It runs before the pattern-stats check, which also opens files. `.gitignore` and `info/exclude` are read only when `is_file()` is true. That check follows a symlink, as today, so whether an in-tree `.gitignore` symlink should be followed is unchanged. That fidelity question belongs to plan 010.
8. **Never crash on output encoding.** At the start of `cli.main()`, if `sys.stdout` is an `io.TextIOWrapper`, call `reconfigure(errors='replace')`. Characters the encoding can't show become `?`, like the control characters in the header. The ASCII fallback probe also checks `·`. When it fails, the legend separator is `'  |  '`. `stderr` is left alone: Python already sets it to `backslashreplace`.
9. **A config with a byte-order mark loads.** Decode with `encoding.text_encoding()`, the rule the counter already uses, then call `tomllib.loads()`. `save_config()` keeps writing UTF-8 without a BOM, so `--setup` drops one.

## Open questions (recommended defaults; implementation goes ahead with them unless Michael says otherwise)

**Confirmed with Michael, 2026-11-10: every default below was chosen.** Implement them as written.


1. **Image card with more than five languages: fold the bar too?** Today the bar draws every segment but the legend names only five. **Recommended: fold in both.** `bar_segments(..., max_languages=MAX_LEGEND_ITEMS)` folds languages past the fifth into "Other", so every coloured block on the card has a legend entry, and the agreement test can say "image = terminal, folded after five". The alternative keeps today's bar and folds only the legend.
2. **Tiny percentages in the legend.** Today an "Other" of 0.3% reads `Other 0%`, next to a 1-cell segment. **Recommended: `<1%`**, and `>99%` for a language that rounds to 100% while something else is listed. Both outputs use one `percent_label()`.
3. **UTF-16/32 configs.** Windows PowerShell 5.1's `>` and `Out-File` write UTF-16 LE with a BOM by default, so a hand-made config can easily arrive that way. **Recommended: accept any BOM** through `text_encoding()` (decision 9), which matches how source files are read. The stricter option accepts only a UTF-8 BOM (`utf-8-sig`), since TOML says UTF-8.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-shared-report-model.plan.md` | Design item, rule 16, bugs 6 and 7, the image crash on a tiny "Other", open questions 1-2, terminal/image agreement test |
| 2 | `phase-02-files-stdout-config.plan.md` | Bugs 1 (including `.gitignore` FIFOs), 2 and 8, open question 3, README note |

They are independent, apart from phase 2 touching the legend code that phase 1 rewrites. Do them in order.

## Workflow

- All plans 008-012 land on one feature branch, `architect-review-fixes` (cut from main @ 75dd0fd). Claude owns the branch and commits after each phase. **Never push** (unlike plan 007, there is no push permission here), never commit to `main`, and leave merging to Michael.
- After each phase, an architect review runs via the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Address its valid findings, then commit.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- New or changed annotations use `Optional[X]`, not `X | None`. This plan deletes two of the seven `X | None` (display.py:195, image.py:114) by replacing that code. Leave the rest to plan 012's sweep.
- Write new test functions with `-> None` (plan 012 adds it everywhere else).
- Each behaviour change lands with a test that fails before the change and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean.
- Changelog entries go under the existing `0.4.3 - UNRELEASED` heading in `change-log.md`, with `Files:` and `Plan:` lines in the existing style. No version bump.
- When test counts change, update the table in `CLAUDE.md` "Test Structure" and the total in "Quick Reference" (`pytest  # all 474 tests`).

## Overlap with the other plans

- **009 spec-colours** changes `as_spec()` colours and recolours "Other". After this plan, every bar colour comes from `BarSegment.color`: either `language.color`, or `languages.OTHER_COLOR`, which this plan adds as `'grey50'` and is the only definition. So 009 changes "Other" by editing that one value to `grey37`, and adds no second constant. The agreement test here includes a specs-plus-docs result (docs Markdown plus Markdown under `plans/`, built through the walker), and its tree helper is shared so 009's tests can build on it.
- **010 git-fidelity** owns `gitignore.py`. This plan adds a single `is_file()` guard to `GitIgnoreSpec._add_file()` (decision 7) and changes nothing else there. If 010 rewrites how `info/exclude` is found for worktrees and submodules, it should keep that guard. Git doesn't follow in-tree `.gitignore` symlinks, so 010 may want to look at those too.
- **011 setup TUI** touches the top of `cli.py`, where Textual is imported lazily. This plan adds `_tolerate_unencodable_stdout()` at the top of `main()`. Small textual conflict at most.
- **012 housekeeping** runs last. This plan removes `Language | None` from display.py and image.py and adds `-> None` to its own tests, so 012 has fewer to sweep. 012's `CLAUDE.md` drift pass should start from the module-map and Key Design Decision 4 edits made here.

## Not in this plan

- Totals label: the terminal says `Combined:` and the image says `Total:`. That is a wording choice, not a disagreement in the numbers, and is left alone.
- Multi-line legends or wrapping on the image card.
