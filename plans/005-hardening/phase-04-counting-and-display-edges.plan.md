# Phase 4 - Counting and Display Edge Cases

Covers H9, H12, H13, H14 and H16 from `00-plan-introduction.plan.md`.

## Goal

Close the small accuracy gaps in which files are counted, how they are identified and how lines are split, and stop directory names being read as Rich markup.

These items are independent. Each can be done and tested on its own.

## H9 - Rich markup in directory names

`_display_report_header()` in `src/tallyman/display.py` prints the directory name through `console.print(f'{directory}')`, which parses markup. `my[bold]proj` prints as `myproj`; `proj[/red]` prints as `red]`.

Change: print it with `markup=False`, or wrap it in `rich.markup.escape()`. Check the other `console.print` calls for user-derived text. Language names come from the registry and are safe.

Test (new `tests/test_display.py`): render to a `Console(file=io.StringIO(), no_color=True)` and assert the literal name appears. This needs `display_results()` to accept an optional console, or the helper to be tested directly.

## H12 - file selection

All in `walk_project()` in `src/tallyman/walker.py`.

1. **Own config.** Skip any file named `CONFIG_FILENAME`. Today `.tally-config.toml` is counted as TOML whenever it is not gitignored.
2. **Lockfiles and minified assets (pending decision 5).** Recommended: skip a small fixed set by default, `package-lock.json` and `npm-shrinkwrap.json` (lockfiles whose extension maps to a known language), and files matching `*.min.js` / `*.min.css`. Keep the list as a module-level constant next to `SPEC_DIR_NAMES`. These are generated and can dwarf the real code.
3. **Symlinked files.** `os.walk(followlinks=False)` does not descend into linked directories, but linked files are counted, so a file and a symlink to it are counted twice. Skip entries where `file_path.is_symlink()`.
4. **`.github/` (pending decision 5).** Hidden directories are skipped wholesale, so workflow YAML is never counted. Recommended: leave as is and note it in the README. If Michael wants it counted, allow-list `.github` in the hidden-directory check.

Tests in `tests/test_walker.py`: one per item that changes behaviour.

## H13 - language identification

In `identify_language()` in `src/tallyman/languages.py`:

- Replace `name.startswith('Dockerfile')` with: `name == 'Dockerfile'`, or `name.startswith('Dockerfile.')` **and** the suffix is not a recognised extension. That keeps `Dockerfile.dev` and `Dockerfile.prod` as Docker, sends `Dockerfile.md` to Markdown, and stops `Dockerfiles.py` being Docker.
- Treat `docker-compose.*.yml` / `.yaml` and `compose.*.yml` / `.yaml` as Docker, consistent with `docker-compose.yml`.

Tests in `tests/test_languages.py` for each of those names.

## H14 - line splitting and encodings

In `count_lines()` in `src/tallyman/counter.py`:

- `str.splitlines()` splits on form feed, vertical tab, `\x1c`-`\x1e`, `\x85`, ` ` and ` ` as well as newlines. A file `a = 1\n\x0c\nb = 2\n` reports 4 lines where `wc -l` reports 3. Split on `\n` only, after normalising `\r\n` and lone `\r` to `\n` (reading with `open(..., newline=None)` does this), and do not count a trailing empty segment after the final newline.
- Read with `encoding='utf-8-sig'` so a BOM does not hide a comment on the first line. Today `﻿# comment` is counted as code.

UTF-16 files contain NUL bytes and are skipped by `_is_binary()`. Recommended: detect a UTF-16 BOM (`\xff\xfe` or `\xfe\xff`) in the first bytes, treat the file as text, and decode it as `utf-16`. This means `count_lines()` needs to know the encoding; have the binary check return it, or sniff the BOM again in `count_lines()`.

Tests in `tests/test_counter.py`: form feed, lone `\r`, `\r\n`, no trailing newline, BOM plus comment, UTF-16 with BOM.

## H16 - double read

`_is_binary()` calls `path.read_bytes()[:8192]`, which reads the entire file, and `count_lines()` then reads it again. Change `_is_binary()` to open the file and `read(8192)`. This is a performance fix with no behaviour change; no new test needed beyond the existing binary-detection tests.

## Done when

- Each item has a passing test.
- Totals for this repo are unchanged, apart from any difference explained by a decision-5 default.
- `pytest`, `ruff check` and `ruff format --check` are clean.
