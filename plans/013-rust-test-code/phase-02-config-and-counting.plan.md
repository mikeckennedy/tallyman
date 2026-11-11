# Phase 2 - Config, Walker and Counting

Covers decisions 1, 5 and 7 from `00-plan-introduction.plan.md`. After this phase, `[rust] exclude_test_modules = true` changes the numbers; phase 3 adds the report line and docs.

## 1. Config: read, validate, carry, save (`config.py`)

### `TallyConfig`

Add one field:

```python
rust_exclude_test_modules: Optional[bool] = None   # [rust] exclude_test_modules; None = this config doesn't say
```

Document it in the class docstring next to `patterns`: like patterns, it belongs to the file it came from (its value covers that file's directory and everything below), so `merge_configs()`, `prefixed()`, `rebase_config()` and `without_copies()` return `None` for it. Check each of those functions builds `TallyConfig` positionally today; adding the field last with a default keeps them correct, but say so in their docstrings where they already mention patterns.

### `load_config()`

Add a `_rust_option(data)` helper beside `_patterns()`:

- No `[rust]` table: `None`.
- `[rust]` is not a table: `ConfigError('[rust] must be a table')`.
- `exclude_test_modules` missing: `None`.
- `exclude_test_modules` not a TOML boolean: `ConfigError('rust.exclude_test_modules must be true or false')`. Note that `isinstance(True, int)` is true in Python; test for `bool` explicitly, and reject `1`, `"true"` and so on.
- Unknown keys in `[rust]` are ignored, as unknown keys are elsewhere.

A malformed `[rust]` makes the config malformed, with the existing consequences: exit 1 naming the file at or above the scan root, a warning and skip under `--setup`, silently skipped when nested.

### `ConfigChain`

Add `rust_exclude_test_modules: bool = False`: the value at the scan root. In `load_config_chain()`, walk the loaded configs shallowest first and keep the last one that isn't `None`. The scan root's own config is the deepest, so `local` wins over `inherited`, and among parents the deeper one wins (decision 5). Every config in the chain is the scan root or an ancestor of it, so a parent's value always covers the scan root.

### `load_nested_config()`

It returns `(prefixed config, patterns)` today, unpacked by the walker and by `setup_app._populate()`. Change it to return a small `NamedTuple`, say `NestedConfig(config, patterns, rust_exclude_test_modules)`, and update both callers. The TUI ignores the new field; it shows directories, not line counts.

### `save_config()`

Add a keyword parameter `rust_exclude_test_modules: Optional[bool] = None`. When it is not `None`, write after the `[specs]` table (or after `[exclude]` if there is no `[specs]`):

```toml

[rust]
# Leave #[cfg(test)] items out of the count
exclude_test_modules = true
```

Write `false` too: an explicit `false` overrides a parent config that turned it on (decision 7). `None` writes no `[rust]` table.

## 2. Walker: the value per file (`walker.py`)

The setting can change in any nested config, so the walker must say, for each file, whether it applies. Keep the value per directory, like `states`:

```python
rust_tests: dict[str, bool] = {}   # rel_dir -> exclude_test_modules for files in that directory
```

- The scan root starts from a new `walk_project()` argument, `exclude_rust_tests: bool = False` (the CLI passes `chain.rust_exclude_test_modules`).
- Every other directory inherits its parent's value, unless its own nested config sets one: `loaded.rust_exclude_test_modules if it is not None else rust_tests[parent]`.
- **Do not** fold this value into `active` with `merge_configs()`. `active` is shared across the whole walk, so a value set in one crate would leak into its sibling crates walked later. Add a test for exactly that.

Report it per file without breaking the ~50 tests that unpack `(path, language)`:

- Add `walk_files()`, which does the walk and yields a frozen, slotted `SourceFile(path, language, exclude_rust_tests)` dataclass (or `NamedTuple`).
- `walk_project()` becomes a thin wrapper over it, yielding `(f.path, f.language)` exactly as today, with the same arguments plus the new one.
- The CLI switches to `walk_files()`. Tests that only care which files are walked keep using `walk_project()`.

Keep the docstrings honest: `walk_files()` carries the full argument documentation, and `walk_project()` points to it.

Crossing a nested git repo boundary changes nothing here: tallyman settings cross repo boundaries on the way down (CLAUDE.md, design decision 7).

## 3. Counter (`counter.py`, `languages.py`)

- In `languages.py`, give the Rust entry a module-level name, `RUST = Language('Rust', ...)`, and use that name in `LANGUAGES`. Language identity is how tallyman tells languages apart (design decision 1), so the counter checks `language is RUST`, not the name string.
- `FileCount` gains `test_lines: int = 0`: lines left out as Rust test code. They are **not** in `total_lines`, `code_lines`, `comment_lines` or `blank_lines`.
- `count_lines(path, language, exclude_rust_tests: bool = False)`. When the flag is set and `language is RUST`, call `rust_tests.test_code_lines()` on the normalised text (the same string that is split into `lines`), then skip those indexes in the loop, adding them to `test_lines` instead. Any other language, or the flag off: behaviour unchanged, and `rust_tests` is never called.
- Update the `count_lines()` docstring.

## 4. Aggregation (`aggregator.py`)

- A file whose every line was test code (`total_lines == 0 and test_lines > 0`, e.g. a `#![cfg(test)]` file) is **not** counted in `LanguageStats.file_count`. An empty `.rs` file (no lines at all) still counts as a file, as today.
- `TallyResult` gains `rust_test_lines: int = 0` and `rust_test_files: int = 0` (files that lost at least one line). `aggregate()` sums them from each `FileCount`. Phase 3's report line reads them.
- `grand_total_lines`, category totals, percentages and the bar don't change their formulas: test lines were never added to them.

## 5. CLI (`cli.py`)

- Pass `exclude_rust_tests=chain.rust_exclude_test_modules` to the walk. On the no-config, no-terminal path it is `False`.
- After setup, the effective value is still the chain's (setup doesn't edit it), so no recomputation is needed.
- Switch the loop to `walk_files()` and call `count_lines(f.path, f.language, f.exclude_rust_tests)`.
- When saving after setup, pass `rust_exclude_test_modules=chain.local.rust_exclude_test_modules` to `save_config()`, beside `patterns=chain.local.patterns`. Update the comment there ("Setup doesn't edit patterns or [rust]: keep the scan-root config's own").

## Tests

Each must fail before its change.

**`tests/test_config.py`**
- `[rust] exclude_test_modules = true` / `false` load as `True` / `False`; no table and an empty table load as `None`.
- `[rust] = 3`, `exclude_test_modules = 1`, `= "true"` each raise `ConfigError` with the file's path.
- The chain: parent `true` + no local value = `True`; parent `true` + local `false` = `False`; two parents, deeper wins; no config anywhere = `False`.
- `merge_configs()`, `prefixed()`, `rebase_config()`, `without_copies()` return `None` for the field.
- `save_config()` writes `true`, writes `false`, omits the table for `None`, and the result reloads to the same value. Patterns and `[specs]` still round-trip with it present.
- `load_nested_config()` returns the new tuple.

**`tests/test_counter.py`**
- A Rust file with a test module: with the flag, `test_lines` equals the module's lines and the other counts cover only the rest; without the flag, counts are unchanged.
- CRLF and lone-CR line endings give the same counts as LF.
- A `.py` file containing the text `#[cfg(test)]` is unaffected by the flag (only `RUST` is scanned).

**`tests/test_walker.py`**
- `walk_files()` reports the scan root's value on every file.
- A nested config turns it on for one crate only; files in a sibling crate walked **after** it keep the root's value (the leak test).
- A nested config turns it off under a root that has it on.
- `walk_project()` still yields 2-tuples with the same files as `walk_files()`.

**`tests/test_aggregator.py`**
- `rust_test_lines` and `rust_test_files` sum correctly; a whole-test file isn't in `file_count`; an empty `.rs` file still is.

**`tests/test_cli.py`**
- End to end: a repo with `src/lib.rs` (code + test module) and a config turning the option on reports fewer Rust lines than the same repo without it, by exactly the module's size.
- A parent config's `true` applies when scanning a subdirectory.
- `--setup` (through the existing setup-saving tests' harness) keeps `[rust] exclude_test_modules = false` in the rewritten config.
- A malformed `[rust]` at the scan root exits 1 naming the file.

**`tests/test_setup_app.py`**
- Only if the `load_nested_config()` change touches it: the existing nested-config tests keep passing. No new TUI behaviour.

## Manual check

Run `tallyman` with and without the option on a real Rust workspace (Michael measured one with about 2,400 test-module lines of 23,000 Rust lines). Spot-check three files by hand: a module at the bottom, a file with code after its tests, and a `#[cfg(test)]` helper fn. Record the before and after Rust totals in the commit message.

## Done when

- Everything above is in, all checks in "Rules for every phase" are clean, and the architect review's valid findings are addressed.
- Commit: `Plan 013 phase 2: [rust] exclude_test_modules through config, walker and counter`.
