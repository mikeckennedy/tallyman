"""Command-line interface for tallyman."""

from __future__ import annotations

import argparse
import io
import os
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from tallyman import __version__
from tallyman.aggregator import aggregate
from tallyman.config import (
    CONFIG_FILENAME,
    SELF,
    ConfigChain,
    ConfigError,
    PatternLayer,
    TallyConfig,
    find_configs,
    load_config_chain,
    merge_configs,
    rust_setting,
    save_config,
)
from tallyman.counter import count_lines
from tallyman.display import display_results
from tallyman.gitignore import GitIgnoreSpec, is_live_pattern, load_gitignore
from tallyman.paths import canonical_case, relative_posix
from tallyman.walker import WalkStats, inside_auto_spec_dir, walk_files

if TYPE_CHECKING:  # Textual is imported only when setup runs: see run_setup()
    from tallyman.tui.setup_app import SetupResult


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
        '--exclude',
        action='append',
        default=[],
        metavar='PATTERN',
        help='Leave out files matching a gitignore-style PATTERN, relative to the scanned directory, '
        'for this run only (repeatable; overrides config patterns; never saved)',
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


def _exclude_problem(pattern: str, roots: tuple[Path, ...]) -> Optional[str]:
    """Why an ``--exclude`` value can never match anything, or None when it is a usable pattern.

    Beyond what the gitignore parser drops, a path segment that is empty, ``.`` or ``..`` never matches (the
    walker's paths have none), and neither does an absolute path into the scan root: patterns are relative to
    it. *roots* are the scan root's spellings: as resolved, and as typed (``/tmp/x`` is ``/private/tmp/x``).
    """
    if '\n' in pattern or '\r' in pattern:
        return f'--exclude takes one pattern per flag; {pattern!r} spans lines'
    shown = shlex.quote(pattern)
    if not pattern.strip():
        return f'--exclude {shown} is blank'
    if pattern.startswith('#'):
        return (
            f'--exclude {shown} is a comment in gitignore syntax; '
            f'write {shlex.quote("\\" + pattern)} to match a name starting with #'
        )
    if not is_live_pattern(pattern):
        return f'--exclude {shown} can never match anything'
    negation, body = ('!', pattern[1:]) if pattern.startswith('!') else ('', pattern)
    for root in roots:
        root_posix = root.as_posix().rstrip('/')  # '' when scanning /, where every anchored pattern is fine
        if root_posix and body.rstrip('/') == root_posix:
            return f'--exclude {shown} names the scanned directory itself, which a pattern never excludes'
        if root_posix and body.startswith(root_posix + '/'):
            relative = shlex.quote(negation + body[len(root_posix) :])
            return (
                f'--exclude {shown} is an absolute path; patterns are relative to the scanned directory: '
                f'write {relative}'
            )
    segments = body.rstrip(' ').removeprefix('/').removesuffix('/').split('/')
    if any(segment in ('', '.', '..') for segment in segments):
        fixed = negation + '/' + body.removeprefix('./')
        # './src/gen/' (what tab completion types) means '/src/gen/', anchored like it
        hint = f'; write {shlex.quote(fixed)}' if body.startswith('./') and not _exclude_problem(fixed, roots) else ''
        return f"--exclude {shown} can never match anything: '.', '..' and empty path segments never match{hint}"
    return None


def _pattern_spec(root: Path, layers: list[PatternLayer]) -> GitIgnoreSpec:
    """The ``[exclude] patterns`` rules for *root*, one layer per config, shallowest first."""
    spec = GitIgnoreSpec.for_patterns(root)
    for config_dir, patterns in layers:
        spec.add_rules(config_dir, patterns)
    return spec


def run_setup(
    root: Path,
    gitignore_spec: GitIgnoreSpec,
    existing_exclusions: set[str],
    existing_specs: set[str],
    *,
    existing_non_specs: Optional[set[str]] = None,
    root_auto_spec: bool = False,
    inherited: Optional[TallyConfig] = None,
    exclude_patterns: Optional[GitIgnoreSpec] = None,
    existing_rust: Optional[bool] = None,
) -> Optional[SetupResult]:
    """Launch the setup TUI (tui.setup_app.run_setup). Textual is imported here, so a plain run never loads it."""
    from tallyman.tui.setup_app import run_setup as launch

    return launch(
        root,
        gitignore_spec,
        existing_exclusions,
        existing_specs,
        existing_non_specs=existing_non_specs,
        root_auto_spec=root_auto_spec,
        inherited=inherited,
        exclude_patterns=exclude_patterns,
        existing_rust=existing_rust,
    )


def _tolerate_unencodable_stdout() -> None:
    """Print '?' for characters stdout's encoding can't represent, instead of crashing.

    Directory names, language display names and the image path can hold any character; a cp1252 or ascii
    stdout can't show them all. stderr needs nothing: Python already opens it with errors='backslashreplace'.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors='replace')


def main() -> None:
    _tolerate_unencodable_stdout()
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

    for pattern in args.exclude:
        if (problem := _exclude_problem(pattern, (root, Path(args.path).absolute()))) is not None:
            print(f'Error: {problem}.', file=sys.stderr)
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
        exclude_rust_tests = chain.rust_exclude_test_modules
    elif not interactive:
        # First run with no terminal (CI, pipes): count with defaults rather than hang in the TUI
        print(
            f'No {CONFIG_FILENAME} found and no terminal for setup; using default settings. '
            'Run `tallyman --setup` in a terminal to configure.',
            file=sys.stderr,
        )
        config = TallyConfig()
        exclude_patterns = _pattern_spec(root, [])
        exclude_rust_tests = False
    else:
        # First run or --setup: launch TUI. --setup is how a broken config gets repaired, so skip
        # a malformed one with a warning rather than refuse.
        chain = load_config_chain(config_paths, root, on_error=_warn_and_skip(root))
        # The TUI reads nested configs as it builds its tree, adding their patterns to this same spec
        exclude_patterns = _pattern_spec(root, chain.pattern_layers)
        # Parent and nested configs are shown locked; they stay in their own files, which are read on every run
        result = run_setup(
            root,
            gitignore_spec,
            chain.local.excluded_dirs,
            chain.local.spec_dirs,
            existing_non_specs=chain.local.non_spec_dirs,
            inherited=chain.inherited,
            root_auto_spec=root_auto_spec,
            exclude_patterns=exclude_patterns,
            existing_rust=chain.local.rust_exclude_test_modules,
        )
        if result is None:
            print('Setup cancelled.')
            sys.exit(0)
        # Only the scan root's own settings: setup drops copies of the others
        local = TallyConfig(result.excluded_dirs, result.spec_dirs, result.non_spec_dirs)
        local_rust = result.rust_exclude_test_modules
        try:
            # Setup doesn't edit patterns: keep the scan-root config's own, as written and in order
            save_config(
                config_path,
                local.excluded_dirs,
                local.spec_dirs,
                local.non_spec_dirs,
                patterns=chain.local.patterns,
                rust_exclude_test_modules=local_rust,
            )
        except (OSError, UnicodeEncodeError) as e:
            # Don't throw away the user's selections: warn, then count with them anyway
            print(f'Warning: could not save {config_path} ({e}); using this run only.', file=sys.stderr)
        config = merge_configs(chain.inherited, local)
        # The scan root's value from setup, else the parents'
        exclude_rust_tests = rust_setting(local_rust, chain.inherited.rust_exclude_test_modules)

    # --exclude is the last word over every config's patterns, nested ones included. Added only now, after
    # setup: the TUI shares this spec, and it shows and saves what the configs do, never a one-off pattern.
    if args.exclude:
        exclude_patterns.add_rules(root, args.exclude, final=True)

    excluded_dirs, spec_dirs, non_spec_dirs = config.excluded_dirs, config.spec_dirs, config.non_spec_dirs

    # A scan root inside plans/, specs/, ... counts as specs, as it does when scanned from above,
    # unless a config already decided for the scan root ('.' in either set)
    if SELF not in spec_dirs and SELF not in non_spec_dirs and root_auto_spec:
        spec_dirs = spec_dirs | {SELF}

    # Walk and count
    file_results = []
    stats = WalkStats()
    for source in walk_files(
        root,
        excluded_dirs,
        gitignore_spec,
        spec_dirs=spec_dirs,
        non_spec_dirs=non_spec_dirs,
        exclude_patterns=exclude_patterns,
        stats=stats,
        exclude_rust_tests=exclude_rust_tests,
    ):
        counts = count_lines(source.path, source.language, source.exclude_rust_tests)
        file_results.append((source.language, counts))

    # Aggregate
    tally = aggregate(file_results)

    # Display
    # no-color.org: NO_COLOR disables colour only when set to a non-empty value
    no_color = args.no_color or bool(os.environ.get('NO_COLOR'))
    display_results(tally, directory=root.name, no_color=no_color, with_spaces=args.with_spaces, stats=stats)

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
