# Phase 3 - Spec Overrides and TUI Fixes

Covers H4, H10 and H11 from `00-plan-introduction.plan.md`.

## Goal

What the setup TUI shows is what the walker does. In particular, a user can turn off spec classification for an auto-detected directory and have it stay off.

## H4 - un-marking an auto-detected spec directory

### Current behaviour

`walk_project()` marks any directory named `specs`, `specifications`, `plans` or `agents` (case-insensitive, at any depth) as a spec directory. In the TUI, pressing `s` on such a directory changes its label to a green check and removes it from `user_spec_dirs`, but nothing is saved that tells the walker to skip auto-detection. Results still show Specs.

A realistic case: `src/myapp/agents/` holds application code with a README. The user does not want that README counted as a spec.

### Change (recommended, pending decision 4)

Add a third set to the config:

```toml
[specs]
directories = ["design-notes"]
ignore = ["src/myapp/agents"]
```

- `config.py`: add `non_spec_dirs: set[str]` to `TallyConfig`; read it from `specs.ignore` in `load_config()`; write it in `save_config()` when non-empty; translate it in `discover_nested_configs()` like the other two sets.
- `walker.py`: `walk_project()` takes `non_spec_dirs`. A directory that is in the set, or beneath a directory in the set, is not a spec directory, and auto-detection by name is skipped for it. An explicit entry in `spec_dirs` deeper than the ignored directory still wins, so a user can ignore `agents/` but mark `agents/plans/` as specs. Nested configs contribute to the set the same way they do for the others.
- `tui/setup_app.py`:
  - Track `user_non_spec_dirs`, seeded from the existing config.
  - `_populate()` treats a directory in that set (or under one) as not spec, including for the inherited and auto cases.
  - `_set_spec(node, False)` on a node that is auto-detected or inherits spec status adds its path to `user_non_spec_dirs`. `_set_spec(node, True)` removes it.
  - The app's return value and `run_setup()` grow from a 2-tuple to a 3-tuple. Update the type parameters and `cli.main()`.
- `cli.py`: pass the new set through to `save_config()` and `walk_project()`.

## H10 - `x` on the root node

Pressing `x` with the cursor on the root adds `''` to `user_excluded`, cascades to every child, and saves `""` in the config. Root-level files are still counted, so the result is neither "everything" nor "nothing".

Change: `action_toggle_node()` and `action_toggle_spec()` return early when `node.data['path'] == ''`. The root is not toggleable.

## H11 - children of an excluded directory show as included

When setup is reopened with `src` already excluded, `_populate()` computes `is_excluded` for each child from `child_rel in self.user_excluded` only, so `src/vendor` shows a green check under a red cross.

Change: pass a `parent_is_excluded` flag down through `_populate()` the same way `parent_is_spec` is passed, and treat a child of an excluded directory as excluded. Do not add the children to `user_excluded`; `_clean_exclusions()` would remove them anyway.

Also fix the related label inconsistency: `_set_excluded(node, True)` clears `data['spec']` but leaves `data['auto_spec']` set, so after exclude then re-include, the label shows `S` while `data['spec']` is `False`. On re-include, recompute spec status from the same rules `_populate()` uses.

## Tests

Add `tests/test_setup_app.py` (new) using Textual's `App.run_test()` pilot. The review drove the app this way successfully; pattern:

```python
async with app.run_test(size=(100, 40)) as pilot:
    app.query_one(SetupTree).focus()
    await pilot.press('down', 's')
    await pilot.click('#save')
assert app.return_value == ...
```

Check whether `pytest-asyncio` is needed or wrap each test body in `asyncio.run()`; prefer the latter to avoid a new dev dependency.

Cases:

- Save with no changes returns empty sets, and `plans` is labelled as specs.
- `s` on `plans` returns `plans` in the non-spec set, and `walk_project()` with that result yields `plans/a.md` and `plans/sub/b.md` as `docs`.
- `x` on the root changes nothing.
- Reopen with `src` excluded: `src/vendor` is labelled excluded; saving returns `{'src'}`.
- `x` twice on `plans` leaves it labelled and stored as a spec directory.

Add to `tests/test_walker.py`:

- `non_spec_dirs` suppresses auto-detection for the directory and its descendants.
- An explicit `spec_dirs` entry beneath a non-spec directory still applies.
- A nested config's `specs.ignore` is translated to root-relative paths.

Add to `tests/test_config.py`: load, save and round-trip of `specs.ignore`.

## Done when

- The five TUI cases pass.
- Old configs without `specs.ignore` load unchanged.
- `pytest`, `ruff check` and `ruff format --check` are clean.
