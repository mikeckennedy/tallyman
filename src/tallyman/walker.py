"""File and directory walking with gitignore and config-based exclusions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pathspec

from tallyman.languages import Language, identify_language


def load_gitignore(root: Path) -> pathspec.PathSpec:
    """Load gitignore patterns from .gitignore and .git/info/exclude."""
    lines: list[str] = []
    for ignore_file in [root / '.gitignore', root / '.git' / 'info' / 'exclude']:
        if ignore_file.is_file():
            lines.extend(ignore_file.read_text(encoding='utf-8', errors='replace').splitlines())
    return pathspec.PathSpec.from_lines('gitignore', lines)  # type: ignore[arg-type]


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
    gitignore_spec: pathspec.PathSpec | None = None,
) -> Iterator[tuple[Path, Language]]:
    """Yield (file_path, language) for every countable source file under root.

    Args:
        root: Project root directory.
        excluded_dirs: Relative directory paths to skip (e.g. {'static/external'}).
        gitignore_spec: Pre-loaded gitignore patterns. Loaded from root if None.
    """
    if gitignore_spec is None:
        gitignore_spec = load_gitignore(root)

    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir = dirpath.relative_to(root)

        # Prune excluded and gitignored subdirectories in-place
        filtered_dirs: list[str] = []
        for d in sorted(dirnames):
            # Skip hidden directories (e.g. .git, .venv)
            if d.startswith('.'):
                continue
            child_rel = str(rel_dir / d) if str(rel_dir) != '.' else d
            # Check config exclusions
            if child_rel in excluded_dirs:
                continue
            # Check gitignore (append / to match directory patterns)
            if gitignore_spec.match_file(child_rel + '/'):
                continue
            filtered_dirs.append(d)

        dirnames[:] = filtered_dirs

        # Yield recognized, non-binary files
        for filename in sorted(filenames):
            file_path = dirpath / filename
            # Skip files matched by gitignore
            file_rel = str(rel_dir / filename) if str(rel_dir) != '.' else filename
            if gitignore_spec.match_file(file_rel):
                continue

            language = identify_language(file_path)
            if language is None:
                continue

            if _is_binary(file_path):
                continue

            yield file_path, language
