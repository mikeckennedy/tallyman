"""Path helpers shared by the walker, gitignore and config modules."""

from __future__ import annotations

from pathlib import PurePath


def relative_posix(path: PurePath, start: PurePath) -> str:
    """Return *path* relative to *start* as a ``/``-separated string.

    Returns ``''`` when the two paths are the same. Config files, gitignore
    patterns and the walker all compare relative paths as POSIX strings, so
    this must never produce a backslash, even on Windows.
    """
    rel = path.relative_to(start)
    return rel.as_posix() if rel.parts else ''
