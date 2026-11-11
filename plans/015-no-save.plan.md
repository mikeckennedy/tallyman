# Plan 015 - `--no-save`: Setup Without Writing a Config

## Context

GitHub issue #5, "Allow usage without storing a config file". The reporter dislikes the clutter of a `.tally-config.toml` in projects they only measure now and then, and would accept going through setup on every run. They suggested `--no-setup`, `--default-settings` or `--readonly`.

## The code today (after plan 014, version 0.6.5, unreleased)

- `cli.main()` has three paths: a config applies at the scan root (load it, no setup); no config and no terminal (defaults, write nothing, a one-line note on stderr); and setup (a first run in a terminal, or `--setup`), which launches the TUI and then calls `save_config()` on the scan root's config. A failed save warns and counts with the selections anyway.
- `cli.run_setup()` only defers the Textual import; its signature must equal `tui.setup_app.run_setup()`'s (`tests/test_cli.py::test_run_setup_hands_every_argument_to_the_tui`, and `_real_setup()` asserts it too).
- The TUI's confirm button is `Button('Save & Run', id='save')`.

## Decisions (confirmed with Michael, 2026-11-11)

1. **`--no-save`.** Setup runs as it does today (a first run in a terminal, or `--setup`), and its choices apply to this run only. Nothing is written, so the next run opens setup again.
2. **Existing configs are still read.** With a config in place and no `--setup`, `--no-save` changes nothing: there is no setup and nothing to save. With `--setup --no-save`, setup opens pre-filled from the existing config, which is left as it is.
3. **The TUI says so.** The button reads `Run` instead of `Save & Run` (the id stays `save`), and the header's subtitle reads `Not saved: this run only` (short, so an 80-column header shows it after the title).
4. **No terminal: unchanged.** That path already writes nothing.
5. **Version 0.7.6**, its own `## 0.7.6 - UNRELEASED` changelog section above 0.6.5.

## Steps

1. `tui/setup_app.py`: `SetupApp(..., save: bool = True)` and `run_setup(..., save: bool = True)`; label and subtitle when `save` is False.
2. `cli.py`: the `--no-save` flag; `cli.run_setup()` gains `save`; the setup path passes `save=not args.no_save` and skips `save_config()` with `--no-save`.
3. Tests: `test_setup_app.py` (button label and subtitle, the result is unchanged), `test_cli.py` (first run and `--setup` write nothing and count with the choices, an existing config is untouched, the real TUI with `--no-save`, no terminal).
4. Docs: README (quick reference, Configuration), `CLAUDE.md` (quick reference, module map, decision 5, test counts), `change-log.md`, version bump and `uv lock`.
5. Architect review with `architect-tallyman`; record findings below; commit.

## Review findings

Architect review (`architect-tallyman`), 2026-11-11. No path writes or changes a config under `--no-save`; the count is the same as a saving run's. Addressed:

1. **Medium: false warning.** `--setup --no-save` over a malformed scan-root config warned "setup will write a new config", but nothing is written. `_warn_and_skip(root, save=...)` now says the file is left as it is. Test: `TestNoSave.test_setup_leaves_a_malformed_config_alone`.
2. **Low: subtitle cut off at 80 columns.** Shortened to `Not saved: this run only`.
3. **Low: patterns under `--setup --no-save` not pinned.** `test_setup_leaves_an_existing_config_alone` now has an `x.log` the config's `*.log` pattern must leave out.
4. **Low (docs): `CLAUDE.md` module map.** The `tui/setup_app.py` row mentions `save=False`.

Also taken: `test_cancel_still_exits` uses `_run(..., setup=...)` like the rest of the class. Left as decided (decision 4): the no-terminal note still suggests `tallyman --setup` under `--no-save`.
