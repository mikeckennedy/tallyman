"""Command-line interface for tallyman."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from tallyman.aggregator import aggregate
from tallyman.config import CONFIG_FILENAME, find_config, load_config, save_config
from tallyman.counter import count_lines
from tallyman.display import display_results
from tallyman.tui.setup_app import run_setup
from tallyman.walker import load_gitignore, walk_project


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
    root = Path(args.path).resolve()

    if not root.is_dir():
        print(f'Error: {root} is not a directory', file=sys.stderr)
        sys.exit(1)

    # Load gitignore
    gitignore_spec = load_gitignore(root)

    # Load or create config
    config_path = root / CONFIG_FILENAME
    existing_config = find_config(root)

    if existing_config and not args.setup:
        excluded_dirs = load_config(existing_config)
    else:
        # First run or --setup: launch TUI
        existing_exclusions = load_config(existing_config) if existing_config else set()
        result = run_setup(root, gitignore_spec, existing_exclusions)
        if result is None:
            print('Setup cancelled.')
            sys.exit(0)
        excluded_dirs = result
        save_config(config_path, excluded_dirs)

    # Walk and count
    file_results = []
    for file_path, language in walk_project(root, excluded_dirs, gitignore_spec):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    tally = aggregate(file_results)

    # Display
    no_color = args.no_color or os.environ.get('NO_COLOR') is not None
    display_results(tally, directory=root.name, no_color=no_color)
