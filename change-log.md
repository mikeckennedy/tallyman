# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## UNRELEASED

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
