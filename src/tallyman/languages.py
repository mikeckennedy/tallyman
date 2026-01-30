"""Language registry — maps file extensions to language metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Language:
    name: str
    category: str  # 'code', 'design', 'docs', 'data'
    color: str  # Rich color name
    single_line_comment: str | None  # e.g. '#', '//', '--'; None if no simple detection
    extensions: tuple[str, ...]


# fmt: off
LANGUAGES: tuple[Language, ...] = (
    # --- Code ---
    Language('Python',       'code',   'yellow',          '#',  ('.py',)),
    Language('Rust',         'code',   'dark_orange',     '//', ('.rs',)),
    Language('Go',           'code',   'cyan',            '//', ('.go',)),
    Language('JavaScript',   'code',   'bright_yellow',   '//', ('.js', '.jsx', '.mjs')),
    Language('TypeScript',   'code',   'dodger_blue',     '//', ('.ts', '.tsx')),
    Language('Java',         'code',   'orange3',         '//', ('.java',)),
    Language('C',            'code',   'steel_blue',      '//', ('.c',)),
    Language('C Header',     'code',   'steel_blue',      '//', ('.h',)),
    Language('C++',          'code',   'bright_blue',     '//', ('.cpp', '.hpp', '.cc', '.cxx')),
    Language('C#',           'code',   'green3',          '//', ('.cs',)),
    Language('Swift',        'code',   'orange_red1',     '//', ('.swift',)),
    Language('Kotlin',       'code',   'medium_purple',   '//', ('.kt', '.kts')),
    Language('Ruby',         'code',   'red',             '#',  ('.rb',)),
    Language('Shell',        'code',   'bright_green',    '#',  ('.sh', '.bash', '.zsh')),
    Language('Lua',          'code',   'blue',            '--', ('.lua',)),
    Language('PHP',          'code',   'medium_purple3',  '//', ('.php',)),
    Language('Perl',         'code',   'grey62',          '#',  ('.pl', '.pm')),
    Language('R',            'code',   'bright_blue',     '#',  ('.r', '.R')),
    Language('Dart',         'code',   'cyan3',           '//', ('.dart',)),
    Language('Scala',        'code',   'red3',            '//', ('.scala',)),
    Language('Elixir',       'code',   'dark_violet',     '#',  ('.ex', '.exs')),
    Language('Zig',          'code',   'orange1',         '//', ('.zig',)),
    # --- Design ---
    Language('CSS',          'design', 'magenta',         None, ('.css',)),
    Language('SCSS',         'design', 'hot_pink',        '//', ('.scss',)),
    Language('LESS',         'design', 'magenta3',        '//', ('.less',)),
    Language('HTML',         'design', 'dark_orange',     None, ('.html', '.htm')),
    Language('SVG',          'design', 'gold1',           None, ('.svg',)),
    # --- Docs ---
    Language('Markdown',     'docs',   'white',           None, ('.md', '.mdx')),
    Language('reStructuredText', 'docs', 'grey70',        None, ('.rst',)),
    # --- Data ---
    Language('TOML',         'data',   'grey50',          '#',  ('.toml',)),
    Language('YAML',         'data',   'light_pink3',     '#',  ('.yml', '.yaml')),
    Language('JSON',         'data',   'green_yellow',    None, ('.json',)),
    Language('XML',          'data',   'grey58',          None, ('.xml',)),
    Language('SQL',          'data',   'bright_cyan',     '--', ('.sql',)),
)
# fmt: on


def _build_extension_map() -> dict[str, Language]:
    ext_map: dict[str, Language] = {}
    for lang in LANGUAGES:
        for ext in lang.extensions:
            ext_map[ext] = lang
    return ext_map


EXTENSION_MAP: dict[str, Language] = _build_extension_map()


def identify_language(path: Path) -> Language | None:
    """Return the Language for a file path, or None if unrecognized."""
    return EXTENSION_MAP.get(path.suffix.lower())
