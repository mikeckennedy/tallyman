from __future__ import annotations

from pathlib import Path

import pytest
from rich.color import Color, ColorSystem

from tallyman.languages import (
    EXTENSION_MAP,
    FILENAME_MAP,
    LANGUAGES,
    OTHER_COLOR,
    Language,
    as_spec,
    identify_language,
)


class TestIdentifyLanguage:
    def test_python_file(self) -> None:
        assert identify_language(Path('main.py')) == EXTENSION_MAP['.py']

    def test_rust_file(self) -> None:
        lang = identify_language(Path('lib.rs'))
        assert lang is not None
        assert lang.name == 'Rust'

    def test_javascript_jsx(self) -> None:
        lang = identify_language(Path('App.jsx'))
        assert lang is not None
        assert lang.name == 'JavaScript'

    def test_typescript_tsx(self) -> None:
        lang = identify_language(Path('component.tsx'))
        assert lang is not None
        assert lang.name == 'TypeScript'

    def test_solidity_file(self) -> None:
        lang = identify_language(Path('Token.sol'))
        assert lang is not None
        assert lang.name == 'Solidity'
        assert lang.category == 'code'
        assert lang.single_line_comment == '//'

    def test_matlab_file(self) -> None:
        lang = identify_language(Path('solver.m'))
        assert lang is not None
        assert lang.name == 'MATLAB'
        assert lang.category == 'code'
        assert lang.single_line_comment == '%'

    def test_markdown(self) -> None:
        lang = identify_language(Path('README.md'))
        assert lang is not None
        assert lang.name == 'Markdown'
        assert lang.category == 'docs'

    def test_html_template_extensions(self) -> None:
        for ext in ('.xhtml', '.shtml', '.pt', '.jinja', '.jinja2', '.j2', '.njk', '.hbs', '.ejs', '.mustache'):
            lang = identify_language(Path(f'template{ext}'))
            assert lang is not None, f'{ext} not recognized'
            assert lang.name == 'HTML', f'{ext} mapped to {lang.name}, expected HTML'

    def test_css(self) -> None:
        lang = identify_language(Path('styles.css'))
        assert lang is not None
        assert lang.category == 'design'

    def test_unknown_extension(self) -> None:
        assert identify_language(Path('photo.png')) is None

    def test_no_extension_unknown(self) -> None:
        assert identify_language(Path('README')) is None

    def test_case_insensitive(self) -> None:
        lang = identify_language(Path('README.MD'))
        assert lang is not None
        assert lang.name == 'Markdown'

    def test_uppercase_r_extension(self) -> None:
        """R files are often saved as .R; lookup lowercases the suffix, so no '.R' key is needed."""
        lang = identify_language(Path('analysis.R'))
        assert lang is not None
        assert lang.name == 'R'


class TestFilenameIdentification:
    def test_makefile(self) -> None:
        lang = identify_language(Path('Makefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_makefile_lowercase(self) -> None:
        lang = identify_language(Path('makefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_gnumakefile(self) -> None:
        lang = identify_language(Path('GNUmakefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_makefile_mk_extension(self) -> None:
        lang = identify_language(Path('rules.mk'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_dockerfile(self) -> None:
        lang = identify_language(Path('Dockerfile'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_dockerfile_variant(self) -> None:
        lang = identify_language(Path('Dockerfile.dev'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_dockerfile_extension(self) -> None:
        lang = identify_language(Path('app.dockerfile'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_docker_compose_yml(self) -> None:
        lang = identify_language(Path('docker-compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_docker_compose_yaml(self) -> None:
        lang = identify_language(Path('docker-compose.yaml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_compose_yml(self) -> None:
        lang = identify_language(Path('compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_compose_yaml(self) -> None:
        lang = identify_language(Path('compose.yaml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_filename_takes_priority_over_extension(self) -> None:
        """docker-compose.yml should be Docker, not YAML."""
        lang = identify_language(Path('docker-compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'
        assert lang.name != 'YAML'

    def test_filename_map_entries_are_valid(self) -> None:
        for name, lang in FILENAME_MAP.items():
            assert lang in LANGUAGES, f'FILENAME_MAP entry {name!r} points to unregistered language'


class TestLanguageRegistry:
    def test_no_duplicate_extensions(self) -> None:
        seen: dict[str, str] = {}
        for lang in LANGUAGES:
            for ext in lang.extensions:
                assert ext not in seen, f'Extension {ext} is mapped to both {seen[ext]} and {lang.name}'
                seen[ext] = lang.name

    def test_all_languages_have_extensions(self) -> None:
        for lang in LANGUAGES:
            assert len(lang.extensions) > 0, f'{lang.name} has no extensions'

    def test_all_extensions_start_with_dot(self) -> None:
        for lang in LANGUAGES:
            for ext in lang.extensions:
                assert ext.startswith('.'), f'{lang.name} extension {ext!r} missing leading dot'

    def test_every_extension_is_lowercase(self) -> None:
        """identify_language() looks up the lowercased suffix, so an extension with a capital would never match."""
        for lang in LANGUAGES:
            for ext in lang.extensions:
                assert ext == ext.lower(), f'{lang.name} extension {ext!r} is never looked up; use {ext.lower()!r}'

    def test_valid_categories(self) -> None:
        valid = {'code', 'devops', 'design', 'docs', 'data'}
        for lang in LANGUAGES:
            assert lang.category in valid, f'{lang.name} has invalid category {lang.category!r}'

    def test_at_least_30_languages(self) -> None:
        assert len(LANGUAGES) >= 30

    def test_language_is_frozen(self) -> None:
        lang = LANGUAGES[0]
        try:
            lang.name = 'Nope'  # type: ignore
            assert False, 'Should have raised FrozenInstanceError'
        except AttributeError:
            pass


class TestAsSpec:
    def test_creates_spec_category(self) -> None:
        md = identify_language(Path('test.md'))
        assert md is not None
        spec_md = as_spec(md)
        assert spec_md.category == 'specs'
        assert spec_md.name == 'Markdown'
        assert spec_md.color == md.spec_color == 'violet'
        assert spec_md.color != md.color  # specs and docs never draw as one bar segment
        assert spec_md.spec_color is None  # the variant isn't a docs language
        assert spec_md.extensions == md.extensions

    def test_caching(self) -> None:
        md = identify_language(Path('test.md'))
        assert md is not None
        assert as_spec(md) is as_spec(md)

    def test_rejects_non_docs(self) -> None:
        py = identify_language(Path('test.py'))
        assert py is not None
        with pytest.raises(ValueError):
            as_spec(py)

    def test_rst(self) -> None:
        rst = identify_language(Path('test.rst'))
        assert rst is not None
        spec_rst = as_spec(rst)
        assert spec_rst.category == 'specs'
        assert spec_rst.name == 'reStructuredText'
        assert spec_rst.color == 'dark_sea_green4'

    def test_docs_language_without_spec_colour_is_rejected(self) -> None:
        with pytest.raises(ValueError, match='spec_color'):
            as_spec(Language('Doc', 'docs', 'white', None, ('.doc',)))


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('Dockerfile', 'Docker'),
        ('Dockerfile.dev', 'Docker'),
        ('Dockerfile.prod', 'Docker'),
        ('Dockerfile.md', 'Markdown'),  # a known extension wins
        ('Dockerfiles.py', 'Python'),
        ('docker-compose.yml', 'Docker'),
        ('docker-compose.override.yml', 'Docker'),
        ('compose.prod.yaml', 'Docker'),
        ('mycompose.prod.yml', 'YAML'),
        ('compose.yml.bak', None),
        ('Dockerfile.go', 'Docker'),  # per-language images: a Dockerfile, not Go
        ('Dockerfile.j2', 'Docker'),
        ('Dockerfile-dev', 'Docker'),
        ('Dockerfile_prod', 'Docker'),
        ('Dockerfile.json', 'JSON'),
        ('Dockerfile.toml', 'TOML'),  # any docs or data extension
        ('Dockerfile.mdx', 'Markdown'),
        ('Dockerfile.txt', None),
        ('Dockerfile.dockerignore', None),  # BuildKit's per-Dockerfile ignore file
        ('api.Dockerfile', 'Docker'),
        ('dockerfile', None),
        ('docker-compose.yml.example', None),
    ],
)
def test_docker_and_compose_variants(name: str, expected: str) -> None:
    lang = identify_language(Path(name))
    assert (lang.name if lang else None) == expected


# C and its header share a colour on purpose. No other entry may share one.
_SHARED_COLOURS = {frozenset({'C', 'C/C++ Header'})}

_DOCS_LANGUAGES = [lang for lang in LANGUAGES if lang.category == 'docs']


def _bar_colours() -> list[tuple[str, str]]:
    """(name, Rich colour) for every colour a bar segment can have: languages, spec variants and Other."""
    colours = [(lang.name, lang.color) for lang in LANGUAGES]
    colours += [(f'{lang.name} (specs)', as_spec(lang).color) for lang in _DOCS_LANGUAGES]
    return colours + [('Other', OTHER_COLOR)]


def _standard_number(colour: str) -> int:
    """The colour's number on a 16-colour terminal."""
    number = Color.parse(colour).downgrade(ColorSystem.STANDARD).number
    assert number is not None
    return number


def test_every_docs_language_has_a_spec_colour() -> None:
    assert _DOCS_LANGUAGES
    for lang in _DOCS_LANGUAGES:
        assert lang.spec_color is not None, lang.name


def test_only_docs_languages_have_spec_colours() -> None:
    for lang in LANGUAGES:
        assert (lang.spec_color is not None) == (lang.category == 'docs'), lang.name


def test_every_colour_is_a_valid_rich_colour() -> None:
    """An invalid name (like 'dodger_blue' once) crashes image export."""
    for _, colour in _bar_colours():
        Color.parse(colour)


@pytest.mark.parametrize('resolve', ['truecolor', 'eight_bit'])
def test_no_new_shared_colours(resolve: str) -> None:
    """Compares what is drawn, not names: the card's RGB, then the 256-colour index (so grey50 = gray50)."""
    by_colour: dict[object, set[str]] = {}
    for name, colour in _bar_colours():
        parsed = Color.parse(colour)
        key = (
            parsed.get_truecolor(None, True)
            if resolve == 'truecolor'
            else parsed.downgrade(ColorSystem.EIGHT_BIT).number
        )
        by_colour.setdefault(key, set()).add(name)
    shared = {frozenset(names) for names in by_colour.values() if len(names) > 1}
    assert shared <= _SHARED_COLOURS, shared - _SHARED_COLOURS


@pytest.mark.parametrize('lang', _DOCS_LANGUAGES, ids=lambda lang: lang.name)
def test_spec_variant_differs_from_its_docs_language_in_16_colours(lang: Language) -> None:
    """A docs language and its spec variant appear together whenever specs exist."""
    assert _standard_number(lang.color) != _standard_number(as_spec(lang).color)


def test_other_is_unique_in_16_colours() -> None:
    """Other can follow any language, so no entry may drop to its 16-colour code."""
    other = _standard_number(OTHER_COLOR)
    clashes = [name for name, colour in _bar_colours() if name != 'Other' and _standard_number(colour) == other]
    assert clashes == []
