# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## UNRELEASED

### Added
- Solidity language support for `.sol` files, counted as Code with `//` single-line comment detection.
- Files: `src/tallyman/languages.py`, `tests/test_languages.py`, `tests/test_counter.py`, `tests/test_walker.py`, `README.md`
- `--with-spaces` flag: use total lines (including comments and blanks) for category totals, combined total, percentage bar, and legend. Applies to both terminal output and PNG image export. Default behavior (effective lines) is unchanged.
- Percentage bar and legend now use effective lines by default, consistent with the category totals shown above them (previously always used total lines).
- Files: `src/tallyman/cli.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `src/tallyman/aggregator.py`, `tests/test_aggregator.py`
- Nested config discovery: when running setup on a parent directory, `.tally-config.toml` files found in subprojects are discovered and their exclusions/spec designations are pre-applied in the TUI (union merge). The walker also respects nested configs during analysis.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/walker.py`, `tests/test_config.py`, `tests/test_walker.py`
- Plan: `plans/004-nested-config-discovery/`

### Changed
- New `[specs] ignore = [...]` config key: directories that are never specs, even when named `specs`, `plans`, `specifications` or `agents`. It covers the whole subtree, including auto-detection; a deeper `[specs] directories` entry still wins. Pressing `s` in setup on an auto-detected spec directory now writes it here, so un-marking one finally sticks.
- Files: `src/tallyman/config.py`, `src/tallyman/walker.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `tests/test_setup_app.py`, `tests/test_walker.py`, `tests/test_config.py`, `tests/test_cli.py`
- Plan: `plans/005-hardening/phase-03-spec-overrides-and-tui.plan.md`
- The `.tally-config.toml` search now stops at the git repo root, and outside a repo only the scanned directory is checked, so a stray config in a home directory no longer applies to every project or suppresses first-run setup.
- With no config and no terminal (CI, pipes), tallyman now counts with default settings and prints a one-line note on stderr instead of launching the setup TUI and hanging. No config is written. `--setup` without a terminal exits with status 2.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `tests/test_config.py`, `tests/test_cli.py`
- Plan: `plans/005-hardening/phase-02-config-handling.plan.md`

### Fixed
- Lines now end only at `\n`, `\r\n` or a lone `\r`, and a final line without a newline still counts. `str.splitlines()` also split on form feeds, vertical tabs, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029; this repo's own phase 4 plan counted 60 lines where `wc -l` says 58. A UTF-8 BOM no longer hides a comment on the first line, and UTF-16 and UTF-32 files with a BOM are counted instead of being skipped as binary.
- Never counted, whatever `.gitignore` says, in any letter case: tallyman's own `.tally-config.toml`, `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `*.min.js` and `*.min.css`. Symlinked files are skipped, so a link to a file in the tree no longer counts it twice.
- Dockerfile variants are matched by name: `Dockerfile.dev`, `Dockerfile.go`, `Dockerfile-prod` and `Dockerfile_ci` are Docker, but `Dockerfile.md`, `Dockerfile.json` and `Dockerfile.dockerignore` are not, and `Dockerfiles.py` is Python. `docker-compose.override.yml`, `compose.prod.yaml` and other Compose variants are Docker, like `docker-compose.yml`.
- A directory name is printed literally in the report header: `[bold]` is no longer read as Rich markup, `:rocket:` is no longer turned into an emoji, and control characters are replaced. In the image, a long directory name is shortened with an ellipsis to fit the card, and the file name is capped at 100 characters; a 253-character name used to crash with "File name too long".
- The binary check reads only the first 8 KB instead of the whole file.
- Files: `src/tallyman/encoding.py`, `src/tallyman/counter.py`, `src/tallyman/walker.py`, `src/tallyman/languages.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `tests/test_counter.py`, `tests/test_walker.py`, `tests/test_languages.py`, `tests/test_display.py`, `tests/test_image.py`
- Plan: `plans/005-hardening/phase-04-counting-and-display-edges.plan.md`
- Setup TUI: the root directory can no longer be toggled; `x` on it used to write `""` into the config and exclude every subdirectory. Children of an excluded directory now show as excluded, and toggling them does nothing, because they are never walked. Excluding then re-including a directory restores its spec status, and a child's own exclusion survives toggling its parent. Pressing `s` twice always restores what was there, and `s` on the root marks or unmarks the whole tree, including when setup is run from inside `plans/`. Settings from nested `.tally-config.toml` files are shown as locked instead of being copied into the root config, where they couldn't be changed anyway. Directory names containing `[...]` are shown literally. The TUI and the walker now share one rule for spec status (`walker.spec_state()`), with a test that checks they agree.
- Files: `src/tallyman/tui/setup_app.py`, `src/tallyman/walker.py`, `tests/test_setup_app.py`
- A config found in a parent directory is now rebased onto the scanned directory. Running `tallyman proj/src` with `proj/.tally-config.toml` excluding `src/vendor` and `docs` used to count `src/vendor` and drop `src/docs`. A parent spec directory that covers the scanned directory now classifies its docs as specs.
- A malformed or wrongly shaped root config is reported on stderr with exit status 1 instead of a traceback. `tallyman --setup` replaces a broken config instead of failing on it.
- Directory names containing `"`, `\` or control characters are escaped when the config is saved, so the next run can read it.
- Hand-edited config paths are normalised: `vendor/`, `./static`, `a//b`, `a/./b`, `a/../b` and `/top` now match, and entries that climb out with `..` are dropped. Backslashes are treated as separators on Windows only.
- `[specs] directories` accepts `"."` for the config's own directory, so `tallyman --setup` run inside a spec directory no longer silently turns its specs into docs.
- Scanning from inside an auto-detected spec directory (`tallyman plans/sub`) now counts its docs as specs, the same as scanning from the repo root.
- A config that isn't valid UTF-8, or is pathologically nested, is reported like any other bad config; in a nested directory it is skipped instead of aborting the scan.
- If setup can't save the config, tallyman warns and still counts with the chosen settings instead of crashing. A closed stdin no longer crashes, and a path typed in the wrong case on macOS (`proj/SRC`) no longer defeats config matching.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/walker.py`, `tests/test_config.py`, `tests/test_cli.py`
- Plan: `plans/005-hardening/phase-02-config-handling.plan.md`

- Gitignore handling rewritten to follow git's rules, in the walker and the setup TUI alike:
  - `.gitignore` files below the scanned directory are honoured, including the `*` file uv and virtualenv write inside a venv.
  - Each file's patterns are anchored to the directory it lives in, and a deeper file wins, so `!pattern` can re-include.
  - Patterns judge one entry at a time, as git does: `!dist/` re-includes the `dist` directory without re-including what a parent ignored inside it, and whitelist files (`*`, `!*/`, `!*.py`) keep the files they name.
  - `.git/info/exclude` ranks below `.gitignore`; nothing inside an ignored directory is counted, even when the scan starts inside it.
  - Odd lines behave as in git instead of breaking the scan: a BOM, an unreadable `.gitignore`, a malformed bracket expression such as `[z-a]` or an unterminated `[`, POSIX classes such as `[[:digit:]]`, and form feeds inside a pattern.
  - Verified against `git ls-files --exclude-standard` on 1,900 generated repositories and about 75 hand-written edge cases, with no differences.
  - Known differences, all documented in `gitignore.py`: matching is case-sensitive (git on macOS is not, by default); `?` matches one character where git matches one byte; and files git already tracks are still skipped if a pattern matches them.
- Relative paths are always built with `/`, so config exclusions and spec directories nested two or more levels deep match on Windows.
- Removed the `pathspec` dependency; tallyman now compiles gitignore patterns itself (`src/tallyman/gitignore.py`).
- Files: `src/tallyman/gitignore.py`, `src/tallyman/walker.py`, `src/tallyman/paths.py`, `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `pyproject.toml`, `uv.lock`, `tests/test_gitignore.py`, `tests/test_walker.py`, `tests/test_paths.py`
- Plan: `plans/005-hardening/phase-01-gitignore-correctness.plan.md`

- Fixed `ColorParseError` crash when generating image for projects containing TypeScript files — `dodger_blue` is not a valid Rich color name; changed to `dodger_blue1`
- Added defensive fallback in `_rich_color_to_rgb` so unrecognised color names degrade to grey instead of crashing the image export
- Files: `src/tallyman/languages.py`, `src/tallyman/image.py`

## 0.3.1 - 2026-02-13

### Fixed
- Fixed `UnicodeEncodeError` on Windows Git Bash (cp1252 encoding) by detecting stdout encoding and falling back to ASCII box-drawing characters when needed (GitHub issue #3)
- Files: `src/tallyman/display.py`

## 0.3.0 - 2026-02-13

### Added
- `--image` flag generates a PNG summary card saved to the Desktop (dark theme by default)
- `--image-light` flag generates the same card with a light theme
- Image includes category totals, a colored percentage bar, and a language legend
- Output filename is the URL-slugified project name; numeric suffix added if file already exists
- Bundled JetBrains Mono font for consistent cross-platform rendering
- `--version` flag to display the current release version
- New dependency: Pillow >= 10.0.0
- Files: `src/tallyman/image.py`, `src/tallyman/fonts/`, `tests/test_image.py`
- Plan: `plans/003-image-export/`

### Changed
- Renamed `*.h` file type label from "C" to "C/C++ Header" for clarity
- Files: `src/tallyman/languages.py`

### Fixed
- Corrected project URLs in `pyproject.toml`
- Fixed `.cursor` rules that referenced the wrong project

## 0.2.1 - 2026-02-08

Initial release.

A CLI tool that scans a project directory and reports codebase size by language, showing raw line counts and effective lines (excluding comments and blanks), grouped into categories: Code, Design, Docs, Specs, and Data.

- 40+ language definitions with per-language comment detection
- Gitignore-aware directory traversal
- Automatic spec directory detection
- Interactive TUI setup wizard for project configuration
- Rich terminal output with colored per-language stats, category totals, and percentage bars


---

## Template for Future Entries

<!--
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features or capabilities
- Files: `path/to/new/file.ext`, `another/file.ext`

### Changed
- Modifications to existing functionality
- Files: `path/to/modified/file.ext` (summary if many files)

### Deprecated
- Features that will be removed in future versions
- Files affected: `path/to/deprecated/file.ext`

### Removed
- Features or files that were deleted
- Files: `path/to/removed/file.ext`

### Fixed
- Bug fixes and corrections
- Files: `path/to/fixed/file.ext`

### Security
- Security patches or vulnerability fixes
- Files: `path/to/security/file.ext`

### Notes
- Additional context or important information
- Major dependencies updated
- Breaking changes explanation
-->
