"""File and directory walking with gitignore and config-based exclusions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pathspec

from tallyman.languages import Language, as_spec, identify_language

SPEC_DIR_NAMES: frozenset[str] = frozenset({'specs', 'specifications', 'plans', 'agents'})


def find_git_root(start: Path) -> Path | None:
    """Walk up from *start* looking for a directory containing ``.git``.

    Returns the git repo root, or None if not inside a git repository.
    """
    current = start.resolve()
    while True:
        if (current / '.git').exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


class GitIgnoreSpec:
    """Wraps a pathspec with an optional path prefix for subdirectory matching.

    When tallyman runs from a subdirectory of a git repo, gitignore patterns
    are relative to the repo root.  This wrapper transparently prepends the
    prefix so callers can keep using paths relative to the analysis directory.
    """

    def __init__(self, spec: pathspec.PathSpec, prefix: str = '') -> None:
        self._spec = spec
        self._prefix = prefix

    def match_file(self, path: str) -> bool:
        if self._prefix:
            full = f'{self._prefix}/{path}'
        else:
            full = path
        return self._spec.match_file(full)


def load_gitignore(root: Path) -> GitIgnoreSpec:
    """Load gitignore patterns, traversing up to find the git repo root.

    Collects patterns from:
    - ``<git-root>/.gitignore``
    - ``<git-root>/.git/info/exclude``
    - Any ``.gitignore`` in directories between the git root and *root*
    """
    git_root = find_git_root(root)
    lines: list[str] = []

    if git_root is None:
        # Not in a git repo  -  just check for a local .gitignore
        local_ignore = root / '.gitignore'
        if local_ignore.is_file():
            lines.extend(local_ignore.read_text(encoding='utf-8', errors='replace').splitlines())
        return GitIgnoreSpec(pathspec.PathSpec.from_lines('gitignore', lines))  # type: ignore[arg-type]

    # Load repo-root files
    for ignore_file in [git_root / '.gitignore', git_root / '.git' / 'info' / 'exclude']:
        if ignore_file.is_file():
            lines.extend(ignore_file.read_text(encoding='utf-8', errors='replace').splitlines())

    # Load intermediate .gitignore files between git root and analysis root
    if root.resolve() != git_root:
        rel = root.resolve().relative_to(git_root)
        current = git_root
        for part in rel.parts:
            current = current / part
            ignore_file = current / '.gitignore'
            if ignore_file.is_file():
                lines.extend(ignore_file.read_text(encoding='utf-8', errors='replace').splitlines())

    spec = pathspec.PathSpec.from_lines('gitignore', lines)  # type: ignore[arg-type]

    # Compute the prefix: path from git root to analysis root
    if root.resolve() != git_root:
        prefix = str(root.resolve().relative_to(git_root))
    else:
        prefix = ''

    return GitIgnoreSpec(spec, prefix)


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
        gitignore_spec: Pre-loaded gitignore patterns. Loaded from root if None.
        spec_dirs: Relative directory paths designated as spec directories.
    """
    if gitignore_spec is None:
        gitignore_spec = load_gitignore(root)

    active_spec_roots: set[str] = set(spec_dirs) if spec_dirs else set()

    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirpath = Path(dirpath_str)
        rel_dir = dirpath.relative_to(root)
        rel_dir_str = str(rel_dir) if str(rel_dir) != '.' else ''

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
            file_rel = str(rel_dir / filename) if str(rel_dir) != '.' else filename
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
