# Hardening Plan - Introduction

## Context

A correctness review on 2026-11-10 (tallyman 0.3.3, `main` at `ba295bd`) established a baseline before new feature work.

**What is solid:** the counting pipeline. On this repo tallyman reports 2,650 Python lines / 2,078 effective, which matches an independent `wc` / `grep` count exactly. All 128 tests pass.

**What is not:** deciding *which* files get counted, and the edges around config and the TUI. Every finding below was reproduced in a temp directory, except the Windows item, which was read from the code only.

## Findings

IDs are referenced from the phase files.

### Change the numbers silently

| ID | Finding | Where |
|----|---------|-------|
| H1 | `.gitignore` files below the scan root are never read. A `sub/.gitignore` with `generated/`, or a `venv2/.gitignore` with `*` (what uv and virtualenv write), is ignored and those files are counted. | `walker.py` `load_gitignore` |
| H2 | `.gitignore` files between the git root and the scan root are concatenated into one spec matched from the git root, so their patterns are anchored to the wrong directory. Scanning `repo/sub` with `sub/.gitignore` = `/build`: `sub/build/` is still counted. With `sub/.gitignore` = `/sub/keep.py`: `sub/keep.py` is wrongly ignored. | `walker.py` `load_gitignore` |
| H3 | A config found in a parent directory is applied as if its paths were relative to the scan root. Parent config excludes `src/vendor` and `docs`; `tallyman proj/src` still counts `src/vendor` and silently drops `src/docs`. A stray config in any ancestor (e.g. `~`) also suppresses first-run setup. | `config.py` `find_config`, `cli.py` |
| H4 | Un-marking an auto-detected spec directory in the TUI does not stick. The walker re-detects `specs`/`plans`/`specifications`/`agents` by name unconditionally and the config cannot express "not specs". | `walker.py`, `tui/setup_app.py`, `config.py` |

### Crashes and hangs

| ID | Finding | Where |
|----|---------|-------|
| H5 | First run with no config and no TTY (CI, pipes) launches the TUI, dumps escape codes and never exits. | `cli.py` |
| H6 | A malformed root `.tally-config.toml` produces a raw `TOMLDecodeError` traceback. Nested configs are guarded; the root one is not. | `cli.py` |
| H7 | `save_config` does not escape strings. A directory name containing `"` or `\` writes a config that fails to load on the next run. | `config.py` `save_config` |

### Smaller issues

| ID | Finding | Where |
|----|---------|-------|
| H8 | Hand-edited config paths such as `"vendor/"` or `"./static"` silently match nothing (exact string equality). | `config.py` `load_config` |
| H9 | Rich markup in directory names is interpreted: `my[bold]proj` prints as `myproj`, `proj[/red]` prints as `red]`. | `display.py` `_display_report_header` |
| H10 | TUI: `x` on the root node writes `""` into the config and excludes every subdirectory, while root-level files are still counted. | `tui/setup_app.py` |
| H11 | TUI: when setup is reopened, children of an already-excluded directory show a green check. | `tui/setup_app.py` `_populate` |
| H12 | File selection: `.tally-config.toml` counts itself as TOML when not gitignored; `package-lock.json` and `*.min.js` are counted; symlinked files are counted twice; `.github/` is never counted (hidden directories are skipped). | `walker.py` |
| H13 | Language identification: any name starting with `Dockerfile` is Docker (`Dockerfile.md`, `Dockerfiles.py`); `docker-compose.override.yml` is YAML while `docker-compose.yml` is Docker. | `languages.py` `identify_language` |
| H14 | Counter: a form feed counts as a line break (4 lines where `wc` says 3); a UTF-8 BOM hides a first-line comment; UTF-16 files are silently skipped as binary. | `counter.py`, `walker.py` `_is_binary` |
| H15 | Windows (not run, read from code): relative paths are built with `str(Path)`, giving `a\b/c`. Exclusions two or more levels deep and spec-directory cascading would not match the `/`-separated config paths. | `walker.py`, `config.py` |
| H16 | `_is_binary` reads the whole file to inspect 8 KB, then `count_lines` reads it again. | `walker.py` |

### Hygiene

| ID | Finding |
|----|---------|
| H17 | `ruff check` fails with one E501 at `languages.py:57`; `ruff format --check` wants to reformat `display.py`. |
| H18 | `ruff.toml` takes precedence over `[tool.ruff]` in `pyproject.toml`, so that block (including the `W` rules) is dead. |
| H19 | No tests for `cli.py`, `display.py` or the TUI, which is where H3-H7 and H9-H11 live. |
| H20 | `CLAUDE.md` is stale (says 84 tests; omits the DevOps category and `image.py`). The README lists `;` as a comment style but no language uses it. |

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-gitignore-correctness.plan.md` | H1, H2, H15 |
| 2 | `phase-02-config-handling.plan.md` | H3, H5, H6, H7, H8 |
| 3 | `phase-03-spec-overrides-and-tui.plan.md` | H4, H10, H11 |
| 4 | `phase-04-counting-and-display-edges.plan.md` | H9, H12, H13, H14, H16 |
| 5 | `phase-05-hygiene-and-coverage.plan.md` | H17, H18, H19, H20 |

Phases 1-3 are ordered by impact on reported numbers and should land first. Phases 4 and 5 are independent of each other. Phase 5's test additions for `cli.py` and the TUI are easier once phases 2 and 3 have settled the behaviour.

## Decisions (confirmed 2026-11-10)

1. **Parent config (phase 2):** rebase the parent config's paths onto the scan root.
2. **How far `find_config` walks up (phase 2):** stop at the git root when inside a repo; outside a repo, check only the scan root.
3. **No TTY and no config (phase 2):** run with defaults, write no config, print a one-line note on stderr.
4. **Config key for "not specs" (phase 3):** `[specs] ignore = [...]`.
5. **Default file skips (phase 4):** always skip `.tally-config.toml`, `package-lock.json` / `npm-shrinkwrap.json`, and `*.min.js` / `*.min.css`. During phase 4, `pnpm-lock.yaml` was added on the same rationale, pending Michael's confirmation. `.github/` stays uncounted (hidden directories are skipped); document that in the README.

## Deferred and awaiting decision

Each item is collected from the phase outcomes.

- **Nearest config wins** (phases 2 and 3, needs a decision).
  - A closer config hides a parent's exclusions, and an intermediate config hides a root config's spec entries for the scan root.
  - The fix would fold every config from the git root down, but then setup could no longer remove a parent's entry from the TUI.
  - Decide alongside issue #6 (pattern excludes).
- **`pnpm-lock.yaml` skip** (phase 4, needs confirmation). It is beyond decision 5's explicit list.
- **Shared language colours** (phase 5, needs a decision).
  - Rust and HTML (`dark_orange`), and C++ and R (`bright_blue`), predate the colour rule.
  - They are allowlisted in `test_no_new_shared_colours`. C and C/C++ Header sharing `steel_blue` looks deliberate.
- **Known gitignore differences** (phase 1):
  - matching is case-sensitive;
  - the global `core.excludesFile` isn't read;
  - `?` matches a character, not a byte;
  - tracked-but-ignored files are skipped.
- **Counting limits** (phase 4):
  - UTF-16 without a BOM is skipped as binary;
  - hard links count twice;
  - the image font has no CJK or emoji glyphs;
  - all-non-ASCII directory names give the slug `tallyman-report`.
- **Annotations.** The `X | None` to `Optional[X]` sweep is plan 006, step 4.

## Workflow

Work happens on the `hardening` branch. After each phase, a Python Architect review runs in a sub-agent, its valid findings are addressed, and the phase is committed on the branch. Nothing is pushed or merged.

## Rules for every phase

- Commit each phase on the `hardening` branch once its review findings are addressed. Never commit to `main`, never push.
- Follow the conventions in `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- Each fix lands with a test that fails before the change and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/` and `ruff format --check src/ tests/` all clean.
- Add an entry under `UNRELEASED` in `change-log.md`.
