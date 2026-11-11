from __future__ import annotations

from typing import Optional

import pytest

from tallyman.aggregator import (
    CATEGORY_ORDER,
    OTHER_LABEL,
    CategoryStats,
    LanguageStats,
    TallyResult,
    active_categories,
    aggregate,
    bar_segments,
    category_language_list,
    language_percentages,
    percent_label,
    segment_widths,
)
from tallyman.counter import FileCount
from tallyman.languages import EXTENSION_MAP, OTHER_COLOR, Language, as_spec


def _lang(name: str, category: str = 'code', comment: Optional[str] = '#') -> Language:
    return Language(name, category, 'white', comment, (f'.{name.lower()}',))


class TestAggregate:
    def test_single_language(self) -> None:
        lang = _lang('Python')
        results = [
            (lang, FileCount(total_lines=100, code_lines=80, comment_lines=10, blank_lines=10)),
            (lang, FileCount(total_lines=50, code_lines=40, comment_lines=5, blank_lines=5)),
        ]
        tally = aggregate(results)
        assert len(tally.by_language) == 1
        stats = tally.by_language[0]
        assert stats.total_lines == 150
        assert stats.code_lines == 120
        assert stats.comment_lines == 15
        assert stats.blank_lines == 15
        assert stats.file_count == 2

    def test_multiple_languages_sorted_descending(self) -> None:
        py = _lang('Python')
        rs = _lang('Rust')
        results = [
            (py, FileCount(total_lines=50, code_lines=40, comment_lines=5, blank_lines=5)),
            (rs, FileCount(total_lines=200, code_lines=180, comment_lines=10, blank_lines=10)),
        ]
        tally = aggregate(results)
        assert tally.by_language[0].language.name == 'Rust'
        assert tally.by_language[1].language.name == 'Python'

    def test_category_grouping(self) -> None:
        py = _lang('Python', 'code')
        css = _lang('CSS', 'design', None)
        md = _lang('Markdown', 'docs', None)
        results = [
            (py, FileCount(total_lines=100, code_lines=80, comment_lines=10, blank_lines=10)),
            (css, FileCount(total_lines=50, code_lines=45, comment_lines=0, blank_lines=5)),
            (md, FileCount(total_lines=30, code_lines=25, comment_lines=0, blank_lines=5)),
        ]
        tally = aggregate(results)

        cat_names = [c.name for c in tally.by_category]
        assert 'Code' in cat_names
        assert 'Design' in cat_names
        assert 'Docs' in cat_names

        code_cat = next(c for c in tally.by_category if c.name == 'Code')
        assert code_cat.total_lines == 100
        assert 'Python' in code_cat.languages

    def test_grand_total(self) -> None:
        py = _lang('Python')
        results = [
            (py, FileCount(total_lines=100, code_lines=80, comment_lines=10, blank_lines=10)),
        ]
        tally = aggregate(results)
        assert tally.grand_total_lines == 100

    def test_empty_results(self) -> None:
        tally = aggregate([])
        assert tally.by_language == []
        assert tally.by_category == []
        assert tally.grand_total_lines == 0


class TestAggregateSpecs:
    def test_specs_category_in_output(self) -> None:
        """Spec-category languages produce a Specs category in results."""
        md = Language('Markdown', 'docs', 'white', None, ('.md',))
        spec_md = Language('Markdown', 'specs', 'white', None, ('.md',))

        results = [
            (md, FileCount(total_lines=100, blank_lines=20)),
            (spec_md, FileCount(total_lines=500, blank_lines=50)),
        ]

        tally = aggregate(results)

        assert len(tally.by_language) == 2

        cat_names = [c.name for c in tally.by_category]
        assert 'Docs' in cat_names
        assert 'Specs' in cat_names

        docs_cat = next(c for c in tally.by_category if c.name == 'Docs')
        specs_cat = next(c for c in tally.by_category if c.name == 'Specs')
        assert docs_cat.effective_lines == 80  # 100 - 20 blank
        assert specs_cat.effective_lines == 450  # 500 - 50 blank

    def test_groups_by_language_object(self) -> None:
        """Two Language objects with same name but different categories stay separate."""
        md_docs = Language('Markdown', 'docs', 'white', None, ('.md',))
        md_specs = Language('Markdown', 'specs', 'white', None, ('.md',))

        results = [
            (md_docs, FileCount(total_lines=100)),
            (md_specs, FileCount(total_lines=200)),
        ]

        tally = aggregate(results)
        assert len(tally.by_language) == 2
        assert tally.grand_total_lines == 300

    def test_specs_category_order(self) -> None:
        """Specs appears between Docs and Data in category output."""
        md = Language('Markdown', 'docs', 'white', None, ('.md',))
        spec_md = Language('Markdown', 'specs', 'white', None, ('.md',))
        toml = Language('TOML', 'data', 'grey50', '#', ('.toml',))

        results = [
            (md, FileCount(total_lines=100, blank_lines=10)),
            (spec_md, FileCount(total_lines=200, blank_lines=20)),
            (toml, FileCount(total_lines=50, code_lines=40, comment_lines=5, blank_lines=5)),
        ]

        tally = aggregate(results)
        cat_names = [c.name for c in tally.by_category]
        assert cat_names.index('Docs') < cat_names.index('Specs')
        assert cat_names.index('Specs') < cat_names.index('Data')


class TestLanguagePercentages:
    def test_single_language_is_100_percent(self) -> None:
        py = _lang('Python')
        tally = TallyResult(
            by_language=[LanguageStats(language=py, total_lines=100, code_lines=80, blank_lines=10)],
            by_category=[],
            grand_total_lines=100,
        )
        pcts = language_percentages(tally)
        assert len(pcts) == 1
        assert pcts[0][0] is py
        assert pcts[0][1] == 100.0

    def test_percentages_sum_to_100(self) -> None:
        py = _lang('Python')
        rs = _lang('Rust')
        tally = TallyResult(
            by_language=[
                LanguageStats(language=py, total_lines=75, code_lines=60, blank_lines=5),
                LanguageStats(language=rs, total_lines=25, code_lines=20, blank_lines=2),
            ],
            by_category=[],
            grand_total_lines=100,
        )
        pcts = language_percentages(tally)
        total = sum(p[1] for p in pcts)
        assert abs(total - 100.0) < 0.01

    def test_with_spaces_uses_total_lines(self) -> None:
        py = _lang('Python')
        rs = _lang('Rust')
        tally = TallyResult(
            by_language=[
                LanguageStats(language=py, total_lines=75, code_lines=30, blank_lines=20),
                LanguageStats(language=rs, total_lines=25, code_lines=20, blank_lines=2),
            ],
            by_category=[],
            grand_total_lines=100,
        )
        pcts = language_percentages(tally, with_spaces=True)
        assert pcts[0][0] is py
        assert pcts[0][1] == 75.0
        assert pcts[1][0] is rs
        assert pcts[1][1] == 25.0

    def test_empty_returns_empty(self) -> None:
        tally = TallyResult(by_language=[], by_category=[], grand_total_lines=0)
        assert language_percentages(tally) == []


def _code(n: int) -> FileCount:
    """*n* lines, all of them code."""
    return FileCount(total_lines=n, code_lines=n)


class TestEffectiveLines:
    def test_with_a_comment_marker_it_is_code_lines(self) -> None:
        stats = LanguageStats(_lang('Python'), total_lines=10, code_lines=6, comment_lines=3, blank_lines=1)
        assert stats.effective_lines == 6

    def test_without_a_comment_marker_it_is_non_blank_lines(self) -> None:
        stats = LanguageStats(_lang('Markdown', 'docs', None), total_lines=10, code_lines=6, blank_lines=1)
        assert stats.effective_lines == 9  # its comments can't be told apart, so only blanks drop out

    def test_category_effective_lines_is_the_sum_of_its_languages(self) -> None:
        tally = aggregate(
            [
                (_lang('Python'), FileCount(total_lines=10, code_lines=6, comment_lines=3, blank_lines=1)),
                (_lang('OCaml', 'code', None), FileCount(total_lines=8, code_lines=5, comment_lines=0, blank_lines=2)),
            ]
        )
        assert tally.by_category[0].effective_lines == sum(s.effective_lines for s in tally.by_language) == 12

    def test_shown_lines_with_spaces_is_total_lines(self) -> None:
        tally = aggregate([(_lang('Python'), FileCount(total_lines=10, code_lines=6, comment_lines=3, blank_lines=1))])
        assert tally.by_language[0].shown_lines(with_spaces=True) == 10
        assert tally.by_language[0].shown_lines(with_spaces=False) == 6
        assert tally.by_category[0].shown_lines(with_spaces=True) == 10
        assert tally.by_category[0].shown_lines(with_spaces=False) == 6


class TestActiveCategories:
    def test_sorted_by_effective_lines_or_by_total_lines_with_spaces(self) -> None:
        tally = aggregate(
            [
                (_lang('Python'), FileCount(total_lines=100, code_lines=10, comment_lines=80, blank_lines=10)),
                (_lang('YAML', 'data'), FileCount(total_lines=50, code_lines=50)),
            ]
        )
        assert [c.name for c in active_categories(tally)] == ['Data', 'Code']
        assert [c.name for c in active_categories(tally, with_spaces=True)] == ['Code', 'Data']

    def test_categories_with_no_lines_are_left_out(self) -> None:
        tally = aggregate([(_lang('Python'), _code(5)), (_lang('YAML', 'data'), FileCount(total_lines=0))])
        assert [c.name for c in tally.by_category] == ['Code', 'Data']
        assert [c.name for c in active_categories(tally)] == ['Code']

    def test_equal_counts_keep_category_order(self) -> None:
        tally = aggregate([(_lang(f'L{key}', key), _code(7)) for key in reversed(CATEGORY_ORDER) if key != 'specs'])
        expected = [c.name for c in tally.by_category]
        assert [c.name for c in active_categories(tally)] == expected
        assert expected == ['Code', 'DevOps', 'Design', 'Docs', 'Data']


class TestCategoryLanguageList:
    """The parenthetical list on each category line, shared by the terminal and the image."""

    @pytest.mark.parametrize(
        ('languages', 'expected'),
        [
            ([], ''),
            (['Python'], 'Python'),
            (['Python', 'Rust', 'Go'], 'Python + Rust + Go'),
            (['Python', 'Rust', 'Go', 'Java'], 'Python + Rust + Go, etc'),
        ],
    )
    def test_names_at_most_three(self, languages: list[str], expected: str) -> None:
        assert category_language_list(CategoryStats('Code', languages=languages)) == expected


class TestBarSegments:
    def test_small_languages_become_other(self) -> None:
        sizes = [('Python', 97), ('Rust', 1), ('Go', 1), ('Lua', 1)]
        tally = aggregate([(_lang(name), _code(n)) for name, n in sizes])
        segments = bar_segments(tally)
        assert [s.label for s in segments] == ['Python', OTHER_LABEL]
        assert segments[0].percent == pytest.approx(97)
        assert segments[1].language is None
        assert segments[1].percent == pytest.approx(3)

    def test_no_other_when_nothing_is_under_the_threshold(self) -> None:
        tally = aggregate([(_lang('Python'), _code(60)), (_lang('Rust'), _code(40))])
        assert [s.label for s in bar_segments(tally)] == ['Python', 'Rust']

    def test_empty_when_nothing_is_counted(self) -> None:
        assert bar_segments(aggregate([])) == []

    def test_empty_when_no_line_is_effective(self) -> None:
        """Bug 6: a file that is all comments has nothing to share out."""
        tally = aggregate([(_lang('Python'), FileCount(total_lines=3, comment_lines=3))])
        assert bar_segments(tally) == []
        assert [s.label for s in bar_segments(tally, with_spaces=True)] == ['Python']

    def test_labels_and_colours(self) -> None:
        md, py = EXTENSION_MAP['.md'], EXTENSION_MAP['.py']
        tally = aggregate([(md, _code(500)), (as_spec(md), _code(499)), (py, _code(1))])
        segments = bar_segments(tally)
        assert [s.label for s in segments] == ['Markdown (docs)', 'Markdown (specs)', OTHER_LABEL]
        assert [s.color for s in segments] == [md.color, as_spec(md).color, OTHER_COLOR]
        assert segments[1].language is as_spec(md)

    def test_max_languages_folds_the_rest_into_other(self) -> None:
        sizes = [30, 20, 15, 12, 10, 8, 5]
        tally = aggregate([(_lang(f'L{i}'), _code(n)) for i, n in enumerate(sizes)])
        segments = bar_segments(tally, max_languages=2)
        assert [s.label for s in segments] == ['L0', 'L1', OTHER_LABEL]
        assert segments[-1].language is None
        assert segments[-1].percent == pytest.approx(sum(sizes[2:]))

    def test_max_languages_merges_with_the_small_languages(self) -> None:
        tally = aggregate([(_lang(name), _code(n)) for name, n in [('A', 50), ('B', 30), ('C', 19), ('D', 1)]])
        segments = bar_segments(tally, max_languages=2)
        assert [s.label for s in segments] == ['A', 'B', OTHER_LABEL]  # one Other, not two
        assert segments[-1].percent == pytest.approx(20)


_SIZE_LISTS = [  # the same lists as test_display.py::TestPercentageBar::test_bar_is_exactly_bar_width
    [100],
    [50, 50],
    [70, 20, 10],
    [97, 1, 1, 1],
    [34, 33, 33],
    [10] * 10,
    [16, 14, 14, 14, 14, 14, 14],
    [1] * 17,
]


class TestSegmentWidths:
    def test_every_segment_gets_a_cell(self) -> None:
        """Bug 7: rounding gave 30 + 30 cells and left the last segment none."""
        assert segment_widths([49.6, 49.6, 0.8], 60, 1) == [30, 29, 1]

    @pytest.mark.parametrize(
        ('percents', 'total', 'minimum'),
        [(sizes, 60, 1) for sizes in _SIZE_LISTS]
        + [(sizes, 1080, 4) for sizes in _SIZE_LISTS]
        + [([99.95, 0.05], 1080, 4), ([99.95, 0.05], 60, 1)],
    )
    def test_widths_fill_the_bar(self, percents: list[float], total: int, minimum: int) -> None:
        widths = segment_widths(percents, total, minimum)
        assert len(widths) == len(percents)
        assert sum(widths) == total
        assert all(w >= minimum for w in widths)
        ideal = [p / sum(percents) * total for p in percents]
        if all(i >= minimum for i in ideal):  # no segment was bumped up to the minimum
            assert all(abs(w - i) < 1 for w, i in zip(widths, ideal))

    def test_spare_cells_go_to_the_largest_remainders(self) -> None:
        assert segment_widths([1, 1, 1], 10, 1) == [4, 3, 3]  # ties: earliest first
        assert segment_widths([25, 50, 25], 6, 1) == [2, 3, 1]  # 1.5, 3.0, 1.5: the tie goes to the first

    def test_a_minimum_too_large_is_lowered(self) -> None:
        widths = segment_widths([50, 30, 20], 5, 4)
        assert sum(widths) == 5
        assert all(w >= 1 for w in widths)  # lowered to 5 // 3

    @pytest.mark.parametrize('percents', [[], [0.0, 0.0]])
    def test_nothing_to_split(self, percents: list[float]) -> None:
        assert segment_widths(percents, 60, 1) == []


class TestPercentLabel:
    @pytest.mark.parametrize(
        ('percent', 'label'),
        [(0.3, '<1%'), (0, '0%'), (0.6, '1%'), (49.6, '50%'), (99.7, '>99%'), (100, '100%'), (2.5, '2%')],
    )
    def test_labels(self, percent: float, label: str) -> None:
        assert percent_label(percent) == label
