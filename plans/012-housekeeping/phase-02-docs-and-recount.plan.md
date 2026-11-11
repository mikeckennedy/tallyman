# Phase 2 - Docs and Recount

Covers the "Doc drift" items from the review that no other plan owns, the dead `.R` extension, and a final consistency pass over the counts in `CLAUDE.md` and `README.md` once plans 008 to 012 have all landed.

## Goal

`CLAUDE.md`, `README.md` and the architect persona say what the code does, and every count in them matches the code on the branch.

Take the before report as in phase 1 (fresh snapshot of `HEAD`). This phase changes no output.

## Step 1 - "uses match statements"

Re-check first: `grep -rnE '^\s*match .*:\s*$' src/ tests/` should still print nothing, and `grep -rnE 'except [A-Za-z_.]+, ' src/` shows whether the PEP 758 `except A, B:` survived plan 008 (at 75dd0fd it is at `display.py:27`).

- `CLAUDE.md`, Tech Stack: "**Python 3.14+** (uses match statements, dataclass slots, `tomllib`)" becomes "**Python 3.14+** (uses dataclass slots, `tomllib`, and PEP 758's unparenthesised `except A, B:`)". PEP 758 is the one 3.14-only feature in use, so it is the honest reason for the floor. If plan 008 removed that `except`, drop the PEP 758 clause in both files and say "(uses dataclass slots and `tomllib`)".
- Persona, Tech stack section (`.claude/agents/architect-tallyman.md`, then the same edit in the copy in `plans/006-tallyman-architect.plan.md`): "`match`, dataclass slots, `tomllib`, and PEP 758 unparenthesised `except A, B:` (in `display.py`) are all in use." becomes "Dataclass slots, `tomllib`, and PEP 758 unparenthesised `except A, B:` (in `display.py`) are in use. There are no `match` statements." Update the file name if the `except` moved.
- Run the persona `diff` from the introduction.

## Step 2 - `paths.py` in the module map

`CLAUDE.md`, Module Map, the `paths.py` row becomes:

`relative_posix()`: `/`-separated relative paths, safe on Windows. `canonical_case()`: the scan root spelled as the filesystem stores it

Check `grep -n '^def ' src/tallyman/paths.py` first in case plan 010 added a function; list every public one. If plan 010 already rewrote this row, leave it.

## Step 3 - "On first run" in the README

The rule, from `cli.main()` and `config.find_configs()` (re-read both; plan 011 changes how the TUI is imported but shouldn't change when it runs):

- Setup runs when `--setup` is given, or when no `.tally-config.toml` is found in the scanned directory or any directory above it up to the Git repository's root (outside a repository, only the scanned directory is checked) **and** stdin and stdout are both terminals.
- If any config in that chain exists, even only a parent's, there is no setup; Tallyman counts with the merged configs. Configs in subdirectories of the scanned directory don't count.
- Without a terminal, see `README.md:223` (unchanged).

Edits:

- `README.md:43`, the "Interactive first-run setup" bullet: "On first run, Tallyman launches a TUI where ..." becomes "The first time you run Tallyman in a project, before any `.tally-config.toml` applies, it launches a TUI where ...". Keep the rest of the bullet.
- `README.md:188`, the first paragraph of Configuration, becomes:

  > When no `.tally-config.toml` applies yet, Tallyman starts with an interactive TUI where you can browse your project tree and configure which directories to exclude or mark as spec directories. Your choices are saved to `.tally-config.toml` in the directory you scanned. A config applies if it is in the scanned directory or any directory above it, up to the root of the Git repository (outside a repository, only the scanned directory counts). So once the repository root has a config, `tallyman src/` counts straight away, using it; run `tallyman --setup` there to give `src/` its own config.

  Check the example against the code: with a root config, `tallyman src/` in a terminal must not open the TUI. At 75dd0fd no test pins that: every `interactive=True` run in `tests/test_cli.py` also passes `--setup`. Add `test_a_parent_config_alone_skips_first_run_setup` to `TestConfigFromParentDirectory`: a `.git` dir and a root config, then `_run(monkeypatch, str(tmp_path / 'src'), interactive=True)`. The helper's fake `run_setup` raises when `setup_result` is left `None`, so the test fails if the TUI would launch; also assert the parent's exclusion applied. It passes today and pins what the README now promises. Skip it if plans 008 to 011 added an equivalent.
- Leave `README.md:44` (the gitignore bullet) to plan 010.

## Step 4 - The dead `.R` extension

- `src/tallyman/languages.py`: R's extensions `('.r', '.R')` become `('.r',)`.
- Re-check that nothing else in `LANGUAGES` has an uppercase extension: `grep -nE "'\.[a-z0-9]*[A-Z]" src/tallyman/languages.py` should print nothing once R is fixed.
- `README.md`, the R row in the Code table (line 114 at 75dd0fd): `` `.r`, `.R` `` becomes `` `.r` ``.
- `README.md`, under `<summary>Full language details with file extensions</summary>`, before the first table: "Extensions match in any case, so `analysis.R` is R and `README.MD` is Markdown." Only extensions: filenames such as `Makefile` match as listed (`FILENAME_MAP` is case-sensitive and lists `makefile` and `GNUmakefile` itself).
- `tests/test_languages.py`, two tests:
  - `test_uppercase_r_extension`: `identify_language(Path('analysis.R'))` is R. It passes before and after the change, which is the point: it pins that dropping the key changes nothing.
  - `test_every_extension_is_lowercase`: every extension of every language in `LANGUAGES` equals its `.lower()`. It fails before the change (on `.R`) and stops a dead key coming back.
- `CLAUDE.md`, "When Adding a New Language": add "Extensions are lowercase; lookup lowercases the suffix."

No changelog entry: `.R` files were counted before and still are.

## Step 4b - `.cursor/rules/coding-guidelines.mdc` (added after the plan 009 review)

This tracked file repeats CLAUDE.md's data-structure summary and has drifted: its `Language(frozen=True)` line lacks `spec_color` (plan 009), its `as_spec()` line says only the category changes (it also swaps in `spec_color`), and its `TallyConfig` line lacks `non_spec_dirs` and `patterns`. Bring every data-structure and design line in it in line with CLAUDE.md as it stands after plans 008-011, or, if Michael would rather not maintain two copies, reduce it to a pointer to CLAUDE.md. Default: update it to match.

## Step 5 - Final recount

Run this after everything above, so it includes this plan's new tests (one in phase 1, three in this phase) and anything 008 to 011 added.

```bash
pytest --collect-only -q | tail -1
for f in tests/test_*.py; do printf '%s %s\n' "$f" "$(pytest --collect-only -q "$f" | grep -c '::')"; done
python -c "from tallyman.languages import LANGUAGES; print(len(LANGUAGES))"
pytest | tail -1        # for the timing
```

Then update:

- `CLAUDE.md`, Quick Reference: `pytest  # all N tests (about S s, mostly the Textual pilot tests)`, with the measured count and a rounded time.
- `CLAUDE.md`, Test Structure: every row's count, a row for every test file (including `tests/test_conventions.py` from phase 1 and any file plans 008 to 011 added), and the "Covers" text where a plan added a topic the row doesn't mention. Rows with no test file and test files with no row are both errors.
- `README.md`: both "N languages" counts (lines 52 and 79 at 75dd0fd) against `len(LANGUAGES)`, the category table against each language's category, and "8 template formats" against the HTML template extensions in `languages.py`. None of plans 008 to 011 adds a language, so 43 should hold; check anyway.
- `CLAUDE.md`, module map: "Language registry (40+ languages)" is still true at 43; leave it.
- `change-log.md`: the top heading is still `0.4.3 - UNRELEASED` and matches `version` in `pyproject.toml`.
- Grep the docs for any count this list missed: `grep -nE '\b[0-9]+ (tests|languages|template)' README.md CLAUDE.md .claude/agents/architect-tallyman.md`.

## Tests

- `tests/test_languages.py`: the two tests in step 4.
- `tests/test_cli.py`: `test_a_parent_config_alone_skips_first_run_setup` from step 3, unless an equivalent exists by then.

## Done when

- No doc says tallyman uses `match`; the PEP 758 mention matches the code.
- The `paths.py` row lists both functions.
- The README's first-run text states the config rule, and its example matches what the CLI does.
- `EXTENSION_MAP` has no uppercase keys, the README's R row says `.r`, and the README says extensions match in any case.
- Every count in `CLAUDE.md` and `README.md` matches the commands in step 5.
- The persona's copy in plan 006 matches the persona file.
- The snapshot report matches the before report.
- All checks in the introduction's rules are clean.
