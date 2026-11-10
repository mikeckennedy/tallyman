# Phase 1 - Merge the Config Chain

Covers decisions 1 and 2 from `00-plan-introduction.plan.md`.

## Goal

Every `.tally-config.toml` from the git root down to the scan root applies, not just the nearest one. Setup shows the inherited settings as locked and saves only local changes.

## Current behaviour

`cli.main()` calls `find_config(root)`, loads the single nearest config and rebases it onto the scan root. With `repo/.tally-config.toml` excluding `vendor` and `repo/app/.tally-config.toml` excluding `app/build`... the second file's entry is relative to `app`, so it excludes `app/build/build`. That part is fine. But scanning `repo/app` uses only `app`'s config, so `repo`'s exclusion of `app/vendor` is silently lost.

## Changes

### `config.py`

- Replace `find_config(root)` with `find_configs(root) -> list[Path]`: every config file from the search stop down to *root*, shallowest first. The search stop is the same as today: the git root inside a repo, *root* itself outside one. Keep the docstring's explanation of why the search stops there.
- Add `merge_configs(shallow, deep) -> TallyConfig` for two configs in the same coordinates:
  - `excluded_dirs`: union.
  - `spec_dirs`: `(shallow.spec_dirs - deep.non_spec_dirs) | deep.spec_dirs`.
  - `non_spec_dirs`: `(shallow.non_spec_dirs - deep.spec_dirs) | deep.non_spec_dirs`.
  So the deeper config wins when both name the same path. Different paths are left to the walker's deepest-entry rule.
- Factor the prefixing in `load_nested_config()` into a `prefixed(config, rel_dir) -> TallyConfig` helper and reuse it.
- Add `load_config_chain(paths, root) -> ConfigChain`, where `ConfigChain` is a small dataclass:
  - `inherited: TallyConfig`: every config above the scan root. Each one is prefixed by its directory relative to the shallowest config's directory, folded shallow to deep with `merge_configs`, then rebased onto *root* with `rebase_config(..., top_dir, root)`. The existing cover rule then decides `'.'`.
  - `local: TallyConfig`: the config at *root* itself, unchanged, or empty if there is none.
  - `paths: list[Path]`: the files loaded, for phase 2's pattern layers.
  - `effective` (property): `merge_configs(inherited, local)`, which is what the walker uses.
  - It raises `ConfigError` for a malformed file. The error carries that file's path; add a `path: Optional[Path]` attribute to `ConfigError`, or have the CLI catch and re-raise per file.

### `walker.py` and `discover_nested_configs()`

Nested configs below the scan root are unioned today, so a spec entry wins over an ignore entry on the same path whichever config said it. Fold them with `merge_configs` instead (current state as *shallow*, the nested config as *deep*). `os.walk` is top-down, so an ancestor's config is always merged before a descendant's, and the deeper config wins, as it does in the chain.

### `cli.py`

- `_load_config_or_exit()` becomes `_load_chain_or_exit(root) -> ConfigChain`. On `ConfigError`, it prints the failing file's path and the same hint as today, then exits 1.
- Normal run: when `find_configs()` returns anything, use `chain.effective` for the walk. First-run setup is skipped exactly as today when any config is found.
- `--setup`: load the chain. If a file is malformed, warn and skip that file (today's behaviour for the one config), and keep going. Pass `chain.local` as the editable settings and `chain.inherited` to the TUI as locked settings.
- Before saving, drop local entries that exactly duplicate an inherited entry in the same set. Older versions of `--setup` copied parent settings into new configs, and this clears those copies the next time setup runs.
- Saving, and walking afterwards, use `merge_configs(chain.inherited, result)`.
- The root-auto-spec step (`SELF` added when `inside_auto_spec_dir`) runs on the effective sets, unchanged.

### `tui/setup_app.py`

- `SetupApp` and `run_setup()` take `inherited: Optional[TallyConfig] = None`.
- Replace `locked_by_nested: bool` with `locked_by: Optional[str]`, either `'parent'` or `'nested'`. A path in an inherited set is locked with `'parent'`, one in a nested set with `'nested'`. If both apply, the deeper source wins, so nested is checked first.
- Labels: `(set in a parent config)` / `(set in a nested config)`.
- `_spec_sets()` and `_derive()` include inherited entries, merged with the user's own via `merge_configs(inherited, user)`, so the TUI computes what the walker will.
- The root node's `'.'` state can come from an inherited config; `root_spec_state()` already takes the sets.
- A child of a directory excluded by a parent config is shown as excluded, through the existing `parent_excluded` path.

## Tests

`tests/test_config.py`:

- `find_configs()` returns git root, middle and scan-root configs shallowest first, and stops at the git root. Outside a repo, it returns at most the scan root's config.
- `merge_configs()`: union of exclusions; deeper wins on the same path in both directions.
- `load_config_chain()`:
  - Parent excludes `app/vendor`, `app`'s config excludes `build`; scanning `app` excludes both `vendor` and `build`.
  - Parent `specs.ignore = ["app/plans"]`, `app`'s config `specs.directories = ["plans"]`: `plans` is specs (deeper config wins).
  - A parent spec entry covering the scan root becomes `'.'`, and a deeper ignore entry in a middle config beats it.
  - A malformed middle config raises `ConfigError` naming that file.

`tests/test_walker.py`: a nested config's ignore entry beats its parent nested config's spec entry on the same path.

`tests/test_cli.py`:

- The `repo` / `repo/app` scenario above, through `main()`.
- A malformed parent config: exit 1, its path on stderr.
- `--setup` with only a parent config writes a scan-root config that contains none of the parent's entries. Patch `run_setup` to return the settings it received.
- `--setup` drops a local entry that duplicates an inherited one.

`tests/test_setup_app.py`:

- An inherited exclusion is labelled excluded and locked, and `x` on it does nothing.
- An inherited spec entry is labelled `(set in a parent config)`, and saving does not return it.

## Done when

- The `repo` / `repo/app` scenario counts the way the merged rules say.
- Old single-config projects produce identical output (the existing tests pass unchanged, apart from the `find_config` rename).
- All checks in the introduction's rules are clean.
