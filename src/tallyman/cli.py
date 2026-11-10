"""Command-line interface for tallyman."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path

from tallyman import __version__
from tallyman.aggregator import aggregate
from tallyman.config import (
    CONFIG_FILENAME,
    SELF,
    ConfigChain,
    ConfigError,
    PatternLayer,
    TallyConfig,
    discover_nested_configs,
    find_configs,
    load_config_chain,
    merge_configs,
    save_config,
    without_inherited,
)
from tallyman.counter import count_lines
from tallyman.display import display_results
from tallyman.gitignore import GitIgnoreSpec, load_gitignore
from tallyman.paths import canonical_case, relative_posix
from tallyman.tui.setup_app import run_setup
from tallyman.walker import WalkStats, inside_auto_spec_dir, walk_project


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


def _load_chain_or_exit(config_paths: list[Path], root: Path) -> ConfigChain:
    """Load the configs that apply at *root*; on a bad one, report it and exit 1."""
    try:
        return load_config_chain(config_paths, root)
    except ConfigError as e:
        bad = e.path or root / CONFIG_FILENAME
        print(f'Error: could not read {bad}: {e}', file=sys.stderr)
        setup_cmd = f'tallyman --setup {shlex.quote(str(bad.parent))}'
        print(f'Fix or delete the file, or re-create it with: {setup_cmd}', file=sys.stderr)
        sys.exit(1)


def _warn_and_skip(root: Path) -> Callable[[ConfigError], None]:
    """An error handler for --setup: report a broken config and carry on without it."""

    def warn(e: ConfigError) -> None:
        if e.path is not None and e.path.parent == root:
            consequence = 'setup will write a new config'
        else:
            consequence = 'its settings are skipped until it is fixed'
        print(f'Warning: ignoring {e.path} ({e}); {consequence}.', file=sys.stderr)

    return warn


def _pattern_spec(root: Path, layers: list[PatternLayer]) -> GitIgnoreSpec:
    """The ``[exclude] patterns`` rules for *root*, one layer per config, shallowest first."""
    spec = GitIgnoreSpec.for_patterns(root)
    for config_dir, patterns in layers:
        spec.add_rules(config_dir, patterns)
    return spec


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

    # Load or create config: every .tally-config.toml from the git root down to the scan root applies
    root_auto_spec = inside_auto_spec_dir(root)
    config_path = root / CONFIG_FILENAME
    config_paths = find_configs(root)

    if config_paths and not args.setup:
        chain = _load_chain_or_exit(config_paths, root)
        config = chain.effective
        exclude_patterns = _pattern_spec(root, chain.pattern_layers)
    elif not interactive:
        # First run with no terminal (CI, pipes): count with defaults rather than hang in the TUI
        print(
            f'No {CONFIG_FILENAME} found and no terminal for setup; using default settings. '
            'Run `tallyman --setup` in a terminal to configure.',
            file=sys.stderr,
        )
        config = TallyConfig()
        exclude_patterns = _pattern_spec(root, [])
    else:
        # First run or --setup: launch TUI. --setup is how a broken config gets repaired, so skip
        # a malformed one with a warning rather than refuse.
        chain = load_config_chain(config_paths, root, on_error=_warn_and_skip(root))
        # Nested configs' patterns are registered up front so the TUI sees them; the walker skips repeats
        nested_layers: list[PatternLayer] = []
        nested = discover_nested_configs(root, nested_layers)
        exclude_patterns = _pattern_spec(root, chain.pattern_layers + nested_layers)
        # Parent and nested configs are shown locked; they stay in their own files, which are read on every run
        result = run_setup(
            root,
            gitignore_spec,
            chain.local.excluded_dirs,
            chain.local.spec_dirs,
            chain.local.non_spec_dirs,
            nested=nested,
            inherited=chain.inherited,
            root_auto_spec=root_auto_spec,
            exclude_patterns=exclude_patterns,
        )
        if result is None:
            print('Setup cancelled.')
            sys.exit(0)
        # Older versions copied parent settings into a new config; drop those copies so each lives in one file
        local = without_inherited(TallyConfig(*result), chain.inherited)
        try:
            # Setup doesn't edit patterns: keep the scan-root config's own, as written and in order
            save_config(
                config_path, local.excluded_dirs, local.spec_dirs, local.non_spec_dirs, patterns=chain.local.patterns
            )
        except (OSError, UnicodeEncodeError) as e:
            # Don't throw away the user's selections: warn, then count with them anyway
            print(f'Warning: could not save {config_path} ({e}); using this run only.', file=sys.stderr)
        config = merge_configs(chain.inherited, local)

    excluded_dirs, spec_dirs, non_spec_dirs = config.excluded_dirs, config.spec_dirs, config.non_spec_dirs

    # A scan root inside plans/, specs/, ... counts as specs, as it does when scanned from above,
    # unless a config already decided for the scan root ('.' in either set)
    if SELF not in spec_dirs and SELF not in non_spec_dirs and root_auto_spec:
        spec_dirs = spec_dirs | {SELF}

    # Walk and count
    file_results = []
    stats = WalkStats()
    for file_path, language in walk_project(
        root,
        excluded_dirs,
        gitignore_spec,
        spec_dirs=spec_dirs,
        non_spec_dirs=non_spec_dirs,
        exclude_patterns=exclude_patterns,
        stats=stats,
    ):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    tally = aggregate(file_results)

    # Display
    # no-color.org: NO_COLOR disables colour only when set to a non-empty value
    no_color = args.no_color or bool(os.environ.get('NO_COLOR'))
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
