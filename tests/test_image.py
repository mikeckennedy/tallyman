"""Tests for image export (slug, path resolution, theme, PNG generation)."""

from __future__ import annotations

from pathlib import Path

from tallyman.aggregator import TallyResult, aggregate
from tallyman.counter import FileCount
from tallyman.image import (
    DARK_THEME,
    LIGHT_THEME,
    _hex_to_rgb,
    _rich_color_to_rgb,
    generate_image,
    resolve_image_path,
    slugify_directory_name,
)
from tallyman.languages import Language


def _lang(name: str, category: str = 'code', color: str = 'yellow') -> Language:
    return Language(name, category, color, '#', (f'.{name.lower()}',))


class TestSlugifyDirectoryName:
    def test_spaces_to_hyphens(self):
        assert slugify_directory_name('Talk Python Training') == 'talk-python-training'

    def test_special_chars_stripped(self):
        assert slugify_directory_name('my_project (v2)') == 'my-project-v2'

    def test_unicode_normalized_to_ascii_chars(self):
        # Non-ASCII become hyphens (regex [^a-z0-9]+)
        assert slugify_directory_name('café') == 'caf'
        assert slugify_directory_name('naïve') == 'na-ve'

    def test_empty_after_strip_returns_fallback(self):
        assert slugify_directory_name('---') == 'tallyman-report'

    def test_single_word_lowercase(self):
        assert slugify_directory_name('Tallyman') == 'tallyman'


class TestResolveImagePath:
    def test_no_conflict_uses_slug_png(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        out = resolve_image_path('My Project', desktop_preferred=True)
        assert out == desktop / 'my-project.png'

    def test_conflict_adds_numeric_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        (desktop / 'my-project.png').touch()
        out = resolve_image_path('My Project', desktop_preferred=True)
        assert out == desktop / 'my-project-1.png'

    def test_multiple_conflicts_increment_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        (desktop / 'foo.png').touch()
        (desktop / 'foo-1.png').touch()
        (desktop / 'foo-2.png').touch()
        out = resolve_image_path('foo', desktop_preferred=True)
        assert out == desktop / 'foo-3.png'

    def test_desktop_missing_falls_back_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        # No Desktop directory
        out = resolve_image_path('proj', desktop_preferred=True)
        assert out == tmp_path / 'proj.png'

    def test_desktop_preferred_false_uses_cwd(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        monkeypatch.chdir(tmp_path)
        out = resolve_image_path('x', desktop_preferred=False)
        assert out == tmp_path / 'x.png'


class TestHexToRgb:
    def test_parses_hex(self):
        assert _hex_to_rgb('#1e1e2e') == (30, 30, 46)
        assert _hex_to_rgb('#ffffff') == (255, 255, 255)


class TestRichColorToRgb:
    def test_named_color_returns_tuple(self):
        r, g, b = _rich_color_to_rgb('yellow')
        assert isinstance(r, int) and isinstance(g, int) and isinstance(b, int)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_grey50(self):
        r, g, b = _rich_color_to_rgb('grey50')
        assert r == g == b


class TestGenerateImage:
    def _make_tally(self, with_data: bool = True) -> TallyResult:
        if not with_data:
            return aggregate([])
        py = _lang('Python')
        md = _lang('Markdown', 'docs', 'white')
        results = [
            (py, FileCount(total_lines=100, code_lines=80, comment_lines=10, blank_lines=10)),
            (md, FileCount(total_lines=50, code_lines=45, comment_lines=0, blank_lines=5)),
        ]
        return aggregate(results)

    def test_produces_valid_png(self, tmp_path):
        tally = self._make_tally()
        out = tmp_path / 'out.png'
        generate_image(tally, 'test-project', out, DARK_THEME)
        assert out.exists()
        with open(out, 'rb') as f:
            header = f.read(8)
        assert header[:8] == b'\x89PNG\r\n\x1a\n'

    def test_empty_results_produces_image(self, tmp_path):
        tally = self._make_tally(with_data=False)
        out = tmp_path / 'empty.png'
        generate_image(tally, 'empty', out, DARK_THEME)
        assert out.exists()
        with open(out, 'rb') as f:
            assert f.read(8) == b'\x89PNG\r\n\x1a\n'

    def test_dark_and_light_differ(self, tmp_path):
        tally = self._make_tally()
        dark_path = tmp_path / 'dark.png'
        light_path = tmp_path / 'light.png'
        generate_image(tally, 'proj', dark_path, DARK_THEME)
        generate_image(tally, 'proj', light_path, LIGHT_THEME)
        with open(dark_path, 'rb') as f:
            dark_bytes = f.read()
        with open(light_path, 'rb') as f:
            light_bytes = f.read()
        assert dark_bytes != light_bytes
