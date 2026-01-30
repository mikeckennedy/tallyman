from tallyman.aggregator import LanguageStats, TallyResult, aggregate, language_percentages
from tallyman.counter import FileCount
from tallyman.languages import Language


def _lang(name: str, category: str = 'code', comment: str | None = '#') -> Language:
    return Language(name, category, 'white', comment, (f'.{name.lower()}',))


class TestAggregate:
    def test_single_language(self):
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

    def test_multiple_languages_sorted_descending(self):
        py = _lang('Python')
        rs = _lang('Rust')
        results = [
            (py, FileCount(total_lines=50, code_lines=40, comment_lines=5, blank_lines=5)),
            (rs, FileCount(total_lines=200, code_lines=180, comment_lines=10, blank_lines=10)),
        ]
        tally = aggregate(results)
        assert tally.by_language[0].language.name == 'Rust'
        assert tally.by_language[1].language.name == 'Python'

    def test_category_grouping(self):
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

    def test_grand_total(self):
        py = _lang('Python')
        results = [
            (py, FileCount(total_lines=100, code_lines=80, comment_lines=10, blank_lines=10)),
        ]
        tally = aggregate(results)
        assert tally.grand_total_lines == 100

    def test_empty_results(self):
        tally = aggregate([])
        assert tally.by_language == []
        assert tally.by_category == []
        assert tally.grand_total_lines == 0


class TestLanguagePercentages:
    def test_single_language_is_100_percent(self):
        py = _lang('Python')
        tally = TallyResult(
            by_language=[LanguageStats(language=py, total_lines=100)],
            by_category=[],
            grand_total_lines=100,
        )
        pcts = language_percentages(tally)
        assert len(pcts) == 1
        assert pcts[0][0] == 'Python'
        assert pcts[0][2] == 100.0

    def test_percentages_sum_to_100(self):
        py = _lang('Python')
        rs = _lang('Rust')
        tally = TallyResult(
            by_language=[
                LanguageStats(language=py, total_lines=75),
                LanguageStats(language=rs, total_lines=25),
            ],
            by_category=[],
            grand_total_lines=100,
        )
        pcts = language_percentages(tally)
        total = sum(p[2] for p in pcts)
        assert abs(total - 100.0) < 0.01

    def test_empty_returns_empty(self):
        tally = TallyResult(by_language=[], by_category=[], grand_total_lines=0)
        assert language_percentages(tally) == []
