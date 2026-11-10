# CLAUDE.md  -  Tallyman

## Important Rules

- **NEVER run push git commands.**
- **On `main`, NEVER run commit.** Only provide commit messages as text when asked.
- **On a feature branch, Claude owns the branch and commits.** When working through a multi-phase plan, commit after each phase so the branch history shows how the work evolved. Never commit to `main`, never push, and leave merging to Michael.

## What This Is

Tallyman is a Python CLI tool that scans a project directory and reports codebase size by language. It shows raw line counts and "effective" lines (excluding comments and blanks), grouped into categories: **Code**, **DevOps**, **Design**, **Docs**, **Specs**, and **Data**. It can also export a PNG summary card.

## Quick Reference

```bash
# Install (dev mode)
uv pip install -e ".[dev]"

# Run
tallyman                    # analyze current directory
tallyman /path/to/project   # analyze specific path
tallyman --setup            # re-run interactive TUI setup
tallyman --no-color         # disable colors
tallyman --with-spaces      # totals and bar use total lines, not effective lines
tallyman --image            # PNG summary card on the Desktop (--image-light for the light theme)

# Tests
pytest                      # all 400 tests (about 15 s, mostly the Textual pilot tests)
pytest -v                   # verbose
pytest tests/test_walker.py # single module

# Lint, format, type check (all must be clean)
ruff check src/ tests/
ruff format src/ tests/
uvx ty check                # ty.toml
uvx pyrefly check           # pyrefly.toml, kept consistent with ty.toml
```

## Tech Stack

- **Python 3.14+** (uses match statements, dataclass slots, `tomllib`)
- **textual**  -  TUI framework for first-run setup wizard
- **rich**  -  colored terminal output
- **Pillow**  -  PNG export, imported lazily so a plain run never loads it
- Gitignore matching is in-house (`gitignore.py`); there is no pathspec dependency
- **pytest** + **ruff** (configured only in `ruff.toml`) + **ty** + **pyrefly** for dev tooling
- Build backend: **hatchling**

## Architecture

Linear pipeline  -  each stage feeds the next:

```
cli.main()
  → Load/create .tally-config.toml (or launch TUI)
  → walker.walk_project()    yields (path, Language) tuples
  → counter.count_lines()    returns FileCount per file
  → aggregator.aggregate()   produces TallyResult
  → display.display_results() renders to terminal
  → image.generate_image()   optional PNG (--image / --image-light)
```

## Module Map

| Module | Role |
|---|---|
| `src/tallyman/cli.py` | Entry point. Arg parsing, config loading and errors, no-terminal handling, orchestrates the pipeline |
| `src/tallyman/languages.py` | Language registry (40+ languages). Frozen dataclasses with name, category, color, comment marker, extensions. `EXTENSION_MAP` for O(1) lookup |
| `src/tallyman/walker.py` | Directory traversal. Respects gitignore + config exclusions. Detects spec dirs. Yields `(Path, Language)` |
| `src/tallyman/gitignore.py` | Gitignore rules (`GitIgnoreSpec`, `load_gitignore`, `find_git_root`). Own pattern compiler that follows gitignore(5) |
| `src/tallyman/encoding.py` | BOM detection: `text_encoding()`, `has_wide_bom()`. Shared by walker (binary check) and counter |
| `src/tallyman/paths.py` | `relative_posix()`: `/`-separated relative paths, safe on Windows |
| `src/tallyman/counter.py` | Reads files, classifies lines as code/comment/blank. Returns `FileCount` |
| `src/tallyman/aggregator.py` | Accumulates FileCount into LanguageStats, groups by category. Produces `TallyResult` |
| `src/tallyman/display.py` | Rich-based rendering. Per-language stats, category totals, percentage bar |
| `src/tallyman/config.py` | `.tally-config.toml` find (up to the git root), load with validation and normalisation, rebase onto the scan root, save with TOML escaping. `ConfigError` for unreadable configs |
| `src/tallyman/image.py` | Pillow PNG summary card, themes, output path (Desktop or cwd, slug capped at 100 chars) |
| `src/tallyman/fonts/` | Bundled JetBrains Mono for the image |
| `src/tallyman/tui/setup_app.py` | Textual App for interactive directory selection (exclude/spec marking) |
| `src/tallyman/__main__.py` | Enables `python -m tallyman` |
| `src/tallyman/__init__.py` | Package init, `__version__` |

## Core Data Structures

```python
# Dataclasses use slots=True (TallyConfig is a plain dataclass; SpecState is a NamedTuple)

Language(frozen=True)         # name, category, color, single_line_comment, extensions
FileCount                     # total_lines, code_lines, comment_lines, blank_lines
LanguageStats                 # language, file_count, total_lines, code_lines, comment_lines, blank_lines
CategoryStats                 # name, total_lines, effective_lines, languages
TallyResult                   # by_language, by_category, grand_total_lines
TallyConfig                   # excluded_dirs, spec_dirs, non_spec_dirs ([specs] ignore): set[str]; '.' = this dir
SpecState(NamedTuple)         # is_spec, detection_suppressed: one directory's spec status (walker.spec_state)
```

## Key Design Decisions

1. **Language objects are frozen and identity matters.** `Markdown(docs)` and `Markdown(specs)` are distinct objects. Aggregation groups by Language object, not name alone.

2. **Spec variants via `as_spec()`.** When a docs-category file is found in a spec directory, `as_spec()` creates a new Language with `category='specs'`. Results are cached with `@cache`.

3. **Comment detection is single-line only.** Strips the line, checks `startswith(marker)`. Multi-line comments (`/* */`, `""" """`) are NOT detected.

4. **Binary detection** checks the first 8KB for a `\x00` byte, unless the file starts with a UTF-16/32 BOM. Lines end only at `\n`, `\r\n` or a lone `\r`, and a final line without a newline counts. BOMs pick the encoding (`encoding.py`). Tallyman's own config, npm/pnpm lockfiles, `*.min.js`/`*.min.css` and symlinked files are never counted.

5. **Config search stops at the git root, and parent configs are rebased.** `find_config()` returns the nearest `.tally-config.toml` from the scan root up to the git repo root (outside a repo, only the scan root itself). `rebase_config()` translates its entries to be relative to the scan root. Entries are normalised on load. In `[specs] directories` and `[specs] ignore`, `"."` means the config's own directory. With no config and no terminal, tallyman runs with defaults and writes nothing.

6. **Auto-detected spec dirs:** `specs/`, `plans/`, `specifications/`, `agents/`  -  detected even without config, at any depth, unless listed (or beneath a directory listed) in `[specs] ignore`. The deepest explicit setting wins. `walker.spec_state()` is the one rule; the walker and the setup TUI both call it. Scanning from inside one (`tallyman plans/sub`) still counts specs, but a repo that is itself named `agents` does not.

7. **Gitignore follows git, entry by entry.** `.git/info/exclude`, then every `.gitignore` from the repo root down, each scoped to its own directory; the deepest opinion wins. Nested files load lazily as the walker and TUI descend, and nothing inside an ignored directory is ever looked at. Callers pass directory paths with a trailing `/`. `tests/test_gitignore.py` checks parity with real `git`; its pattern-compiler table runs without git.

## Test Structure

| Test File | Tests | Covers |
|---|---|---|
| `tests/test_counter.py` | 29 | Line counting, line endings, BOMs and wide encodings |
| `tests/test_languages.py` | 58 | Language registry, extension map, Docker/Compose variants, valid and unshared colours, `as_spec` |
| `tests/test_display.py` | 17 | Terminal rendering: header escaping, wording, labels, bar width |
| `tests/test_image.py` | 20 | Slugs, image paths, themes, PNG generation, title fitting |
| `tests/test_walker.py` | 42 | Walking, exclusions, spec detection, nested configs |
| `tests/test_gitignore.py` | 93 | Git root, gitignore loading and scoping, negation, TUI agreement, parity with `git` |
| `tests/test_paths.py` | 6 | POSIX relative paths, canonical case |
| `tests/test_aggregator.py` | 12 | Stats aggregation, categories, percentages |
| `tests/test_config.py` | 58 | Config find/load/save, `[specs] ignore`, normalisation, rebasing, escaping, directory cleanup |
| `tests/test_setup_app.py` | 39 | Setup TUI via Textual pilot: toggles, labels, agreement with the walker |
| `tests/test_cli.py` | 26 | End-to-end CLI: parent configs, errors, no-terminal runs, setup pre-fill, flags, colour |

Tests use `tmp_path` fixtures extensively. Helper functions like `_lang()` create test Language instances.

## Code Conventions

- Single quotes for strings (Ruff enforced)
- `from __future__ import annotations` in every module
- Type hints on all function signatures
- `_prefixed` for module-private functions
- 120-char line length
- Frozen dataclasses for immutable values, mutable ones for accumulators

## When Adding a New Language

Add a `Language(...)` instance to `languages.py` and include it in the `LANGUAGES` tuple. The `EXTENSION_MAP` is built automatically. Then:

- Check the extensions don't collide with an existing language.
- Pick a colour no other language uses. `test_languages.py` checks every colour parses and that no new colour is shared (three existing pairs are allowlisted).
- Update the README's category table, the per-language extension table, and both "N languages" counts. Recount them against `LANGUAGES`.
- Add tests in `test_languages.py`.

## When Adding a New Category

Update `aggregator.py` category ordering, `display.py` rendering, and ensure walker handles it correctly. The Specs category addition in `plans/002-specs-category/` is a reference implementation.

## Environment & Config

- **NO_COLOR** env var, when set to a non-empty value, disables colored output (no-color.org)
- `.tally-config.toml` is gitignored and generated per-project
- No other env vars needed
- Entry point defined in `pyproject.toml`: `tallyman = "tallyman.cli:main"`

## Planning Documents

`plans/` contains structured planning docs organized by feature number. `plans/agents/` has AI agent prompts. `plans/planning-rules.md` has project planning guidelines. Consult these when implementing new features.
