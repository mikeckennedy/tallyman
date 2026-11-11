"""Find test-only Rust code: items under ``#[cfg(test)]``, and files or modules under ``#![cfg(test)]``.

:func:`rust_test_lines` is the whole interface. It works on text that is
already decoded and newline-normalised, as :func:`tallyman.counter.count_lines`
splits it, and returns the indexes of the lines to leave out.

This is not a Rust parser. It lexes just enough to know which brackets are
real (skipping strings, raw strings, char literals and nested block comments),
then walks the items of each *item container* (the file, and the bodies of
``mod``, ``impl``, ``trait`` and ``extern`` blocks). An item with a test-only
``cfg`` attribute is dropped from its first attribute or doc comment to its
end. Attributes anywhere else (statements, fields, variants, match arms) are
left alone. When the text can't be followed (an unterminated string or
comment, brackets that don't balance), nothing is dropped: the scanner may
miss test code, but it must never drop real code.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from typing import NamedTuple

# Token kinds
_IDENT = 'ident'
_PUNCT = 'punct'
_OPEN = 'open'
_CLOSE = 'close'
_LITERAL = 'literal'  # strings, chars, numbers, lifetimes and labels
_COMMENT = 'comment'
_OUTER_DOC = 'outer-doc'  # /// and /** */: an attribute of the item that follows
_INNER_DOC = 'inner-doc'  # //! and /*! */: an attribute of the enclosing container

_NOT_CODE = frozenset({_COMMENT, _OUTER_DOC, _INNER_DOC})
_PAIRS = {')': '(', ']': '[', '}': '{'}

# Item kinds whose body is a list of items, so the attributes inside it can drop code too
_CONTAINER_KINDS = frozenset({'mod', 'impl', 'trait', 'extern'})
# Item kinds that end only at ';', even with a '{' on the way (`use a::{b, c};`, `const X: S = S { a: 1 };`)
_SEMICOLON_KINDS = frozenset({'use', 'const', 'static', 'type', 'extern crate'})
# Words that can come before an item's keyword; 'const' and 'extern' are handled separately
_MODIFIERS = frozenset({'unsafe', 'safe', 'async', 'default', 'auto'})
# After 'const', a keyword makes it a modifier (`const fn`, `const unsafe fn`, nightly's `const trait`/`const impl`);
# only a name or '_' makes it a const item, which ends at ';'
_KEYWORDS = frozenset({
    'as', 'async', 'auto', 'await', 'break', 'const', 'continue', 'crate', 'default', 'dyn', 'else', 'enum', 'extern',
    'false', 'fn', 'for', 'if', 'impl', 'in', 'let', 'loop', 'macro_rules', 'match', 'mod', 'move', 'mut', 'pub', 'ref',
    'return', 'safe', 'self', 'static', 'struct', 'super', 'trait', 'true', 'type', 'union', 'unsafe', 'use', 'where',
    'while',
})  # fmt: skip
_EXTERN_FN_FOLLOWERS = frozenset({'fn', 'unsafe', 'safe', 'async', 'const'})

_WHITESPACE = re.compile(r'[\s\ufeff]+')
_IDENTIFIER = re.compile(r'(?:r#)?[^\W\d]\w*')
_NUMBER = re.compile(r'\d\w*')
_RAW_STRING_START = re.compile(r'(?:br|cr|r)(#*)"')
_STRING = re.compile(r'(?:b|c)?"[^"\\]*(?:\\.[^"\\]*)*"', re.DOTALL)
_STRING_START = re.compile(r'(?:b|c)?"')
_CHAR_ESCAPE = re.compile(r"'\\(?:u\{[0-9A-Fa-f_]*\}|x[0-9A-Fa-f]{2}|[^\n])'")
_LIFETIME = re.compile(r"'(?:r#)?[^\W\d]\w*")
_BLOCK_COMMENT_MARK = re.compile(r'/\*|\*/')
_SHEBANG_ATTRIBUTE = re.compile(r'#!\s*\[')


class _Unclear(Exception):
    """The text isn't Rust the scanner can follow, so the file is counted in full."""


class _BadPredicate(Exception):
    """A cfg predicate the scanner doesn't understand: not test-only."""


class _Token(NamedTuple):
    kind: str
    start: int
    end: int
    text: str


def rust_test_lines(text: str) -> frozenset[int]:
    """0-based indexes of the lines in *text* that belong to test-only Rust code.

    *text* must use only ``\\n`` between lines. The indexes match
    ``text.split('\\n')``, without the empty string after a final newline.
    An empty result means "count everything", which is also the answer for
    any text the scanner can't follow. Never raises.
    """
    if 'cfg' not in text or 'test' not in text:
        return frozenset()  # the common case: no attribute could be test-only
    try:
        tokens = _tokenize(text)
        scan = _Scan([t for t in tokens if t.kind != _COMMENT])
        whole_file = scan.container(0, len(scan.tokens))
    except _Unclear:
        return frozenset()
    except RecursionError:  # brackets nested thousands deep: not worth following
        return frozenset()
    if whole_file:
        return frozenset(range(_line_count(text)))
    if not scan.regions:
        return frozenset()
    return _lines_in_regions(text, tokens, scan.regions)


def _line_count(text: str) -> int:
    """How many lines ``count_lines()`` sees in *text*."""
    lines = text.count('\n') + 1
    return lines - 1 if text.endswith('\n') or not text else lines


def _tokenize(text: str) -> list[_Token]:
    """Split *text* into tokens, comments included. Raises _Unclear on an unterminated literal or comment."""
    tokens: list[_Token] = []
    append = tokens.append
    n = len(text)
    i = 0

    # A shebang is a comment line, unless the file starts with an inner attribute (`#![...]`)
    if text.startswith('#!') and not _SHEBANG_ATTRIBUTE.match(text):
        end = text.find('\n')
        i = n if end == -1 else end
        append(_Token(_COMMENT, 0, i, text[:i]))

    while i < n:
        c = text[i]

        if c.isspace() or c == '\ufeff':
            m = _WHITESPACE.match(text, i)
            i = m.end() if m else i + 1
            continue

        if c == '/' and text.startswith('//', i):
            end = text.find('\n', i)
            end = n if end == -1 else end
            body = text[i:end]
            if body.startswith('///') and not body.startswith('////'):
                kind = _OUTER_DOC
            elif body.startswith('//!'):
                kind = _INNER_DOC
            else:
                kind = _COMMENT
            append(_Token(kind, i, end, body))
            i = end
            continue

        if c == '/' and text.startswith('/*', i):
            end = _block_comment_end(text, i)
            body = text[i:end]
            if body.startswith('/**') and not body.startswith('/***') and body != '/**/':
                kind = _OUTER_DOC
            elif body.startswith('/*!'):
                kind = _INNER_DOC
            else:
                kind = _COMMENT
            append(_Token(kind, i, end, body))
            i = end
            continue

        if c in 'rbc':
            m = _RAW_STRING_START.match(text, i)
            if m:
                closing = '"' + m.group(1)
                found = text.find(closing, m.end())
                if found == -1:
                    raise _Unclear
                end = found + len(closing)
                append(_Token(_LITERAL, i, end, text[i:end]))
                i = end
                continue

        if c == '"' or (c in 'bc' and _STRING_START.match(text, i)):
            m = _STRING.match(text, i)
            if not m:
                raise _Unclear
            append(_Token(_LITERAL, i, m.end(), m.group()))
            i = m.end()
            continue

        if c == "'" or (c == 'b' and text.startswith("b'", i)):
            quote = i if c == "'" else i + 1
            end = _char_or_lifetime_end(text, quote, allow_lifetime=c == "'")
            append(_Token(_LITERAL, i, end, text[i:end]))
            i = end
            continue

        if c.isdigit():
            m = _NUMBER.match(text, i)
            end = m.end() if m else i + 1
            append(_Token(_LITERAL, i, end, text[i:end]))
            i = end
            continue

        m = _IDENTIFIER.match(text, i)
        if m:
            append(_Token(_IDENT, i, m.end(), m.group()))
            i = m.end()
            continue

        if c in '([{':
            append(_Token(_OPEN, i, i + 1, c))
        elif c in ')]}':
            append(_Token(_CLOSE, i, i + 1, c))
        else:
            append(_Token(_PUNCT, i, i + 1, c))
        i += 1

    return tokens


def _block_comment_end(text: str, start: int) -> int:
    """End of the block comment opening at *start*. Block comments nest."""
    depth = 0
    for m in _BLOCK_COMMENT_MARK.finditer(text, start):
        depth += 1 if m.group() == '/*' else -1
        if depth == 0:
            return m.end()
    raise _Unclear


def _char_or_lifetime_end(text: str, quote: int, allow_lifetime: bool) -> int:
    """End of the char literal or lifetime whose ``'`` is at *quote*.

    A char literal is an escape (``'\\n'``, ``'\\u{7B}'``) or one character
    between quotes. Anything else after ``'`` is a lifetime or label
    (``'a``, ``'static``, ``'outer:``), which a byte literal (``b'``) can't be.
    """
    if text.startswith('\\', quote + 1):
        m = _CHAR_ESCAPE.match(text, quote)
        if not m:
            raise _Unclear
        return m.end()
    if quote + 2 < len(text) and text[quote + 2] == "'" and text[quote + 1] != '\n':
        return quote + 3
    if allow_lifetime:
        m = _LIFETIME.match(text, quote)
        if m:
            return m.end()
    raise _Unclear


class _Scan:
    """Walks the item containers of a token list, collecting the regions to drop."""

    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.regions: list[tuple[int, int]] = []  # character ranges, end exclusive
        self.match = _match_brackets(tokens)

    def container(self, i: int, end: int) -> bool:
        """Scan the items in ``tokens[i:end]``. True if an inner attribute makes the whole container test-only."""
        tokens = self.tokens
        at_start = True  # inner attributes may only come before the first item
        test_container = False
        while i < end:
            item_start = -1
            test = False
            # The item's attributes and doc comments
            while i < end:
                token = tokens[i]
                if token.kind == _INNER_DOC:
                    i += 1
                    continue
                if token.kind == _OUTER_DOC:
                    at_start = False
                    if item_start < 0:
                        item_start = token.start
                    i += 1
                    continue
                if token.kind == _PUNCT and token.text == '#':
                    j = i + 1
                    inner = j < end and tokens[j].kind == _PUNCT and tokens[j].text == '!'
                    if inner:
                        j += 1
                    if j < end and tokens[j].kind == _OPEN and tokens[j].text == '[':
                        close = self.match[j]
                        is_test = self._test_only_attribute(j + 1, close)
                        if inner:
                            test_container = test_container or (at_start and is_test)
                        else:
                            at_start = False
                            if item_start < 0:
                                item_start = token.start
                            test = test or is_test
                        i = close + 1
                        continue
                break
            if i >= end:
                break  # attributes with no item after them
            at_start = False
            if item_start < 0:
                item_start = tokens[i].start
            last, inner_test = self._item(i, end)
            if last < 0:
                if test:
                    raise _Unclear  # a test item with no end: don't guess how much to drop
                break
            if test or inner_test:
                self.regions.append((item_start, tokens[last].end))
            i = last + 1
        return test_container

    def _item(self, i: int, end: int) -> tuple[int, bool]:
        """The index of the last token of the item starting at *i*, or -1 if it runs to *end* unfinished.

        Also says whether an inner attribute made the item's body test-only.
        """
        tokens = self.tokens
        kind = self._kind(i, end)
        j = i
        while j < end:
            token = tokens[j]
            if token.kind == _OPEN:
                close = self.match[j]
                if token.text == '{' and kind not in _SEMICOLON_KINDS:
                    inner_test = kind in _CONTAINER_KINDS and self.container(j + 1, close)
                    return close, inner_test
                j = close + 1
                continue
            if token.kind == _PUNCT and token.text == ';':
                return j, False
            j += 1
        return -1, False

    def _kind(self, i: int, end: int) -> str:
        """The item's keyword after its modifiers: 'fn' for ``pub(crate) const unsafe fn``, 'extern' for a block."""
        tokens = self.tokens
        j = i
        while j < end and tokens[j].kind == _IDENT:
            word = tokens[j].text
            following = tokens[j + 1] if j + 1 < end else None
            following_word = following.text if following is not None and following.kind == _IDENT else ''
            if word == 'pub':
                j += 1
                if following is not None and following.kind == _OPEN and following.text == '(':
                    j = self.match[j] + 1
                continue
            if word in _MODIFIERS and following_word:
                j += 1
                continue
            # A wrong semicolon kind drops the real items up to the next ';', while a wrong brace kind only misses
            # test code, so 'const' is a const item only when a name or '_' follows it
            if word == 'const' and following_word in _KEYWORDS:
                j += 1
                continue
            if word == 'extern':
                k = j + 1
                if k < end and tokens[k].kind == _LITERAL:
                    k += 1  # the ABI string
                after = tokens[k].text if k < end and tokens[k].kind == _IDENT else ''
                if after == 'crate':
                    return 'extern crate'
                if after in _EXTERN_FN_FOLLOWERS:
                    j = k
                    continue
                return 'extern'
            return word
        return ''

    def _test_only_attribute(self, i: int, end: int) -> bool:
        """True if ``tokens[i:end]``, an attribute's body, is ``cfg(<test-only predicate>)``."""
        tokens = self.tokens
        if end - i < 3:
            return False
        name, paren = tokens[i], tokens[i + 1]
        if name.kind != _IDENT or name.text != 'cfg' or paren.kind != _OPEN or paren.text != '(':
            return False
        if self.match[i + 1] != end - 1:
            return False  # something after cfg(...)
        try:
            value, after = self._predicate(i + 2, end - 1)
        except _BadPredicate:
            return False
        if after == end - 2 and tokens[after].kind == _PUNCT and tokens[after].text == ',':
            after += 1  # cfg(test,) is valid Rust
        return value and after == end - 1

    def _predicate(self, i: int, end: int) -> tuple[bool, int]:
        """Parse the cfg predicate at *i*: whether it is test-only, and the index after it.

        ``test`` is test-only; ``all(...)`` is when any argument is; ``any(...)``
        is when every argument is; ``not(...)``, ``key = "value"`` and other
        names never are.
        """
        tokens = self.tokens
        if i >= end or tokens[i].kind != _IDENT:
            raise _BadPredicate
        name = tokens[i].text
        j = i + 1
        if j < end and tokens[j].kind == _PUNCT and tokens[j].text == '=':
            if j + 1 < end and tokens[j + 1].kind == _LITERAL:
                return False, j + 2
            raise _BadPredicate
        if j < end and tokens[j].kind == _OPEN and tokens[j].text == '(':
            close = self.match[j]
            args = self._arguments(j + 1, close)
            if name == 'all':
                return any(args), close + 1
            if name == 'any':
                return bool(args) and all(args), close + 1
            return False, close + 1
        return name == 'test', j

    def _arguments(self, i: int, end: int) -> list[bool]:
        """Parse a comma-separated list of predicates in ``tokens[i:end]``; a trailing comma is fine."""
        tokens = self.tokens
        values: list[bool] = []
        while i < end:
            value, i = self._predicate(i, end)
            values.append(value)
            if i < end:
                if tokens[i].kind != _PUNCT or tokens[i].text != ',':
                    raise _BadPredicate
                i += 1
        return values


def _match_brackets(tokens: list[_Token]) -> dict[int, int]:
    """Map each opening bracket's index to its closing bracket's. Raises _Unclear if they don't balance."""
    match: dict[int, int] = {}
    stack: list[int] = []
    for index, token in enumerate(tokens):
        if token.kind == _OPEN:
            stack.append(index)
        elif token.kind == _CLOSE:
            if not stack or tokens[stack[-1]].text != _PAIRS[token.text]:
                raise _Unclear
            match[stack.pop()] = index
    if stack:
        raise _Unclear
    return match


def _lines_in_regions(text: str, tokens: list[_Token], regions: list[tuple[int, int]]) -> frozenset[int]:
    """The lines that overlap *regions* and have no code outside them (comments outside are fine)."""
    newlines = [m.start() for m in re.finditer('\n', text)]

    def line_of(position: int) -> int:
        return bisect_left(newlines, position)

    merged: list[list[int]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    starts = [start for start, _ in merged]

    candidates: set[int] = set()
    for start, end in merged:
        candidates.update(range(line_of(start), line_of(end - 1) + 1))

    for token in tokens:
        if token.kind in _NOT_CODE:
            continue
        k = bisect_right(starts, token.start) - 1
        if k >= 0 and token.start < merged[k][1]:
            continue  # inside a region
        first, last = line_of(token.start), line_of(token.end - 1)
        if first == last:
            candidates.discard(first)
        else:  # a multi-line string outside every region: each of its lines holds code
            candidates.difference_update(range(first, last + 1))
    return frozenset(candidates)
