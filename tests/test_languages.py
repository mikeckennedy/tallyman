from __future__ import annotations

from pathlib import Path

import pytest

from tallyman.languages import EXTENSION_MAP, FILENAME_MAP, LANGUAGES, as_spec, identify_language


class TestIdentifyLanguage:
    def test_python_file(self):
        assert identify_language(Path('main.py')) == EXTENSION_MAP['.py']

    def test_rust_file(self):
        lang = identify_language(Path('lib.rs'))
        assert lang is not None
        assert lang.name == 'Rust'

    def test_javascript_jsx(self):
        lang = identify_language(Path('App.jsx'))
        assert lang is not None
        assert lang.name == 'JavaScript'

    def test_typescript_tsx(self):
        lang = identify_language(Path('component.tsx'))
        assert lang is not None
        assert lang.name == 'TypeScript'

    def test_solidity_file(self):
        lang = identify_language(Path('Token.sol'))
        assert lang is not None
        assert lang.name == 'Solidity'
        assert lang.category == 'code'
        assert lang.single_line_comment == '//'

    def test_markdown(self):
        lang = identify_language(Path('README.md'))
        assert lang is not None
        assert lang.name == 'Markdown'
        assert lang.category == 'docs'

    def test_html_template_extensions(self):
        for ext in ('.xhtml', '.shtml', '.pt', '.jinja', '.jinja2', '.j2', '.njk', '.hbs', '.ejs', '.mustache'):
            lang = identify_language(Path(f'template{ext}'))
            assert lang is not None, f'{ext} not recognized'
            assert lang.name == 'HTML', f'{ext} mapped to {lang.name}, expected HTML'

    def test_css(self):
        lang = identify_language(Path('styles.css'))
        assert lang is not None
        assert lang.category == 'design'

    def test_unknown_extension(self):
        assert identify_language(Path('photo.png')) is None

    def test_no_extension_unknown(self):
        assert identify_language(Path('README')) is None

    def test_case_insensitive(self):
        lang = identify_language(Path('README.MD'))
        assert lang is not None
        assert lang.name == 'Markdown'


class TestFilenameIdentification:
    def test_makefile(self):
        lang = identify_language(Path('Makefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_makefile_lowercase(self):
        lang = identify_language(Path('makefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_gnumakefile(self):
        lang = identify_language(Path('GNUmakefile'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_makefile_mk_extension(self):
        lang = identify_language(Path('rules.mk'))
        assert lang is not None
        assert lang.name == 'Makefile'

    def test_dockerfile(self):
        lang = identify_language(Path('Dockerfile'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_dockerfile_variant(self):
        lang = identify_language(Path('Dockerfile.dev'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_dockerfile_extension(self):
        lang = identify_language(Path('app.dockerfile'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_docker_compose_yml(self):
        lang = identify_language(Path('docker-compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_docker_compose_yaml(self):
        lang = identify_language(Path('docker-compose.yaml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_compose_yml(self):
        lang = identify_language(Path('compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_compose_yaml(self):
        lang = identify_language(Path('compose.yaml'))
        assert lang is not None
        assert lang.name == 'Docker'

    def test_filename_takes_priority_over_extension(self):
        """docker-compose.yml should be Docker, not YAML."""
        lang = identify_language(Path('docker-compose.yml'))
        assert lang is not None
        assert lang.name == 'Docker'
        assert lang.name != 'YAML'

    def test_filename_map_entries_are_valid(self):
        for name, lang in FILENAME_MAP.items():
            assert lang in LANGUAGES, f'FILENAME_MAP entry {name!r} points to unregistered language'


class TestLanguageRegistry:
    def test_no_duplicate_extensions(self):
        seen: dict[str, str] = {}
        for lang in LANGUAGES:
            for ext in lang.extensions:
                assert ext not in seen, f'Extension {ext} is mapped to both {seen[ext]} and {lang.name}'
                seen[ext] = lang.name

    def test_all_languages_have_extensions(self):
        for lang in LANGUAGES:
            assert len(lang.extensions) > 0, f'{lang.name} has no extensions'

    def test_all_extensions_start_with_dot(self):
        for lang in LANGUAGES:
            for ext in lang.extensions:
                assert ext.startswith('.'), f'{lang.name} extension {ext!r} missing leading dot'

    def test_valid_categories(self):
        valid = {'code', 'devops', 'design', 'docs', 'data'}
        for lang in LANGUAGES:
            assert lang.category in valid, f'{lang.name} has invalid category {lang.category!r}'

    def test_at_least_30_languages(self):
        assert len(LANGUAGES) >= 30

    def test_language_is_frozen(self):
        lang = LANGUAGES[0]
        try:
            lang.name = 'Nope'  # type: ignore[misc]
            assert False, 'Should have raised FrozenInstanceError'
        except AttributeError:
            pass


class TestAsSpec:
    def test_creates_spec_category(self):
        md = identify_language(Path('test.md'))
        assert md is not None
        spec_md = as_spec(md)
        assert spec_md.category == 'specs'
        assert spec_md.name == 'Markdown'
        assert spec_md.color == md.color
        assert spec_md.extensions == md.extensions

    def test_caching(self):
        md = identify_language(Path('test.md'))
        assert md is not None
        assert as_spec(md) is as_spec(md)

    def test_rejects_non_docs(self):
        py = identify_language(Path('test.py'))
        assert py is not None
        with pytest.raises(ValueError):
            as_spec(py)

    def test_rst(self):
        rst = identify_language(Path('test.rst'))
        assert rst is not None
        spec_rst = as_spec(rst)
        assert spec_rst.category == 'specs'
        assert spec_rst.name == 'reStructuredText'
