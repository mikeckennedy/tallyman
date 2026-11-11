# Phase 4 - A Setup Toggle for Rust Test Code

Added after phases 1-3. Michael asked (2026-11-11) for `--setup` to set `[rust] exclude_test_modules`, shown only when the project has Rust code. This reverses decision 7's "no toggle"; the rest of decision 7 (setup writes the scan root's own value, never a parent's) stands.

## Decisions (2026-11-11)

1. **Shown only when there is Rust.** The status line, the `r` binding and the mention in the instructions appear only if setup found a `.rs` file (by `identify_language() is RUST`, so `.RS` too) in a directory it reads while building the tree. Those are the directories the walker would enter, plus the scan root's own exclusions, which the user can lift in setup. Files under gitignored, pattern-excluded or parent/nested-excluded directories aren't looked at. Symlinks don't count, as in the walker.
2. **`r` flips the effective value**: counted ↔ excluded. Michael didn't pick between flipping and cycling; a flip, with rule 3, needs no third "inherit" state on screen.
3. **The smallest change, as `s` does.** After a toggle, the scan root's value is the first of these that gives the wanted state: the value it had when setup opened, then None (no `[rust]` table: the parent configs' value, or off when none sets it), then an explicit `true`/`false`. So pressing `r` twice always returns to where it started, and a value that only repeats the parents' isn't written. With no parent and no local value, on writes `true` and off removes the table again; under a parent's `true`, off writes `false`.
4. **Untouched means unchanged.** If `r` is never pressed, the scan root's value is saved exactly as loaded, as in phase 2.
5. **The line says where the value comes from:** `Rust test code: counted` or `Rust test code: excluded (#[cfg(test)] items left out)`, plus `(set in a parent config)` when the scan root's config doesn't set it and a parent does.

## Changes

- `config.py`: `load_config_chain()` sets `chain.inherited.rust_exclude_test_modules` to the deepest parent's value (None when no parent sets it), so setup gets it through the existing `inherited` argument. `ConfigChain.rust_exclude_test_modules` is unchanged (local, else parents, else False). Update the `ConfigChain` docstring.
- `tui/setup_app.py`:
  - `SetupResult` becomes a `NamedTuple`: `excluded_dirs`, `spec_dirs`, `non_spec_dirs`, `rust_exclude_test_modules`. The CLI reads the fields; `TallyConfig(*result)` would now put the fourth item in `patterns`.
  - `SetupApp(..., existing_rust: Optional[bool] = None)` and the same keyword on `run_setup()`.
  - `_populate()` sets `self.has_rust` when it sees a Rust file.
  - The tree is built before the instructions are composed, so they can mention `r` only when there is Rust.
  - `Binding('r', 'toggle_rust_tests', ...)`, hidden and inactive without Rust (`check_action()`). A `Static#rust` line under the tree, only with Rust.
- `cli.py`: `run_setup(..., existing_rust=...)` passes `chain.local.rust_exclude_test_modules`. After setup, save `result.rust_exclude_test_modules` and count with it (or the parents' value, or False).

## Tests

- `tests/test_setup_app.py` (pilot):
  - no `.rs` file: no `#rust` widget, and `r` does nothing (the result keeps the loaded value);
  - a `.rs` file, including in a subdirectory and in a directory the scan root's config excludes: the line shows;
  - `.rs` only under a gitignored directory: no line;
  - `r` with no parent: `True`; `r` twice: None; an existing `false` with no parent: `r` gives `True`, `r` again gives `false` back;
  - under a parent's `true`: the line says "(set in a parent config)"; `r` gives `False`; `r` again gives None;
  - untouched: an existing `false` (or `true`) comes back as loaded.
- `tests/test_cli.py`: through `_real_setup`, pressing `r` writes `[rust] exclude_test_modules = true` and that run counts without the test module. The fake setup returns the new four-field result.
- `tests/test_config.py`: `chain.inherited.rust_exclude_test_modules` is the deepest parent's value and ignores the scan root's own.

## Docs

README (the "Setup" bullet of "Leaving out Rust test code", and the TUI keys under Configuration), `CLAUDE.md` (decision 10, module map row for `setup_app.py`, test counts), the persona copies, and the changelog's 0.5.4 entry.

## Done when

All checks in "Rules for every phase" are clean, the architect review's valid findings are addressed, and the phase is committed: `Plan 013 phase 4: setup toggle for Rust test code`.

## Review findings (2026-11-11)

The architect checked Rust detection against the walker in 15 trees, the toggle rule in all 36 combinations of parent value, local value and 0-3 presses (the line always shows what the CLI counts with, two presses always restore the loaded value, and a value that only repeats the parents' is never written), the footer, and every `SetupResult` consumer.

Fixed:
- **Must fix: a nested config's `[rust]` was ignored.** In a workspace whose crate sets its own value, the line said "counted" while that crate's tests were left out, and `r` did nothing there. `_populate()` now carries the nested value per directory, like the walker's map. Rust it governs sets `has_nested_rust` instead of `has_rust`: the line then says `set in a nested config` (when all Rust is there, with `r` hidden) or adds `(some directories set their own in a nested config)`.
- The footer test is now a pilot test of the footer's keys, and a parametrized test checks setup's Rust detection against the walker (nested patterns, nested repos, hidden directories, negation).
- `config.rust_setting(local, parents)` is the one "local, else parents, else off" rule, used by the chain, the CLI after setup and setup's line.
- README wording; `TallyConfig` docstring notes that `ConfigChain.inherited` carries the parents' `[rust]` value.

Known and left: a binary `.rs` file shows the line although the walker skips it (setup reads no file contents).
