"""Line counting and classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tallyman.encoding import text_encoding
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

    Lines end at ``\\n``, ``\\r\\n`` or a lone ``\\r``, as an editor sees them;
    form feeds and other characters ``str.splitlines()`` would split on do not
    end a line. A final line without a newline still counts. A byte-order mark
    picks the encoding (so it never hides a comment on the first line), and
    undecodable bytes are replaced rather than crashing the run.
    """
    counts = FileCount()
    comment_marker = language.single_line_comment

    try:
        data = path.read_bytes()
    except OSError:
        return counts

    text = data.decode(text_encoding(data[:4]), errors='replace')
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines[-1] == '':
        lines.pop()  # the text ended with a newline (or was empty): no line after it

    for line in lines:
        counts.total_lines += 1
        stripped = line.strip()

        if not stripped:
            counts.blank_lines += 1
        elif comment_marker is not None and stripped.startswith(comment_marker):
            counts.comment_lines += 1
        else:
            counts.code_lines += 1

    return counts
