# Plan 007 - Exclude Patterns and Merged Configs - Introduction

## Context

GitHub issue #6 asks for gitignore-style file patterns in `.tally-config.toml`:

```toml
[exclude]
patterns = ["tests.rs", "testing.rs"]
```

The motivating case is Rust, which keeps unit tests in `src/` next to the code they test (`src/routing.rs` plus `src/routing/tests.rs`). When that directory also holds real code, a directory exclude can't reach the tests. In the workspace Michael measured, directory excludes reach about 5,600 of the 9,400 lines of test code under `src/`. Patterns would reach roughly another 1,500. The rest is inline `#[cfg(test)]` modules, which is issue #8 and is **not** part of this plan.

This plan also takes on a decision recorded in plan 005's introduction ("Deferred and decided after the branch"): **merge every config from the git root down to the scan root** instead of letting the nearest one win. It goes here because both changes rewrite the same config code.

Deferred to issue #10: a `--exclude PATTERN` command-line flag for one-off runs.

## The code today (after plan 005)

- `config.find_config()` returns the nearest config at or above the scan root, stopping at the git root. Outside a repo, it checks only the scan root.
- `config.rebase_config()` moves a parent config's directory entries onto the scan root. Entries that cover the scan root become `'.'`, and the deeper of a spec entry and an ignore entry wins.
- Nested configs below the scan root are read by the walker as it descends (`load_nested_config`), and by `discover_nested_configs()` for the setup TUI. Their entries are prefixed and unioned.
- `gitignore.GitIgnoreSpec` holds ignore files as `(base, rules)` layers. `base` is relative to the git root, the deepest layer with an opinion wins, and `!` re-includes. Config patterns reuse this class.
- Phase 4's default skips are plain filename checks (`walker._is_generated`), not a pattern list. They stay that way.
- The TUI already shows nested-config settings as locked (`NodeInfo.locked_by_nested`, `SetupApp(nested=...)`).

## Decisions (confirmed with Michael, 2026-11-10)

1. **Merge the config chain.** Load every `.tally-config.toml` from the search stop (git root, or the scan root outside a repo) down to the scan root. Exclusions are a union. For specs, the deeper entry wins, and on the same path the deeper config wins.
2. **Parent settings are locked in setup, not copied.** `--setup` shows them as "(set in a parent config)" and writes only local changes to the scan-root config. This changes today's behaviour, where a new config copied the parent's rebased settings.
3. **Pattern syntax is gitignore syntax**, matched relative to the directory of the config that declares it. A pattern with no slash matches at any depth, so `tests.rs` is enough and `**/` isn't needed.
4. **Patterns layer like nested `.gitignore` files.** A deeper config's `!pattern` can bring back what a shallower config's pattern excluded.
5. **Patterns are exclude-only and separate from gitignore.** A file is out if gitignore, `exclude.directories` or a pattern excludes it. `!` overrides only other config patterns. It can't bring back gitignored entries, excluded directories, hidden directories or the default skips.
6. **Patterns can match directories** (`fixtures/`), with gitignore semantics. `exclude.directories` stays the key the TUI writes; patterns are hand-edited.
7. **Parent patterns never exclude the scan root or the directories above it.** The user asked to scan that directory, which matches how `rebase_config()` drops directory excludes that cover the scan root.
8. **`--setup` preserves hand-written patterns verbatim and in order**, since order matters with `!`.
9. **Report:** one dim terminal line at the end of the report, shown only when patterns excluded something: `Excluded by [exclude] patterns: 12 files, 1 directory`. It counts only files tallyman would otherwise have counted (recognised language, not binary), plus the directories that patterns pruned. It doesn't appear on the image card.
10. **No CLI flag now.** Tracked in issue #10.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-merge-config-chain.plan.md` | Decisions 1, 2; deeper-wins for nested configs |
| 2 | `phase-02-exclude-patterns.plan.md` | Decisions 3-8, including the TUI |
| 3 | `phase-03-report-and-docs.plan.md` | Decision 9; README, `CLAUDE.md`, changelog |

Phase 1 comes first because phase 2's pattern layers need the list of configs in the chain, which phase 1 builds.

## Workflow

- Work on a feature branch, `exclude-patterns`. Commit and push this branch after each phase; Michael asked for pushes on it (2026-11-10). Never commit to or push `main`, never force-push, and leave merging to Michael.
- After each phase, an architect review runs in a sub-agent using the tallyman persona, `plans/agents/architect-tallyman.md` (plan 006). Address its valid findings, then commit.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- New or changed annotations use `Optional[X]`, not `X | None`. Don't convert untouched code; that sweep is plan 006, step 4.
- Each behaviour change lands with a test that fails before the change and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean.
- Add entries under `0.4.3 - UNRELEASED` in `change-log.md` (0.4.3 has not shipped).
- What the setup TUI shows must match what the walker does, at every commit.
