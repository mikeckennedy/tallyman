"""Tests for image export (slug, path resolution, theme, PNG generation)."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional, Union

import pytest
from rich.console import Console

from tallyman import display, image
from tallyman.aggregator import OTHER_LABEL, TallyResult, aggregate, bar_segments, percent_label
from tallyman.counter import FileCount, count_lines
from tallyman.image import (
    DARK_THEME,
    LIGHT_THEME,
    MAX_LEGEND_ITEMS,
    MAX_SLUG_LENGTH,
    _fit_text,
    _hex_to_rgb,
    _load_font,
    _rich_color_to_rgb,
    generate_image,
    resolve_image_path,
    slugify_directory_name,
)
from tallyman.languages import EXTENSION_MAP, Language
from tallyman.walker import walk_project


def _lang(name: str, category: str = 'code', color: str = 'yellow') -> Language:
    return Language(name, category, color, '#', (f'.{name.lower()}',))


class TestSlugifyDirectoryName:
    def test_spaces_to_hyphens(self) -> None:
        assert slugify_directory_name('Talk Python Training') == 'talk-python-training'

    def test_special_chars_stripped(self) -> None:
        assert slugify_directory_name('my_project (v2)') == 'my-project-v2'

    def test_unicode_normalized_to_ascii_chars(self) -> None:
        # Non-ASCII become hyphens (regex [^a-z0-9]+)
        assert slugify_directory_name('café') == 'caf'
        assert slugify_directory_name('naïve') == 'na-ve'

    def test_empty_after_strip_returns_fallback(self) -> None:
        assert slugify_directory_name('---') == 'tallyman-report'

    def test_single_word_lowercase(self) -> None:
        assert slugify_directory_name('Tallyman') == 'tallyman'

    def test_long_names_are_capped(self) -> None:
        assert len(slugify_directory_name('a' * 253)) == MAX_SLUG_LENGTH

    def test_cap_does_not_leave_a_trailing_hyphen(self) -> None:
        assert not slugify_directory_name('ab ' * 60).endswith('-')


class TestResolveImagePath:
    def test_no_conflict_uses_slug_png(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        out = resolve_image_path('My Project', desktop_preferred=True)
        assert out == desktop / 'my-project.png'

    def test_conflict_adds_numeric_suffix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        (desktop / 'my-project.png').touch()
        out = resolve_image_path('My Project', desktop_preferred=True)
        assert out == desktop / 'my-project-1.png'

    def test_multiple_conflicts_increment_suffix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        (desktop / 'foo.png').touch()
        (desktop / 'foo-1.png').touch()
        (desktop / 'foo-2.png').touch()
        out = resolve_image_path('foo', desktop_preferred=True)
        assert out == desktop / 'foo-3.png'

    def test_desktop_missing_falls_back_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        # No Desktop directory
        out = resolve_image_path('proj', desktop_preferred=True)
        assert out == tmp_path / 'proj.png'

    def test_desktop_preferred_false_uses_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        desktop = tmp_path / 'Desktop'
        desktop.mkdir()
        monkeypatch.chdir(tmp_path)
        out = resolve_image_path('x', desktop_preferred=False)
        assert out == tmp_path / 'x.png'


class TestHexToRgb:
    def test_parses_hex(self) -> None:
        assert _hex_to_rgb('#1e1e2e') == (30, 30, 46)
        assert _hex_to_rgb('#ffffff') == (255, 255, 255)


class TestRichColorToRgb:
    def test_named_color_returns_tuple(self) -> None:
        r, g, b = _rich_color_to_rgb('yellow')
        assert isinstance(r, int) and isinstance(g, int) and isinstance(b, int)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_grey50(self) -> None:
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

    def test_produces_valid_png(self, tmp_path: Path) -> None:
        tally = self._make_tally()
        out = tmp_path / 'out.png'
        generate_image(tally, 'test-project', out, DARK_THEME)
        assert out.exists()
        with open(out, 'rb') as f:
            header = f.read(8)
        assert header[:8] == b'\x89PNG\r\n\x1a\n'

    def test_empty_results_produces_image(self, tmp_path: Path) -> None:
        tally = self._make_tally(with_data=False)
        out = tmp_path / 'empty.png'
        generate_image(tally, 'empty', out, DARK_THEME)
        assert out.exists()
        with open(out, 'rb') as f:
            assert f.read(8) == b'\x89PNG\r\n\x1a\n'

    def test_long_directory_name_saves_and_fits(self, tmp_path: Path) -> None:
        """A 253-character name used to crash the save with 'File name too long'."""
        name = 'x' * 253
        out = resolve_image_path(name, desktop_preferred=False).name
        generate_image(self._make_tally(), name, tmp_path / out, DARK_THEME)
        assert (tmp_path / out).exists()

    def test_fit_text_adds_an_ellipsis_only_when_needed(self) -> None:
        font = _load_font(36, bold=True)
        assert _fit_text('short', font, 1080) == 'short'
        fitted = _fit_text('Code stats for ' + 'x' * 200, font, 1080)
        assert fitted.endswith('…')
        assert font.getlength(fitted) <= 1080

    def test_dark_and_light_differ(self, tmp_path: Path) -> None:
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


def _record_drawing(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Record what generate_image() draws: 'text' holds each string, 'rectangles' each (x0, y0, x1, y1),
    and 'fills' each rectangle's fill colour.

    Only the bar's segments are drawn as rectangles. The originals still run, so Pillow's own checks apply.
    """
    from PIL import ImageDraw, ImageFont

    drawn: dict[str, list] = {'text': [], 'rectangles': [], 'fills': []}
    original_text = ImageDraw.ImageDraw.text
    original_rectangle = ImageDraw.ImageDraw.rectangle

    # The arguments generate_image() passes, with Pillow's defaults
    def text(
        self: ImageDraw.ImageDraw,
        xy: tuple[float, float],
        text: str,
        fill: Optional[tuple[int, int, int]] = None,
        font: Optional[Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]] = None,
    ) -> None:
        drawn['text'].append(text)
        original_text(self, xy, text, fill=fill, font=font)

    def rectangle(
        self: ImageDraw.ImageDraw, xy: tuple[float, float, float, float], fill: Optional[tuple[int, int, int]] = None
    ) -> None:
        drawn['rectangles'].append(tuple(xy))
        drawn['fills'].append(fill)
        original_rectangle(self, xy, fill=fill)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', text)
    monkeypatch.setattr(ImageDraw.ImageDraw, 'rectangle', rectangle)
    return drawn


def _image_legend(drawn: dict[str, list]) -> list[str]:
    """The legend entries the image drew: the only text with a percentage in it."""
    (legend,) = [t for t in drawn['text'] if '%' in t]
    return legend.split(image.LEGEND_SEPARATOR)


def _code_tally(sizes: list[int]) -> TallyResult:
    exts = ['.py', '.rs', '.go', '.java', '.c', '.rb', '.lua', '.php', '.kt']
    return aggregate([(EXTENSION_MAP[exts[i]], FileCount(total_lines=n, code_lines=n)) for i, n in enumerate(sizes)])


def _height(path: Path) -> int:
    from PIL import Image

    with Image.open(path) as img:
        return img.size[1]


class TestBar:
    def test_tiny_other_segment_does_not_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Other at 0.05% was left 1 px, and drawing it 2 px narrower raised ValueError."""
        drawn = _record_drawing(monkeypatch)
        out = tmp_path / 'out.png'
        generate_image(_code_tally([2000, 1]), 'proj', out, DARK_THEME)
        assert out.exists()
        assert len(drawn['rectangles']) == 2
        assert all(x1 >= x0 for x0, _, x1, _ in drawn['rectangles'])
        assert _image_legend(drawn) == ['Python >99%', 'Other <1%']

    def test_no_effective_lines_draws_no_bar(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bug 6: a project of comments drew no bar but still left room for one."""
        tally = aggregate([(EXTENSION_MAP['.py'], FileCount(total_lines=3, comment_lines=3))])
        drawn = _record_drawing(monkeypatch)
        generate_image(tally, 'proj', tmp_path / 'effective.png', DARK_THEME)
        assert drawn['rectangles'] == []
        assert not any('%' in t for t in drawn['text'])
        generate_image(tally, 'proj', tmp_path / 'total.png', DARK_THEME, with_spaces=True)
        assert len(drawn['rectangles']) == 1
        assert _height(tmp_path / 'effective.png') < _height(tmp_path / 'total.png')

    def test_bar_and_legend_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Seven languages drew seven blocks over a legend that named five, plus Other."""
        drawn = _record_drawing(monkeypatch)
        generate_image(_code_tally([300, 200, 150, 120, 100, 80, 50]), 'proj', tmp_path / 'out.png', DARK_THEME)
        legend = _image_legend(drawn)
        assert len(legend) == MAX_LEGEND_ITEMS + 1
        assert len(drawn['rectangles']) == len(legend)

    def test_segments_tile_the_bar(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        drawn = _record_drawing(monkeypatch)
        generate_image(_code_tally([496, 496, 8]), 'proj', tmp_path / 'out.png', DARK_THEME)
        rects = drawn['rectangles']
        assert rects[0][0] == image.PADDING
        assert rects[-1][2] == image.IMAGE_WIDTH - image.PADDING - image.BAR_GAP
        for left, right in zip(rects, rects[1:]):
            assert right[0] == left[2] + image.BAR_GAP  # each segment starts where the last one's gap ends
        assert all(x1 - x0 >= image.MIN_SEGMENT_PX - image.BAR_GAP for x0, _, x1, _ in rects)


def _specs_and_docs_tree(tmp_path: Path) -> Path:
    """A project with a docs Markdown file (40 lines, 4 blank) and a spec one under plans/ (30 lines, 3 blank).

    Walking it yields the real as_spec() Markdown, the way a scan would, rather than one made by hand.
    """
    root = tmp_path / 'proj'
    (root / 'plans').mkdir(parents=True)
    (root / 'README.md').write_text(''.join('text\n' if i % 10 else '\n' for i in range(40)))
    (root / 'plans' / 'design.md').write_text(''.join('plan\n' if i % 10 else '\n' for i in range(30)))
    return root


def _walked(root: Path) -> list[tuple[Language, FileCount]]:
    return [(lang, count_lines(path, lang)) for path, lang in walk_project(root, set())]


_CATEGORY_LINE = re.compile(r'^\s*(\w+):\s+([\d,]+) lines(?: \((.*)\))?$')


def _category_lines(lines: list[str]) -> list[tuple[str, str, Optional[str]]]:
    """(name, lines, language list) for each category line, then the Combined or Total line."""
    return [(m[1], m[2], m[3]) for line in lines if (m := _CATEGORY_LINE.match(line.rstrip()))]


def _terminal_report(tally: TallyResult, with_spaces: bool) -> tuple[list[tuple[str, str, Optional[str]]], list[str]]:
    out = io.StringIO()
    display.display_results(tally, 'proj', with_spaces=with_spaces, console=Console(file=out, no_color=True, width=200))
    lines = out.getvalue().splitlines()
    bar = next(i for i, line in enumerate(lines) if display.BLOCK_CHAR in line)
    return _category_lines(lines), lines[bar + 1].strip().split(display.LEGEND_SEPARATOR)


def _image_report(
    tally: TallyResult, with_spaces: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[tuple[str, str, Optional[str]]], list[str], list[tuple[int, int, int]]]:
    """The image's category lines, legend entries and bar segment colours, in drawing order."""
    drawn = _record_drawing(monkeypatch)
    generate_image(tally, 'proj', tmp_path / 'out.png', DARK_THEME, with_spaces=with_spaces)
    return _category_lines(drawn['text']), _image_legend(drawn), drawn['fills']


class TestMatchesTerminal:
    """The terminal report and the image card show the same numbers (the image folds its bar after five)."""

    @pytest.mark.parametrize('with_spaces', [False, True])
    def test_same_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_spaces: bool) -> None:
        files = [
            (EXTENSION_MAP['.py'], FileCount(total_lines=600, code_lines=496, comment_lines=64, blank_lines=40)),
            (EXTENSION_MAP['.rs'], FileCount(total_lines=560, code_lines=496, comment_lines=40, blank_lines=24)),
            (EXTENSION_MAP['.go'], FileCount(total_lines=10, code_lines=8, comment_lines=1, blank_lines=1)),
            # Mostly comments: Data is last by effective lines but second by total lines
            (EXTENSION_MAP['.yaml'], FileCount(total_lines=40, code_lines=15, comment_lines=20, blank_lines=5)),
            (EXTENSION_MAP['.json'], FileCount(total_lines=10, code_lines=9, blank_lines=1)),  # no comment marker
        ]
        walked = _walked(_specs_and_docs_tree(tmp_path))
        assert sorted(lang.category for lang, _ in walked) == ['docs', 'specs']
        tally = aggregate(files + walked)

        term_lines, term_legend = _terminal_report(tally, with_spaces)
        img_lines, img_legend, fills = _image_report(tally, with_spaces, tmp_path, monkeypatch)

        if with_spaces:
            assert [name for name, _, _ in term_lines] == ['Code', 'Data', 'Docs', 'Specs', 'Combined']
        else:
            assert [name for name, _, _ in term_lines] == ['Code', 'Docs', 'Specs', 'Data', 'Combined']
        assert term_lines[:-1] == img_lines[:-1]
        assert (term_lines[-1][0], img_lines[-1][0]) == ('Combined', 'Total')
        assert term_lines[-1][1] == img_lines[-1][1] == ('1,290' if with_spaces else '1,087')
        assert term_legend == img_legend
        assert 'Markdown (specs)' in ' '.join(term_legend)
        segments = bar_segments(tally, with_spaces=with_spaces, max_languages=MAX_LEGEND_ITEMS)
        assert fills == [_rich_color_to_rgb(s.color) for s in segments]  # BarSegment.color is the only source
        assert len(fills) == len(img_legend)
        fill_of = {s.label: fill for s, fill in zip(segments, fills)}
        assert fill_of['Markdown (specs)'] != fill_of['Markdown (docs)']  # they drew as one #c0c0c0 block

    def test_image_folds_after_five(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tally = _code_tally([300, 200, 150, 120, 100, 80, 50])  # every language above the threshold
        _, term_legend = _terminal_report(tally, with_spaces=False)
        _, img_legend, fills = _image_report(tally, False, tmp_path, monkeypatch)
        rest = sum(s.percent for s in bar_segments(tally)[MAX_LEGEND_ITEMS:])
        assert len(term_legend) == 7
        assert img_legend == term_legend[:MAX_LEGEND_ITEMS] + [f'{OTHER_LABEL} {percent_label(rest)}']
        assert len(fills) == 6
