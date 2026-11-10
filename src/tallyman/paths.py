"""Path helpers shared by the walker, gitignore and config modules."""

from __future__ import annotations

import os
from pathlib import Path, PurePath


def relative_posix(path: PurePath, start: PurePath) -> str:
    """Return *path* relative to *start* as a ``/``-separated string.

    Returns ``''`` when the two paths are the same. Config files, gitignore
    patterns and the walker all compare relative paths as POSIX strings, so
    this must never produce a backslash, even on Windows.
    """
    rel = path.relative_to(start)
    return rel.as_posix() if rel.parts else ''


def canonical_case(path: Path) -> Path:
    """Return *path* with each component spelled the way the filesystem stores it.

    On a case-insensitive filesystem (the macOS default) ``proj/SRC`` and
    ``proj/src`` are the same directory, but ``Path.resolve()`` keeps whatever
    case was typed. Config and gitignore entries are matched as strings, so the
    real spelling matters. Components that can't be listed are kept as typed.
    """
    current = Path(path.parts[0])
    for part in path.parts[1:]:
        candidate = current / part
        spelled = part
        try:
            names = os.listdir(current)
            if part not in names:
                spelled = next(
                    (n for n in names if n.lower() == part.lower() and (current / n).samefile(candidate)), part
                )
        except OSError:
            pass
        current = current / spelled
    return current
