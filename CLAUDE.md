# CLAUDE.md  -  Tallyman

## Important Rules

- **NEVER run push git commands.**
- **On `main`, NEVER run commit.** Only provide commit messages as text when asked.
- **On a feature branch, Claude owns the branch and commits.** When working through a multi-phase plan, commit after each phase so the branch history shows how the work evolved. Never commit to `main`, never push, and leave merging to Michael.

## Versioning

`MAJOR.MINOR.BUILD`. MINOR goes up for new features and behaviour changes, MAJOR for breaking changes. The last number counts releases: it goes up by one with every release and never resets, so 0.3.2 is followed by 0.4.3, then 0.4.4 or 0.5.4. The version lives in `pyproject.toml`; run `uv lock` after changing it.

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
pytest                      # all 637 tests (about 20 s, mostly the Textual pilot tests)
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
  → Load every .tally-config.toml from the git root down (or launch TUI)
  → walker.walk_project()    yields (path, Language) tuples
  → counter.count_lines()    returns FileCount per file
  → aggregator.aggregate()   produces TallyResult
  → display.display_results() renders to terminal
  → image.generate_image()   optional PNG (--image / --image-light)
```

## Module Map

| Module | Role |
|---|---|
| `src/tallyman/cli.py` | Entry point. Sets stdout to replace characters it can't encode, arg parsing, config loading and errors, no-terminal handling, orchestrates the pipeline |
| `src/tallyman/languages.py` | Language registry (40+ languages). Frozen dataclasses with name, category, color, comment marker, extensions, and `spec_color` on docs languages. `EXTENSION_MAP` for O(1) lookup. `OTHER_COLOR` for the bar's "Other" segment |
| `src/tallyman/walker.py` | Directory traversal. Respects gitignore, config exclusions and `[exclude] patterns`. Detects spec dirs. Yields `(Path, Language)`; fills `WalkStats` |
| `src/tallyman/gitignore.py` | Gitignore rules (`GitIgnoreSpec`, `load_gitignore`, `find_git_root`). Own pattern compiler that follows gitignore(5). Finds `info/exclude` through `gitdir:`/`commondir`. `add_directory()` notices nested repos, whose own rules replace the outer ones inside them. `GitIgnoreSpec.for_patterns()` + `add_rules()` hold `[exclude] patterns` |
| `src/tallyman/encoding.py` | BOM detection: `text_encoding()`, `has_wide_bom()`. Shared by walker (binary check), counter and config loading |
| `src/tallyman/paths.py` | `relative_posix()`: `/`-separated relative paths, safe on Windows |
| `src/tallyman/counter.py` | Reads files, classifies lines as code/comment/blank. Returns `FileCount` |
| `src/tallyman/aggregator.py` | Accumulates FileCount into LanguageStats, groups by category. Produces `TallyResult`, and the report model both outputs draw: `active_categories()`, `bar_segments()`, `segment_widths()`, `percent_label()`, `language_display_names()` |
| `src/tallyman/display.py` | Rich-based rendering; draws the shared report model. Per-language stats, category totals, percentage bar, the "Excluded by [exclude] patterns" line |
| `src/tallyman/config.py` | `.tally-config.toml` find (every one up to the git root), load with validation and normalisation, merge the chain and rebase onto the scan root (`ConfigChain`), save with TOML escaping. A config may start with a UTF-8/16/32 BOM (`text_encoding()`); save writes UTF-8 without one. `ConfigError` (with `.path`) for unreadable configs |
| `src/tallyman/image.py` | Pillow PNG summary card; draws the shared report model (bar folded after five languages). Themes, output path (Desktop or cwd, slug capped at 100 chars) |
| `src/tallyman/fonts/` | Bundled JetBrains Mono for the image |
| `src/tallyman/tui/setup_app.py` | Textual App for interactive directory selection (exclude/spec marking) |
| `src/tallyman/__main__.py` | Enables `python -m tallyman` |
| `src/tallyman/__init__.py` | Package init, `__version__` |

## Core Data Structures

```python
# Dataclasses use slots=True (TallyConfig is a plain dataclass; SpecState is a NamedTuple)

Language(frozen=True)         # name, category, color, single_line_comment, extensions; spec_color (docs only, keyword-only)
FileCount                     # total_lines, code_lines, comment_lines, blank_lines
LanguageStats                 # language, file_count, total_lines, code_lines, comment_lines, blank_lines;
                              # .effective_lines is the one definition (code lines, or non-blank without a comment marker)
CategoryStats                 # name, total_lines, effective_lines, languages
BarSegment(frozen=True)       # language (None for Other), label, color, percent: one bar block and its legend entry
TallyResult                   # by_language, by_category, grand_total_lines
TallyConfig                   # excluded_dirs, spec_dirs, non_spec_dirs ([specs] ignore): set[str]; '.' = this dir;
                              # patterns: list[str], raw, in file order, relative to the config's own directory
ConfigChain                   # inherited (configs above the scan root, merged + rebased), local, paths, pattern_layers
WalkStats                     # pattern_files, pattern_dirs: what [exclude] patterns removed, for the report
SpecState(NamedTuple)         # is_spec, detection_suppressed: one directory's spec status (walker.spec_state)
```

## Key Design Decisions

1. **Language objects are frozen and identity matters.** `Markdown(docs)` and `Markdown(specs)` are distinct objects. Aggregation groups by Language object, not name alone.

2. **Spec variants via `as_spec()`.** When a docs-category file is found in a spec directory, `as_spec()` creates a new Language with `category='specs'` and the docs language's `spec_color` as its colour, so specs and docs never share a bar colour. Results are cached with `@cache`.

3. **Comment detection is single-line only.** Strips the line, checks `startswith(marker)`. Multi-line comments (`/* */`, `""" """`) are NOT detected.

4. **Binary detection** checks the first 8KB for a `\x00` byte, unless the file starts with a UTF-16/32 BOM. Lines end only at `\n`, `\r\n` or a lone `\r`, and a final line without a newline counts. BOMs pick the encoding (`encoding.py`). Tallyman's own config, npm/pnpm lockfiles and `*.min.js`/`*.min.css` are never counted. Symlinks and other non-regular files (FIFOs, sockets, devices) are never counted or opened (`walker._is_regular_file()`, one `lstat()`, checked before anything opens the file); `.gitignore` files are read only if they are a regular file, or a symlink to one.

5. **Every config from the git root down to the scan root applies.** `find_configs()` lists them shallowest first (outside a repo, only the scan root's). `load_config_chain()` folds the ones above the scan root with `merge_configs()` (exclusions add up; the deeper config wins on the same path) and rebases the result onto the scan root with `rebase_config()`: that is `ConfigChain.inherited`. The scan root's own config is `local`, and the walker uses `effective`. Nested configs below the scan root merge the same way as the walk descends. Setup edits only `local`: parent and nested settings are shown locked and never copied (`without_inherited()` drops old copies on save). A malformed config at or above the scan root exits 1 naming the file; `--setup` skips it with a warning. A malformed nested config is skipped silently, since it is often third-party code. Entries are normalised on load. In `[specs] directories` and `[specs] ignore`, `"."` means the config's own directory. With no config and no terminal, tallyman runs with defaults and writes nothing.

6. **Auto-detected spec dirs:** `specs/`, `plans/`, `specifications/`, `agents/`  -  detected even without config, at any depth, unless listed (or beneath a directory listed) in `[specs] ignore`. The deepest explicit setting wins. `walker.spec_state()` is the one rule; the walker and the setup TUI both call it. Scanning from inside one (`tallyman plans/sub`) still counts specs, but a repo that is itself named `agents` does not.

7. **Gitignore follows git, entry by entry.** `info/exclude`, then every `.gitignore` from the repo root down, each scoped to its own directory; the deepest opinion wins. `info/exclude` is found through the `.git` directory, or a `.git` file's `gitdir:` and its `commondir` (worktrees, submodules). Nested files load lazily as the walker and TUI descend, and nothing inside an ignored directory is ever looked at. Callers pass directory paths with a trailing `/`. A nested repo (any `.git` directory or file below the scan root, the same test as `find_git_root()`) is still counted, but `add_directory()` records its root, and inside it only its own `info/exclude` and `.gitignore` files apply, as if git were run there; its own entry is judged by the outer rules, so an ignored nested repo stays out. Tallyman settings (configs, `[exclude] patterns`, `[specs]`, spec auto-detection) cross repo boundaries. `tests/test_gitignore.py` checks parity with real `git` (run in every repo), including worktrees, submodules and nested repos; its pattern-compiler table runs without git.

8. **`[exclude] patterns` are a second `GitIgnoreSpec`.** `GitIgnoreSpec.for_patterns(root)` holds one `add_rules()` layer per config, scoped to that config's directory, so patterns layer like nested `.gitignore` files and a deeper `!` wins. It is separate from the gitignore spec, and the walker checks it last, so `!` never brings back gitignored, hidden, excluded or generated entries. The scan root and its ancestors are never checked, so a parent's pattern can't exclude the scan root. Patterns are kept raw and never rebased, merged or sorted; they travel as `ConfigChain.pattern_layers`, and `--setup` writes `local.patterns` back verbatim. The TUI shows matched directories as "(excluded by pattern)" and locks them.

9. **Terminal and image draw one report model.** `aggregator.py` decides what both outputs show: `active_categories()`, `bar_segments()` (labels, colours, the 2% threshold, Other; the image passes `max_languages=5`), `segment_widths()` (largest remainder, a minimum per segment, always the full width) and `percent_label()` (`<1%`, `>99%`). `LanguageStats.effective_lines` is the one definition of effective lines. `display.py` and `image.py` only lay this out, so they can't drift; `tests/test_image.py::TestMatchesTerminal` checks they agree.

## Test Structure

| Test File | Tests | Covers |
|---|---|---|
| `tests/test_counter.py` | 29 | Line counting, line endings, BOMs and wide encodings |
| `tests/test_languages.py` | 65 | Language registry, extension map, Docker/Compose variants, valid and unshared colours (languages, spec variants, Other), `as_spec` |
| `tests/test_display.py` | 38 | Terminal rendering: header escaping, wording, labels, bar width and cells, bar colour runs, no bar for nothing, pattern note, Unicode probe |
| `tests/test_image.py` | 27 | Slugs, image paths, themes, PNG generation, title fitting, bar segments, agreement with the terminal |
| `tests/test_walker.py` | 59 | Walking, exclusions, spec detection, nested configs, exclude patterns, `WalkStats`, FIFOs and sockets, settings inside nested repos |
| `tests/test_gitignore.py` | 171 | Git root, gitignore loading and scoping, `info/exclude` in worktrees and submodules, negation, line-end escapes, nested repos, TUI agreement, parity with `git`, config pattern layers, FIFO ignore files |
| `tests/test_paths.py` | 6 | POSIX relative paths, canonical case |
| `tests/test_aggregator.py` | 56 | Stats aggregation, categories, percentages, effective lines, the report model: bar segments, widths, labels |
| `tests/test_config.py` | 90 | Config find/load/save, `[specs] ignore`, `[exclude] patterns`, normalisation, rebasing, chain merging, escaping, directory cleanup, BOMs |
| `tests/test_setup_app.py` | 53 | Setup TUI via Textual pilot: toggles, labels, parent/nested locks, patterns, agreement with the walker (also across nested repos) |
| `tests/test_cli.py` | 43 | End-to-end CLI: config chain, errors, no-terminal runs, setup pre-fill and pattern preservation, flags, colour, narrow stdout encodings, BOM config |

Tests use `tmp_path` fixtures extensively. Helper functions like `_lang()` create test Language instances. `tests/conftest.py` holds the `make_fifo` fixture: it creates a FIFO and, if a reader blocks on it, writes to it after 2 s, so a regression fails instead of hanging the suite (skip FIFO tests where `os.mkfifo` is missing).

## Code Conventions

- Single quotes for strings (Ruff enforced)
- `from __future__ import annotations` in every module
- Type hints on all function signatures
- Use `Optional[X]` from `typing` for optional types, not `X | None`
- `_prefixed` for module-private functions
- 120-char line length
- Frozen dataclasses for immutable values, mutable ones for accumulators

## When Adding a New Language

Add a `Language(...)` instance to `languages.py` and include it in the `LANGUAGES` tuple. The `EXTENSION_MAP` is built automatically. Then:

- Check the extensions don't collide with an existing language.
- Pick a colour no other language uses. `test_languages.py` checks every colour parses and that no new colour is shared, comparing resolved colours (the card's RGB and the 256-colour index) across languages, spec variants and Other (only C and its header may share one). No language may drop to ANSI `90` on a 16-colour terminal: that is Other's.
- A new docs language must set `spec_color`: a colour no other entry uses, and one that differs from its docs colour on a 16-colour terminal.
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

`plans/` contains structured planning docs organized by feature number. `plans/agents/` has other AI agent prompts. Architect reviews (including the per-phase reviews plans call for) use the `architect-tallyman` sub-agent, `.claude/agents/architect-tallyman.md` (gitignored; plan 006 holds a copy). `plans/planning-rules.md` has project planning guidelines. Consult these when implementing new features.
