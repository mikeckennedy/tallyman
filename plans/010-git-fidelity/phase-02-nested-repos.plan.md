# Phase 2 - Nested Repositories Use Their Own Rules

Covers review item 5 and decisions 1 and 3-10 from `00-plan-introduction.plan.md`.

## Goal

Tallyman keeps counting nested git repositories (plain nested clones, submodules, worktrees inside the tree). Inside each one it applies only that repository's own `info/exclude` and `.gitignore` stack, exactly what git reports when run inside it. The setup TUI shows the same thing, with no TUI code change.

## Current behaviour

- The outer `.gitignore` has `*.md`, and `sub/` is its own repo holding `a.md` and `b.py`. `tallyman` counts `sub/b.py` and drops `sub/a.md`. Git run in `sub` lists both.
- `sub/.git/info/exclude` is never read.
- `a/.gitignore` has `*.py` and `a/sub` is a repo holding `x.py`. Tallyman drops `a/sub/x.py`; git run in `a/sub` lists it.

## The rule

For an entry at path *p* (relative to the anchor, git's root for the scan):

- Its **owner** is the deepest nested repo root *r* registered on the spec with *p* strictly inside it (*p* starts with `r + '/'`), or `''` (the scan's own repo) if there is none.
- Only layers whose base is the owner or lies under it take part. The usual scoping (`full.startswith(base + '/')`) and deepest-opinion-wins rules then run unchanged.

Consequences, each matching git:

- The nested repo's own directory entry `sub` is not strictly inside `sub`, so the enclosing rules judge it (decision 3). An outer `sub/`, `sub` or `*` keeps it out, and it is never entered.
- Everything inside `sub` sees only `sub`'s layers: its `info/exclude` and its `.gitignore` files. Outer layers stop there, including `.gitignore` files in directories between the outer root and `sub`, and outer `!` negations (decision 4).
- A layer belonging to a repo deeper than the owner can't match anyway, since its base scope already excludes the path. Repos nest recursively with no extra logic.
- `_ignore_all` (the scan root itself is inside an ignored directory) still wins first. A nested repo below an ignored scan root is never entered, as git, run in the enclosing repo, never enters it.

## Changes

### `src/tallyman/gitignore.py`

`GitIgnoreSpec`:

- `__init__`: add `self._repo_roots: set[str] = set()`, the bases (relative to the anchor) of nested repositories found below the analysis root. The repo that `for_root()` found is the implicit `''`-owner and is not in the set.
- `add_directory(rel_dir, dir_path)`: before registering `dir_path/.gitignore`, if `rel_dir` is non-empty (the analysis root's own repo is handled by `for_root()`), `base` is not already in `_repo_roots`, and `_has_git(dir_path)` (phase 1's helper, the same test as `find_git_root()`):
  1. add `base` to `_repo_roots`;
  2. if `(exclude := _info_exclude(dir_path)) is not None`, `self._add_file(base, exclude)`.

  Then register `dir_path/.gitignore` as today. Registering `info/exclude` first keeps it below the repo's root `.gitignore`, because both have the same base depth and `_add_lines()` sorts stably. Keep the existing comment on that sort and extend it to say so.
  - Idempotent: a second call for the same directory adds nothing. `_add_file()` already dedupes on `(base, filename)`, and `info/exclude`'s filename `exclude` can't collide with `.gitignore`.
  - Cost: one extra `stat` per entered directory. `add_directory()` already tries to read a `.gitignore` per directory, so this is the same order of work.
  - Docstring: "If *dir_path* is the root of a nested git repository (it has a ``.git`` directory or file), it starts a new set of rules: inside it, only its own ``info/exclude`` and ``.gitignore`` files apply, as if git were run there. The directory's own entry was already judged by the enclosing rules."
- New `_owner(self, full: str) -> str`: the deepest entry of `_repo_roots` that is a proper ancestor of *full*, or `''`. Walk the `'/'` prefixes of *full* from longest to shortest, excluding *full* itself, and return the first one in the set.
- `_is_ignored(full, is_dir)`: after the `_ignore_all` check, `owner = self._owner(full) if self._repo_roots else ''`. In the layer loop, when `owner` is non-empty, skip a layer unless `base == owner or base.startswith(owner + '/')`. Nothing else changes, so a spec with no nested repos behaves byte-for-byte as before. The scan root's ancestors in `for_root()` are never nested roots, because `find_git_root()` returned the nearest repo, so `for_root()`'s own `_is_ignored()` calls are unaffected.
- Class docstring: add a paragraph on repository boundaries. Nested repos are discovered by `add_directory()`. Inside one, only its own rules apply. Its own entry is judged by the enclosing rules. `[exclude] patterns` specs (`for_patterns()`) never call `add_directory()`, so they never see repository boundaries (decision 9).
- `add_rules()` docstring: one sentence. Pattern layers apply across nested repositories, since they are tallyman settings, not git rules.
- Module docstring, "Known differences", add:

```
- Any ``.git`` (directory or file) marks a repository root, the same test
  :func:`find_git_root` uses. Git requires a valid repository, so to git an
  empty ``.git`` directory or a ``.git`` file pointing nowhere is an ordinary
  directory and the enclosing rules continue inside it; here they stop.
```

and a short positive note above the list: "Nested repositories, submodules and worktrees inside the tree are walked with their own rules, as if git were run inside each."

### `src/tallyman/walker.py`, `src/tallyman/tui/setup_app.py`

No logic change. Both already call `add_directory()` on a directory before judging its children, which is all the rule needs.

- `walk_project()` docstring, `gitignore_spec`: add "A nested git repository found while walking starts its own rules (see :meth:`GitIgnoreSpec.add_directory`)."
- `SetupApp._populate()`: extend the existing comment ("This directory's own .gitignore governs its children, matching walk_project()") to mention that this is also where a nested repository's own rules start.

### `src/tallyman/config.py`, `src/tallyman/cli.py`

No change (decision 9). `find_configs()` still stops at the nearest git root. `discover_nested_configs()` still finds configs inside nested repos. Plan 011 prunes it with the walker's spec, which inherits this phase's semantics; see the introduction's overlap notes.

## Tests

Fake repositories (`(dir / '.git').mkdir()` or a `.git` file) are enough for the rule, and run without git. Real-git parity tests check the rule against git itself.

### `tests/test_gitignore.py`, new class `TestNestedRepos` (no git needed)

Use `_make()` and `_walked()`. The scan root gets its own `.git/` directory unless the test says otherwise.

- `test_outer_gitignore_stops_at_nested_repo`: outer `.gitignore` `*.md`, `sub/.git/`, files `top.md`, `top.py`, `sub/a.md`, `sub/b.py`. Walked: `{'top.py', 'sub/a.md', 'sub/b.py'}`.
- `test_outer_subdirectory_gitignore_stops_too`: `a/.gitignore` `*.py`, `a/sub/.git/`, `a/y.py`, `a/sub/x.py`. Walked: `{'a/sub/x.py'}`.
- `test_outer_info_exclude_stops_at_nested_repo`: outer `.git/info/exclude` `*.md`. `sub/a.md` is counted and `top.md` isn't.
- `test_nested_repo_reads_its_own_info_exclude`: `sub/.git/info/exclude` `b.py`. `sub/b.py` is not counted; `b.py` at the top is.
- `test_nested_repo_gitignore_stack_is_scoped_to_it`: `sub/.gitignore` `/gen/`, `sub/lib/.gitignore` `*.md`, files `sub/gen/a.py`, `sub/lib/b.md`, `sub/lib/c.py`, `sub/d.md`, `gen/e.py`. Walked: `{'sub/lib/c.py', 'sub/d.md', 'gen/e.py'}`.
- `test_outer_negation_cannot_reach_into_nested_repo`: outer `.gitignore` `!sub/keep.py`, `sub/.gitignore` `*.py`, `sub/keep.py`. Not counted.
- `test_nested_repo_ignored_by_outer_stays_out` (parametrize the outer rule over `.gitignore` `sub/`, `.gitignore` `sub` and `info/exclude` `sub/`): nothing under `sub` is counted, even with `sub/.gitignore` `!*`.
- `test_repo_inside_nested_repo`: `deep/.git/`, `deep/.gitignore` `*.py`, `deep/inner/.git/`, `deep/d.py`, `deep/inner/e.py`. Walked includes `deep/inner/e.py`, not `deep/d.py`.
- `test_submodule_style_git_file`: `sub/.git` is the file `'gitdir: ../.git/modules/sub\n'`, `.git/modules/sub/info/exclude` lists `secret.py`, outer `.gitignore` `*.md`, files `sub/secret.py` and `sub/a.md`. Walked: `{'sub/a.md'}`. The modules dir is hidden, so nothing under `.git` is walked.
- `test_child_repos_of_a_plain_directory`: no `.git` at the scan root (`tmp_path` isn't in a repo; `TestFindGitRoot.test_returns_none_when_no_git` relies on the same thing). Root `.gitignore` `*.md`, `proj/.git/`, `proj/a.md`, `notes/b.md`. Walked: `{'proj/a.md'}`.
- `test_scan_inside_ignored_directory_skips_nested_repo`: outer `.gitignore` `build/`, `build/sub/.git/`, `build/sub/x.py`. Scanning `build` walks nothing, as today.
- `test_nested_repo_registration_is_idempotent`: build the spec with `load_gitignore(root)`, call `add_directory('sub', root / 'sub')` twice, and check that `match_file('sub/b.py')` is unchanged and still follows `sub`'s `info/exclude`. Keep it behavioural.

### `tests/test_walker.py`, tallyman settings cross repo boundaries (decision 9)

New class `TestNestedReposKeepConfigSemantics`, with the scan root and `sub` both fake repos:

- `test_patterns_apply_inside_nested_repo`: `exclude_patterns = GitIgnoreSpec.for_patterns(root)`, `add_rules(root, ['*.md'])`. `sub/a.md` is not walked.
- `test_excluded_directory_inside_nested_repo`: `excluded_dirs={'sub/vendor'}`. `sub/vendor/x.py` is not walked.
- `test_nested_config_inside_nested_repo`: `sub/.tally-config.toml` excludes `gen`. `sub/gen/x.py` is not walked, as for any nested config.
- `test_spec_detection_crosses_repo_boundaries`: `plans/sub/.git/` and `plans/sub/a.md`. The Markdown is counted as specs.

### `tests/test_gitignore.py`, parity with git

Use phase 1's `_git_env()`, `_git()`, `_git_view()` and `needs_git`.

`_NESTED_GIT_CASES`, run by `test_nested_repos_match_git(tmp_path, files, repos, scan, excludes) -> None`:

- `files: dict[str, str]`.
- `repos: list[str]`: directories to `git init`, shallowest first. `''` (the outer repo) is always initialised first.
- `scan: str`.
- `excludes: dict[str, str]`: repo dir to `info/exclude` text.

The test writes the files, initialises the repos, writes the excludes, and asserts `_walked(repo / scan) == _git_view(repo / scan, env)`. Cases (ids):

- `outer-rules-stop`: outer `.gitignore` `*.md`; repo `sub` with `a.md`, `b.py`; `top.md`, `top.py`.
- `outer-subdir-gitignore-stops`: `a/.gitignore` `*.py`; repo `a/sub` with `x.py`; `a/y.py`.
- `outer-info-exclude-stops`: excludes `{'': '*.md\n'}`; repo `sub` with `a.md`.
- `inner-info-exclude`: excludes `{'sub': 'b.py\n'}`.
- `ignored-by-outer-gitignore`: outer `.gitignore` `sub/`.
- `ignored-by-outer-info-exclude`: excludes `{'': 'sub/\n'}`.
- `outer-negation-cannot-reach-in`: outer `!sub/keep.py`, `sub/.gitignore` `*.py`.
- `repo-in-repo`: repos `deep`, `deep/inner`; `deep/.gitignore` `*.py`; `deep/d.py`, `deep/inner/e.py`, `deep/inner/f.md`; outer `.gitignore` `*.md`.
- `scan-from-inside`: as `outer-rules-stop` with `scan='sub'`.
- `scan-subdir-holding-repo`: as `outer-subdir-gitignore-stops` with `scan='a'`.
- `scan-inside-repo-the-outer-ignores`: outer `.gitignore` `sub/`, scan `sub`: counted with `sub`'s rules (decision 7).

Two tests with their own setup:

- `test_submodule_from_outer_matches_git`: phase 1's submodule layout, scanned from `outer`. Expected `{'top.py', 'sub/kept.py', 'sub/b.py', 'sub/a.md'}`, asserted through `_git_view(outer, env)` and also literally, so a `_git_view` bug can't hide a regression.
- `test_worktree_inside_repo_matches_git`: `main` with a committed `.gitignore` of `*.md` and a common `info/exclude` of `secret.py`. `git -C main worktree add -q main/wt`, not ignored by `main`. Add untracked `wt/secret.py`, `wt/ok.py`, `wt/a.md` and `top.py`. Assert `_walked(main) == _git_view(main, env)`. The worktree uses the main repo's `info/exclude` through `commondir`, so `wt/secret.py` stays out.

### Walker and setup TUI agreement

`tests/test_gitignore.py`, `TestSetupTuiAgrees.test_tui_applies_nested_repo_rules`:

- Outer `.git/`, outer `.gitignore` `gen/` and `skipped/`.
- `sub/.git/` with `sub/.gitignore` `out/`.
- Directories `gen/`, `sub/gen/`, `sub/out/`, and `skipped/inner/` with `skipped/.git/`.

Assert labels: `gen` ends with `(gitignored)`, `sub/gen` doesn't, `sub/out` does, `skipped` does, and `skipped/inner` is absent (never populated). Reuse the existing label-collecting pattern from `test_tui_marks_nested_gitignored_directory`.

`tests/test_setup_app.py`, new class `TestNestedRepos`:

- Extend `Session._record()` to keep `self.excluded: dict[str, bool]` from `node.data.excluded`.
- `test_tui_and_walker_agree_across_nested_repos`:
  - Tree: outer repo with `.gitignore` `*.md` and `build/`, `info/exclude` `vendor/`; `sub` (repo) with `sub/.gitignore` `tmp/`, plus `sub/build/`, `sub/vendor/` and `sub/tmp/`; `sub/deep` (repo) with `sub/deep/.git/info/exclude` `cache/`, plus `sub/deep/tmp/` and `sub/deep/cache/`; `lib/sub2` with a `.git` file (submodule style) whose modules-dir `info/exclude` lists `out/`, plus `lib/sub2/out/`; and an outer `build/`.
  - Put one `x.py` in every directory, and use only directory rules, so "a directory the walker enters" equals "the parent of a walked file".
  - Run `Session(tmp_path).run([])`, then walk with the returned settings.
  - Assert `{d for d, ex in session.excluded.items() if not ex} == {parent dirs of walked files} - {''}`.
- `test_nested_repo_labels_follow_its_rules`: with the same tree, `sub/build` is not labelled gitignored while `build` is.

### `tests/test_cli.py`

`test_nested_repo_counts_with_its_own_gitignore`: an outer fake repo with `.gitignore` `*.md`, a `top.md` of 5 lines, and a nested `sub/.git/` holding a 3-line `sub/README.md`. Run through `main()` the way the existing no-config, no-terminal tests do (patch `_is_interactive`, capture stdout). Markdown appears in the output with 3 lines, so `sub/README.md` is counted and `top.md` is still ignored.

### Added after the phase 1 review: submodule inside a submodule

Add a parity case for a submodule of a submodule, scanned from the middle repo (`mid/leaf`, with `leaf`'s git dir at `../../.git/modules/mid/modules/leaf`). Before this phase, tallyman counts `leaf/deep.py`, which leaf's own `info/exclude` lists, and drops `leaf/secret.py` because mid's `info/exclude` reaches into leaf. After it, both must match `git ls-files` run inside each repo. The phase 1 reviewer's layout script is `scratchpad/review010p1/scripts/layouts.py`.

## Changelog

Under `0.4.3 - UNRELEASED`, `### Changed`:

- Nested git repositories, including submodules and worktrees inside the tree, are still counted, but now with their own rules: inside one, only its own `.gitignore` files and `info/exclude` apply, as if git were run there, and the outer repository's patterns stop at its root. A nested repository the outer one ignores stays out. `[exclude]` and `[specs]` settings apply across repository boundaries as before.
- Files: `src/tallyman/gitignore.py`, `src/tallyman/walker.py`, `src/tallyman/tui/setup_app.py`, `tests/test_gitignore.py`, `tests/test_walker.py`, `tests/test_setup_app.py`, `tests/test_cli.py`
- Plan: `plans/010-git-fidelity/phase-02-nested-repos.plan.md`

## Done when

- A recursive parity view (git run inside the outer repo and inside each nested repo, like `_git_view()` in the tests; `scratchpad/impl010p2/parity_recursive.py`) prints `OK` for every case. *(Amended after the phase 2 review: the review's original `parity.py` runs git only in the outer repo, which lists a nested repo as the single entry `sub/`, so it can never match while nested repos are counted, per decision 1.)*
- A scan of a folder of checkouts (no repo at the scan root) applies each checkout's own `.gitignore` and `info/exclude`. Check by hand on a copy of a real layout in the scratchpad, for example a few clones under one directory.
- Timing on a large tree (`../commandbookapp`, or this repo with a populated `venv/`) is within noise of before. Report the numbers in the phase review.
- Repos without nested repositories produce identical output: the existing tests pass unchanged.
- All checks in the introduction's rules are clean, and the `CLAUDE.md` test counts are updated.
