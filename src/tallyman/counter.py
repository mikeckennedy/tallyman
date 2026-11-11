"""Line counting and classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tallyman.encoding import text_encoding
from tallyman.languages import RUST, Language
from tallyman.rust_tests import rust_test_lines


@dataclass(slots=True)
class FileCount:
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    test_lines: int = 0  # Rust test code left out ([rust] exclude_test_modules); in none of the counts above


def count_lines(path: Path, language: Language, exclude_rust_tests: bool = False) -> FileCount:
    """Read a file and classify each line as blank, comment, or code.

    For languages with a single_line_comment marker, a line is a comment if
    the stripped line starts with that marker. For languages without one,
    comment_lines stays 0  -  we only distinguish blank from non-blank.

    Lines end at ``\\n``, ``\\r\\n`` or a lone ``\\r``, as an editor sees them;
    form feeds and other characters ``str.splitlines()`` would split on do not
    end a line. A final line without a newline still counts. A byte-order mark
    picks the encoding (so it never hides a comment on the first line), and
    undecodable bytes are replaced rather than crashing the run.

    With *exclude_rust_tests*, a Rust file's test-only code
    (:func:`tallyman.rust_tests.rust_test_lines`) is left out: those lines go
    to ``test_lines`` and nowhere else. Other languages ignore the flag.
    """
    counts = FileCount()
    comment_marker = language.single_line_comment

    try:
        data = path.read_bytes()
    except OSError:
        return counts

    text = data.decode(text_encoding(data[:4]), errors='replace')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()  # the text ended with a newline (or was empty): no line after it

    # The scanner gets the same normalised text that was split, so its line indexes match these
    test_lines = rust_test_lines(text) if exclude_rust_tests and language is RUST else frozenset()

    for index, line in enumerate(lines):
        if index in test_lines:
            counts.test_lines += 1
            continue
        counts.total_lines += 1
        stripped = line.strip()

        if not stripped:
            counts.blank_lines += 1
        elif comment_marker is not None and stripped.startswith(comment_marker):
            counts.comment_lines += 1
        else:
            counts.code_lines += 1

    return counts
