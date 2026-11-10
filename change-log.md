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

### Fixed
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
