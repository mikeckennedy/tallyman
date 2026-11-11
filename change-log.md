# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions are `MAJOR.MINOR.BUILD`, where the last number counts releases and never resets (see `CLAUDE.md`).

## 0.4.3 - UNRELEASED

### Added
- New `[exclude] patterns = [...]` config key: gitignore-style patterns, matched relative to the directory of the config that declares them, for files a directory exclude can't reach, such as Rust's `src/routing/tests.rs` beside `src/routing.rs` (issue #6). A pattern without a slash matches at any depth, a trailing `/` matches directories, and a deeper config's `!pattern` can bring back what a shallower config's pattern excluded. Patterns never bring back gitignored files, excluded or hidden directories, or the default skips, and a parent config's patterns never exclude the scanned directory itself. Setup shows directories a pattern excludes as locked and keeps the patterns, in order, when it rewrites the config.
- Files: `src/tallyman/config.py`, `src/tallyman/gitignore.py`, `src/tallyman/walker.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `tests/test_config.py`, `tests/test_gitignore.py`, `tests/test_walker.py`, `tests/test_cli.py`, `tests/test_setup_app.py`
- Plan: `plans/007-exclude-patterns/phase-02-exclude-patterns.plan.md`
- When `[exclude] patterns` remove anything, the report ends with a dim line such as `Excluded by [exclude] patterns: 12 files, 1 directory`, also shown when nothing else was counted. The image card is unchanged.
- README and `CLAUDE.md` describe the merged config chain and patterns.
- Files: `src/tallyman/display.py`, `src/tallyman/cli.py`, `tests/test_display.py`, `tests/test_cli.py`, `README.md`, `CLAUDE.md`
- Plan: `plans/007-exclude-patterns/phase-03-report-and-docs.plan.md`
- Solidity language support for `.sol` files, counted as Code with `//` single-line comment detection.
- Files: `src/tallyman/languages.py`, `tests/test_languages.py`, `tests/test_counter.py`, `tests/test_walker.py`, `README.md`
- New `[specs] ignore = [...]` config key: directories that are never specs, even when named `specs`, `plans`, `specifications` or `agents`. It covers the whole subtree, including auto-detection; a deeper `[specs] directories` entry still wins. Pressing `s` in setup on an auto-detected spec directory now writes it here, so un-marking one finally sticks.
- Files: `src/tallyman/config.py`, `src/tallyman/walker.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `tests/test_setup_app.py`, `tests/test_walker.py`, `tests/test_config.py`, `tests/test_cli.py`
- Plan: `plans/005-hardening/phase-03-spec-overrides-and-tui.plan.md`

### Changed
- A plain run no longer imports Textual; only setup loads it. That roughly halves start-up: importing `tallyman.cli` went from about 75 ms to about 33 ms. A test checks that a plain run, with or without a config, loads neither Textual nor Pillow.
- Files: `src/tallyman/cli.py`, `tests/test_cli.py`, `CLAUDE.md`
- Plan: `plans/011-setup-tui/phase-01-lazy-textual-and-text-labels.plan.md`
- Nested git repositories, including submodules and worktrees inside the tree, are still counted, but now with their own rules: inside one, only its own `.gitignore` files and `info/exclude` apply, as if git were run there, and the outer repository's patterns stop at its root. A nested repository the outer one ignores stays out. When the scanned folder isn't itself a repository, its .gitignore likewise stops at each repository inside it. `[exclude]` and `[specs]` settings apply across repository boundaries as before.
- Files: `src/tallyman/gitignore.py`, `src/tallyman/walker.py`, `src/tallyman/tui/setup_app.py`, `tests/test_gitignore.py`, `tests/test_walker.py`, `tests/test_setup_app.py`, `tests/test_cli.py`, `CLAUDE.md`
- Plan: `plans/010-git-fidelity/phase-02-nested-repos.plan.md`
- The image card's bar now folds languages past the fifth into Other, as its legend already did, so every coloured block on the card has a legend entry.
- A legend share that isn't zero but rounds to 0% reads `<1%`, and one that rounds to 100% while something else is listed reads `>99%`, in the terminal and on the image.
- The terminal report and the image card now get their categories, totals, bar segments, legend labels and segment widths from one report model in `aggregator.py` (`active_categories()`, `bar_segments()`, `segment_widths()`, `percent_label()`), so they can't disagree; a test checks that they don't. The image no longer imports from `display.py`.
- Files: `src/tallyman/aggregator.py`, `src/tallyman/languages.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `tests/test_aggregator.py`, `tests/test_display.py`, `tests/test_image.py`, `CLAUDE.md`
- Plan: `plans/008-output-hardening/phase-01-shared-report-model.plan.md`
- The image card's attribution footer links to mkennedy.codes/tools/tallyman.
- Files: `src/tallyman/image.py`
- Removed the `pathspec` dependency; tallyman now compiles gitignore patterns itself (`src/tallyman/gitignore.py`).
- Ruff is configured only in `ruff.toml`; the ignored `[tool.ruff]` tables in `pyproject.toml` are gone, and the `W` rules they listed are now on.
- The `.tally-config.toml` search now stops at the git repo root, and outside a repo only the scanned directory is checked, so a stray config in a home directory no longer applies to every project or suppresses first-run setup.
- With no config and no terminal (CI, pipes), tallyman now counts with default settings and prints a one-line note on stderr instead of launching the setup TUI and hanging. No config is written. `--setup` without a terminal exits with status 2.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `tests/test_config.py`, `tests/test_cli.py`
- Plan: `plans/005-hardening/phase-02-config-handling.plan.md`
- Every `.tally-config.toml` from the git repo root down to the scanned directory now applies, instead of only the nearest one. Exclusions add up; for specs, the deeper setting wins, and on the same path the deeper config wins. Scanning `repo/app` with configs in both `repo` and `repo/app` no longer silently drops `repo`'s settings.
- `--setup` in a directory below another config shows that config's settings as locked ("set in a parent config") and no longer copies them into the new config. Copies written by earlier versions are dropped the next time setup saves.
- Nested configs below the scanned directory also resolve a spec/ignore clash on the same path in favour of the deeper config. Before, the spec entry always won.
- In setup, `x` now works on a directory whose spec setting comes from a nested config; only exclusions set in another config are locked. The walker already honoured such an exclusion.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/walker.py`, `src/tallyman/tui/setup_app.py`, `tests/test_config.py`, `tests/test_cli.py`, `tests/test_walker.py`, `tests/test_setup_app.py`
- Plan: `plans/007-exclude-patterns/phase-01-merge-config-chain.plan.md`

### Fixed
- Setup shows directory names exactly as they are on disk. A directory named `:rocket:` no longer turns into an emoji, and a name ending in a backslash is no longer doubled, in the tree and on the root. The labels are built as Rich `Text`, never markup.
- Files: `src/tallyman/tui/setup_app.py`, `tests/test_setup_app.py`
- Plan: `plans/011-setup-tui/phase-01-lazy-textual-and-text-labels.plan.md`
- Setup drops scan-root copies of nested config settings, as it already did for parent settings, and now does both when it opens as well as on save. Earlier versions wrote these copies, and they could never be removed in setup, so removing the nested setting later left the directory excluded. A copy is the same directory in the same list; a scan-root entry that overrides a parent's, or that a nested config overrides, stays. No message: the dropped settings still apply from their own files, so the counts don't change.
- A directory a config excludes is labelled as excluded by that config (`✗ name`), even when gitignore or a pattern also matches it, matching the walker, which checks config exclusions first. A redundant scan-root exclusion there can now be toggled off, after which the label reads "(gitignored)" or "(excluded by pattern)".
- `--setup` no longer hangs when the scanned directory's `.tally-config.toml` is a named pipe (FIFO) or another non-regular file: saving refuses it with the usual "could not save" warning and counts with the chosen settings for that run. A dangling symlink there is refused the same way, rather than creating its target wherever it points.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_setup_app.py`, `tests/test_cli.py`, `README.md`, `CLAUDE.md`
- Plan: `plans/011-setup-tui/phase-02-precedence-and-copies.plan.md`
- A project with no effective lines (only comments and blanks) no longer prints an empty bar and legend under the totals, and the image no longer leaves a blank band where the bar would be. The totals still say `0 lines`. With `--with-spaces` the bar is drawn as before.
- A small "Other" always gets at least one cell of the terminal bar. Python 496, Rust 496 and Go 8 lines used to give Python and Rust 30 cells each and leave Other, still listed in the legend, with none. Bar widths are now split by largest remainder, in both outputs, and always fill the bar exactly.
- `--image` no longer crashes with `ValueError: x1 must be greater than or equal to x0` when "Other" is under about 0.1% of the lines; every image segment is at least 4 px wide.
- Files: `src/tallyman/aggregator.py`, `src/tallyman/languages.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `tests/test_aggregator.py`, `tests/test_display.py`, `tests/test_image.py`, `CLAUDE.md`
- Plan: `plans/008-output-hardening/phase-01-shared-report-model.plan.md`
- A named pipe (FIFO) with a source-file extension, or named `.gitignore`, no longer hangs the scan. Only regular files are read: FIFOs, sockets and devices are skipped like symlinks, and a `.gitignore` or `.git/info/exclude` that isn't a regular file, or a symlink to one, is treated as absent.
- Files: `src/tallyman/walker.py`, `src/tallyman/gitignore.py`, `tests/conftest.py`, `tests/test_walker.py`, `tests/test_gitignore.py`, `README.md`, `CLAUDE.md`
- Plan: `plans/008-output-hardening/phase-02-files-stdout-config.plan.md`
- A terminal whose encoding can't show a character (Windows cp1252, `PYTHONIOENCODING=ascii`) gets `?` instead of a crash, and the legend separator falls back to `|` with the rest of the ASCII output. An encoding with box drawing but no `·` (such as cp852) now gets the ASCII report too.
- Files: `src/tallyman/cli.py`, `src/tallyman/display.py`, `tests/test_cli.py`, `tests/test_display.py`, `CLAUDE.md`
- Plan: `plans/008-output-hardening/phase-02-files-stdout-config.plan.md`
- A `.tally-config.toml` saved with a byte-order mark loads instead of failing with "Invalid statement". A UTF-8, UTF-16 or UTF-32 mark picks the encoding, as it does for source files; `--setup` rewrites the file as UTF-8 without one.
- Files: `src/tallyman/config.py`, `tests/test_config.py`, `tests/test_cli.py`, `README.md`, `CLAUDE.md`
- Plan: `plans/008-output-hardening/phase-02-files-stdout-config.plan.md`
- Spec and docs Markdown no longer merge into one block in the composition bar. Spec variants of docs languages now have their own colour (Markdown violet, reStructuredText dark sea green), in every terminal colour mode and on the image card.
- The bar's "Other" segment is now dark grey (`grey37`). It no longer merges with TOML, or with Markdown on 16-colour terminals.
- Files: `src/tallyman/languages.py`, `tests/test_languages.py`, `tests/test_display.py`, `tests/test_image.py`, `CLAUDE.md`, `plans/006-tallyman-architect.plan.md`
- Plan: `plans/009-spec-colours.plan.md`
- `.git/info/exclude` is now honoured in git worktrees and submodules, where `.git` is a file pointing at the real git directory. Worktrees use the main repository's `info/exclude`, as git does. A `.git` file that is malformed, over 1 MB, or points at a directory with no `HEAD` (such as `gitdir: ..`) means no `info/exclude`, never an error; git refuses to run in such a checkout.
- A gitignore or `[exclude]` pattern ending in a lone backslash (`a\`) now matches nothing, as in git, instead of matching a name ending in `\`; `!a\` no longer re-includes anything. An escaped backslash before trailing spaces (`a\\ `) no longer keeps the spaces.
- Files: `src/tallyman/gitignore.py`, `tests/test_gitignore.py`, `CLAUDE.md`, `plans/006-tallyman-architect.plan.md`
- Plan: `plans/010-git-fidelity/phase-01-gitdir-and-escapes.plan.md`
- README, `CLAUDE.md` and `gitignore.py`'s docstring describe worktrees, submodules and nested repositories. The README has a new "Git repositories inside your project" section listing the differences users meet, including the global excludes file and symlinked `.gitignore` files (tallyman reads them; git skips them). The docstring has the full list, including the `GIT_DIR` and `GIT_COMMON_DIR` environment variables.
- Files: `README.md`, `CLAUDE.md`, `src/tallyman/gitignore.py`, `plans/006-tallyman-architect.plan.md`
- Plan: `plans/010-git-fidelity/phase-03-docs.plan.md`
- An empty `NO_COLOR` no longer disables colour; per no-color.org only a non-empty value does.
- Solidity's colour changed from `bright_cyan`, which SQL also uses, to `slate_blue1`, so the two are distinguishable in the bar.
- README and `CLAUDE.md` describe the current behaviour: config search and rebasing, `[specs] ignore`, `"."`, no-terminal runs, what is never counted, and the language count (43, not 41).
- New baseline tests for terminal rendering, CLI flags and colour switches, and checks that every language colour is valid and no new colour is shared.
- Files: `src/tallyman/cli.py`, `src/tallyman/languages.py`, `ruff.toml`, `pyproject.toml`, `README.md`, `CLAUDE.md`, `.cursor/rules/`, `tests/test_cli.py`, `tests/test_display.py`, `tests/test_languages.py`
- Plan: `plans/005-hardening/phase-05-hygiene-and-coverage.plan.md`
- Lines now end only at `\n`, `\r\n` or a lone `\r`, and a final line without a newline still counts. `str.splitlines()` also split on form feeds, vertical tabs, `\x1c`-`\x1e`, `\x85`, U+2028 and U+2029, so files containing them were over-counted. A UTF-8 BOM no longer hides a comment on the first line, and UTF-16 and UTF-32 files with a BOM are counted instead of being skipped as binary.
- Never counted, whatever `.gitignore` says, in any letter case: tallyman's own `.tally-config.toml`, `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `*.min.js` and `*.min.css`. Symlinked files are skipped, so a link to a file in the tree no longer counts it twice.
- Dockerfile variants are matched by name: `Dockerfile.dev`, `Dockerfile.go`, `Dockerfile-prod` and `Dockerfile_ci` are Docker, but a docs or data suffix (`Dockerfile.md`, `Dockerfile.json`, `Dockerfile.toml`, ...), `.txt` and `.dockerignore` are not, and `Dockerfiles.py` is Python. `docker-compose.override.yml`, `compose.prod.yaml` and other Compose variants are Docker, like `docker-compose.yml`.
- A directory name is printed literally in the report header: `[bold]` is no longer read as Rich markup, `:rocket:` is no longer turned into an emoji, and control characters are replaced. In the image, a long directory name is shortened with an ellipsis to fit the card, and the file name is capped at 100 characters; a 253-character name used to crash with "File name too long".
- The binary check reads only the first 8 KB instead of the whole file.
- Files: `src/tallyman/encoding.py`, `src/tallyman/counter.py`, `src/tallyman/walker.py`, `src/tallyman/languages.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `tests/test_counter.py`, `tests/test_walker.py`, `tests/test_languages.py`, `tests/test_display.py`, `tests/test_image.py`
- Plan: `plans/005-hardening/phase-04-counting-and-display-edges.plan.md`
- Setup TUI: the root directory can no longer be toggled; `x` on it used to write `""` into the config and exclude every subdirectory. Children of an excluded directory now show as excluded, and toggling them does nothing, because they are never walked. Excluding then re-including a directory restores its spec status, and a child's own exclusion survives toggling its parent. Pressing `s` twice always restores what was there, and `s` on the root marks or unmarks the whole tree, including when setup is run from inside `plans/`. Settings from nested `.tally-config.toml` files are shown as locked instead of being copied into the root config, where they couldn't be changed anyway. Directory names containing `[...]` are shown literally. The TUI and the walker now share one rule for spec status (`walker.spec_state()`), with a test that checks they agree.
- Files: `src/tallyman/tui/setup_app.py`, `src/tallyman/walker.py`, `tests/test_setup_app.py`
- Plan: `plans/005-hardening/phase-03-spec-overrides-and-tui.plan.md`
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
- Files: `src/tallyman/gitignore.py`, `src/tallyman/walker.py`, `src/tallyman/paths.py`, `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/tui/setup_app.py`, `pyproject.toml`, `uv.lock`, `tests/test_gitignore.py`, `tests/test_walker.py`, `tests/test_paths.py`
- Plan: `plans/005-hardening/phase-01-gitignore-correctness.plan.md`

## 0.3.2 - 2026-03-06

### Added
- `--with-spaces` flag: use total lines (including comments and blanks) for category totals, combined total, percentage bar, and legend. Applies to both terminal output and PNG image export. Default behavior (effective lines) is unchanged.
- Percentage bar and legend now use effective lines by default, consistent with the category totals shown above them (previously always used total lines).
- Files: `src/tallyman/cli.py`, `src/tallyman/display.py`, `src/tallyman/image.py`, `src/tallyman/aggregator.py`, `tests/test_aggregator.py`
- Nested config discovery: when running setup on a parent directory, `.tally-config.toml` files found in subprojects are discovered and their exclusions/spec designations are pre-applied in the TUI (union merge). The walker also respects nested configs during analysis.
- Files: `src/tallyman/config.py`, `src/tallyman/cli.py`, `src/tallyman/walker.py`, `tests/test_config.py`, `tests/test_walker.py`
- Plan: `plans/004-nested-config-discovery/`

### Changed
- The image card's attribution footer lines are right-aligned to the edge of the percentage bar.
- Files: `src/tallyman/image.py`

### Fixed
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
