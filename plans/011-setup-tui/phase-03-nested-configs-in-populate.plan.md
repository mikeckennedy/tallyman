# Phase 3 - Nested Configs Collected While the Tree Is Built

Covers decisions 6-8 from `00-plan-introduction.plan.md` (review item 12 and "setup scales with tree size").

## Goal

Setup reads a nested `.tally-config.toml` only where the walker would. The one exception is directories under the scan root's own exclusions, which the user can toggle. Setup does this without a separate walk of the whole tree. Directories excluded by a parent or nested config are leaves. Toggles don't recompute the spec sets for every node.

## Before starting

Read plan 010's diff (`plans/010-git-fidelity/phase-02-nested-repos.plan.md`, and the commits). The introduction's "Assumptions about plan 010" says what this phase relies on. The one rule that matters here: `_populate()` calls `self.gitignore_spec.add_directory(rel_path, dir_path)` first, before anything judges that directory's children, because that is where 010 starts a nested repo's rules. Nothing in this phase may move a `match_file()` call ahead of it.

## Changes

### `src/tallyman/tui/setup_app.py`

- `_populate(parent_node, dir_path, rel_path)`, in this order, mirroring `walk_project()`:
  1. `self.gitignore_spec.add_directory(rel_path, dir_path)`. Unchanged, and still first (plan 010).
  2. If `rel_path` is non-empty and `dir_path / CONFIG_FILENAME` is a file, `load_nested_config(config_file, rel_path)`. If it returns something, set `self.nested = merge_configs(self.nested, nested)` and call `self.exclude_patterns.add_rules(dir_path, patterns)`. A malformed one returns None and is skipped silently, as in the walker. Import `load_nested_config` by name (`from tallyman.config import ...`), so tests can spy on it.
  3. Judge each child as today (hidden: skip; `gitignored`; `pattern_excluded` only if not gitignored), and also `locked_out = child_rel in self.inherited.excluded_dirs or child_rel in self.nested.excluded_dirs`.
  4. Add the node. Recurse only if it is not `locked_out`, not gitignored and not pattern-excluded. User exclusions still recurse: the user can toggle them off, and then the walker enters them.

  Pre-order is enough for precedence. A config can only name paths beneath its own directory (`..` entries are dropped on load), so every config that can name a child has been merged before that child is judged, and a deeper config merges later and wins, as in the walker.
- `SetupApp.__init__` and `run_setup()`: remove the `nested` parameter. `self.nested` starts as `TallyConfig()` and `_populate()` fills it. While touching the signatures, make every parameter after `existing_specs` keyword-only (`*`), so dropping `nested` can't silently shift positional arguments. Update `tests/test_setup_app.py`'s `Session` and `TestNestedPatternLayers`, the two `SetupApp(...)` calls in `tests/test_gitignore.py` (positional up to `existing_specs`, so they keep working), and `cli.run_setup()`'s mirror signature from phase 1.
- Docstrings: `__init__` says nested configs are read while the tree is built, wherever the walker would read them plus beneath the scan root's own exclusions. `NodeInfo`: a directory excluded by another config is a leaf.
- `_drop_copies()` (phase 2) already runs after `_populate()`, so it sees every nested config. Check that it still does.
- **One spec-set computation per refresh.** `_refresh(node)` computes `sets = self._spec_sets()` once and recurses through a private `_refresh_tree(node, sets)`. `_derive()` and `_label_for()` take `sets` as a parameter instead of calling `_spec_sets()`. `_would_be_spec()` computes it once for its probe. Only the user's toggles change the sets, and every toggle ends in `_refresh()`, so nothing can go stale.

### `src/tallyman/config.py`

- Delete `discover_nested_configs()`. `load_nested_config()`, `prefixed()` and `merge_configs()` stay, since the walker and the TUI both use them. Remove it from the module docstring and from any `__all__` or docs that list it.

### `src/tallyman/cli.py`

- `--setup` branch: delete `nested_layers` and the `discover_nested_configs()` call. `exclude_patterns = _pattern_spec(root, chain.pattern_layers)`. The TUI adds nested layers to that same instance as it populates, and the walker that runs afterwards registers them again as it descends (a no-op). Remove the "registered up front" comment. Drop `nested=` from the `run_setup()` call.

## Tests

`tests/test_setup_app.py`:

- Remove every `nested=discover_nested_configs(...)` argument (the configs are on disk already) and the `discover_nested_configs` import. `TestNestedPatternLayers` shrinks to `Session(tmp_path).run([])`.
- New class `TestNestedConfigDiscovery`:
  - `test_setup_reads_the_configs_the_walker_reads`. Tree: configs in `a/` (plain), `node_modules/p/` (gitignored by `.gitignore` `node_modules/`), `fixtures/f/` (scan-root pattern `fixtures/`), `vendor/v/` (`inherited=TallyConfig({'vendor'})`), `b/gen/` (excluded by `b/.tally-config.toml`), `mine/m/` (`excluded={'mine'}`), and `.hidden/h/`. Spy on `load_nested_config` in both `tallyman.tui.setup_app` and `tallyman.walker` with `monkeypatch.setattr`, wrapping the real function and recording `rel_dir`. Assert:
    - setup read exactly `{'a', 'b', 'mine/m'}`;
    - the walker, run with the effective settings (`merge_configs(inherited, result)` plus the same pattern spec), read `{'a', 'b'}`;
    - the walker, run with `mine` removed from the exclusions, read `{'a', 'b', 'mine/m'}`, the same as setup.
  - `test_directory_excluded_by_another_config_is_a_leaf`: `inherited=TallyConfig({'src'})` and a nested `b/.tally-config.toml` excluding `gen`. `src` and `b/gen` are labelled `✗ ... (set in a parent/nested config)`, and none of their children are in `session.labels`.
  - `test_nested_config_below_a_user_exclusion_applies_when_it_is_lifted`: `excluded={'mine'}`, `mine/.tally-config.toml` with `[specs] directories = ["."]`. After `x` on `mine`, the label is `S mine (set in a nested config)` and the walker counts `mine/notes.md` as specs.
- Change `TestParentConfigs.test_child_of_an_inherited_exclusion_is_excluded` to assert that `src/vendor` is not listed (open question 3).
- Extend plan 010's `TestNestedRepos.test_tui_and_walker_agree_across_nested_repos`, or add a sibling test with the same tree:
  - a `.tally-config.toml` inside the nested repo `sub` (`[specs] directories = ["."]` in `sub/`), which setup reads and shows as `S sub (set in a nested config)`, agreeing with the walker;
  - a nested repo `skipped/` that the outer `.gitignore` ignores, holding `skipped/.tally-config.toml`. The `load_nested_config` spy shows that neither setup nor the walker reads it.
- The phase 2 `TestCopies` tests pass unchanged apart from the dropped argument. This is the check that copy-dropping still sees every nested config.

`tests/test_config.py`: delete `TestDiscoverNestedConfigs` (7 tests) and `test_nested_configs_report_their_layers`. What they covered (prefixing, merging, hidden directories, malformed configs, pattern layers) is now covered by the walker's nested-config tests and the pilot tests above. Check that `tests/test_walker.py` has a malformed-nested-config test and a hidden-directory one. If either is missing, add it there.

`tests/test_cli.py`:

- `test_setup_shows_parent_local_and_nested_patterns` needs one change. The spec handed to `run_setup` no longer holds the nested `crate/out/` layer, because the real TUI adds it while populating, so the `pattern_calls` fake can't see it and the `specs[0].match_file('crate/out/')` assertion fails. Keep the parent and scan-root assertions on the fake, and move the nested half to a `_real_setup` run (phase 2's helper) that asserts the spec matches `crate/out/` after setup and that the walk skips `crate/out/`.
- `test_setup_ignores_configs_under_gitignored_directories`: `.gitignore` `node_modules/` with `node_modules/p/.tally-config.toml` and `[specs] directories = ["."]`. `--setup` with `_real_setup` succeeds, and the saved root config is empty.

## Benchmark (report the numbers in the phase review)

Rebuild the introduction's synthetic trees under `$TMPDIR` or the session scratchpad, never in the repo. Leaf directories `src/m{i}/p{j}/q{k}`, each holding `a.py`, give a fake repo (`.git/` directory) with about 1k, 5k and 20k directories. A fourth tree has `node_modules/pkg{0..2999}/{lib,lib/internal,dist}` and `.gitignore` `node_modules/`. For each, time:

- TUI start: `SetupApp(root, load_gitignore(root), set(), set())`, from entering `run_test()` to after the first `pilot.pause()`;
- `s` on the root, followed by `pilot.pause()`;
- for comparison, `walk_project(root, set())`.

Also time `cli`'s `--setup` path on the node_modules tree with `cli.run_setup` patched to return immediately. It should no longer include a walk of `node_modules`. Expected, against the introduction's table:

- node_modules tree: the 0.29 s discovery cost is gone, and setup start-up is within noise of the 114-directory tree on its own.
- 20k tree: no regression in TUI start (about 1.5 s), and `s` on the root faster than 0.57 s (phase 1's `Text` labels plus one `_spec_sets()` per refresh; a prototype measured 0.41-0.48 s).

## Docs

- `CLAUDE.md`, Key Design Decision 5: replace the setup half with: "Setup reads nested configs while it builds its tree (`_populate()`), wherever the walker would read them, and also beneath the scan root's own exclusions, which the user can lift. Directories another config excludes are leaves." Module map: the `config.py` row is unaffected; the `tui/setup_app.py` row gains "reads nested configs as it builds the tree". Test table and the Quick Reference total.
- `README.md`, near the `--setup` bullet: directories excluded by a parent or nested config are shown without their contents.
- Architect persona, both copies (`.claude/agents/architect-tallyman.md` line 132, `plans/006-tallyman-architect.plan.md` line 182 at 75dd0fd): replace the `discover_nested_configs()` parenthesis with "under `--setup`, `SetupApp._populate()` reads them the same way as it builds the tree, registering their patterns on the shared spec; the walker's repeat registration is a no-op." And: a directory another config excludes is a leaf in setup.
- `change-log.md` under `0.4.3 - UNRELEASED`, `### Changed`:
  - Setup reads nested configs only where the walker would (not inside gitignored, pattern-excluded or hidden directories, or ones another config excludes), and no longer walks the whole tree first to find them. Setup on a project with a large gitignored `node_modules` opens without that extra walk.
  - Directories excluded by a parent or nested config are shown in setup without their contents.
  - `Files:` and `Plan:` lines.

## Done when

- The `load_nested_config` spy test shows setup and the walker reading the same configs, nested repos included.
- `discover_nested_configs` appears nowhere in `src/` or `tests/` (`grep -rn discover_nested_configs src tests` is empty).
- The benchmark numbers meet the expectations above.
- All checks in the introduction's rules are clean.
