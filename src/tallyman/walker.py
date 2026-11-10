"""File and directory walking with gitignore and config-based exclusions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from tallyman.config import CONFIG_FILENAME, SELF, load_nested_config
from tallyman.gitignore import GitIgnoreSpec, find_git_root, load_gitignore
from tallyman.languages import Language, as_spec, identify_language
from tallyman.paths import relative_posix

SPEC_DIR_NAMES: frozenset[str] = frozenset({'specs', 'specifications', 'plans', 'agents'})


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


def _is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary."""
    try:
        chunk = path.read_bytes()[:8192]
        return b'\x00' in chunk
    except OSError:
        return True


def walk_project(
    root: Path,
    excluded_dirs: set[str],
    gitignore_spec: GitIgnoreSpec | None = None,
    spec_dirs: Optional[set[str]] = None,
) -> Iterator[tuple[Path, Language]]:
    """Yield (file_path, language) for every countable source file under root.

    Args:
        root: Project root directory.
        excluded_dirs: Relative directory paths to skip (e.g. {'static/external'}).
        gitignore_spec: Pre-loaded gitignore patterns. Loaded from root if None. ``.gitignore``
            files found while walking are registered on it as each directory is entered.
        spec_dirs: Relative directory paths designated as spec directories. ``'.'`` marks *root*
            itself, so docs files at every level count as specs.
    """
    if gitignore_spec is None:
        gitignore_spec = load_gitignore(root)

    working_excluded = set(excluded_dirs)
    active_spec_roots: set[str] = set(spec_dirs) if spec_dirs else set()
    root_is_spec = SELF in active_spec_roots

    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir_str = relative_posix(dirpath, root)

        # This directory's own .gitignore governs its children, so load it before filtering them
        gitignore_spec.add_directory(rel_dir_str, dirpath)

        # Discover nested config files in subdirectories
        if rel_dir_str:
            config_file = dirpath / CONFIG_FILENAME
            if config_file.is_file() and (nested := load_nested_config(config_file, rel_dir_str)) is not None:
                working_excluded |= nested.excluded_dirs
                active_spec_roots |= nested.spec_dirs

        # Prune excluded and gitignored subdirectories in-place
        filtered_dirs: list[str] = []
        for d in sorted(dirnames):
            # Skip hidden directories (e.g. .git, .venv)
            if d.startswith('.'):
                continue
            child_rel = f'{rel_dir_str}/{d}' if rel_dir_str else d
            # Check config exclusions
            if child_rel in working_excluded:
                continue
            # Check gitignore (append / to match directory patterns)
            if gitignore_spec.match_file(child_rel + '/'):
                continue
            filtered_dirs.append(d)

        dirnames[:] = filtered_dirs

        # Determine if this directory is inside a spec directory
        dir_is_spec = root_is_spec
        if rel_dir_str and not dir_is_spec:
            # Check auto-detection by directory name
            if dirpath.name.lower() in SPEC_DIR_NAMES:
                dir_is_spec = True
                active_spec_roots.add(rel_dir_str)
            # Check user-designated spec dirs
            elif rel_dir_str in active_spec_roots:
                dir_is_spec = True
            # Check if parent is a spec dir (cascading)
            else:
                for sr in active_spec_roots:
                    if rel_dir_str.startswith(sr + '/'):
                        dir_is_spec = True
                        break

        # Yield recognized, non-binary files
        for filename in sorted(filenames):
            file_path = dirpath / filename
            # Skip files matched by gitignore
            file_rel = f'{rel_dir_str}/{filename}' if rel_dir_str else filename
            if gitignore_spec.match_file(file_rel):
                continue

            language = identify_language(file_path)
            if language is None:
                continue

            if _is_binary(file_path):
                continue

            # Swap docs → specs if inside a spec directory
            if dir_is_spec and language.category == 'docs':
                language = as_spec(language)

            yield file_path, language
