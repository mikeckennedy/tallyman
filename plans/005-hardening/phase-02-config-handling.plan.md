# Phase 2 - Config Handling

Covers H3, H5, H6, H7 and H8 from `00-plan-introduction.plan.md`.

## Goal

A config file is always applied relative to the directory it lives in, bad configs produce a readable error, and tallyman never hangs when there is no terminal.

## H3 - parent config applied with the wrong base

### Current behaviour

`find_config(root)` in `src/tallyman/config.py` walks up to the filesystem root. `cli.main()` loads whatever it finds and passes `excluded_dirs` / `spec_dirs` straight to `walk_project(root, ...)`, which treats them as relative to the scan root.

Reproduction: `proj/.tally-config.toml` excludes `["src/vendor", "docs"]`. Running `tallyman proj/src` counts `src/vendor/lib.py` and drops `src/docs/conf.py`.

With `--setup` in a subdirectory, the parent's paths are also fed to the TUI as existing exclusions and then saved into a new config at the scan root.

### Change (recommended, pending decisions 1 and 2)

- Add `rebase_config(config, config_dir, root) -> TallyConfig` in `config.py`. With `rel = root.relative_to(config_dir).as_posix()`:
  - `rel == '.'`: return the config unchanged.
  - An entry that starts with `rel + '/'`: keep it with that prefix stripped.
  - An entry equal to `rel`, or an ancestor of it: drop it. The user asked for this directory explicitly, so scan it. For `spec_dirs`, an entry equal to or above `rel` means the whole scan root is a spec directory; represent that so docs files at every level are classified as specs (see the note below).
  - Any other entry: drop it, since it points outside the scan root.
- `cli.main()` calls `rebase_config()` after `load_config()` in both the normal and the `--setup` branch.
- `find_config()` stops at the git root when the scan root is inside a git repo. Outside a repo it checks only the scan root itself. `find_git_root()` lives in `walker.py`; move it to a place both modules can import without a cycle (`walker.py` already imports from `config.py`).

Note on whole-root spec: `walk_project()` currently only evaluates spec status for `rel_dir_str != ''`. Supporting "the scan root itself is a spec dir" needs a small change there, for example a `root_is_spec: bool` argument. If that proves awkward, it is acceptable to drop the case and document it.

## H5 - no TTY

### Current behaviour

With no config, `cli.main()` always calls `run_setup()`. With stdin not a terminal, Textual starts anyway, writes escape codes to the pipe and never exits.

### Change (recommended, pending decision 3)

In `cli.main()`, before launching the TUI, check `sys.stdin.isatty() and sys.stdout.isatty()`.

- No config, no TTY, no `--setup`: skip the TUI, run with empty exclusions (auto-detected spec dirs still apply), write no config, and print one line to stderr saying setup was skipped and how to run it.
- `--setup` with no TTY: print an error to stderr and exit with status 2.

## H6 - malformed root config

Wrap the root `load_config()` call in `cli.main()`. On `tomllib.TOMLDecodeError` or `OSError`, print `Error: could not read <path>: <reason>` to stderr with a hint to fix the file or re-run `tallyman --setup`, and exit 1. No traceback.

Also validate shape in `load_config()`: `exclude.directories` and `specs.directories` must be lists of strings. Raise a `ValueError` with a clear message otherwise, and have the CLI report it the same way. Nested configs keep their existing skip-on-error behaviour.

## H7 - string escaping in `save_config`

`save_config()` writes `f'    "{d}",'`. Escape `\` and `"` (and control characters) per the TOML basic-string rules, in a small `_toml_string()` helper. A round-trip test is the acceptance check: `load_config(save_config(x)) == x` for names containing `"`, `\`, and non-ASCII characters.

## H8 - path normalisation

In `load_config()`, normalise each directory entry: replace `\` with `/`, strip a leading `./`, strip trailing `/`, and drop empty strings. The empty-string case also cleans up configs already written by the TUI root-toggle bug (H10, fixed in phase 3).

## Tests

Add to `tests/test_config.py`:

- `rebase_config` for each of the five entry cases above.
- `find_config` stops at the git root; outside a repo it does not look above the scan root.
- Round-trip of awkward directory names (H7).
- Normalisation of `vendor/`, `./static`, `a\\b` and `""` (H8).
- Shape validation errors.

Add `tests/test_cli.py` (new), calling `cli.main()` with `sys.argv` patched and `capsys`:

- Parent config with `src/vendor` excluded, scan `proj/src`: `vendor` is excluded and `docs` is counted.
- Malformed root config: exit status 1, message on stderr, no traceback.
- No config and no TTY: completes, prints results, writes no `.tally-config.toml`.
- `--setup` with no TTY: exit status 2.

## Done when

- The H3 reproduction gives the correct file list.
- `tallyman some/dir < /dev/null` on a directory with no config returns promptly.
- `pytest`, `ruff check` and `ruff format --check` are clean.

## Outcome

Implemented as planned, plus fixes from the architect review.

**Review fixes:**

- A non-UTF-8 config raised `UnicodeDecodeError`, which is not a `TOMLDecodeError`. That gave a traceback, and in a nested config it aborted the whole scan. This was a regression from narrowing `except Exception`.
- `--setup` run inside a parent-config spec directory saved an empty config, so specs became docs. The `root_is_spec` field could not be saved. It is gone: `"."` in `[specs] directories` now means "this directory", and it round-trips through setup.
- Scanning from inside an auto-detected spec directory counted Docs.
- The error hint pointed at the scan root instead of the broken config's directory.
- A failed config save lost the user's setup choices. A closed stdin crashed. A mistyped path case on macOS (`proj/SRC`) defeated rebasing; `paths.canonical_case()` now fixes the spelling.
- The `--setup` path had no test of its pre-fill or saved file.

**Deferred, needs Michael's decision.** Nearest config wins, so a parent's exclusions vanish when a closer config exists. For example:

- `n/.tally-config.toml` excludes `src/vendor`.
- `n/src/.tally-config.toml` excludes `gen`.
- Scanning `n/src` counts `vendor`.

The fix would be to union every config from the git root down to the scan root, matching how nested configs below the root already merge. But setup saves only at the scan root, so a user could no longer remove a parent's exclusion from the TUI. This is the same "top-level takes precedence" rule plan 004 chose for nested configs. It interacts with issue #6's pattern excludes, so decide it there.

**README, for phase 5:**

- The config search boundary and the no-terminal behaviour are not documented.
- A dotfiles repo (`~/.git`) makes `~` the git root, so `~/.tally-config.toml` is then found from any directory below it that isn't its own repo. Rebasing keeps the counts right, but it suppresses first-run setup.
