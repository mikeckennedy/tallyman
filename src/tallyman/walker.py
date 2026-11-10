"""File and directory walking with gitignore and config-based exclusions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from tallyman.config import CONFIG_FILENAME, load_config
from tallyman.gitignore import GitIgnoreSpec, load_gitignore
from tallyman.languages import Language, as_spec, identify_language
from tallyman.paths import relative_posix

SPEC_DIR_NAMES: frozenset[str] = frozenset({'specs', 'specifications', 'plans', 'agents'})


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
    spec_dirs: set[str] | None = None,
) -> Iterator[tuple[Path, Language]]:
    """Yield (file_path, language) for every countable source file under root.

    Args:
        root: Project root directory.
        excluded_dirs: Relative directory paths to skip (e.g. {'static/external'}).
        gitignore_spec: Pre-loaded gitignore patterns. Loaded from root if None. ``.gitignore``
            files found while walking are registered on it as each directory is entered.
        spec_dirs: Relative directory paths designated as spec directories.
    """
    if gitignore_spec is None:
        gitignore_spec = load_gitignore(root)

    working_excluded = set(excluded_dirs)
    active_spec_roots: set[str] = set(spec_dirs) if spec_dirs else set()

    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir_str = relative_posix(dirpath, root)

        # This directory's own .gitignore governs its children, so load it before filtering them
        gitignore_spec.add_directory(rel_dir_str, dirpath)

        # Discover nested config files in subdirectories
        if rel_dir_str:
            config_file = dirpath / CONFIG_FILENAME
            if config_file.is_file():
                try:
                    nested_config = load_config(config_file)
                    for excl in nested_config.excluded_dirs:
                        working_excluded.add(f'{rel_dir_str}/{excl}')
                    for spec in nested_config.spec_dirs:
                        active_spec_roots.add(f'{rel_dir_str}/{spec}')
                except Exception:
                    pass  # Skip malformed configs in subdirectories

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
        dir_is_spec = False
        if rel_dir_str:
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
