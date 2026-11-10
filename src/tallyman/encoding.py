"""Text encoding detection from a file's first bytes, shared by the walker and the counter."""

from __future__ import annotations

import codecs

# Byte-order marks, longest first: the UTF-32 LE mark begins with the UTF-16 LE one
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, 'utf-32'),
    (codecs.BOM_UTF32_BE, 'utf-32'),
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16'),
    (codecs.BOM_UTF16_BE, 'utf-16'),
)


def text_encoding(head: bytes) -> str:
    """Pick the encoding for a file from its first bytes: the one its BOM names, else UTF-8.

    A UTF-16 or UTF-32 file is full of NUL bytes, so callers must check for a
    BOM before treating NULs as a sign of binary content.
    """
    for bom, encoding in _BOMS:
        if head.startswith(bom):
            return encoding
    return 'utf-8'


def has_wide_bom(head: bytes) -> bool:
    """True if *head* starts with a UTF-16 or UTF-32 byte-order mark."""
    return any(head.startswith(bom) for bom, encoding in _BOMS if encoding != 'utf-8-sig')
