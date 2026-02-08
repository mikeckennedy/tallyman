# Phase 1: Project Foundation

## Goal

Create a properly structured Python package that installs with UV and provides a `tallyman` command. At the end of this phase, running `tallyman` prints a placeholder message and exits. Everything else builds on top of this skeleton.

## Steps

### 1.1  -  Create `pyproject.toml`

This is the single source of truth for the package. Use the modern `[project]` table format (PEP 621).

```toml
[project]
name = "tallyman"
version = "0.1.0"
description = "A command-line tool that summarizes codebase size by language."
readme = "README.md"
requires-python = ">=3.14"
license = "MIT"
dependencies = [
    "textual>=1.0.0",
    "rich>=13.0.0",
    "pathspec>=0.12.0",
]

[project.scripts]
tallyman = "tallyman.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tallyman"]

[tool.ruff]
line-length = 120
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]

[tool.ruff.format]
quote-style = "single"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Key details:
- Entry point: `tallyman.cli:main`  -  the `main()` function in `src/tallyman/cli.py`.
- Build backend: `hatchling` with explicit src layout.
- Ruff configured for 120-char lines, single quotes, Python 3.14.
- `rich` is listed explicitly even though `textual` depends on it, so we can pin/import it directly.

### 1.2  -  Create the `src/tallyman/` package directory

Create these files:

**`src/tallyman/__init__.py`**
```python
__version__ = '0.1.0'
```

**`src/tallyman/__main__.py`**
```python
from tallyman.cli import main

main()
```

This enables `python -m tallyman` in addition to the `tallyman` console script.

**`src/tallyman/cli.py`**
```python
import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='tallyman',
        description='Summarize codebase size by language.',
    )
    parser.add_argument(
        'path',
        nargs='?',
        default='.',
        help='Directory to analyze (default: current directory)',
    )
    parser.add_argument(
        '--setup',
        action='store_true',
        help='Re-run the setup TUI even if .tally-config.toml exists',
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output',
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(f'Tallyman v0.1.0  -  analyzing: {args.path}')
    print('(not yet implemented)')
    sys.exit(0)
```

Stub entry point. Parses arguments, prints a placeholder. Replaced with real logic in later phases.

### 1.3  -  Create empty module stubs

Create these files with just a module docstring so the package structure exists:

- `src/tallyman/languages.py`  -  `"""Language registry."""`
- `src/tallyman/walker.py`  -  `"""File and directory walking."""`
- `src/tallyman/counter.py`  -  `"""Line counting and classification."""`
- `src/tallyman/aggregator.py`  -  `"""Statistics aggregation."""`
- `src/tallyman/config.py`  -  `"""Configuration file handling."""`
- `src/tallyman/display.py`  -  `"""Terminal output formatting."""`
- `src/tallyman/tui/__init__.py`  -  empty
- `src/tallyman/tui/setup_app.py`  -  `"""Textual TUI for first-run setup."""`

### 1.4  -  Create test directory

- `tests/__init__.py`  -  empty
- `tests/test_counter.py`  -  empty, placeholder
- `tests/test_languages.py`  -  empty, placeholder
- `tests/test_walker.py`  -  empty, placeholder
- `tests/test_aggregator.py`  -  empty, placeholder
- `tests/test_config.py`  -  empty, placeholder

### 1.5  -  Install in development mode

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Verify:
```bash
tallyman --help
tallyman
python -m tallyman
```

All three should work. The first should show help text. The other two should print the placeholder message.

## Acceptance Criteria

- [ ] `pyproject.toml` exists with correct metadata, dependencies, and entry point
- [ ] `tallyman` command is available after `uv pip install -e .`
- [ ] `python -m tallyman` also works
- [ ] `tallyman --help` shows usage information
- [ ] `tallyman /some/path` accepts a path argument
- [ ] `tallyman --setup` and `--no-color` flags are accepted without error
- [ ] Ruff passes with no errors on all files
- [ ] All module stubs exist in the correct locations
