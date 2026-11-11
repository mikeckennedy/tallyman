# Phase 3 - Report Line, Docs and Version

Covers decision 6 from `00-plan-introduction.plan.md`, plus the docs and version for release 0.5.4.

## 1. The report line (`display.py`)

When `TallyResult.rust_test_lines > 0`, the report ends with a dim line:

```
  Excluded by [exclude] patterns: 12 files, 1 directory
  Excluded Rust test code: 2,412 lines in 37 files
```

- Wording: `Excluded Rust test code: {lines} in {files}`, both through `_plural()` (`1 line in 1 file`).
- It comes after the patterns line. The two notes share **one** blank line above them (today `_display_pattern_note()` prints its own blank line; restructure into one `_display_notes()` that collects the notes and prints the blank line once, only when there is at least one note).
- It is printed with `Text`, not markup, like the patterns note.
- It also appears when nothing else was counted (`No recognized source files found.`): a crate whose only `.rs` files are `#![cfg(test)]` files is one way to get there, and the line explains it. Note that `display_results()` returns early in that case; the notes must still be printed there.
- The image card does not get the line. It already shows the reduced numbers.

`display_results()` already receives the `TallyResult`, so no new parameter is needed. Update its docstring (it mentions only the patterns line).

### Tests (`tests/test_display.py`)

- The line appears with the right counts and plurals (`1 line in 1 file`, `2,412 lines in 37 files`).
- It doesn't appear when `rust_test_lines == 0`.
- With both notes: one blank line, patterns first, Rust second.
- With no counted files but some test lines: the line still appears.
- `--no-color` output contains the literal text (no markup swallowed).

## 2. README

- Under `## Configuration`, after `### Excluding files by pattern`, add `### Leaving out Rust test code`:
  - What it does, with the `[rust] exclude_test_modules = true` snippet and a short before/after example of a file with a `mod tests`.
  - What counts as test-only: `#[cfg(test)]` on any item, including `impl` methods; `cfg(all(test, ...))`; `#![cfg(test)]` for a whole file or module. `cfg(any(test, ...))` doesn't, since that code also builds outside tests.
  - What it leaves alone: `#[cfg(test)]` on statements, fields, variants and match arms; `mod tests;` points at a file that `[exclude] patterns` should handle (`patterns = ["tests.rs"]`), unless that file starts with `#![cfg(test)]`. Integration tests in `tests/` are a directory exclude.
  - It applies per directory like every other setting: a nested config (one per crate) can turn it on or off, and `false` overrides a parent's `true`. `--setup` keeps it but has no toggle.
  - The report's `Excluded Rust test code` line.
  - If a file can't be read cleanly (an unterminated string, unbalanced braces around a test module), it is counted in full.
- In `## How It Works`, one sentence where line classification is described: with the option on, Rust test-only items are left out before lines are classified.
- In `## Features`, one bullet.

## 3. `CLAUDE.md`

- **Module map:** add `src/tallyman/rust_tests.py` (`test_code_lines()`: the Rust test-code scanner, a pure function on normalised text). Update `config.py` (`[rust]`, `NestedConfig`), `walker.py` (`walk_files()`, `SourceFile`, per-directory `exclude_rust_tests`), `counter.py` (`exclude_rust_tests`, `test_lines`), `display.py` (the Rust note), `languages.py` (`RUST`).
- **Core data structures:** `FileCount.test_lines`; `TallyResult.rust_test_lines`, `.rust_test_files`; `TallyConfig.rust_exclude_test_modules`; `ConfigChain.rust_exclude_test_modules`; `SourceFile`.
- **Key design decisions:** a new numbered entry, "Rust test code (opt-in)", covering: brace tracking with the lexing rules; item positions only (containers: top level, `mod`, `impl`, `trait`, `extern` bodies); the cfg predicate rule (`all` needs one test-only argument, `any` needs all); inner `#![cfg(test)]`; when in doubt, count; the per-directory value that must never go through `merge_configs()` (the sibling-leak trap); setup preserves the value without a toggle.
- **Architecture** diagram: `walker.walk_files()` yields `SourceFile`; `counter.count_lines()` takes the flag.
- **Test structure table:** add `tests/test_rust_tests.py` and recount every row against `pytest --collect-only -q` (the counts drift; plan 012 recounted them all). Update the total in Quick Reference ("all N tests").

## 4. Changelog and version

- `change-log.md`: new section `## 0.5.4 - UNRELEASED` above `0.4.3`, with an `### Added` entry in the house style (what it does, then `Files:` and `Plan:` lines), one per phase:
  - Phase 1: the scanner (`src/tallyman/rust_tests.py`, `tests/test_rust_tests.py`, `plans/013-rust-test-code/phase-01-scanner.plan.md`).
  - Phase 2: the `[rust] exclude_test_modules` key, issue #8, with its scope and nested-config behaviour.
  - Phase 3: the report line and docs.
- `pyproject.toml`: `version = "0.5.4"` (new feature, so MINOR goes from 4 to 5; the release counter goes from 3 to 4). Then `uv lock`.
- Check the version shows in the report header (`Tallyman v0.5.4`) and that no test pins `0.4.3`.

## 5. Close-out

- Don't post to GitHub or push. Michael merges the branch and closes issue #8 himself. The final summary says the work is ready for review on the `rust-test-code` branch, with the before/after Rust totals from phase 2's manual check.

## Done when

- The line, docs, changelog and version are in; all checks in "Rules for every phase" are clean; the architect review (this time over the whole branch, `main...rust-test-code`) has its valid findings addressed.
- Commit: `Plan 013 phase 3: Rust test-code report line, docs, 0.5.4`.
