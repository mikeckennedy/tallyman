# Plan 011 - Setup TUI - Introduction

## Context

The architect review of main @ 75dd0fd (2026-11-10) found these setup-TUI problems, now split out of plans 008 to 012:

- **Item 3.** A scan-root copy of a nested config's setting is locked in setup and saved again every time. Versions before plan 007 (plan 004's "TUI pre-population") merged nested settings into the scan-root config's pre-fill, so these copies exist in real configs, both exclusions and spec entries. `cli.py` drops copies of *parent* settings on save (`without_inherited(..., chain.inherited)`) but not nested ones. If someone later removes the setting from the nested config, the directory stays excluded and setup still blames the nested config.
- **Item 10.** A directory that a config excludes and a pattern also matches is labelled "(excluded by pattern)" and can't be toggled. The walker checks config exclusions first (then gitignore, then patterns), so `WalkStats.pattern_dirs` doesn't count it, and a redundant user exclusion can never be removed.
- **Item 11.** Labels are built as Rich markup. `rich.markup.escape()` stops `[tags]`, but `Text.from_markup()` (which Textual's `Tree.process_label()` calls on every `str` label) still expands `:emoji:` codes, and a name ending in `\` comes out doubled.
- **Item 12 and "setup scales with tree size".** `discover_nested_configs()` prunes only hidden directories. It walks into `node_modules`, gitignored, pattern-excluded and config-excluded trees and reads configs the walker never reaches. `_populate()` builds every node up front, and `_refresh()` calls `_spec_sets()` twice per node.
- **Item 15.** `tests/test_config.py` (`TestCleanExclusions`) calls the private `SetupApp._clean_exclusions` directly.
- **Design concern, Michael's decision: import Textual lazily.** `cli.py` imports `tallyman.tui.setup_app` at module level, so every plain run loads Textual.

Plans 008 (output hardening), 009 (spec colours) and 010 (git fidelity) land before this one; 012 (housekeeping) lands after it.

## Verified while planning (scratchpad experiments, Textual 7.5.0, Rich 14.3.1, Python 3.15)

- **Item 3 confirmed.** Pilot run: scan-root `excluded={'sub/gen'}`, nested `sub` config excluding `gen`. The label is `✗ gen (set in a nested config)`, `x` does nothing, and Save returns `{'sub/gen'}`. Spec copies behave the same way: a nested spec entry locks the node whatever the scan-root config says.
- **Item 10 confirmed.** Scan-root `excluded={'vendor'}` with pattern `vendor/`: the label is `vendor (excluded by pattern)`, while the walker reports `WalkStats(pattern_files=0, pattern_dirs=0)`. The same mismatch exists for gitignore: the walker checks config exclusions before gitignore too (`walker.py` `walk_project()`'s directory loop), but the TUI shows `(gitignored)` and locks the node, so a user exclusion of a since-gitignored directory can't be removed either.
- **Item 11 confirmed, and wider than the review says.** `:rocket:` renders as `✓ 🚀`, and the **root** label has the same bug (scan root named `:rocket:` shows `🚀`). The doubled backslash shows wherever a backslash name isn't immediately closed by a tag: `✓ foo\\`, `S baz\\ (set in a parent config)`, `✓ plans\\`. `[dim]foo\\[/dim]` happens to render right. The header title (`App.title`) is fine.
- **Item 12 confirmed.** On a tree with 3,000 gitignored packages (12,114 directories, 114 visible): `discover_nested_configs()` takes 0.29 s, a walker-style pruned walk 0.002 s, and the TUI itself starts in 0.13 s. So today discovery is most of setup's start-up cost on a JavaScript project.
- **The "local override" exception only applies to parent settings.** `_lock()` leaves a parent spec setting editable when the scan-root config had an entry for that path when setup opened (`_original_entry`). There is no such exception for nested settings, and there can't be: the scan root's config is deeper than its parents but shallower than nested configs, so a nested setting always wins on the same path (`_spec_sets()` merges inherited, then user, then nested).
- **Textual import cost.** `python -X importtime -c "import tallyman.cli"`: 77-79 ms total, of which `tallyman.tui.setup_app` is 43-45 ms. The modules a plain run needs (`config`, `walker`, `counter`, `aggregator`, `display`, `gitignore`, `paths`) import in about 29 ms. `tallyman.display` alone doesn't load Textual.
- **There is no existing lazy-Pillow test.** `CLAUDE.md` says Pillow is imported lazily, and `image.py` does it, but no test checks it. Phase 1's test covers both.

### Setup timings on synthetic trees (`src/mN/pJ/qK`, one `.py` per leaf)

| Tree | Dirs | `discover_nested_configs()` | Pruned walk | TUI start | `s` on root | Walk after Save |
|---|---|---|---|---|---|---|
| 1k visible | 1,112 | 0.03 s | 0.02 s | 0.20 s | 0.10 s | 0.05 s |
| 5k visible | 5,108 | 0.13 s | 0.11 s | 0.49 s | 0.19 s | 0.26 s |
| 20k visible | 20,093 | 0.52 s | 0.46 s | 1.51 s | 0.57 s | 1.00 s |
| 100 visible + 12k gitignored | 12,114 | 0.29 s | 0.002 s | 0.13 s | 0.08 s | 0.005 s |

At 20k directories, TUI start breaks down as `_populate()` 0.66 s, `_refresh()` 0.21 s, and the rest (Textual building, expanding and rendering 20k nodes) about 0.8 s. Profiling one full `_refresh()` with realistic config sets: `set_label()`/`process_label()` (markup parsing) is 0.47 s of 0.79 s, and `_spec_sets()` 0.11 s. A prototype with `Text` labels and one `_spec_sets()` per refresh cut `s` on the root from 0.57 s to 0.41-0.48 s. Start barely moved (1.5 s), since node building dominates.

## Decisions

From the review (Michael, 2026-11-10):

1. **Import Textual lazily**, only when setup actually runs, with a test that a plain run doesn't import it.

Proposed here (open questions below cover the ones that are Michael's call):

2. **A "copy" is a scan-root entry that a parent or nested config already has in the same set**: the same path in `excluded_dirs`, `spec_dirs` or `non_spec_dirs`. Copies are dropped so each setting lives in one file. A scan-root entry in the *opposite* spec set to a parent's is an override, not a copy. It stays and stays editable (today's `_original_entry` exception). A path the scan-root config lists as both specs and ignored keeps both entries, as `without_inherited()` does today.
3. **Setup drops copies when it opens, not only on save.** Then the labels, the locks and the `s` round-trip history (`_original_entry`) all start from what will be saved. The save drops them again as a guard (idempotent). `SetupApp` is the one place that knows every source of locked settings, so it does this and `run_setup()` returns only scan-root settings, as its docstring already claims. `cli.py` saves what setup returns.
4. **The TUI follows the walker's exclusion precedence: config exclusion, then gitignore, then patterns.** A directory any config excludes is labelled as config-excluded (`✗ name`, plus `(set in a parent/nested config)` when locked), even if gitignore or a pattern also matches it. A user exclusion there can be toggled off, after which the label becomes `(gitignored)` or `(excluded by pattern)`. "(excluded by pattern)" then appears exactly where the walker would count `pattern_dirs`.
5. **Labels are `rich.text.Text`**, built with `Text.assemble()`, never markup strings. Directory names are inserted as plain text, so markup, emoji codes and backslashes all show literally. This also skips the markup parse on every `set_label()`.
6. **Setup collects nested configs while it builds the tree.** `_populate()` loads each directory's `.tally-config.toml` on entering it and registers its patterns before judging the children, as `walk_project()` does. `discover_nested_configs()` goes away. Setup then reads a nested config exactly where the walker would if the scan root's own exclusions were lifted (setup must see what's under a user exclusion, since the user can toggle it off). It never reads configs under gitignored, pattern-excluded or hidden directories, or under directories a parent or nested config excludes.
7. **Directories excluded by a parent or nested config are leaves in the tree.** The walker never enters them and setup can't un-exclude them, so their children are noise. This is what keeps configs inside them from being read (decision 6). Open question 3.
8. **No lazy population on expand.** See "Lazy population" below. Cheaper fixes go in instead: decision 6 removes the extra full walk, decision 5 the markup parsing, and `_refresh()` computes the spec sets once per call.

### Lazy population: measured, not recommended

Populating only two levels (what a collapsed start would need) starts the 20k-directory tree in 0.13 s instead of 1.51 s. But:

- Copy-dropping (decision 3) needs every nested config at open (or at save), so a full pruned config walk stays: 0.46 s at 20k. The real saving is about 0.9 s at 20k directories and about 0.3 s at 5k, once per setup run.
- Save is followed by the count, which walks the same tree: 1.0 s at 20k. Setup is rare (first run, or `--setup`).
- It changes the UI. Setup opens fully expanded today (`expand_all()` plus `_collapse_excluded()`), and a lazy tree would have to open collapsed.
- It changes the model. `_refresh()`, `_derive()` and `_would_be_spec()` assume every node exists. Toggles would have to derive unloaded children on expand. Plan 010 notes that a lazily populated node must call `add_directory()` when it is expanded, not when it is created. And the 51 pilot tests navigate to deep nodes that would first need expanding.

Revisit if someone reports a slow setup on a tree well past 20k directories. Then the benchmark in phase 3 is the starting point.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-lazy-textual-and-text-labels.plan.md` | Decisions 1 and 5: lazy Textual import with a no-import test; `Text` labels (item 11) |
| 2 | `phase-02-precedence-and-copies.plan.md` | Decisions 2-4: drop nested and parent copies in setup (item 3); walker precedence in labels and toggles (item 10); pilot tests replace `TestCleanExclusions` (item 15) |
| 3 | `phase-03-nested-configs-in-populate.plan.md` | Decisions 6-8: nested configs collected in `_populate()`, `discover_nested_configs()` removed, locked-excluded directories as leaves, one `_spec_sets()` per refresh (item 12) |

Phase 1 is independent and lowest risk. Phase 2 comes before 3 because it fixes visible bugs, and its tests (written against on-disk nested configs) carry over to phase 3 unchanged apart from dropping the `nested=` argument.

## Assumptions about plan 010 (git fidelity), which lands just before this plan

Plan 010 is written (`plans/010-git-fidelity/`, especially `phase-02-nested-repos.plan.md`). Its decision 10 keeps one `GitIgnoreSpec` per scan, and this plan builds on that interface:

- **Nested repo rules start inside `GitIgnoreSpec.add_directory()`.** Any `.git` (directory or file) below the scan root makes a nested repo, and `_is_ignored()` uses only the rules of the deepest repo above each entry. So every traversal must call `gitignore_spec.add_directory(rel_dir, dir_path)` on a directory **before** `match_file()` on that directory's children. `walk_project()` and `_populate()` already do. Phase 3 keeps that call first in `_populate()` and adds the nested-config load right after it, mirroring `walk_project()`. (Lazy population would have had to call it on expand, not on node creation. One more reason it isn't recommended.)
- **The TUI and the walker share one spec**, built by `load_gitignore()` / `GitIgnoreSpec.for_root()` in `cli.main()`. Don't build a second one. Registration is idempotent.
- **Configs inside a nested repo that the outer repo ignores are not read by setup, which matches the walker.** 010 expected this plan to prune `discover_nested_configs()` with the shared spec. Phase 3 goes one step further and removes that function, collecting configs in `_populate()` instead. `_populate()` never descends into a gitignored directory, and with 010 an outer rule that ignores `sub/` keeps the nested repo `sub` out, so its configs are never read. Configs inside a nested repo that isn't ignored are still nested configs (010 decision 9), and `[exclude]`/`[specs]` settings keep applying across repo boundaries.
- **Agreement tests.** 010 phase 2 adds `TestNestedRepos.test_tui_and_walker_agree_across_nested_repos` to `tests/test_setup_app.py` (and `Session._record()` gains `self.excluded`). Phase 3 extends that test with nested configs (see that phase).
- If 010 landed differently from its plan (a per-repo spec, a resolver object), use whatever `walk_project()` calls when it enters a directory and judges its children, at the same point in `_populate()`. Read 010's diff before starting phase 3. The guarantee to keep: what the TUI shows matches what the walker does, inside nested repos too.

## Workflow

- All of plans 008-012 land on one feature branch, `architect-review-fixes`. Claude owns the branch and commits after each phase, so the history shows how the work evolved. **Never push** (unlike plan 007), never commit to `main`, never force-push, and leave merging to Michael.
- After each phase, run an architect review with the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Point it at the phase file and the diff. Address its valid findings, then commit.
- Line numbers in the review and in this plan are from 75dd0fd. Plans 008-010 land first and shift them, so find code by function name.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- New or changed annotations use `Optional[X]`, not `X | None`. New test functions get `-> None` (Michael's decision on review item 14; plan 012 sweeps the rest).
- Each behaviour change lands with a test that fails before the change and passes after.
- Test the TUI through Textual's `run_test()` pilot (the `Session` helper in `tests/test_setup_app.py`), not by calling private methods.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean.
- Add entries under the existing `0.4.3 - UNRELEASED` heading in `change-log.md`, with `Files:` and `Plan:` lines in the existing style. No version bump.
- Update the `CLAUDE.md` test table and the "all N tests" count in Quick Reference where they change. Recount with `pytest --collect-only -q`, since plans 008-010 change the counts first. Update the module map and Key Design Decisions where a phase makes them false.
- The architect persona exists twice: `.claude/agents/architect-tallyman.md` (gitignored, so edits don't show in commits) and the copy in `plans/006-tallyman-architect.plan.md`. Fix any line in either that a phase makes false. Each phase lists the lines it knows about.
- What the setup TUI shows must match what the walker does, at every commit.

## Overlap with other plans

- **008 output hardening** adds `_tolerate_unencodable_stdout()` at the top of `cli.main()`. Phase 1 here edits the imports at the top of `cli.py`. A small textual conflict at most. 008's walker file-loop change (`lstat()`/`S_ISREG`) doesn't touch directories, so `_populate()` is unaffected.
- **009 spec colours.** No overlap. The TUI's `S` marker is `bright_cyan`, not a language colour.
- **010 git fidelity.** See "Assumptions about plan 010" above. Its overlap note expected 011 to plan lazy population and to prune `discover_nested_configs()` with the shared spec. This plan does neither: it measured lazy population and recommends against it, and it removes `discover_nested_configs()`, collecting configs in `_populate()`, which already uses the shared spec in the right order. 010's guarantees carry over. 010 phase 2 also edits `_populate()`'s comment and `Session._record()`; phases 1 and 3 here build on those edits. 010's open question 3 (a dim `(git repo)` label) is listed here as an optional item (open question 7).
- **012 housekeeping** runs last. Its Pyrefly fix in `_record()` (`str(node.data.path)`, `bool(node.data.spec)`) still applies after phase 1. Keep `str(node.label)`: the label is a `Text`. 012 recounts tests and handles the doc drift this plan doesn't cause ("uses match statements", the `paths.py` row, the README first-run sentence).

## Open questions (Michael's call; defaults are what the phases implement)

**Confirmed with Michael, 2026-11-10: every default below was chosen.** Implement them as written.


1. **Shadowed scan-root spec entries.** A scan-root `[specs] directories = ["lib"]` while `lib/.tally-config.toml` says `ignore = ["."]`: the nested config wins, so the scan-root entry does nothing, and setup shows `lib` locked by the nested config. It isn't a copy (opposite set). *Default: keep it.* It may be deliberate, it takes effect again if the nested setting is removed, and dropping it would change behaviour then.
2. **Scan-root exclusions beneath a parent's or nested config's exclusion** (scan-root `src/vendor` while a parent excludes `src`). Not a copy, and inert while the outer exclusion stands. With decision 7 it isn't shown at all. *Default: keep it*, for the same reason as 1. (`_clean_exclusions()` already drops children of the user's *own* exclusions on save. That is unchanged.)
3. **Directories excluded by a parent or nested config become leaves** (decision 7). Today their children are listed, all `✗`. *Default: leaves.* That changes `test_child_of_an_inherited_exclusion_is_excluded`.
4. **Config exclusion outranks gitignore in labels too, not only patterns** (decision 4). The review asked only about patterns. *Default: yes, the same rule.* It's the walker's order, and it lets a redundant user exclusion of a since-gitignored directory be removed.
5. **Tell the user when setup dropped copies?** *Default: no message.* The changelog says so, and the dropped settings still apply from their own files, so counts don't change.
6. **Lazy population.** *Default: not now* (see above).
7. **Optional item: a `(git repo)` label for nested repos** (plan 010's open question 3; 010 defaults to no label). It would explain why an outer `.gitignore` rule stops applying beneath a directory. With `Text` labels it's small: `GitIgnoreSpec` would expose whether a path is a recorded repo root (a public `is_repo_root(rel)` over 010's `_repo_roots`), and `_label_for()` appends a dim ` (git repo)` to visible, non-excluded nodes. *Default: not in this plan.* If Michael wants it, add it as a final step of phase 3, with one pilot test (`sub` with `sub/.git/` is labelled `✓ sub (git repo)`; a plain directory isn't).
