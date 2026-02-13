"""Command-line interface for tallyman."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from tallyman import __version__
from tallyman.aggregator import aggregate
from tallyman.config import CONFIG_FILENAME, TallyConfig, find_config, load_config, save_config
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
    parser.add_argument(
        '--image',
        action='store_true',
        help='Generate a summary image on the Desktop',
    )
    parser.add_argument(
        '--image-light',
        action='store_true',
        help='Generate a light-themed summary image on the Desktop',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
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
        config = load_config(existing_config)
        excluded_dirs = config.excluded_dirs
        spec_dirs = config.spec_dirs
    else:
        # First run or --setup: launch TUI
        existing = load_config(existing_config) if existing_config else TallyConfig()
        result = run_setup(root, gitignore_spec, existing.excluded_dirs, existing.spec_dirs)
        if result is None:
            print('Setup cancelled.')
            sys.exit(0)
        excluded_dirs, spec_dirs = result
        save_config(config_path, excluded_dirs, spec_dirs)

    # Walk and count
    file_results = []
    for file_path, language in walk_project(root, excluded_dirs, gitignore_spec, spec_dirs):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    tally = aggregate(file_results)

    # Display
    no_color = args.no_color or os.environ.get('NO_COLOR') is not None
    display_results(tally, directory=root.name, no_color=no_color)

    # Image export (lazy import so Pillow only loaded when requested)
    if args.image or args.image_light:
        from tallyman.image import DARK_THEME, LIGHT_THEME, generate_image, resolve_image_path

        theme = LIGHT_THEME if args.image_light else DARK_THEME
        desktop = (Path.home() / 'Desktop').is_dir()
        output_path = resolve_image_path(root.name, desktop_preferred=True)
        if not desktop:
            print('Desktop not found; saving to current directory.', file=sys.stderr)
        generate_image(tally, root.name, output_path, theme)
        if output_path.is_relative_to(Path.home()):
            display_path = '~/' + str(output_path.relative_to(Path.home())).replace('\\', '/')
        else:
            display_path = str(output_path)
        print(f'Image saved to {display_path}')
