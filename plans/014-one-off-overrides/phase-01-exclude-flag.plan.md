# Phase 1 - `--exclude PATTERN`

Covers decisions 1-7 and 11 from `00-plan-introduction.plan.md`. Closes issue #10.

## 1. A last-word layer in `GitIgnoreSpec` (`gitignore.py`)

Command-line patterns must beat every config layer, including nested layers the walker and setup add later (decision 3). Today `_add_lines()` sorts layers by depth only.

- Add a keyword to `add_rules()`: `add_rules(config_dir, lines, *, final: bool = False)`. A final layer is registered under its own source name (`'<command line>'`, so it never collides with the scan root's `'<config>'` layer in `_loaded`) and sorts after every non-final layer, whatever its depth. Implementation: carry the flag in `_files` entries (or keep final layers in a separate list that `_is_ignored()` reads after `_files`); keep the sort stable.
- `match_file()`'s fast path (`if not self._files ...`) must see final layers too.
- Docstrings: `for_patterns()` and `add_rules()` say what a final layer is and that it's for `--exclude`.

### Tests (`tests/test_gitignore.py`, in the config pattern layers section)

- A final layer at the root beats a deeper layer's `!`, whether the deeper layer was added before or after it.
- A final layer's `!` re-includes what any config layer excluded.
- Within the final layer, the last matching pattern wins.
- A final layer at the root and the root's own config layer both register (no `_loaded` collision).
- Directory-only (`tests/`), anchored (`/src/gen`, `src/gen/`) and `**` patterns behave in the final layer exactly as in a config layer.

## 2. Parsing and validation (`cli.py`)

- `parser.add_argument('--exclude', action='append', default=[], metavar='PATTERN', help=...)`. Help text along the lines of: `Leave out files matching a gitignore-style PATTERN for this run (repeatable; never saved)`.
- A private `_check_exclude_patterns(patterns: list[str]) -> None` runs before any config is loaded or setup opens. For each value, in order, the first problem found exits 2 via `parser.error()`-style output (`Error: ...` on stderr, exit 2, matching the existing `--setup needs an interactive terminal` error):
  - contains `\n` or `\r`: `--exclude takes one pattern per flag; {value!r} spans lines`;
  - empty or whitespace only: `--exclude '' is empty`;
  - starts with `#`: `--exclude '#gen' is a comment in gitignore syntax; write '\#gen' to match a name starting with #`;
  - anything else `_parse_line()` returns None for (a lone `!`, `/`, `!/`, a pattern that can't compile): `--exclude {value!r} can never match anything`.
- Export what the check needs from `gitignore.py` without making `_parse_line` public by name: add `def is_live_pattern(line: str) -> bool` (True when `_parse_line(line)` is not None) and use it after the specific checks.
- Note that gitignore trims trailing spaces unless escaped (`'gen '` is `gen`); that's accepted, as in a config.

## 3. Wiring (`cli.py`)

- After the three-way `if config_paths and not args.setup / elif not interactive / else` block, and **after** `run_setup()` returns, add the layer once:

  ```python
  if args.exclude:
      exclude_patterns.add_rules(root, args.exclude, final=True)
  ```

  Adding it before `run_setup()` would show the patterns in setup (the spec object is shared with the TUI), which decision 5 rules out. Put a one-line comment there saying so.
- `save_config()` is untouched: it already writes `chain.local.patterns`, so command-line patterns are never saved.
- The walker needs no change: it reads the spec it is given, and its `WalkStats` counts already include the new layer, so the footer (decision 6) needs no change either. Check that `display.display_results()`'s docstring and `_pattern_note()`'s docstring still describe it; reword them to mention `--exclude` if they say "config".

## 4. Tests (`tests/test_cli.py`)

A new `TestExcludeFlag` class, end to end through `main()` like the existing CLI tests:

- One `--exclude` removes a file; two remove both; the footer counts them (`Excluded by [exclude] patterns: 2 files`).
- A directory pattern (`tests/`) removes the directory and counts it as a directory.
- Anchored at the scan root: run on a subdirectory path from elsewhere (`tallyman <tmp>/proj --exclude 'src/gen/'`), and from a cwd that isn't the scan root.
- `!` brings back a file the scan root's config pattern excluded, and a file a **nested** config's pattern excluded.
- A nested config's `!tests/` doesn't bring back what `--exclude 'tests/'` removed (decision 3).
- `!` doesn't bring back an `[exclude] directories` entry, a gitignored file, a hidden directory, or a generated file (decision 4).
- Never saved: after a run with `--exclude`, the config file is byte-for-byte unchanged.
- With `--setup` through `_real_setup`: the setup tree doesn't label the matched directory `(excluded by pattern)`, the saved config has no trace of the pattern, and the count after setup still leaves it out. Same for a first run with no config.
- With no config and no terminal (the defaults path): `--exclude` still applies.
- Validation: each error case from section 2 exits 2 with its message, writes nothing, and opens no setup (also with `--setup`). An escaped `'\#gen'` is accepted and matches `#gen`.
- `--help` lists `--exclude PATTERN`.

`tests/test_walker.py` needs one test: a spec with a final layer passed to `walk_files()` beats a nested config's `!` met during the walk, and `WalkStats` counts it.

## 5. Docs and version

- `README.md`:
  - Usage block: `tallyman --exclude 'tests/'` with a one-line comment.
  - Under `### Excluding files by pattern`, a short `#### For one run: --exclude` part: repeatable, gitignore syntax anchored at the scan root (`./src` matches nothing; write `src/` or `/src`), beats every config pattern including nested ones, `!` undoes only patterns, never saved, ignored by `--setup`, counted in the same footer line, and the dead-pattern errors. Mention the Rust case: `--exclude 'tests.rs'` for `mod tests;` files.
  - `## Features`: extend the patterns bullet or add one.
- `CLAUDE.md`: Quick Reference (`tallyman --exclude 'tests/'`), module map rows for `cli.py` and `gitignore.py`, decision 8 (the final layer, its sort, why it's added after setup), the test table and total.
- `.cursor/rules/*.mdc` and the architect persona (`plans/006-tallyman-architect.plan.md` plus the gitignored `.claude/agents/architect-tallyman.md`): the same facts where they describe patterns and the CLI.
- `change-log.md`: a new `## 0.6.5 - UNRELEASED` section above `0.5.4 - UNRELEASED`, with an `### Added` entry in the house style (what it does, then `Files:` and `Plan:` lines), naming issue #10.
- `pyproject.toml`: `version = "0.6.5"`, then `uv lock`. Check no test pins `0.5.4` and the header reads `Tallyman v0.6.5`.

## Done when

All checks in "Rules for every phase" are clean, the architect review's valid findings are addressed and recorded below, and the phase is committed: `Plan 014 phase 1: --exclude PATTERN for one-off exclusions`.
