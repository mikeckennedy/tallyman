"""Line counting and classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tallyman.languages import Language


@dataclass(slots=True)
class FileCount:
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0


def count_lines(path: Path, language: Language) -> FileCount:
    """Read a file and classify each line as blank, comment, or code.

    For languages with a single_line_comment marker, a line is a comment if
    the stripped line starts with that marker. For languages without one,
    comment_lines stays 0  -  we only distinguish blank from non-blank.

    Encoding errors are replaced to avoid crashes on non-UTF-8 files.
    """
    counts = FileCount()
    comment_marker = language.single_line_comment

    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return counts

    for line in text.splitlines():
        counts.total_lines += 1
        stripped = line.strip()

        if not stripped:
            counts.blank_lines += 1
        elif comment_marker is not None and stripped.startswith(comment_marker):
            counts.comment_lines += 1
        else:
            counts.code_lines += 1

    return counts
