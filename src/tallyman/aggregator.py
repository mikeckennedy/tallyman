"""Statistics aggregation  -  collect per-file counts into language and category summaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from tallyman.counter import FileCount
from tallyman.languages import Language

CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    'code': 'Code',
    'design': 'Design',
    'docs': 'Docs',
    'specs': 'Specs',
    'data': 'Data',
}

CATEGORY_ORDER: list[str] = ['code', 'design', 'docs', 'specs', 'data']


@dataclass(slots=True)
class LanguageStats:
    language: Language
    file_count: int = 0
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0

    @property
    def non_blank_non_comment(self) -> int:
        """Lines excluding comments and blank lines."""
        return self.code_lines

    @property
    def non_blank(self) -> int:
        """Lines excluding blank lines (for languages without comment detection)."""
        return self.total_lines - self.blank_lines


@dataclass
class CategoryStats:
    name: str  # 'Code', 'Design', 'Docs', 'Specs', 'Data'
    total_lines: int = 0
    effective_lines: int = 0  # non-blank non-comment (or non-blank for languages without comment detection)
    languages: list[str] = field(default_factory=list)


@dataclass
class TallyResult:
    by_language: list[LanguageStats]  # Sorted by total_lines descending
    by_category: list[CategoryStats]  # In display order: Code, Design, Docs, Specs, Data
    grand_total_lines: int = 0


def aggregate(file_results: Iterable[tuple[Language, FileCount]]) -> TallyResult:
    """Consume per-file results and produce aggregated stats.

    Groups by Language object (not name) so that the same language name in
    different categories (e.g. Markdown in docs vs specs) stays separate.
    """
    by_lang: dict[Language, LanguageStats] = {}

    for language, counts in file_results:
        if language not in by_lang:
            by_lang[language] = LanguageStats(language=language)
        stats = by_lang[language]
        stats.file_count += 1
        stats.total_lines += counts.total_lines
        stats.code_lines += counts.code_lines
        stats.comment_lines += counts.comment_lines
        stats.blank_lines += counts.blank_lines

    # Sort by total lines descending
    sorted_langs = sorted(by_lang.values(), key=lambda s: s.total_lines, reverse=True)

    # Build category stats
    cat_lines: dict[str, int] = {}
    cat_effective: dict[str, int] = {}
    cat_langs: dict[str, list[str]] = {}
    for stats in sorted_langs:
        cat = stats.language.category
        cat_lines[cat] = cat_lines.get(cat, 0) + stats.total_lines
        if stats.language.single_line_comment is not None:
            cat_effective[cat] = cat_effective.get(cat, 0) + stats.non_blank_non_comment
        else:
            cat_effective[cat] = cat_effective.get(cat, 0) + stats.non_blank
        if cat not in cat_langs:
            cat_langs[cat] = []
        cat_langs[cat].append(stats.language.name)

    categories = []
    for cat_key in CATEGORY_ORDER:
        if cat_key in cat_lines:
            categories.append(
                CategoryStats(
                    name=CATEGORY_DISPLAY_NAMES[cat_key],
                    total_lines=cat_lines[cat_key],
                    effective_lines=cat_effective[cat_key],
                    languages=cat_langs[cat_key],
                )
            )

    grand_total = sum(s.total_lines for s in sorted_langs)

    return TallyResult(
        by_language=sorted_langs,
        by_category=categories,
        grand_total_lines=grand_total,
    )


def language_percentages(result: TallyResult) -> list[tuple[Language, float]]:
    """Return [(Language, percentage), ...] sorted by percentage descending.

    Percentage is of total lines across all languages.
    """
    if result.grand_total_lines == 0:
        return []
    return [(s.language, s.total_lines / result.grand_total_lines * 100) for s in result.by_language]
