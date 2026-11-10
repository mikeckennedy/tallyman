"""Command-line interface for tallyman."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from tallyman import __version__
from tallyman.aggregator import aggregate
from tallyman.config import (
    CONFIG_FILENAME,
    SELF,
    ConfigError,
    TallyConfig,
    discover_nested_configs,
    find_config,
    load_config,
    rebase_config,
    save_config,
)
from tallyman.counter import count_lines
from tallyman.display import display_results
from tallyman.gitignore import load_gitignore
from tallyman.paths import canonical_case, relative_posix
from tallyman.tui.setup_app import run_setup
from tallyman.walker import inside_auto_spec_dir, walk_project


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
        '--with-spaces',
        action='store_true',
        help='Use total lines (including comments and blanks) for summary totals',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    return parser


def _is_interactive() -> bool:
    """True when both stdin and stdout are a terminal, so the setup TUI can run."""
    # Either stream can be None when a launcher closes it (some cron and daemon setups)
    return bool(sys.stdin and sys.stdout and sys.stdin.isatty() and sys.stdout.isatty())


def _load_config_or_exit(config_path: Path, root: Path) -> TallyConfig:
    """Load the config at *config_path*, rebased onto *root*; on a bad config, report it and exit 1."""
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f'Error: could not read {config_path}: {e}', file=sys.stderr)
        setup_cmd = f'tallyman --setup {shlex.quote(str(config_path.parent))}'
        print(f'Fix or delete the file, or re-create it with: {setup_cmd}', file=sys.stderr)
        sys.exit(1)
    return rebase_config(config, config_path.parent, root)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = canonical_case(Path(args.path).resolve())

    if not root.is_dir():
        print(f'Error: {root} is not a directory', file=sys.stderr)
        sys.exit(1)

    interactive = _is_interactive()
    if args.setup and not interactive:
        print('Error: --setup needs an interactive terminal.', file=sys.stderr)
        sys.exit(2)

    # Load gitignore
    gitignore_spec = load_gitignore(root)

    # Load or create config
    config_path = root / CONFIG_FILENAME
    existing_config = find_config(root)

    if existing_config and not args.setup:
        config = _load_config_or_exit(existing_config, root)
        excluded_dirs = config.excluded_dirs
        spec_dirs = config.spec_dirs
    elif not interactive:
        # First run with no terminal (CI, pipes): count with defaults rather than hang in the TUI
        print(
            f'No {CONFIG_FILENAME} found and no terminal for setup; using default settings. '
            'Run `tallyman --setup` in a terminal to configure.',
            file=sys.stderr,
        )
        excluded_dirs, spec_dirs = set(), set()
    else:
        # First run or --setup: launch TUI
        existing = TallyConfig()
        if existing_config:
            try:
                existing = rebase_config(load_config(existing_config), existing_config.parent, root)
            except ConfigError as e:
                # --setup is how a broken config gets repaired, so start fresh rather than refuse
                print(f'Warning: ignoring {existing_config} ({e}); setup will write a new config.', file=sys.stderr)
        # Discover nested configs and pre-apply their exclusions/specs
        nested = discover_nested_configs(root)
        merged_excluded = existing.excluded_dirs | nested.excluded_dirs
        merged_specs = existing.spec_dirs | nested.spec_dirs
        result = run_setup(root, gitignore_spec, merged_excluded, merged_specs)
        if result is None:
            print('Setup cancelled.')
            sys.exit(0)
        excluded_dirs, spec_dirs = result
        try:
            save_config(config_path, excluded_dirs, spec_dirs)
        except (OSError, UnicodeEncodeError) as e:
            # Don't throw away the user's selections: warn, then count with them anyway
            print(f'Warning: could not save {config_path} ({e}); using this run only.', file=sys.stderr)

    # A scan root inside plans/, specs/, ... counts as specs, as it does when scanned from above
    if inside_auto_spec_dir(root):
        spec_dirs = spec_dirs | {SELF}

    # Walk and count
    file_results = []
    for file_path, language in walk_project(root, excluded_dirs, gitignore_spec, spec_dirs=spec_dirs):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    tally = aggregate(file_results)

    # Display
    no_color = args.no_color or os.environ.get('NO_COLOR') is not None
    display_results(tally, directory=root.name, no_color=no_color, with_spaces=args.with_spaces)

    # Image export (lazy import so Pillow only loaded when requested)
    if args.image or args.image_light:
        from tallyman.image import DARK_THEME, LIGHT_THEME, generate_image, resolve_image_path

        theme = LIGHT_THEME if args.image_light else DARK_THEME
        desktop = (Path.home() / 'Desktop').is_dir()
        output_path = resolve_image_path(root.name, desktop_preferred=True)
        if not desktop:
            print('Desktop not found; saving to current directory.', file=sys.stderr)
        generate_image(tally, root.name, output_path, theme, with_spaces=args.with_spaces)
        if output_path.is_relative_to(Path.home()):
            display_path = '~/' + relative_posix(output_path, Path.home())
        else:
            display_path = str(output_path)
        print(f'Image saved to {display_path}')
