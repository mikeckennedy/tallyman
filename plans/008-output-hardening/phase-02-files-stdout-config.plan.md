# Phase 2 - Non-regular Files, Stdout Encoding, BOM Configs

Covers decisions 7-9 and open question 3 from `00-plan-introduction.plan.md`. Bugs 1, 2 and 8.

## Goal

Tallyman never blocks on a FIFO or other special file, never crashes because the terminal's encoding is narrow, and reads a config that an editor saved with a byte-order mark.

## Bug 1 - Count only regular files

Repro on main: `mkdir e; echo 'x=1' > e/a.py; mkfifo e/pipe.py; tallyman e` never returns. The same happens with `mkfifo e/sub/.gitignore`.

### `walker.py`

- Add:

  ```python
  def _is_regular_file(path: Path) -> bool:
      """True for a regular file that is not a symlink, from one lstat().

      FIFOs, sockets and devices are skipped: opening a FIFO blocks until something writes to it.
      Symlinks are skipped too: the walk doesn't follow linked directories either, and a link to a
      file in the tree would count that file twice.
      """
      try:
          return stat.S_ISREG(path.lstat().st_mode)
      except OSError:
          return False  # vanished or unreadable mid-walk
  ```

- In `walk_project()`, replace `file_path.is_symlink()` (walker.py:206) with `not _is_regular_file(file_path)`, and move the comment into the docstring above. The check stays **before** the `exclude_patterns` branch, because the stats path there opens the file through `_is_binary()`. It still costs one `lstat()` per file, as `is_symlink()` did.
- No change to `counter.py`. It only reads files the walker yields.

### `gitignore.py` (decision 7; plan 010 owns the rest of this file)

In `GitIgnoreSpec._add_file()`, before `read_bytes()`: if `not ignore_file.is_file()`, add `(base, ignore_file.name)` to `self._loaded` and return, as the `OSError` branch does. `is_file()` follows symlinks, so a symlinked `.gitignore` behaves as today. Say in the docstring that only regular files are read, so a FIFO can't block the walk. This also covers `.git/info/exclude`.

### Tests

The tests must fail, not hang, on the old code. Add `tests/conftest.py` with a fixture:

```python
@pytest.fixture
def make_fifo() -> Iterator[Callable[..., Path]]:
    """Create a FIFO. If anything blocks opening it, a writer unblocks it after 2 s, sending *payload*,
    so a regression fails its assertion instead of hanging the suite."""
```

- It calls `os.mkfifo(path)` and starts a daemon `threading.Timer(2.0, ...)`.
- The timer callback calls `os.open(path, os.O_WRONLY | os.O_NONBLOCK)`. That succeeds only if a reader is blocked, and raises `ENXIO` otherwise, so wrap it in `try/except OSError`. It writes *payload*, then closes.
- Teardown cancels every timer.
- Any test that uses it is marked `skipif(not hasattr(os, 'mkfifo'))`.

`tests/test_walker.py`:

- `test_fifo_is_not_counted`: `a.py` plus a FIFO `pipe.py`. `walk_project` yields only `a.py`. Before the fix, the reader unblocks after 2 s, reads `b''` (not binary) and yields `pipe.py`, so the assertion fails.
- `test_fifo_matched_by_a_pattern_is_not_counted_in_stats`: the FIFO `pipe.py`, with an `[exclude] patterns` layer of `pipe.py`. Assert `stats.pattern_files == 0` and nothing yielded. This covers the stats path.
- `test_socket_is_not_counted`: bind an `AF_UNIX` socket at `tmp_path / 's.py'`, and close it in `finally`. Only regular files are yielded. Skip it where `AF_UNIX` is missing. On macOS, `tmp_path` can exceed the 104-byte socket path limit; if so, `os.chdir` into the directory and bind the relative name `s.py`.

`tests/test_gitignore.py`:

- `test_fifo_gitignore_is_not_read`: `sub/.gitignore` is a FIFO whose writer sends `a.py\n`, and `sub/a.py` exists. After `add_directory('sub', ...)`, `match_file('sub/a.py')` is False. Before the fix, the rule arrives through the FIFO after 2 s and the file is ignored.

## Bug 2 - Unencodable stdout characters

Repro on main:

- `PYTHONIOENCODING=ascii tallyman <dir with two languages>` prints the ASCII bar, then raises `UnicodeEncodeError` on `'\xb7'`.
- `PYTHONIOENCODING=cp1252 tallyman 日本` crashes on the header.

Verified fix: `sys.stdout.reconfigure(errors='replace')` before the run. Both cases then exit 0.

### `cli.py`

- Add:

  ```python
  def _tolerate_unencodable_stdout() -> None:
      """Print '?' for characters stdout's encoding can't represent, instead of crashing.

      Directory names, language display names and the image path can hold any character; a cp1252 or ascii
      stdout can't show them all. stderr needs nothing: Python already opens it with errors='backslashreplace'.
      """
      if isinstance(sys.stdout, io.TextIOWrapper):
          sys.stdout.reconfigure(errors='replace')
  ```

- Call it as the first line of `main()`. It runs before `parse_args()`, which can also print. `sys.stdout` can be `None` under some launchers, and is something else under some test runners; the `isinstance` check covers both. pytest's capture streams are `TextIOWrapper` subclasses, so this is harmless in tests.
- `display.py` is imported earlier than this call, so `_USE_UNICODE` is unaffected. `errors` doesn't change the encoding, so the probe gives the same answer either way.

### `display.py`

- `_can_encode_unicode()` probes `'─█·'`, not `'─█'`.
- `LEGEND_SEPARATOR = '  ·  ' if _USE_UNICODE else '  |  '`. Phase 1 made this a module constant.
- So under cp1252, which has `·` but not `─`, the whole report goes ASCII rather than mixing the two. The image keeps its own `·` separator: it is drawn with a font, not written to stdout.

### Tests

`tests/test_cli.py`:

- Give `_run_process()` an `env: Optional[dict[str, str]] = None` parameter, merged over the current environment.
- `TestRealProcess.test_narrow_stdout_encoding_does_not_crash`, parametrized over `'ascii'` and `'cp1252'`:
  - a directory named `日本` holding `a.py` and `b.rs`, so the legend has a separator;
  - run with `PYTHONIOENCODING=<enc>`;
  - assert returncode 0, `'??'` in stdout (the name), a line of `#`, and `'  |  '` in the legend.

  This fails today with a traceback in stderr. Skip it if the filesystem refuses the name (`OSError` on `mkdir`).

`tests/test_display.py`:

- `test_unicode_probe`, parametrized: `utf-8 -> True`, `cp1252 -> False` (no `─`), `ascii -> False`. Monkeypatch `sys.stdout` with a stand-in that has only an `encoding` attribute, and call `_can_encode_unicode()`.

## Bug 8 - Config with a byte-order mark

Repro on main: a config starting with `EF BB BF` fails with `Error: could not read ...: Invalid statement (at line 1, column 1)` and exit 1. Verified.

### `config.py`

In `load_config()`:

- Read with `config_path.read_bytes()`, keeping the `OSError` handling.
- Then `tomllib.loads(data.decode(text_encoding(data[:4])))`, with `text_encoding` from `tallyman.encoding`.
- The existing `except (ValueError, RecursionError)` still catches `UnicodeDecodeError` and `TOMLDecodeError`, since both are `ValueError`s.
- Update the docstring: a UTF-8, UTF-16 or UTF-32 byte-order mark picks the encoding, and without one the file must be UTF-8.

If Michael picks the strict answer to open question 3, decode with `'utf-8-sig'` instead and drop the UTF-16 test below.

`save_config()` is unchanged: it writes UTF-8 without a BOM.

### Tests

`tests/test_config.py`:

- `test_utf8_bom_is_accepted`: BOM + `[exclude]\ndirectories = ["vendor"]\n` loads with `excluded_dirs == {'vendor'}`.
- `test_utf16_bom_is_accepted`: the same text encoded `'utf-16'`, which Python writes with a BOM.
- `test_invalid_utf8_still_raises`: `b'\xc3\x28'` raises `ConfigError` with `.path` set. Don't use `b'\xff\xfe'`; that is a UTF-16 BOM.
- `test_setup_rewrite_drops_the_bom`: `load_config` the BOM file, `save_config` it, and the new bytes don't start with `codecs.BOM_UTF8` and still load the same.

`tests/test_cli.py`: `test_config_with_bom_applies`. A scan-root config with a BOM excluding `vendor`, and `vendor/x.py` isn't counted. Exit 0.

## Docs

- `README.md`, "Some files are never counted": the `Symlinks` bullet becomes "Symlinks, so a linked file is never counted twice, and special files such as named pipes and sockets". In the Configuration section, add one sentence: a config saved with a byte-order mark (some Windows editors add one) is read fine.
- `CLAUDE.md`:
  - Key Design Decision 4: "symlinked files are never counted" becomes "symlinks and other non-regular files (FIFOs, sockets, devices) are never counted or opened; `.gitignore` files are read only if they are regular files".
  - Decision 5, or the `config.py` module-map row: configs may start with a BOM.
  - The `cli.py` module-map row: mention that stdout is set to replace unencodable characters.
  - Update the test counts, and add `tests/conftest.py` (the `make_fifo` fixture) under the Test Structure table.
- `change-log.md`, under `0.4.3 - UNRELEASED` `### Fixed`, each with `Files:` and `Plan:` lines:
  - A named pipe (FIFO) with a source-file extension, or named `.gitignore`, no longer hangs the scan. Only regular files are read.
  - A terminal whose encoding can't show a character (Windows cp1252, `PYTHONIOENCODING=ascii`) gets `?` instead of a crash, and the legend separator falls back to `|` with the rest of the ASCII output.
  - A `.tally-config.toml` saved with a byte-order mark loads instead of failing with "Invalid statement".

## Done when

- The three repros above behave as described: no hang, exit 0, and the config loads.
- Every new test failed (not hung) on the old code and passes now.
- All checks in the introduction's rules are clean, and the architect review's valid findings are addressed and committed.
