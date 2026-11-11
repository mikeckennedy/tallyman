"""File and directory walking with gitignore and config-based exclusions."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

from tallyman.config import CONFIG_FILENAME, SELF, TallyConfig, load_nested_config, merge_configs
from tallyman.encoding import has_wide_bom
from tallyman.gitignore import GitIgnoreSpec, find_git_root, load_gitignore
from tallyman.languages import Language, as_spec, identify_language
from tallyman.paths import relative_posix

SPEC_DIR_NAMES: frozenset[str] = frozenset({'specs', 'specifications', 'plans', 'agents'})


class SpecState(NamedTuple):
    """Spec status of one directory."""

    is_spec: bool
    detection_suppressed: bool  # under a [specs] ignore entry: names like plans/ are not auto-detected


def root_spec_state(spec_dirs: set[str], non_spec_dirs: set[str], auto: bool = False) -> SpecState:
    """Spec status of the scan root itself, from '.' entries.

    The root's own name is never auto-detected. *auto* is True when the root
    sits inside an auto-detected spec directory (see :func:`inside_auto_spec_dir`);
    it then counts as specs unless an ignore entry says otherwise.
    """
    if SELF in spec_dirs:
        return SpecState(True, False)
    if SELF in non_spec_dirs:
        return SpecState(False, True)
    return SpecState(auto, False)


def spec_state(rel: str, name: str, parent: SpecState, spec_dirs: set[str], non_spec_dirs: set[str]) -> SpecState:
    """Spec status of the directory at *rel*, given its parent's.

    The deepest explicit setting wins: a ``spec_dirs`` entry makes the subtree
    specs; a ``non_spec_dirs`` entry makes it not specs and stops
    auto-detection by name beneath it. Otherwise spec status is inherited, and
    a directory named like ``plans`` is detected unless an ancestor is ignored.
    Shared by walk_project() and the setup TUI so they always agree.
    """
    if rel in spec_dirs:
        return SpecState(True, False)
    if rel in non_spec_dirs:
        return SpecState(False, True)
    if parent.is_spec:
        return SpecState(True, False)
    if parent.detection_suppressed:
        return SpecState(False, True)
    return SpecState(name.lower() in SPEC_DIR_NAMES, False)


def inside_auto_spec_dir(root: Path) -> bool:
    """True if *root* is, or is inside, a directory auto-detected as specs (``plans/``, ``specs/``, ...).

    Only directories inside the git repo count, so scanning a project that is
    itself named ``agents`` does not turn its docs into specs. Outside a repo
    there is nothing above the scan root to check.
    """
    resolved = root.resolve()
    git_root = find_git_root(resolved)
    if git_root is None:
        return False
    return any(part.lower() in SPEC_DIR_NAMES for part in resolved.relative_to(git_root).parts)


# Skipped whatever .gitignore says.
# Generated files that would dwarf the real code. Lower case: the check ignores case.
GENERATED_FILENAMES: frozenset[str] = frozenset(
    {CONFIG_FILENAME, 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml'}
)
GENERATED_SUFFIXES: tuple[str, ...] = ('.min.js', '.min.css')


def _is_generated(filename: str) -> bool:
    """True for tallyman's own config, npm and pnpm lockfiles, and minified bundles, in any letter case."""
    name = filename.lower()
    return name in GENERATED_FILENAMES or name.endswith(GENERATED_SUFFIXES)


def _is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary (a NUL byte in the first 8 KB).

    UTF-16 and UTF-32 text is full of NUL bytes, so a file that starts with
    their byte-order mark is text. Only the first 8 KB is read.
    """
    try:
        with path.open('rb') as f:
            chunk = f.read(8192)
    except OSError:
        return True
    return b'\x00' in chunk and not has_wide_bom(chunk)


def _is_regular_file(path: Path) -> bool:
    """True for a regular file that is not a symlink, from one lstat().

    FIFOs, sockets and devices are skipped: opening a FIFO blocks until something writes to it.
    Symlinks are skipped too: the walk doesn't follow linked directories either, and a link to a
    file in the tree would count that file twice.
    """
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False  # vanished or unreadable mid-walk


@dataclass(slots=True)
class WalkStats:
    """What ``[exclude] patterns`` removed from a walk, for the report.

    ``pattern_files`` counts only files that would otherwise have been counted
    (a recognised language, not binary). ``pattern_dirs`` counts directories
    pruned by a pattern; the files inside them are not looked at.
    """

    pattern_files: int = 0
    pattern_dirs: int = 0


class SourceFile(NamedTuple):
    """A file to count, and how: what :func:`walk_files` yields."""

    path: Path
    language: Language
    exclude_rust_tests: bool  # [rust] exclude_test_modules as it applies in this file's directory


def walk_project(
    root: Path,
    excluded_dirs: set[str],
    gitignore_spec: Optional[GitIgnoreSpec] = None,
    spec_dirs: Optional[set[str]] = None,
    non_spec_dirs: Optional[set[str]] = None,
    exclude_patterns: Optional[GitIgnoreSpec] = None,
    stats: Optional[WalkStats] = None,
    exclude_rust_tests: bool = False,
) -> Iterator[tuple[Path, Language]]:
    """Yield (file_path, language) for every countable source file under root.

    The files :func:`walk_files` yields, without how to count them; its
    docstring describes the arguments. *exclude_rust_tests* is accepted so the
    two take the same arguments, but can't change which files are yielded.
    """
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
        yield source.path, source.language


def walk_files(
    root: Path,
    excluded_dirs: set[str],
    gitignore_spec: Optional[GitIgnoreSpec] = None,
    spec_dirs: Optional[set[str]] = None,
    non_spec_dirs: Optional[set[str]] = None,
    exclude_patterns: Optional[GitIgnoreSpec] = None,
    stats: Optional[WalkStats] = None,
    exclude_rust_tests: bool = False,
) -> Iterator[SourceFile]:
    """Yield a :class:`SourceFile` for every countable source file under root.

    Args:
        root: Project root directory.
        excluded_dirs: Relative directory paths to skip (e.g. {'static/external'}).
        gitignore_spec: Pre-loaded gitignore patterns. Loaded from root if None. ``.gitignore``
            files found while walking are registered on it as each directory is entered. A nested
            git repository found while walking starts its own rules (see
            :meth:`GitIgnoreSpec.add_directory`).
        spec_dirs: Relative directory paths designated as spec directories. ``'.'`` marks *root*
            itself, so docs files at every level count as specs.
        non_spec_dirs: Relative directory paths that are never specs (``[specs] ignore``).
        exclude_patterns: ``[exclude] patterns`` from the configs that apply at *root*
            (:meth:`GitIgnoreSpec.for_patterns`). An empty one is made if None. Patterns from
            nested configs found while walking are registered on it as each directory is entered.
        stats: Filled with what the patterns excluded, if given.
        exclude_rust_tests: ``[rust] exclude_test_modules`` at *root*
            (``ConfigChain.rust_exclude_test_modules``). A nested config found while walking
            that sets it changes it for its directory and everything below.
    """
    if gitignore_spec is None:
        gitignore_spec = load_gitignore(root)
    if exclude_patterns is None:
        exclude_patterns = GitIgnoreSpec.for_patterns(root)

    active = TallyConfig(set(excluded_dirs), set(spec_dirs or ()), set(non_spec_dirs or ()))
    states: dict[str, SpecState] = {}
    # Per directory, like states. Never folded into `active`: that is shared by the whole walk, so a value
    # set in one crate would leak into the sibling crates walked after it.
    rust_tests: dict[str, bool] = {}

    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir_str = relative_posix(dirpath, root)

        # This directory's own .gitignore governs its children, so load it before filtering them. If the
        # directory is a nested git repo, this is also where its own rules start and the outer ones stop.
        gitignore_spec.add_directory(rel_dir_str, dirpath)

        # Discover nested config files in subdirectories
        dir_rust_tests = rust_tests[rel_dir_str.rpartition('/')[0]] if rel_dir_str else exclude_rust_tests
        if rel_dir_str:
            config_file = dirpath / CONFIG_FILENAME
            if config_file.is_file() and (loaded := load_nested_config(config_file, rel_dir_str)) is not None:
                # os.walk is top-down, so an ancestor's config is merged first and the deeper config wins
                active = merge_configs(active, loaded.config)
                # Like a .gitignore, its patterns govern this directory's children, so register them first
                exclude_patterns.add_rules(dirpath, loaded.patterns)
                if loaded.rust_exclude_test_modules is not None:
                    dir_rust_tests = loaded.rust_exclude_test_modules
        rust_tests[rel_dir_str] = dir_rust_tests

        # Prune excluded and gitignored subdirectories in-place
        filtered_dirs: list[str] = []
        for d in sorted(dirnames):
            # Skip hidden directories (e.g. .git, .venv)
            if d.startswith('.'):
                continue
            child_rel = f'{rel_dir_str}/{d}' if rel_dir_str else d
            # Check config exclusions
            if child_rel in active.excluded_dirs:
                continue
            # Check gitignore (append / to match directory patterns)
            if gitignore_spec.match_file(child_rel + '/'):
                continue
            if exclude_patterns.match_file(child_rel + '/'):
                # A linked directory is never entered anyway, so it isn't something the pattern removed
                if stats is not None and not (dirpath / d).is_symlink():
                    stats.pattern_dirs += 1
                continue
            filtered_dirs.append(d)

        dirnames[:] = filtered_dirs

        # Determine if this directory is inside a spec directory
        if rel_dir_str:
            parent_state = states[rel_dir_str.rpartition('/')[0]]
            state = spec_state(rel_dir_str, dirpath.name, parent_state, active.spec_dirs, active.non_spec_dirs)
        else:
            state = root_spec_state(active.spec_dirs, active.non_spec_dirs)
        states[rel_dir_str] = state
        dir_is_spec = state.is_spec

        # Yield recognized, non-binary files
        for filename in sorted(filenames):
            file_path = dirpath / filename
            # Skip files matched by gitignore
            file_rel = f'{rel_dir_str}/{filename}' if rel_dir_str else filename
            if gitignore_spec.match_file(file_rel):
                continue

            # Skip generated files, and anything but a regular file. This comes before the pattern
            # check, whose stats path opens the file.
            if _is_generated(filename) or not _is_regular_file(file_path):
                continue

            if exclude_patterns.match_file(file_rel):
                # Report only files that would otherwise have been counted
                if stats is not None and identify_language(file_path) is not None and not _is_binary(file_path):
                    stats.pattern_files += 1
                continue

            language = identify_language(file_path)
            if language is None:
                continue

            if _is_binary(file_path):
                continue

            # Swap docs → specs if inside a spec directory
            if dir_is_spec and language.category == 'docs':
                language = as_spec(language)

            yield SourceFile(file_path, language, dir_rust_tests)
