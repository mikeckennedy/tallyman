"""Configuration file handling for .tally-config.toml."""

from __future__ import annotations

import os
import posixpath
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tallyman.gitignore import find_git_root
from tallyman.paths import relative_posix

CONFIG_FILENAME = '.tally-config.toml'

# A spec entry of '.' marks the config's own directory as a spec directory
SELF = '.'

# Backslash is a separator only on Windows; elsewhere it is a legal filename character
_WINDOWS = os.sep == '\\'


class ConfigError(Exception):
    """A .tally-config.toml that can't be read, isn't valid TOML, or has the wrong shape."""


@dataclass
class TallyConfig:
    """Parsed contents of .tally-config.toml.

    Entries are POSIX paths relative to the directory the config applies to.
    ``spec_dirs`` may contain ``'.'`` (:data:`SELF`), meaning that directory itself.
    """

    excluded_dirs: set[str] = field(default_factory=set)
    spec_dirs: set[str] = field(default_factory=set)


def find_config(root: Path) -> Optional[Path]:
    """Return the nearest .tally-config.toml at or above *root*, or None.

    Inside a git repo the search stops at the repo root, so a stray config in
    a home directory can't leak into every project. Outside a repo only
    *root* itself is checked.
    """
    current = root.resolve()
    stop = find_git_root(current) or current
    while True:
        config_path = current / CONFIG_FILENAME
        if config_path.is_file():
            return config_path
        if current == stop or current.parent == current:
            return None
        current = current.parent


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


def _directories(data: dict[str, Any], section: str, allow_self: bool) -> set[str]:
    """Read ``[section] directories`` as a set of normalised entries, validating its shape."""
    table = data.get(section, {})
    if not isinstance(table, dict):
        raise ConfigError(f'[{section}] must be a table')
    entries = table.get('directories', [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ConfigError(f'{section}.directories must be a list of strings')
    return {normalized for e in entries if (normalized := _normalize_dir(e, allow_self))}


def load_config(config_path: Path) -> TallyConfig:
    """Load a .tally-config.toml and return the configuration.

    Raises ConfigError if the file can't be read, isn't valid UTF-8 TOML, or has the wrong shape.
    """
    try:
        with config_path.open('rb') as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(e.strerror or str(e)) from e
    except (ValueError, RecursionError) as e:  # TOMLDecodeError and UnicodeDecodeError are both ValueErrors
        raise ConfigError(str(e) or type(e).__name__) from e
    return TallyConfig(
        excluded_dirs=_directories(data, 'exclude', allow_self=False),
        spec_dirs=_directories(data, 'specs', allow_self=True),
    )


def rebase_config(config: TallyConfig, config_dir: Path, root: Path) -> TallyConfig:
    """Translate a config that lives in *config_dir* so its paths are relative to *root*.

    *root* must be *config_dir* or a directory beneath it. Entries beneath
    *root* keep their path below it. An excluded entry that is *root* or one of
    its ancestors is dropped, because the user asked to scan this directory
    explicitly. A spec entry that is *root* or an ancestor becomes ``'.'``, so
    the whole scan counts as specs. Entries elsewhere point outside the scan and
    are dropped.
    """
    rel = relative_posix(root.resolve(), config_dir.resolve())
    if not rel:
        return TallyConfig(set(config.excluded_dirs), set(config.spec_dirs))

    def rebase(entries: set[str]) -> tuple[set[str], bool]:
        inside: set[str] = set()
        covers_root = False
        for entry in entries:
            if entry == SELF or entry == rel or rel.startswith(entry + '/'):
                covers_root = True
            elif entry.startswith(rel + '/'):
                inside.add(entry[len(rel) + 1 :])
        return inside, covers_root

    excluded, _ = rebase(config.excluded_dirs)
    specs, root_is_spec = rebase(config.spec_dirs)
    if root_is_spec:
        specs.add(SELF)
    return TallyConfig(excluded, specs)


def load_nested_config(config_file: Path, rel_dir: str) -> Optional[TallyConfig]:
    """Load a config found in the subdirectory *rel_dir*, with its entries prefixed by *rel_dir*.

    Returns None if the config is malformed: a broken config inside a scanned
    tree (often third-party code) must not stop the scan.
    """
    try:
        nested = load_config(config_file)
    except ConfigError:
        return None

    def prefix(entry: str) -> str:
        return rel_dir if entry == SELF else f'{rel_dir}/{entry}'

    return TallyConfig({prefix(e) for e in nested.excluded_dirs}, {prefix(e) for e in nested.spec_dirs})


def discover_nested_configs(root: Path) -> TallyConfig:
    """Scan subdirectories for .tally-config.toml and merge their settings.

    Paths from nested configs are translated to be relative to *root*.
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
        if config_file.is_file() and (nested := load_nested_config(config_file, rel_dir_str)) is not None:
            merged.excluded_dirs |= nested.excluded_dirs
            merged.spec_dirs |= nested.spec_dirs

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


def save_config(config_path: Path, excluded_dirs: set[str], spec_dirs: set[str]) -> None:
    """Write a .tally-config.toml file. Sorts directories for deterministic output.

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

    if spec_dirs:
        lines.append('')
        lines.append('[specs]')
        lines.append('directories = [')
        for d in sorted(spec_dirs):
            lines.append(f'    {_toml_string(d)},')
        lines.append(']')

    lines.append('')
    config_path.write_text('\n'.join(lines), encoding='utf-8')
