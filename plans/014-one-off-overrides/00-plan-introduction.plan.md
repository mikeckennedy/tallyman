# Plan 014 - One-Off Overrides on the Command Line - Introduction

## Context

GitHub issue #10, a follow-up to #6 (plan 007). Sometimes you want to leave files out of a single run without editing `.tally-config.toml`, for example to see how big a project is without its tests:

```bash
tallyman --exclude 'tests.rs' --exclude 'tests/'
```

Plan 013 (issue #8) added `[rust] exclude_test_modules` and left `mod tests;` files to `[exclude] patterns`, so the same one-off need now exists for the Rust setting too. Michael asked for both in this plan: `--exclude PATTERN` (phase 1) and `--exclude-rust-tests` / `--no-exclude-rust-tests` (phase 2).

## The code today (after plan 013, version 0.5.4, unreleased)

- `cli._pattern_spec(root, layers)` builds the `[exclude] patterns` spec from `ConfigChain.pattern_layers`: `GitIgnoreSpec.for_patterns(root)`, then one `add_rules(config_dir, patterns)` per config, shallowest first. All three paths in `main()` (a config, no terminal, setup) build `exclude_patterns` this way.
- In the setup path the **same spec object** goes to `run_setup()`, and the TUI adds nested configs' patterns to it as it builds the tree (`setup_app._populate()`). The walk then reuses it; re-adding a layer is a no-op (`_loaded` is keyed on `(base, source)`, and config layers use the source `'<config>'`).
- `GitIgnoreSpec._add_lines()` keeps layers sorted by depth (shallowest first), and `_is_ignored()` lets the last layer with an opinion win, so the deepest layer wins. The walker adds nested configs' layers as it descends.
- `_parse_line()` returns None for blanks, comments, a lone `!` or `/`, and patterns it can't compile; those lines are dropped silently.
- The walker checks, in order: hidden, `[exclude] directories`, gitignore, generated/non-regular, then patterns. A `!` pattern can only undo another pattern (decision 8 in `CLAUDE.md`). `WalkStats` counts what patterns removed, and `display._pattern_note()` prints `Excluded by [exclude] patterns: N files, M directories`.
- The Rust setting reaches the walker as `walk_files(..., exclude_rust_tests=chain.rust_exclude_test_modules)`; the walker's per-directory `rust_tests` map lets a nested config's `[rust]` change it for its subtree.
- `build_parser()` has `path`, `--setup`, `--no-color`, `--image`, `--image-light`, `--with-spaces`, `--version`. No short options.

## Decisions (confirmed with Michael, 2026-11-11)

1. **`--exclude PATTERN`, repeatable, no short form.** Each value is one gitignore-style pattern, as one line of `[exclude] patterns` would be.
2. **Anchored at the scan root.** `tallyman ../proj --exclude 'src/gen/'` means `../proj/src/gen`, as a pattern in the scan root's own config would.
3. **The command line wins everywhere.** `--exclude` patterns are the last word across the whole tree, beating every config's patterns at any depth (a crate's `!tests/` can't bring back what `--exclude 'tests/'` removed). In the spec, the command-line layer always sorts after every config layer, including nested layers added later during the walk.
4. **Same `!` rule as config patterns.** `--exclude '!vendor/'` undoes only patterns (config or command line). It can't bring back `[exclude] directories`, gitignored, hidden or generated entries. The walker's check order doesn't change.
5. **Never saved, and setup ignores them.** With `--setup` (or a first run, where setup opens anyway) the TUI shows and saves only what the configs do. The command-line patterns apply to the count that runs after setup.
6. **One footer line.** What `--exclude` removed is counted in the existing `Excluded by [exclude] patterns: ...` line, wording unchanged.
7. **A pattern that can never match is an error, exit 2.** An empty or whitespace-only value, a comment (`#gen`), and anything else `_parse_line()` drops (a lone `!` or `/`, a pattern it can't compile) stop the run before anything is counted, with a message that says why (for a comment: write `\#gen` to match a name starting with `#`). A value containing a newline or carriage return is an error too, since it isn't one line.
8. **`--exclude-rust-tests` / `--no-exclude-rust-tests`** (argparse `BooleanOptionalAction`, default None = no override), named after the config key. They override `[rust] exclude_test_modules` for one run.
9. **The Rust flag wins everywhere,** as `--exclude` does: every Rust file in the tree gets the flag's value, and nested configs' `[rust]` values are ignored for that run.
10. **Setup ignores the Rust flag too.** The setup line shows, and `r` edits, the config's value; the saved value is the config's. The count after setup uses the flag.
11. **Version 0.6.5.** A new MINOR, with its own `## 0.6.5 - UNRELEASED` changelog section above `0.5.4 - UNRELEASED`.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-exclude-flag.plan.md` | Decisions 1-7, 11: `--exclude`, its spec layer, validation, setup, docs, version |
| 2 | `phase-02-rust-flag.plan.md` | Decisions 8-10: `--exclude-rust-tests` / `--no-exclude-rust-tests`, docs |

Each phase updates the docs for what it adds, so the branch is consistent at every commit.

## Workflow

- Work on the feature branch `one-off-overrides`, created from `main` after PR #13 merged. Claude owns the branch and commits after each phase (`CLAUDE.md`). Never commit to `main`. Push and open a PR only when Michael asks.
- After each phase, run an architect review with the `architect-tallyman` sub-agent. Address its valid findings, record them in the phase file under "Review findings", then commit the phase.
- Install with `uv pip install -e ".[dev]"`; never `uv sync`.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, full type hints (`-> None` on tests), `Optional[X]` never `X | None`, `_prefixed` private helpers, 120-char lines.
- Each behaviour change lands with a test that fails before the change and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` (also clean with `--min-severity=warn`) all clean.
- What the setup TUI shows must still match what the walker does **for the configs**. Command-line overrides are deliberately invisible to setup (decisions 5 and 10); the parity tests between setup and the walker must keep passing without flags.
- Recount the `CLAUDE.md` test table against `pytest --collect-only -q` and update the Quick Reference total.

## Out of scope

- Running without storing a config file (issue #5).
- Command-line overrides for `[exclude] directories` or `[specs]`.
- Rewriting `./src`-style patterns: `--exclude` takes gitignore syntax as is, where `./src` matches nothing (the README says to write `src/` or `/src`).
- Showing the overrides on the image card. Its numbers already reflect them.
