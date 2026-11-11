"""Configuration file handling for .tally-config.toml."""

from __future__ import annotations

import os
import posixpath
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tallyman.encoding import text_encoding
from tallyman.gitignore import find_git_root
from tallyman.paths import relative_posix

CONFIG_FILENAME = '.tally-config.toml'

# A spec entry of '.' marks the config's own directory as a spec directory
SELF = '.'

# Backslash is a separator only on Windows; elsewhere it is a legal filename character
_WINDOWS = os.sep == '\\'

# One config's [exclude] patterns, with the directory they are relative to
PatternLayer = tuple[Path, list[str]]


class ConfigError(Exception):
    """A .tally-config.toml that can't be read, isn't valid TOML, or has the wrong shape.

    ``path`` is the offending file, set by :func:`load_config`.
    """

    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.path = path


@dataclass
class TallyConfig:
    """Parsed contents of .tally-config.toml.

    Entries are POSIX paths relative to the directory the config applies to.
    ``spec_dirs`` and ``non_spec_dirs`` may contain ``'.'`` (:data:`SELF`),
    meaning that directory itself. ``non_spec_dirs`` (``[specs] ignore``) turns
    off spec classification for a directory and its descendants, including
    auto-detection by name; a deeper ``spec_dirs`` entry still wins.

    ``patterns`` (``[exclude] patterns``) are gitignore-style lines in file
    order, relative to the config's own directory. They stay attached to the
    file they came from, so the functions that move or combine entries
    (:func:`rebase_config`, :func:`prefixed`, :func:`merge_configs`,
    :func:`without_inherited`) return none; see :class:`ConfigChain`.
    """

    excluded_dirs: set[str] = field(default_factory=set)
    spec_dirs: set[str] = field(default_factory=set)
    non_spec_dirs: set[str] = field(default_factory=set)
    patterns: list[str] = field(default_factory=list)


def find_configs(root: Path) -> list[Path]:
    """Return every .tally-config.toml from the search stop down to *root*, shallowest first.

    Inside a git repo the search stops at the repo root, so a stray config in
    a home directory can't leak into every project. Outside a repo only
    *root* itself is checked.
    """
    current = root.resolve()
    stop = find_git_root(current) or current
    found: list[Path] = []
    while True:
        config_path = current / CONFIG_FILENAME
        if config_path.is_file():
            found.append(config_path)
        if current == stop or current.parent == current:
            break
        current = current.parent
    found.reverse()
    return found


def _normalize_dir(entry: str, allow_self: bool) -> str:
    """Normalise a hand-edited directory entry, or return '' to drop it.

    Separators become '/', './' and '..' segments are resolved, and leading and
    trailing slashes go. Entries that climb out of the config's directory are
    dropped. The directory itself (``'.'``) is kept only where *allow_self*.
    """
    if _WINDOWS:
        entry = entry.replace('\\', '/')
    if not entry.strip('/'):
        return ''
    entry = posixpath.normpath(entry.strip('/'))
    if entry == '..' or entry.startswith('../'):
        return ''
    if entry == SELF:
        return SELF if allow_self else ''
    return entry


def _directories(data: dict[str, Any], section: str, key: str, allow_self: bool) -> set[str]:
    """Read ``[section] key`` as a set of normalised directory entries, validating its shape."""
    table = data.get(section, {})
    if not isinstance(table, dict):
        raise ConfigError(f'[{section}] must be a table')
    entries = table.get(key, [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ConfigError(f'{section}.{key} must be a list of strings')
    return {normalized for e in entries if (normalized := _normalize_dir(e, allow_self))}


def _patterns(data: dict[str, Any]) -> list[str]:
    """Read ``[exclude] patterns`` as written. Gitignore syntax gives slashes and backslashes their meaning."""
    table = data.get('exclude', {})
    if not isinstance(table, dict):
        raise ConfigError('[exclude] must be a table')
    patterns = table.get('patterns', [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ConfigError('exclude.patterns must be a list of strings')
    return list(patterns)


def load_config(config_path: Path) -> TallyConfig:
    """Load a .tally-config.toml and return the configuration.

    A UTF-8, UTF-16 or UTF-32 byte-order mark picks the encoding, as it does for
    source files; without one the file must be UTF-8.

    Raises ConfigError, with ``path`` set to *config_path*, if the file can't be
    read or decoded, isn't valid TOML, or has the wrong shape.
    """
    try:
        raw = config_path.read_bytes()
    except OSError as e:
        raise ConfigError(e.strerror or str(e), config_path) from e
    try:
        data = tomllib.loads(raw.decode(text_encoding(raw[:4])))
    except (ValueError, RecursionError) as e:  # TOMLDecodeError and UnicodeDecodeError are both ValueErrors
        raise ConfigError(str(e) or type(e).__name__, config_path) from e
    try:
        return TallyConfig(
            excluded_dirs=_directories(data, 'exclude', 'directories', allow_self=False),
            spec_dirs=_directories(data, 'specs', 'directories', allow_self=True),
            non_spec_dirs=_directories(data, 'specs', 'ignore', allow_self=True),
            patterns=_patterns(data),
        )
    except ConfigError as e:
        e.path = config_path
        raise


def merge_configs(shallow: TallyConfig, deep: TallyConfig) -> TallyConfig:
    """Combine two configs whose entries share a base directory; *deep* came from the deeper file.

    Exclusions add up. When both configs name the same path, one as specs and
    the other as ignored, the deeper config wins. Entries on different paths
    are left to the walker's rule that the deepest entry wins.
    """
    return TallyConfig(
        shallow.excluded_dirs | deep.excluded_dirs,
        (shallow.spec_dirs - deep.non_spec_dirs) | deep.spec_dirs,
        (shallow.non_spec_dirs - deep.spec_dirs) | deep.non_spec_dirs,
    )


def prefixed(config: TallyConfig, rel_dir: str) -> TallyConfig:
    """*config*, which lives in the directory *rel_dir*, with its entries made relative to that directory's base."""
    if not rel_dir:
        return TallyConfig(set(config.excluded_dirs), set(config.spec_dirs), set(config.non_spec_dirs))

    def prefix(entry: str) -> str:
        return rel_dir if entry == SELF else f'{rel_dir}/{entry}'

    return TallyConfig(
        {prefix(e) for e in config.excluded_dirs},
        {prefix(e) for e in config.spec_dirs},
        {prefix(e) for e in config.non_spec_dirs},
    )


def without_inherited(local: TallyConfig, inherited: TallyConfig) -> TallyConfig:
    """*local* minus entries that *inherited* already has in the same set, so each setting lives in one file.

    A path that *local* lists as both specs and ignored (a contradictory hand
    edit) keeps both entries, so dropping one can't change which of them wins.
    """
    contradictory = local.spec_dirs & local.non_spec_dirs
    return TallyConfig(
        local.excluded_dirs - inherited.excluded_dirs,
        local.spec_dirs - (inherited.spec_dirs - contradictory),
        local.non_spec_dirs - (inherited.non_spec_dirs - contradictory),
    )


def rebase_config(config: TallyConfig, config_dir: Path, root: Path) -> TallyConfig:
    """Translate a config that lives in *config_dir* so its paths are relative to *root*.

    *root* must be *config_dir* or a directory beneath it. Entries beneath
    *root* keep their path below it. An excluded entry that is *root* or one of
    its ancestors is dropped, because the user asked to scan this directory
    explicitly. Spec and ignore entries that are *root* or an ancestor become
    ``'.'`` in the matching set; when both kinds cover *root*, the deeper one
    wins, as it does in the walker. Entries elsewhere point outside the scan and
    are dropped.
    """
    rel = relative_posix(root.resolve(), config_dir.resolve())
    if not rel:
        return TallyConfig(set(config.excluded_dirs), set(config.spec_dirs), set(config.non_spec_dirs))

    def depth(entry: str) -> int:
        return 0 if entry == SELF else entry.count('/') + 1

    def rebase(entries: set[str]) -> tuple[set[str], Optional[int]]:
        """Entries below *root*, re-rooted; plus the depth of the deepest entry covering *root*, if any."""
        inside: set[str] = set()
        cover: Optional[int] = None
        for entry in entries:
            if entry == SELF or entry == rel or rel.startswith(entry + '/'):
                cover = depth(entry) if cover is None else max(cover, depth(entry))
            elif entry.startswith(rel + '/'):
                inside.add(entry[len(rel) + 1 :])
        return inside, cover

    excluded, _ = rebase(config.excluded_dirs)
    specs, spec_cover = rebase(config.spec_dirs)
    non_specs, non_spec_cover = rebase(config.non_spec_dirs)
    if spec_cover is not None and (non_spec_cover is None or spec_cover >= non_spec_cover):
        specs.add(SELF)
    elif non_spec_cover is not None:
        non_specs.add(SELF)
    return TallyConfig(excluded, specs, non_specs)


def load_nested_config(config_file: Path, rel_dir: str) -> Optional[tuple[TallyConfig, list[str]]]:
    """Load a config found in the subdirectory *rel_dir*: its entries prefixed by *rel_dir*, and its patterns.

    The patterns are returned as written, relative to the config's own
    directory. Returns None if the config is malformed: a broken config inside
    a scanned tree (often third-party code) must not stop the scan.
    """
    try:
        config = load_config(config_file)
    except ConfigError:
        return None
    return prefixed(config, rel_dir), config.patterns


@dataclass
class ConfigChain:
    """The configs that apply at a scan root: every one from the git root down to it.

    ``inherited`` merges the configs above the scan root, rebased onto it. They
    are shown locked in setup and stay in their own files. ``local`` is the
    scan root's own config, the one setup edits, patterns included. ``paths``
    lists the files that loaded, shallowest first, and ``pattern_layers`` the
    patterns of each one that has any, in the same order.
    """

    inherited: TallyConfig = field(default_factory=TallyConfig)
    local: TallyConfig = field(default_factory=TallyConfig)
    paths: list[Path] = field(default_factory=list)
    pattern_layers: list[PatternLayer] = field(default_factory=list)

    @property
    def effective(self) -> TallyConfig:
        """What the walker applies: the inherited settings, overridden by the local ones."""
        return merge_configs(self.inherited, self.local)


def load_config_chain(
    paths: list[Path], root: Path, on_error: Optional[Callable[[ConfigError], None]] = None
) -> ConfigChain:
    """Load *paths* (from :func:`find_configs`, shallowest first) as they apply at *root*.

    Each config above *root* is made relative to the shallowest one's directory
    and merged shallow to deep, so a deeper config wins on the same path; the
    result is then rebased onto *root*. A malformed file raises ConfigError,
    unless *on_error* is given: it is then called with the error and the file is
    skipped.
    """
    root = root.resolve()
    chain = ConfigChain()
    if not paths:
        return chain
    top = paths[0].parent.resolve()
    merged = TallyConfig()
    for path in paths:
        try:
            config = load_config(path)
        except ConfigError as e:
            if on_error is None:
                raise
            on_error(e)
            continue
        chain.paths.append(path)
        config_dir = path.parent.resolve()
        if config.patterns:
            chain.pattern_layers.append((config_dir, config.patterns))
        if config_dir == root:
            chain.local = config
        else:
            merged = merge_configs(merged, prefixed(config, relative_posix(config_dir, top)))
    chain.inherited = rebase_config(merged, top, root)
    return chain


def discover_nested_configs(root: Path, pattern_layers: Optional[list[PatternLayer]] = None) -> TallyConfig:
    """Scan subdirectories for .tally-config.toml and merge their settings.

    If *pattern_layers* is given, each nested config's patterns are appended to
    it, shallowest first.

    Paths from nested configs are translated to be relative to *root*, and a
    deeper config wins on the same path, as in :func:`merge_configs`.
    Only non-root configs are considered (the root config is loaded separately).
    Hidden directories are skipped for performance.
    """
    merged = TallyConfig()

    for dirpath_str, dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
        # Skip hidden directories (e.g. .git, .venv)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))

        dirpath = Path(dirpath_str)
        rel_dir_str = relative_posix(dirpath, root)
        if not rel_dir_str:
            continue

        config_file = dirpath / CONFIG_FILENAME
        if config_file.is_file() and (loaded := load_nested_config(config_file, rel_dir_str)) is not None:
            nested, patterns = loaded
            # Top-down, so an ancestor's config is merged before a descendant's and the deeper one wins
            merged = merge_configs(merged, nested)
            if pattern_layers is not None and patterns:
                pattern_layers.append((dirpath, patterns))

    return merged


def _toml_string(value: str) -> str:
    """Quote *value* as a TOML basic string, escaping backslashes, quotes and control characters."""
    out: list[str] = []
    for ch in value:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch < ' ' or ch == '\x7f':
            out.append(f'\\u{ord(ch):04x}')
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def save_config(
    config_path: Path,
    excluded_dirs: set[str],
    spec_dirs: set[str],
    non_spec_dirs: Optional[set[str]] = None,
    patterns: Sequence[str] = (),
) -> None:
    """Write a .tally-config.toml file. Sorts directories for deterministic output.

    *patterns* are written in the order given, since a later ``!pattern`` can
    undo an earlier one. Setup passes the loaded config's patterns through.

    Raises OSError if the file can't be written, and UnicodeEncodeError if a
    directory name isn't valid Unicode (possible on Linux, never on macOS).
    """
    lines = [
        '# Generated by tallyman. Edit manually or re-run: tallyman --setup',
        '',
        '[exclude]',
        'directories = [',
    ]
    for d in sorted(excluded_dirs):
        lines.append(f'    {_toml_string(d)},')
    lines.append(']')
    if patterns:
        lines.append("# Gitignore-style patterns, relative to this file's directory")
        lines.append('patterns = [')
        for pattern in patterns:
            lines.append(f'    {_toml_string(pattern)},')
        lines.append(']')

    if spec_dirs or non_spec_dirs:
        lines.append('')
        lines.append('[specs]')
        lines.append('directories = [')
        for d in sorted(spec_dirs):
            lines.append(f'    {_toml_string(d)},')
        lines.append(']')
        if non_spec_dirs:
            lines.append('# Not specs, even if named specs/plans/specifications/agents')
            lines.append('ignore = [')
            for d in sorted(non_spec_dirs):
                lines.append(f'    {_toml_string(d)},')
            lines.append(']')

    lines.append('')
    config_path.write_text('\n'.join(lines), encoding='utf-8')
