"""Language registry  -  maps file extensions to language metadata."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Language:
    name: str
    category: str  # 'code', 'devops', 'design', 'docs', 'data'
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
    Language('C/C++ Header', 'code',   'steel_blue',      '//', ('.h',)),
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
    Language('Haskell',      'code',   'purple',          '--', ('.hs',)),
    Language('Erlang',       'code',   'salmon1',         '%',  ('.erl',)),
    Language('OCaml',        'code',   'sandy_brown',     None, ('.ml', '.mli')),
    Language('Nim',          'code',   'gold3',           '#',  ('.nim', '.nims')),
    Language('V',            'code',   'sky_blue1',       '//', ('.v', '.vv')),
    # --- DevOps ---
    Language('Terraform',    'devops', 'purple4',         '#',  ('.tf', '.tfvars')),
    Language('Makefile',     'devops', 'bright_white',    '#',  ('.mk',)),
    Language('Docker',       'devops', 'deep_sky_blue1',  '#',  ('.dockerfile',)),
    # --- Design ---
    Language('CSS',          'design', 'magenta',         None, ('.css',)),
    Language('SCSS',         'design', 'hot_pink',        '//', ('.scss',)),
    Language('LESS',         'design', 'magenta3',        '//', ('.less',)),
    Language('HTML',         'design', 'dark_orange',     None, ('.html', '.htm', '.xhtml', '.shtml', '.pt', '.jinja', '.jinja2', '.j2', '.njk', '.hbs', '.ejs', '.mustache')),
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


def _build_filename_map() -> dict[str, Language]:
    """Map specific filenames to languages for files identified by name rather than extension."""
    by_name = {lang.name: lang for lang in LANGUAGES}
    docker = by_name['Docker']
    makefile = by_name['Makefile']
    return {
        'Dockerfile': docker,
        'Makefile': makefile,
        'makefile': makefile,
        'GNUmakefile': makefile,
        'docker-compose.yml': docker,
        'docker-compose.yaml': docker,
        'compose.yml': docker,
        'compose.yaml': docker,
    }


FILENAME_MAP: dict[str, Language] = _build_filename_map()


def identify_language(path: Path) -> Language | None:
    """Return the Language for a file path, or None if unrecognized.

    Checks exact filename matches first (e.g. Makefile, docker-compose.yml),
    then Dockerfile prefix variants (Dockerfile.dev, Dockerfile.prod),
    then falls back to extension matching.
    """
    name = path.name
    if name in FILENAME_MAP:
        return FILENAME_MAP[name]
    if name.startswith('Dockerfile'):
        return FILENAME_MAP['Dockerfile']
    return EXTENSION_MAP.get(path.suffix.lower())


@functools.cache
def as_spec(lang: Language) -> Language:
    """Return a spec-category variant of a docs-category language.

    Creates a Language identical to *lang* but with category='specs'.
    Results are cached since Language is frozen and hashable.

    Raises ValueError if lang.category is not 'docs'.
    """
    if lang.category != 'docs':
        raise ValueError(f'as_spec() only applies to docs languages, got {lang.category!r}')
    return Language(
        lang.name,
        'specs',
        lang.color,
        lang.single_line_comment,
        lang.extensions,
    )
