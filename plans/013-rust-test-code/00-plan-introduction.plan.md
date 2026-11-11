# Plan 013 - Leave Rust `#[cfg(test)]` Code Out of the Count - Introduction

## Context

GitHub issue #8. Rust keeps most unit tests in an inline module at the bottom of the file it tests:

```rust
pub fn parse(input: &str) -> Thing { ... }

#[cfg(test)]
mod tests {
    use super::*;
    // often hundreds of lines
}
```

Tallyman counts those lines as Rust code. Directory excludes can't remove them, and neither can `[exclude] patterns` (issue #6, plan 007), because the tests share a file with the real code. On the workspace Michael measured, inline test modules were about 2,400 of 23,000 Rust lines, roughly 10%. Plan 007 left this case out on purpose; this plan finishes the job.

The goal: an opt-in setting that leaves test-only Rust code out of the count, so tallyman measures the code that ships.

```toml
[rust]
exclude_test_modules = true
```

## The code today (after plan 012, release 0.4.3)

- `counter.count_lines(path, language)` reads the bytes, decodes them (BOM-aware), normalises `\r\n` and lone `\r` to `\n`, splits on `\n`, and classifies each line as blank, comment (`stripped.startswith(marker)`) or code. It knows nothing about configs.
- `config.TallyConfig` holds path-keyed sets plus `patterns`. `merge_configs()`, `prefixed()`, `rebase_config()` and `without_copies()` move or combine path entries and return no patterns: patterns stay attached to their file and travel as `ConfigChain.pattern_layers`. This plan's setting follows that precedent.
- `load_config_chain()` loads every config from the git root down to the scan root. `ConfigChain.local` is the scan root's own config; `inherited` is everything above it, merged and rebased.
- `walker.walk_project()` yields `(Path, Language)`. It reads nested configs as it descends (`load_nested_config()`) and folds their path entries into one `active` config with `merge_configs()`. That works for path-keyed entries but **not for a scalar**: a sibling crate's setting would leak into crates walked after it. The walker already keeps one per-directory value, `states: dict[str, SpecState]`; the new setting needs the same treatment.
- About 50 tests unpack `walk_project()` results as 2-tuples (`for p, _ in walk_project(...)`).
- `save_config()` rewrites the whole file, so setup drops any table it doesn't write. Plan 007 had to thread `patterns` through for this reason; `[rust]` needs the same.
- `display._pattern_note()` writes the dim `Excluded by [exclude] patterns: ...` line at the end of the report, even when nothing else was counted.
- The setup TUI reads nested configs through `load_nested_config()` too (`setup_app._populate()`), so a change to its return shape touches both callers.
- Rust is `Language('Rust', 'code', 'dark_orange', '//', ('.rs',))` in `languages.py`, with no module-level name.

## Decisions (confirmed with Michael, 2026-11-11)

1. **Opt-in, one key:** `[rust] exclude_test_modules = true`. Default off. One table per language leaves room for later language options. The name stays as the issue wrote it, although it covers any test-only item (decision 3), not only modules.
2. **Brace tracking, not "stop at the first `#[cfg(test)]`".** A small Rust-aware scanner finds where each test-only item ends, so code after a test module still counts. It skips brackets inside strings, raw strings, byte and C strings, char literals (told apart from lifetimes and labels) and nested block comments.
3. **Any item, not only `mod`.** `#[cfg(test)]` on a `mod`, `fn`, `impl`, `use`, `struct`, `const`, macro invocation and so on drops that whole item. This includes associated items inside `impl` and `trait` bodies (test-only helper methods). Attributes on statements inside function bodies, struct fields, enum variants and match arms are out of scope and stay counted (phase 1 explains why).
4. **Test-only cfg forms:** `cfg(test)`, `cfg(all(.., test, ..))`, and an inner `#![cfg(test)]`, which makes the whole file (or the whole enclosing `mod { }`) test-only. `cfg(any(test, ..))` is **not** test-only, since that code also builds outside tests. Precisely: a predicate is test-only if it is `test`, an `all(...)` with at least one test-only argument, or an `any(...)` whose arguments are *all* test-only. `not(...)` never is.
5. **The whole config chain applies, nested configs included.** Parent configs, the scan root's config and nested configs (one per crate, say) can each set it, `true` or `false`. The deepest config that sets it wins for its directory and everything below, like every other tallyman setting.
6. **Report:** a dim terminal line after the patterns note, shown only when something was left out: `Excluded Rust test code: 2,412 lines in 37 files`. Terminal only; the image card is unchanged apart from its numbers.
7. **Setup has no toggle.** *(Changed in phase 4: `r` toggles it when the project has Rust code; the rest stands.)* The key is hand-edited like `[exclude] patterns`. `--setup` writes the scan root's own value back unchanged (including an explicit `false`, which overrides a parent).
8. **`#[cfg(test)] mod tests;` drops only that declaration.** The file it points at is left to `[exclude] patterns` (issue #6), or drops out on its own if it starts with `#![cfg(test)]`. Counting stays one file at a time.
9. **When in doubt, count.** If the scanner can't make sense of a file (an unterminated string or comment, or unbalanced brackets around a test item), that file is counted in full, as it is today.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-scanner.plan.md` | Decisions 2, 3, 4, 8, 9: the pure scanner module and its table tests |
| 2 | `phase-02-config-and-counting.plan.md` | Decisions 1, 5, 7: config, chain, walker, counter, CLI, save |
| 3 | `phase-03-report-and-docs.plan.md` | Decision 6; README, `CLAUDE.md`, changelog, version |
| 4 | `phase-04-setup-toggle.plan.md` | Added later: an `r` toggle in setup, shown only with Rust code |

Phase 1 is a pure function with no config or I/O, so it can be built and tested exhaustively before anything calls it. Phase 2 wires it in. Phase 3 makes the result visible and documents it.

## Workflow

- Work on a feature branch, `rust-test-code`, created from `main`. Claude owns the branch and commits after each phase (CLAUDE.md). Never commit to `main`, **never push**, and leave merging to Michael.
- After each phase, run an architect review with the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Address its valid findings, then commit the phase.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, full type hints (`-> None` on tests), `Optional[X]` never `X | None`, `_prefixed` private helpers, 120-char lines.
- Each behaviour change lands with a test that fails before the change and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` (also clean with `--min-severity=warn`) all clean.
- Changelog entries go under a new `0.5.4 - UNRELEASED` section (0.4.3 has shipped; this is a new feature, so MINOR goes up and the release counter goes to 4).
- What the setup TUI shows must still match what the walker does at every commit. This feature doesn't change which files are walked, only how Rust lines are counted, so the TUI needs no new labels.

## Out of scope

- Following `mod tests;` to the file it declares (decision 8).
- `#[cfg(test)]` on statements, expressions, fields, variants and match arms.
- `#[cfg_attr(test, ...)]`: it changes attributes, not whether code exists.
- Integration tests under `tests/`, benches and examples: directory excludes already handle those.
- Similar options for other languages. The `[rust]` table name leaves room for them.
