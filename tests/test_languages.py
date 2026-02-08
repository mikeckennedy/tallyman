from __future__ import annotations

from pathlib import Path

import pytest

from tallyman.languages import EXTENSION_MAP, LANGUAGES, as_spec, identify_language


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

    def test_markdown(self):
        lang = identify_language(Path('README.md'))
        assert lang is not None
        assert lang.name == 'Markdown'
        assert lang.category == 'docs'

    def test_css(self):
        lang = identify_language(Path('styles.css'))
        assert lang is not None
        assert lang.category == 'design'

    def test_unknown_extension(self):
        assert identify_language(Path('photo.png')) is None

    def test_no_extension(self):
        assert identify_language(Path('Makefile')) is None

    def test_case_insensitive(self):
        lang = identify_language(Path('README.MD'))
        assert lang is not None
        assert lang.name == 'Markdown'


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
        valid = {'code', 'design', 'docs', 'data'}
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
