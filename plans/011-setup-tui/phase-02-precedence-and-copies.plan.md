# Phase 2 - Walker Precedence and One File per Setting

Covers decisions 2-4 from `00-plan-introduction.plan.md` (review items 3, 10 and 15).

## Goal

Setup never keeps a scan-root copy of a setting that a parent or nested config already holds. Its labels and toggles follow the walker's exclusion order: config exclusion, then gitignore, then patterns.

## Copies (item 3)

### What counts as a copy

A scan-root entry is a **copy** when a parent config (`inherited`) or a nested config (`nested`) has the same path **in the same set**:

| Scan root has | Other config has | What it is | Setup |
|---|---|---|---|
| `excluded_dirs` `sub/gen` | nested `excluded_dirs` `sub/gen` | copy | dropped |
| `spec_dirs` `lib` | nested `spec_dirs` `lib` | copy | dropped |
| `spec_dirs` `docs` | parent `spec_dirs` `docs` | copy | dropped |
| `non_spec_dirs` `docs` | parent `spec_dirs` `docs` | override (scan root is deeper) | kept, editable (today's `_original_entry` exception) |
| `spec_dirs` `lib` | nested `non_spec_dirs` `lib` | shadowed (nested is deeper and wins) | kept, locked by the nested config (open question 1) |
| both `spec_dirs` and `non_spec_dirs` `docs` | parent `spec_dirs` `docs` | contradictory hand edit | both kept, as `without_inherited()` does today |
| `excluded_dirs` `src/vendor` | parent `excluded_dirs` `src` | redundant child, not a copy | kept (open question 2) |

### `src/tallyman/config.py`

- Rename `without_inherited(local, inherited)` to `without_copies(local, *others)`: *local* minus every entry that any of *others* has in the same set, with the contradictory-entry rule unchanged (compute `contradictory` from *local* once, then subtract each other config in turn). The docstring should explain "copy" as in the table above and say why opposite-set entries stay. Update `TallyConfig`'s docstring, which lists it among the functions that return no patterns.

### `src/tallyman/tui/setup_app.py`

- New `_drop_copies()`: `local = without_copies(TallyConfig(user_excluded, user_spec_dirs, user_non_spec_dirs), self.inherited, self.nested)`. Reassign the three `user_*` sets from it and rebuild `_original_entry` from the cleaned spec sets.
- Call it in `compose()` right after `_populate()` and before `_refresh()`. (Phase 3 makes `_populate()` collect the nested configs, so this position is the one that keeps working.) Setup then opens showing a dropped copy as locked, with `(set in a parent config)` or `(set in a nested config)`, which is what will be true after saving.
- On Save, return `without_copies(...)` of the user sets once more, after `_clean_exclusions()`. It's idempotent, and it guarantees that setup never returns a setting another config holds, whatever the toggles did.
- `run_setup()`'s docstring already promises this. Make it true.

### `src/tallyman/cli.py`

- Save what setup returns: `local = TallyConfig(*result)`. Drop the `without_inherited` import and its comment. The comment moves to `_drop_copies()`, which is now the one place that knows every source of locked settings.

## Precedence (item 10)

### `src/tallyman/tui/setup_app.py`

- `NodeInfo` gains a derived `config_excluded: bool = False`: the path is in `user_excluded`, `nested.excluded_dirs` or `inherited.excluded_dirs`. `gitignored` and `pattern_excluded` stay as they are: static facts from `_populate()`, meaning "gitignore or a pattern would exclude this entry if no config did". Update the class docstring.
- `_derive()`: set `config_excluded` (today's `excluded_here`), and `excluded = config_excluded or gitignored or pattern_excluded or parent.excluded`. The `excluded` value doesn't change; only what explains it does.
- Add a small helper, `_rule_excluded(info) -> bool`: `(info.gitignored or info.pattern_excluded) and not info.config_excluded`. That means "excluded by gitignore or a pattern, which setup can't change". Use it in:
  - `_cursor()`: return None only when `_rule_excluded(info)`. A user exclusion on a gitignored or pattern-matched directory can then be toggled off with `x`.
  - `_label_for()`: pass `gitignored=info.gitignored and not info.config_excluded` and the same for `pattern_excluded` to `_make_label()`, so a config-excluded node gets `✗ name`. Replace `unchangeable` with `_rule_excluded(info)` for the lock-credit rule.
  - `_would_be_spec()`'s probe: copy the static flags as today; `_derive()` fills `config_excluded`.
- `_populate()` doesn't change in this phase. It still doesn't recurse into gitignored or pattern-matched directories, so a config-excluded one of those still has no children. That matches the walker either way.
- Comment at the `_derive()` exclusion line: "Same order as walk_project(): a config exclusion is checked first, then gitignore, then patterns."

## Tests

`tests/test_setup_app.py`. Write nested-config cases with real config files on disk, passing `nested=discover_nested_configs(tmp_path)` as the existing tests do, so phase 3 only has to delete that argument.

New class `TestCopies`:

- `test_copy_of_a_nested_exclusion_is_dropped` (the review's case): `sub/.tally-config.toml` excludes `gen`, `Session(excluded={'sub/gen'}, ...)`. `run([])` returns `(set(), set(), set())`, and the label is `✗ gen (set in a nested config)`.
- `test_copy_of_a_nested_spec_setting_is_dropped`: `lib/.tally-config.toml` with `[specs] directories = ["."]`, `specs={'lib'}`. Result `(set(), set(), set())`; label `S lib (set in a nested config)`.
- `test_copy_of_a_parent_spec_setting_is_dropped_and_locked`: `specs={'docs'}`, `inherited=TallyConfig(spec_dirs={'docs'})`. `run([('docs', 's')])` returns `(set(), set(), set())`: `s` does nothing, because the node is now locked. Label `S docs (set in a parent config)`.
- `test_shadowed_entry_is_kept`: `specs={'lib'}` with `lib/.tally-config.toml` `[specs] ignore = ["."]`. Result `(set(), {'lib'}, set())`; label `✓ lib (not specs) (set in a nested config)`.
- `test_tui_and_walker_agree_after_dropping_copies`: the copy cases above, walked with `merge_configs(inherited, result)` and the nested configs on disk, give the same categories as walking with the original, undropped settings. Dropping a copy never changes a count.
- Keep `TestParentConfigs.test_a_local_override_of_a_parent_setting_stays_editable` unchanged. It is the regression test for the override exception.

New class `TestExclusionPrecedence`:

- `test_config_exclusion_outranks_a_pattern`: `Session(excluded={'vendor'}, patterns=['vendor/'])`. Before any key, the label is `✗ vendor`. After `x` on `vendor`, the result is `(set(), set(), set())` and the label is `vendor (excluded by pattern)`.
- `test_walker_counts_the_pattern_only_where_the_tui_shows_it`: a tree with `vendor` (user-excluded and pattern), `fixtures` (pattern only), and `gen` (inherited exclusion and pattern). Walk with the saved settings, the same pattern spec and a `WalkStats`. `stats.pattern_dirs` equals the number of labels containing `(excluded by pattern)` whose parent node isn't excluded (here 1). Repeat after `x` on `vendor` (here 2).
- `test_parent_exclusion_outranks_a_pattern`: `inherited=TallyConfig({'gen'})`, `patterns=['gen/']`. Label `✗ gen (set in a parent config)`; `x` does nothing.
- `test_config_exclusion_outranks_gitignore` (open question 4): `.gitignore` `build/`, `excluded={'build'}`. Label `✗ build`. After `x`: result `(set(), set(), set())`, label `build (gitignored)`, and a second `x` does nothing.

Replacing `TestCleanExclusions` (item 15). Delete it from `tests/test_config.py`, along with that file's `SetupApp` import, so `test_config.py` no longer imports Textual. Add to `TestExcludeToggles`:

- `test_saving_drops_exclusions_below_an_excluded_directory`: `Session(excluded={'src/vendor', 'src/agents/inner'}).run([('src', 'x')])` returns `({'src'}, set(), set())`.
- `test_saving_drops_a_chain_of_nested_exclusions`: pre-filled `{'src', 'src/agents', 'src/agents/inner'}`, `run([])` returns `({'src'}, set(), set())`.
- `test_sibling_and_prefix_named_exclusions_are_kept`: `_make_tree(tmp_path, ['src', 'src2', 'lib'])`, pre-filled `{'src', 'src2', 'lib'}`, `run([])` returns all three. `src2` starts with `src`, but it isn't beneath it.
- The empty case is already covered by `TestSpecToggles.test_untouched_save`.

`tests/test_config.py`: rename the `without_inherited` tests to `without_copies`, and add one with two *others* (a parent and a nested config), checking both kinds of copy are removed and a contradictory pair survives.

`tests/test_cli.py`:

- Add a helper, `_real_setup(monkeypatch, actions=())`. It patches `cli.run_setup` with a function that builds the real `SetupApp` from the arguments it receives (same names and order as `run_setup()`), drives it headless through `run_test()`, presses *actions* the way `Session.run()` does, clicks `#save`, and returns `app.return_value`. Import `SetupApp` inside the helper. This is the only end-to-end path that exercises copy-dropping now that it lives in the app.
- `test_setup_drops_a_local_copy_of_a_nested_exclusion`, the review's scenario end to end. Root config `[exclude] directories = ["sub/gen"]`, `sub/.tally-config.toml` excluding `gen`, `sub/gen/a.py`. Run `--setup` with `_real_setup`. The root config's `excluded_dirs` is now empty. Then delete `sub/.tally-config.toml` and run normally: `sub/gen/a.py` is counted.
- Rewrite `TestSetupWithParentConfig.test_setup_drops_local_copies_of_parent_settings` to use `_real_setup` instead of the `ECHO` fake. The saved file excludes only `build`.

## Docs

- `CLAUDE.md`, Key Design Decision 5: "Setup edits only `local`: parent and nested settings are shown locked and never copied (`without_copies()` drops copies of either, an entry with the same path in the same set, when setup opens and again on save; an opposite-set entry over a parent's is an override and stays editable)." Decision 8: "The TUI shows matched directories as "(excluded by pattern)" and locks them, unless a config excludes them: the walker checks config exclusions first, then gitignore, then patterns, and the TUI labels follow that order."
- `README.md`, the `--setup` bullet (line 218 at 75dd0fd): say nested settings are shown "(set in a nested config)" too, and that copies of either kind written by earlier versions are removed the next time setup saves.
- Architect persona, both copies (`.claude/agents/architect-tallyman.md` lines 126, 130 and 183; `plans/006-tallyman-architect.plan.md` lines 180 and 183 at 75dd0fd): `without_inherited()` becomes `without_copies()`, dropping parent *and* nested copies inside `SetupApp`. The pattern-label sentence gains the precedence rule.
- `change-log.md` under `0.4.3 - UNRELEASED`, `### Fixed`:
  - Setup drops scan-root copies of nested config settings, as it already did for parent settings. Earlier versions wrote these copies, and they could never be removed in setup, so removing the nested setting later left the directory excluded.
  - A directory a config excludes is labelled as excluded by that config, even when gitignore or a pattern also matches it, matching the walker. A redundant scan-root exclusion there can now be toggled off.
  - `Files:` and `Plan:` lines.
- `CLAUDE.md` test table (`test_setup_app.py`, `test_config.py`, `test_cli.py`) and the Quick Reference total.

## Done when

- The review's item 3 scenario saves an empty exclusion list, and removing the nested config then counts `sub/gen`.
- The review's item 10 scenario labels `vendor` `✗ vendor`, `x` removes the entry, and `WalkStats` agrees with the labels in both states.
- `test_config.py` has no `SetupApp` or `_clean_exclusions` reference.
- All checks in the introduction's rules are clean.
