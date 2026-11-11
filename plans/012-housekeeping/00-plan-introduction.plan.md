# Plan 012 - Housekeeping - Introduction

## Context

The architect review of main @ 75dd0fd (2026-11-10) found a batch of issues, now split into plans 008 to 012. This plan takes the rule violations and the doc drift: review items 13 and 14, the "Doc drift" section, and the two Pyrefly warnings in `tests/test_setup_app.py`. None of it changes what tallyman counts or prints.

It is implemented **last**, after plans 008 (output hardening), 009 (spec colours), 010 (git fidelity) and 011 (setup TUI). Those plans add and move code, so every count and line number below is a snapshot of 75dd0fd. Each step says what to grep for at implementation time; trust the grep, not the snapshot.

This plan also finishes plan 006, step 4 (the `Optional` sweep), which was deferred there (plan 006, decision 5).

## The code today (main @ 75dd0fd)

Measured with Ruff 0.14.14 (the venv) and 0.17.4 (`uvx ruff`), which agree:

- **`X | None`:** 7 annotations, the same 7 the review lists: `src/tallyman/walker.py:119`, `display.py:195`, `image.py:114`, `image.py:165`, `languages.py:17`, `tests/test_aggregator.py:8`, `tests/test_counter.py:11`. No `Union[X, None]`. No Ruff rule prefers `Optional`; `UP045` enforces the opposite, and `ruff.toml` selects only `E`, `F`, `W`, `I`.
- **Missing annotations** (`ruff check --select ANN --statistics src/ tests/`): 346.
  - `ANN201`: 330, every one a test function. The repo has 330 `def test_` functions and none has `-> None`. Fixtures and `_` helpers are already annotated.
  - `ANN001`: 15 unannotated arguments. 14 are `tmp_path` and `monkeypatch` in `tests/test_image.py` (lines 54, 61, 69, 79, 86, 124, 133, 141, 155); one is `node` in the nested `collect()` at `tests/test_gitignore.py:235`.
  - `ANN202`: 1, `src/tallyman/image.py:81` `_load_font()`. It is the only `src/` signature missing a hint.
  - Nothing else in the `ANN` set fires (no `ANN204`, `ANN401`, ...).
  - Ruff has an unsafe fix for `ANN201`. On a copy of the repo, `ruff check --select ANN201,ANN202 --unsafe-fixes --fix tests/` changed exactly 330 signatures and nothing else (checked by comparing ASTs), and after `ruff format` wrapped the 8 lines that grew past 120 characters, all five checks were clean with 474 tests passing.
- **Pyrefly warnings:** `uvx pyrefly check` prints `0 errors (1 suppressed, 2 warnings not shown)`. With `--min-severity=warn` they are `unnecessary-type-conversion` at `tests/test_setup_app.py:91` (`str(node.data.path)`; `NodeInfo.path` is `str`) and `:93` (`bool(node.data.spec)`; `NodeInfo.spec` is `bool`). Warnings don't change the exit code, so nothing stops new ones.
- **Doc drift, each checked against the code:**
  - "uses match statements": there is no `match` statement in `src/` or `tests/`. It appears in `CLAUDE.md:45` (Tech Stack) and in the persona's Tech stack section (`.claude/agents/architect-tallyman.md:249`, and the copy in `plans/006-tallyman-architect.plan.md:299`). The persona also names PEP 758's unparenthesised `except A, B:` (`display.py:27`), which is real.
  - `CLAUDE.md:76`, module map: the `paths.py` row lists only `relative_posix()`. `paths.py` also defines `canonical_case()`, which `cli.main()` uses on the scan root. The persona's module map already lists both.
  - `README.md:43` and `README.md:188` say "On first run, Tallyman launches an interactive TUI". `cli.main()` launches it only when `find_configs(root)` returns nothing (no `.tally-config.toml` in the scanned directory or any directory above it up to the git root; outside a repo, only the scanned directory is checked) and stdin and stdout are both terminals, or when `--setup` is given. So `tallyman src/` in a repo with a root config goes straight to counting. Configs below the scan root don't count. `README.md:223` already covers the no-terminal case.
  - `languages.py:41`: R's extensions are `('.r', '.R')`. `identify_language()` looks up `path.suffix.lower()`, so the `.R` key in `EXTENSION_MAP` is never hit. `.R` files are counted today through `.r`; removing the key changes nothing. It is the only extension in `LANGUAGES` with an uppercase letter. `README.md:114` lists `` `.r`, `.R` ``, and the README never says extensions match in any case.
- **Counts to recount at the end:** `CLAUDE.md` says "all 474 tests (about 15 s ...)" and lists per-file counts; `README.md` says "43 languages" twice and "8 template formats". All are correct at 75dd0fd. Plans 008 to 011 add tests, and this plan adds four (one in phase 1, three in phase 2).
- `.claude/agents/` is gitignored, so edits to the persona file are not committed; the tracked copy in plan 006 is. The two are identical today: `diff .claude/agents/architect-tallyman.md <(awk '/^````markdown$/{f=1;next} /^````$/{f=0} f' plans/006-tallyman-architect.plan.md)` prints nothing.

## Decisions

Michael's, from the review (2026-11-10):

1. **Do the `Optional[X]` sweep now.** Every `X | None` in `src/` and `tests/` becomes `Optional[X]` from `typing`. Ruff's `UP` rules stay off.
2. **Every test function gets `-> None`**, along with `_load_font()` and any other signature missing a hint.

Proposed here (see Open questions):

3. **Enforce both going forward.** Ruff's `ANN` rules for annotations, in `src/` and `tests/`. For `Optional`, no linter has a rule, so a small AST-based test, `tests/test_conventions.py`, fails on any `X | None`, `None | X` or `Union[X, None]` in an annotation.
4. **Make Pyrefly's `unnecessary-type-conversion` an error** in `pyrefly.toml`, so the two warnings can't come back silently.
5. **No changelog entry.** Nothing user-visible changes: the counts, the output and the CLI are the same. Removing `.R` is invisible because lookup already lowercases.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-type-hints.plan.md` | Decisions 1 to 4: the `Optional` sweep, `-> None` everywhere, the enforcement, the Pyrefly warnings, and the plan 006 update |
| 2 | `phase-02-docs-and-recount.plan.md` | The doc drift, the dead `.R` extension, and the final recount of tests and languages after plans 008 to 012 |

Phase 1 comes first so that phase 2's recount includes the test it adds.

## Overlap with plans 008 to 011

- **008** moves the bar/legend selection into a shared `bar_segments()` in `aggregator.py`, so the `X | None` at `display.py:195` and `image.py:114,165` may move or disappear. It also replaces `image.py`'s import of `display._language_display_names`, and may touch the stdout fallback around `display.py:27`, where the only PEP 758 `except A, B:` lives. Phase 2's Tech Stack wording depends on whether that survives.
- **010** changes `walk_project()`'s neighbourhood (nested repos), so `walker.py:119` may move. It also edits `gitignore.py`'s "Known differences" docstring, `CLAUDE.md` decision 7 and possibly `README.md:44`, the line after one this plan edits. Don't redo its edits.
- **011** rebuilds the setup TUI's labels as `Text` and moves the `_clean_exclusions` test into `tests/test_setup_app.py`. The `_record()` helper with the two Pyrefly warnings may change shape. The fix is the same wherever it ends up.
- Plans 008 to 011 will likely add test functions without `-> None`, following the existing style. That is expected; phase 1's scripted fix covers them.

## Workflow

- All plans 008 to 012 land on one feature branch, `architect-review-fixes`. Claude commits after each phase. **Never push** (unlike plan 007), never commit to `main`, and leave merging to Michael.
- After each phase, run an architect review with the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Address its valid findings, then commit.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines, `Optional[X]` rather than `X | None`.
- No behaviour change. Before the phase, export the branch to a scratch snapshot (`git archive HEAD | tar -x -C "$SCRATCH/snapshot"`) and save `venv/bin/tallyman --no-color "$SCRATCH/snapshot"` output. After the phase, the same command on the same snapshot prints the same report. (Scanning the repo itself won't do: the phase's own edits change its line counts.)
- Each enforcement change lands with proof that it bites: the new check fails on the code before the fix and passes after.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean. From phase 1 on, also `uvx pyrefly check --min-severity=warn` shows no warnings.
- No version bump. A changelog entry under the existing `0.4.3 - UNRELEASED` heading in `change-log.md` only if something user-visible changes (decision 5 says nothing does).
- Keep the persona and its copy in plan 006 identical. The `diff` command above must print nothing after any persona edit.

## Open questions for Michael (defaults in bold)

**Confirmed with Michael, 2026-11-10: every default below was chosen.** Implement them as written.


1. **Enforce `Optional` with `tests/test_conventions.py`?** It is about 60 lines, standard library only, and runs in milliseconds. It finds the same 7 sites as the review today, including the nested `list[tuple[Language | None, float]]` ones that a line grep can only approximate. The alternative is a note in `CLAUDE.md` and trusting the architect review. **Default: add the test.**
2. **All of `ANN`, or only the rules that fire today (`ANN001`, `ANN201`, `ANN202`)?** The full set also brings `ANN002`/`ANN003` (`*args`/`**kwargs`), `ANN204` (`__init__` and other special methods) and `ANN401` (a bare `Any` argument or return type). None fires today; `config.py`'s `dict[str, Any]` is nested and allowed. **Default: all of `ANN`.**
3. **Promote only `unnecessary-type-conversion`, or all Pyrefly warnings?** Pyrefly has no "warnings are errors" switch; each kind is promoted by name. **Default: only this one**, since it is the only kind that fires.
4. **Changelog.** The 0.4.3 log already records one tooling change ("Ruff is configured only in `ruff.toml` ... the `W` rules ... are now on"). A matching line, "Ruff's `ANN` rules are on, and a test enforces `Optional[X]`", would follow that precedent. **Default: no entry, since nothing user-visible changes; add that one line if you want tooling changes logged.**
5. **Say in the README that extensions match in any case?** It is true for every extension and explains why the R row loses `.R`. **Default: yes, one sentence above the extension tables.**
