# Tallyman CLI Tool — Build Plan

## What We're Building

Tallyman is a command-line tool written in Python that scans a project directory and reports codebase size broken down by language. For each language it shows total lines and lines excluding comments and blank lines. Results are grouped into categories (Code, Design, Docs) with totals and a GitHub-style percentage breakdown.

On first run, when no `.tally-config.toml` exists, Tallyman launches a Textual TUI that shows a directory tree. The user toggles directories in or out with the spacebar (gitignored paths are pre-excluded and grayed out). The resulting config is saved so subsequent runs go straight to output.

## Key Design Decisions

- **Python 3.14+**, packaged properly with `pyproject.toml` so it can be installed and managed with UV.
- **Textual** for the first-run setup TUI.
- **Rich** for colored terminal output (Textual already depends on Rich).
- **`pathspec`** for parsing `.gitignore` files using the same glob rules Git uses.
- **Simple line counting initially** — for each line, check if it starts with the language's single-line comment marker, is blank, or has content. Multi-line comment detection deferred to a future iteration.
- **`tomllib`** (stdlib in Python 3.11+) for reading TOML config; manual string building for writing it (avoids a `tomli-w` dependency for simple output).

## Package Structure

```
tallyman/
├── pyproject.toml
├── README.md
├── .gitignore
├── src/
│   └── tallyman/
│       ├── __init__.py           # Package version
│       ├── __main__.py           # python -m tallyman support
│       ├── cli.py                # Argument parsing, main entry point
│       ├── languages.py          # Language registry (extensions, comment markers, colors, categories)
│       ├── walker.py             # Directory walking, gitignore + config exclusions
│       ├── counter.py            # Line classification (blank / comment / code)
│       ├── aggregator.py         # Collect per-language stats, compute categories & percentages
│       ├── config.py             # Read/write .tally-config.toml
│       ├── display.py            # Rich-based colored terminal output
│       └── tui/
│           ├── __init__.py
│           └── setup_app.py      # Textual app for first-run directory selection
└── tests/
    ├── __init__.py
    ├── test_counter.py
    ├── test_languages.py
    ├── test_walker.py
    ├── test_aggregator.py
    └── test_config.py
```

## Phases

| Phase | Focus | Deliverable |
|-------|-------|-------------|
| [Phase 1](phase-01-project-foundation.plan.md) | Project Foundation | Installable package with `tallyman` command, stub entry point |
| [Phase 2](phase-02-core-counting-engine.plan.md) | Core Counting Engine | Language registry, file walker, line counter, aggregator |
| [Phase 3](phase-03-configuration-and-tui.plan.md) | Configuration & Textual TUI | `.tally-config.toml` read/write, first-run directory tree TUI |
| [Phase 4](phase-04-output-and-formatting.plan.md) | Output & Display | Colored per-language output, sorted display, category totals, percentage bar |

Each phase builds on the previous one. After Phase 2 we have a working (plain-text) tool. Phase 3 adds the config/TUI experience. Phase 4 adds the polished colored output.

## Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `textual` | First-run setup TUI | Includes Rich as a dependency |
| `rich` | Colored terminal output | Comes with Textual |
| `pathspec` | Gitignore pattern matching | Lightweight, well-maintained |

No other third-party dependencies. `tomllib` is stdlib in Python 3.11+.

## CLI Interface

```
tallyman [PATH] [OPTIONS]

Arguments:
  PATH               Directory to analyze (default: current directory)

Options:
  --setup            Re-run the setup TUI even if .tally-config.toml exists
  --no-color         Disable colored output (also respects NO_COLOR env var)
  --help             Show help message
```

## Language Categories

Three categories for the summary totals:

| Category | Languages |
|----------|-----------|
| **Code** | Python, Rust, Go, JavaScript, TypeScript, Java, C, C++, C#, Swift, Kotlin, Ruby, Shell, Lua, PHP, Perl, R, Dart, Scala, Elixir, Zig |
| **Design** | CSS, SCSS, LESS, HTML, SVG |
| **Docs** | Markdown, reStructuredText |

Config/data files (TOML, YAML, JSON, XML, SQL) are counted per-language but rolled into a fourth "Data" category in the totals if present.
