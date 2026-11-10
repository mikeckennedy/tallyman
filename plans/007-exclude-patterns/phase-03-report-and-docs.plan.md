# Phase 3 - Report and Docs

Covers decision 9 from `00-plan-introduction.plan.md`, plus the documentation for the whole plan.

## Goal

Users can see when patterns removed files, and the README, `CLAUDE.md` and changelog describe the merged-config and pattern rules.

## Report line

### `display.py`

`display_results()` takes `stats: Optional[WalkStats] = None`. When `stats.pattern_files` or `stats.pattern_dirs` is non-zero, print one dim line as the last line of the report, after the percentage bar legend:

```
  Excluded by [exclude] patterns: 12 files, 1 directory
```

- Build it as a `rich.text.Text`, or escape it. `[exclude]` is valid Rich markup syntax and would otherwise be swallowed.
- Singular and plural: `1 file`, `2 files`, `1 directory`, `2 directories`. Leave out a part that is zero: `3 files`, or `1 directory`.
- Print it even when no files were counted. The "No recognized source files found." path is exactly where a too-broad pattern would show, so this line explains it.
- Respect `--no-color` and `NO_COLOR` the same way as the rest of the output.
- Not on the image card. `image.py` doesn't change.

### `cli.py`

Create a `WalkStats()`, pass it to `walk_project()` and then to `display_results()`.

## Docs

### `README.md`

In "Configuration":

- Replace "uses the nearest `.tally-config.toml`" with the merged rule: every config from the repo root down to the scanned directory applies; exclusions add up; for specs the deeper setting wins.
- Explain what `--setup` does with parent configs: they're shown locked and stay in their own files.
- A new "Excluding files by pattern" subsection with the Rust example. Cover:
  - gitignore syntax, relative to the config's directory;
  - a slashless `tests.rs` matches at any depth;
  - a trailing `/` matches directories;
  - a deeper config's `!pattern` can bring a file back, but not gitignored files, excluded directories, hidden directories or the default skips;
  - setup doesn't edit patterns but keeps them;
  - the report line.
- Mention issue #8 (inline `#[cfg(test)]` modules) as the known gap for Rust.

- From the phase 1 review: README.md's "uses the nearest `.tally-config.toml`" line is now false. Also note one asymmetry: a malformed config inside a directory that a parent excludes stops a scan started inside that directory, while a scan from the repo root never reads it.

### `CLAUDE.md`

- Key Design Decision 5 ("Config search walks up"): describe the chain and the merge.
- Mention `[exclude] patterns` and that they use a second `GitIgnoreSpec`.
- Update the test counts in "Test Structure" if they are listed.

### `change-log.md`

Under `0.4.3 - UNRELEASED`:

- Added: `[exclude] patterns`, and the report line.
- Changed: configs merge from the git root to the scan root; `--setup` shows parent settings locked and no longer copies them; nested configs resolve same-path spec conflicts by depth.
- Each with `Files:` and `Plan:` lines in the existing style.

## Tests

`tests/test_display.py`:

- No stats, or zero counts: no extra line.
- `12 files, 1 directory`, `1 file`, `2 directories`: exact wording.
- The literal `[exclude]` appears in the output, so the markup is escaped.
- With no counted files and `pattern_files > 0`: both the "No recognized source files" line and the pattern line print.

`tests/test_cli.py`: an end-to-end run with a pattern prints the line.

## Done when

- The Rust example prints `Excluded by [exclude] patterns: N files`.
- The README describes the merge and the patterns, and its examples work as written.
- All checks in the introduction's rules are clean.
