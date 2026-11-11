"""Gitignore rules, matched the way git matches them.

Git decides one directory entry at a time and never looks inside a directory
it has ignored. A pattern such as ``dist/`` therefore matches the ``dist``
entry itself, not the files beneath it; those are skipped only because the
walk never descends into ``dist``. General-purpose matchers that test whole
paths blur that distinction, which matters once several ``.gitignore`` files
and ``!`` negations combine, so the patterns are compiled here following
gitignore(5).

Known differences from git:

- Matching is always case-sensitive; git on a case-insensitive filesystem
  (``core.ignorecase``, the macOS default) is not.
- ``?`` and bracket expressions match one character; git matches one byte, so
  ``?`` does not match a multi-byte character such as ``é`` there.
- Git never ignores a file it already tracks. Tallyman can't see the index, so
  a force-added file under an ignored pattern is skipped.
- A ``.gitignore`` or ``info/exclude`` that isn't a regular file (or a symlink
  to one) is treated as absent; git opens it, and blocks on a FIFO.
- A worktree whose ``commondir`` file can't be read uses the ``info/exclude``
  in its own git directory; git refuses to run there.
- Only the repo's own ignore files are read: ``info/exclude`` and the
  ``.gitignore`` files. The global excludes file (``core.excludesFile``,
  by default ``~/.config/git/ignore``) is not, so counts don't depend on the
  machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tallyman.paths import relative_posix


def find_git_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a directory containing ``.git``.

    Returns the git repo root, or None if not inside a git repository.
    """
    current = start.resolve()
    while True:
        if _has_git(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _has_git(directory: Path) -> bool:
    """True if *directory* is a repository root: it holds a ``.git`` directory or file, valid or not."""
    return (directory / '.git').exists()


_MAX_PATH_FILE = 1 << 20  # git refuses a .git file larger than this


def _read_path_file(path: Path) -> Optional[str]:
    """The contents of a one-line file holding a path, without git's trailing ``\\n``/``\\r``, or None.

    Only a regular file of at most 1 MB is read, so a FIFO or a huge file can't stall the scan.
    Bytes that aren't UTF-8 are kept as surrogates, so the path still opens on POSIX.
    """
    try:
        if not path.is_file():
            return None
        with path.open('rb') as f:
            raw = f.read(_MAX_PATH_FILE + 1)
    except OSError:
        return None
    if len(raw) > _MAX_PATH_FILE:
        return None
    return raw.decode('utf-8', errors='surrogateescape').rstrip('\r\n')


def _git_dir(repo_root: Path) -> Optional[Path]:
    """The git directory of the repository at *repo_root*, or None if there is none to be found.

    ``.git`` is either that directory or, in worktrees and submodules, a file holding
    ``gitdir: <path>``, relative to *repo_root* unless absolute. A ``.git`` file without
    that exact prefix, over 1 MB, or naming a directory with no ``HEAD`` (the cheapest
    part of git's own check; ``gitdir: ..`` would otherwise read an ``info/exclude`` outside
    the repo) gives None. Git refuses to run in such a checkout. A ``.git`` directory is
    taken as it is, as :func:`find_git_root` takes any ``.git``.
    """
    dot_git = repo_root / '.git'
    if dot_git.is_dir():
        return dot_git
    contents = _read_path_file(dot_git)
    if contents is None or not contents.startswith('gitdir: '):
        return None  # git's prefix is case-sensitive, and the space is required
    target = contents.removeprefix('gitdir: ')
    if not target:
        return None
    git_dir = repo_root / target
    return git_dir if (git_dir / 'HEAD').exists() else None


def _info_exclude(repo_root: Path) -> Optional[Path]:
    """The ``info/exclude`` git reads for the repository at *repo_root*, or None.

    It lives in the common directory: the git directory itself, or, when that holds a
    ``commondir`` file, the directory named there (relative to the git directory unless
    absolute). Worktrees share the main repo's ``info/exclude`` that way, and git doesn't
    read one in a worktree's own git directory (checked against git 2.54). An unreadable
    ``commondir`` falls back to the git directory; git refuses to run then.
    """
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return None
    commondir = _read_path_file(git_dir / 'commondir')
    common = git_dir / commondir if commondir is not None else git_dir
    return common / 'info' / 'exclude'


@dataclass(frozen=True, slots=True)
class _Pattern:
    """One compiled line of a .gitignore file."""

    regex: re.Pattern[str]
    negate: bool  # '!pattern': re-include
    dir_only: bool  # 'pattern/': match directories only
    anchored: bool  # contains a '/': match the path relative to the .gitignore, not just the name

    def matches(self, rel: str, name: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        return self.regex.fullmatch(rel if self.anchored else name) is not None


# POSIX classes allowed inside a bracket expression, as regex set contents (ASCII, as in git)
_POSIX_CLASSES: dict[str, str] = {
    'alnum': 'a-zA-Z0-9',
    'alpha': 'a-zA-Z',
    'blank': r' \t',
    'cntrl': r'\x00-\x1f\x7f',
    'digit': '0-9',
    'graph': r'!-~',
    'lower': 'a-z',
    'print': r' -~',
    'punct': r'!-/:-@\[-`{-~',
    'space': r' \t\n\r\x0b\x0c',
    'upper': 'A-Z',
    'xdigit': '0-9A-Fa-f',
}


def _char_class(glob: str, start: int) -> Optional[tuple[str, int]]:
    """Translate the bracket expression at ``glob[start]``; return (regex, index after it).

    Returns None when the expression is invalid (unterminated, or an unknown
    ``[:class:]``). Git then treats the whole pattern as matching nothing.
    """
    i = start + 1
    negate = i < len(glob) and glob[i] in '!^'
    if negate:
        i += 1
    items: list[str] = []
    first = True
    while True:
        if i >= len(glob):
            return None  # unterminated
        c = glob[i]
        if c == ']' and not first:
            break
        first = False
        if glob.startswith('[:', i):
            close = glob.find(':]', i + 2)
            if close != -1:
                cls = _POSIX_CLASSES.get(glob[i + 2 : close])
                if cls is None:
                    return None
                items.append(cls)
                i = close + 2
                continue
        if c == '\\':
            i += 1
            if i >= len(glob):
                return None
            c = glob[i]
        i += 1
        if i + 1 < len(glob) and glob[i] == '-' and glob[i + 1] != ']':
            hi = glob[i + 1]
            i += 2
            if hi == '\\':
                if i >= len(glob):
                    return None
                hi = glob[i]
                i += 1
            if c <= hi:
                items.append(f'{re.escape(c)}-{re.escape(hi)}')
            else:
                items.append(re.escape(c))  # a reversed range matches only its first character, as in git
            continue
        items.append(re.escape(c))

    # A bracket expression never matches '/'
    if negate:
        regex = '[^/' + ''.join(items) + ']'
    else:
        regex = '(?!/)[' + ''.join(items) + ']' if items else '(?!)'
    return regex, i + 1


def _glob_to_regex(glob: str) -> Optional[str]:
    """Translate a gitignore glob (leading '/' already removed) into a regex for ``fullmatch``.

    Returns None if the glob is invalid, in which case it matches nothing.
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == '*':
            j = i
            while j < len(glob) and glob[j] == '*':
                j += 1
            at_segment_start = i == 0 or glob[i - 1] == '/'
            at_segment_end = j == len(glob) or glob[j] == '/'
            if j - i >= 2 and at_segment_start and at_segment_end:
                if j == len(glob):
                    out.append('.*')  # trailing '**': everything inside
                else:
                    out.append('(?:.*/)?')  # '**/': zero or more directories
                    j += 1
            else:
                out.append('[^/]*')  # '*', or '**' not bounded by slashes
            i = j
        elif c == '?':
            out.append('[^/]')
            i += 1
        elif c == '[':
            translated = _char_class(glob, i)
            if translated is None:
                return None
            regex, i = translated
            out.append(regex)
        elif c == '\\':
            if i + 1 == len(glob):
                return None  # a trailing unescaped backslash makes the whole pattern invalid in git
            out.append(re.escape(glob[i + 1]))
            i += 2
        else:
            out.append(re.escape(c))
            i += 1
    return ''.join(out)


def _trim_trailing_spaces(line: str) -> str:
    """Drop trailing spaces that aren't escaped, following git's ``trim_trailing_spaces()``.

    A backslash escapes exactly the next character, so in ``c\\\\ `` (an escaped backslash,
    then a space) the space is trailing and goes, while ``foo\\ `` keeps its escaped space.
    A line ending in a lone backslash is returned as it is; the glob then rejects it.
    """
    run_start: Optional[int] = None  # where the current run of unescaped spaces began
    i = 0
    while i < len(line):
        c = line[i]
        if c == ' ':
            if run_start is None:
                run_start = i
        else:
            if c == '\\':
                i += 1
                if i == len(line):
                    return line
            run_start = None
        i += 1
    return line if run_start is None else line[:run_start]


def _parse_line(line: str) -> Optional[_Pattern]:
    """Compile one .gitignore line, or return None for blanks, comments and patterns that can never match."""
    if not line or line.startswith('#'):
        return None
    line = _trim_trailing_spaces(line)

    negate = line.startswith('!')
    if negate:
        line = line[1:]

    dir_only = line.endswith('/')
    if dir_only:
        line = line[:-1]  # exactly one: 'd//' is not the same as 'd/'
    if not line:
        return None

    anchored = '/' in line
    regex = _glob_to_regex(line.removeprefix('/'))
    if regex is None:
        return None
    try:
        compiled = re.compile(regex)
    except re.error:
        return None  # a pattern tallyman can't translate must never take the scan down
    return _Pattern(compiled, negate, dir_only, anchored)


def _split_lines(text: str) -> list[str]:
    """Split like git: on '\\n' only, dropping one trailing '\\r' (str.splitlines() also splits on form feeds)."""
    return [line.removesuffix('\r') for line in text.split('\n')]


class _IgnoreFile:
    """The patterns from one ignore file."""

    def __init__(self, lines: list[str]) -> None:
        self._patterns = [p for p in map(_parse_line, lines) if p is not None]

    def decide(self, rel: str, is_dir: bool) -> Optional[bool]:
        """True if ignored, False if re-included, None if no pattern matches *rel*."""
        name = rel.rsplit('/', 1)[-1]
        for pattern in reversed(self._patterns):  # the last matching pattern wins
            if pattern.matches(rel, name, is_dir):
                return not pattern.negate
        return None


class GitIgnoreSpec:
    """Gitignore rules for one analysis root, scoped per directory the way git scopes them.

    Each ignore file applies only to entries beneath the directory that owns it,
    and its patterns are matched relative to that directory. When several files
    have an opinion on an entry, the deepest one wins, so a nested ``!pattern``
    can re-include what a parent ignored. ``info/exclude`` ranks below every
    ``.gitignore``, as in git.

    Callers pass paths relative to the analysis root, with a trailing ``/`` for
    directories. Like git, :meth:`match_file` judges only the entry itself and
    assumes its parent directories have already been checked, which is how
    :func:`tallyman.walker.walk_project` and the setup TUI use it: they never
    descend into an ignored directory. ``.gitignore`` files below the analysis
    root are registered with :meth:`add_directory` as the tree is walked, so an
    instance is bound to one analysis root and must not be reused for another.
    """

    def __init__(self, prefix: str = '', anchor: Optional[Path] = None) -> None:
        # Analysis root relative to the git root (POSIX), or '' when they are the same.
        self._prefix = prefix
        # The directory layer bases are relative to: the git root, or the analysis root outside a repo
        self._anchor = anchor
        self._files: list[tuple[str, _IgnoreFile]] = []
        self._loaded: set[tuple[str, str]] = set()
        self._ignore_all = False

    @classmethod
    def for_root(cls, root: Path) -> GitIgnoreSpec:
        """Build the rules that apply at *root*, traversing up to find the git repo root.

        Registers, in increasing precedence:
        - The repo's ``info/exclude`` (found through a ``.git`` file's ``gitdir:`` and
          ``commondir`` in worktrees and submodules)
        - ``<git-root>/.gitignore``
        - Any ``.gitignore`` in directories between the git root and *root*

        If any directory on the way down to *root* (or *root* itself) is ignored,
        everything under *root* is ignored, as git never looks inside an ignored
        directory. Outside a git repo, *root* plays the part of the git root.
        ``.gitignore`` files below *root* are registered as the walk descends.
        """
        resolved_root = root.resolve()
        git_root = find_git_root(resolved_root)

        if git_root is None:
            spec = cls(anchor=resolved_root)
            spec._add_file('', resolved_root / '.gitignore')
            return spec

        spec = cls(relative_posix(resolved_root, git_root), git_root)
        if (exclude := _info_exclude(git_root)) is not None:
            spec._add_file('', exclude)
        spec._add_file('', git_root / '.gitignore')

        current = git_root
        for part in resolved_root.relative_to(git_root).parts:
            current = current / part
            rel = relative_posix(current, git_root)
            if spec._is_ignored(rel, is_dir=True):
                spec._ignore_all = True
                break
            spec._add_file(rel, current / '.gitignore')

        return spec

    @classmethod
    def for_patterns(cls, root: Path) -> GitIgnoreSpec:
        """An empty spec for ``[exclude] patterns`` at *root*, filled with :meth:`add_rules`.

        It is kept apart from the gitignore spec, so a ``!pattern`` can only undo
        another config pattern. Nothing above *root* is ever checked, so a parent
        config's pattern can't exclude the directory the user asked to scan.
        """
        resolved_root = root.resolve()
        git_root = find_git_root(resolved_root)
        if git_root is None:
            return cls(anchor=resolved_root)
        return cls(relative_posix(resolved_root, git_root), git_root)

    def add_rules(self, config_dir: Path, lines: list[str]) -> None:
        """Register *lines* as one layer of rules scoped to *config_dir*, the way a .gitignore there would be.

        *config_dir* is the directory of the config that declares them: the
        analysis root, a directory above it inside the repo, or one below it.
        Registering the same directory twice is a no-op, and a directory outside
        the repo (or, outside a repo, outside the analysis root) is ignored.
        """
        if self._anchor is None:
            raise ValueError('add_rules() needs a spec from GitIgnoreSpec.for_patterns() or for_root()')
        resolved = config_dir.resolve()
        if not resolved.is_relative_to(self._anchor):
            return
        self._add_lines(relative_posix(resolved, self._anchor), '<config>', lines)

    def add_directory(self, rel_dir: str, dir_path: Path) -> None:
        """Register ``dir_path/.gitignore``, where *rel_dir* is its path relative to the analysis root.

        Missing or unreadable files are skipped, and registering the same directory twice is a no-op.
        """
        base = '/'.join(part for part in (self._prefix, rel_dir) if part)
        self._add_file(base, dir_path / '.gitignore')

    def match_file(self, path: str) -> bool:
        """Return True if the entry at *path* (relative to the analysis root) is ignored."""
        if not self._files and not self._ignore_all:
            return False  # nothing registered, the usual case for [exclude] patterns
        is_dir = path.endswith('/')
        rel = path.rstrip('/')
        full = f'{self._prefix}/{rel}' if self._prefix else rel
        return self._is_ignored(full, is_dir)

    def _add_file(self, base: str, ignore_file: Path) -> None:
        """Register *ignore_file*, scoped to *base* (relative to the git root).

        Only a regular file is read (``is_file()``, which follows a symlink), so a FIFO
        named ``.gitignore`` or ``info/exclude`` can't block the walk.
        """
        if (base, ignore_file.name) in self._loaded:
            return
        if not ignore_file.is_file():
            self._loaded.add((base, ignore_file.name))
            return  # missing, or not a regular file: treated as absent
        try:
            lines = _split_lines(ignore_file.read_bytes().decode('utf-8-sig', errors='replace'))
        except OSError:
            self._loaded.add((base, ignore_file.name))
            return  # missing or unreadable: git treats it as absent too
        self._add_lines(base, ignore_file.name, lines)

    def _add_lines(self, base: str, source: str, lines: list[str]) -> None:
        """Register *lines* from *source* as one layer scoped to *base* (relative to the git root)."""
        key = (base, source)
        if key in self._loaded:
            return
        self._loaded.add(key)
        self._files.append((base, _IgnoreFile(lines)))
        # Shallowest first; the sort is stable, so info/exclude stays ahead of the root .gitignore.
        self._files.sort(key=lambda item: item[0].count('/') + 1 if item[0] else 0)

    def _is_ignored(self, full: str, is_dir: bool) -> bool:
        """Judge one entry, given as a path relative to the git root."""
        if self._ignore_all:
            return True
        ignored = False
        for base, ignore_file in self._files:
            if base:
                if not full.startswith(base + '/'):
                    continue
                rel = full[len(base) + 1 :]
            else:
                rel = full
            decision = ignore_file.decide(rel, is_dir)
            if decision is not None:
                ignored = decision
        return ignored


def load_gitignore(root: Path) -> GitIgnoreSpec:
    """Load the gitignore rules that apply at *root*. See :meth:`GitIgnoreSpec.for_root`."""
    return GitIgnoreSpec.for_root(root)
