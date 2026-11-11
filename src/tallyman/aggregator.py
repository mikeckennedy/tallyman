"""Statistics aggregation  -  collect per-file counts into language and category summaries."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Optional

from tallyman.counter import FileCount
from tallyman.languages import OTHER_COLOR, Language

CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    'code': 'Code',
    'devops': 'DevOps',
    'design': 'Design',
    'docs': 'Docs',
    'specs': 'Specs',
    'data': 'Data',
}

CATEGORY_ORDER: list[str] = ['code', 'devops', 'design', 'docs', 'specs', 'data']

SMALL_LANGUAGE_THRESHOLD = 2.0  # Percentage below which languages are grouped as "Other" in the bar
OTHER_LABEL = 'Other'


@dataclass(slots=True)
class LanguageStats:
    language: Language
    file_count: int = 0
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0

    @property
    def effective_lines(self) -> int:
        """The one definition of "effective lines": what both outputs count unless ``--with-spaces`` is given.

        Code lines (excluding comments and blanks) for a language with a comment marker,
        and non-blank lines for one without (its comments can't be told apart).
        """
        if self.language.single_line_comment is not None:
            return self.code_lines
        return self.total_lines - self.blank_lines

    def shown_lines(self, *, with_spaces: bool) -> int:
        """The lines the report shows: total lines with ``--with-spaces``, else effective lines."""
        return self.total_lines if with_spaces else self.effective_lines


@dataclass(slots=True)
class CategoryStats:
    name: str  # 'Code', 'DevOps', 'Design', 'Docs', 'Specs', 'Data'
    total_lines: int = 0
    effective_lines: int = 0  # the sum of its languages' LanguageStats.effective_lines
    languages: list[str] = field(default_factory=list)

    def shown_lines(self, *, with_spaces: bool) -> int:
        """The lines the report shows: total lines with ``--with-spaces``, else effective lines."""
        return self.total_lines if with_spaces else self.effective_lines


@dataclass(slots=True)
class TallyResult:
    by_language: list[LanguageStats]  # Sorted by total_lines descending
    by_category: list[CategoryStats]  # In display order: Code, DevOps, Design, Docs, Specs, Data
    grand_total_lines: int = 0
    rust_test_lines: int = 0  # Rust test code left out ([rust] exclude_test_modules), in no other count
    rust_test_files: int = 0  # files that lost at least one line to it


def aggregate(file_results: Iterable[tuple[Language, FileCount]]) -> TallyResult:
    """Consume per-file results and produce aggregated stats.

    Groups by Language object (not name) so that the same language name in
    different categories (e.g. Markdown in docs vs specs) stays separate.

    Rust test code left out by the counter (``FileCount.test_lines``) is summed
    into ``rust_test_lines``, with ``rust_test_files`` counting the files that
    lost any. A file that was all test code (``#![cfg(test)]``) is not counted
    as a file of its language; an empty file still is.
    """
    by_lang: dict[Language, LanguageStats] = {}
    rust_test_lines = rust_test_files = 0

    for language, counts in file_results:
        if counts.test_lines:
            rust_test_lines += counts.test_lines
            rust_test_files += 1
            if not counts.total_lines:
                continue  # all test code (#![cfg(test)]): not a file of this language. An empty file still is.
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
    cat_lines: defaultdict[str, int] = defaultdict(int)
    cat_effective: defaultdict[str, int] = defaultdict(int)
    cat_langs: defaultdict[str, list[str]] = defaultdict(list)
    for stats in sorted_langs:
        cat = stats.language.category
        cat_lines[cat] += stats.total_lines
        cat_effective[cat] += stats.effective_lines
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
        rust_test_lines=rust_test_lines,
        rust_test_files=rust_test_files,
    )


def language_percentages(result: TallyResult, *, with_spaces: bool = False) -> list[tuple[Language, float]]:
    """Return [(Language, percentage), ...] sorted by percentage descending.

    By default uses effective lines (excluding comments and blanks).
    When *with_spaces* is True, uses total lines instead.
    """
    if not result.by_language:
        return []

    total = sum(s.shown_lines(with_spaces=with_spaces) for s in result.by_language)
    if total == 0:
        return []
    pairs = [(s.language, s.shown_lines(with_spaces=with_spaces) / total * 100) for s in result.by_language]

    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


# The report model: what the terminal (display.py) and the image card (image.py) both draw.
# They choose the categories, segments, labels and widths here, and only lay them out themselves.


def language_display_names(result: TallyResult) -> dict[Language, str]:
    """Build display names, appending category when a language name appears in multiple categories."""
    name_categories: dict[str, set[str]] = {}
    for stats in result.by_language:
        name_categories.setdefault(stats.language.name, set()).add(stats.language.category)

    display_names: dict[Language, str] = {}
    for stats in result.by_language:
        if len(name_categories[stats.language.name]) > 1:
            cat_label = CATEGORY_DISPLAY_NAMES.get(stats.language.category, stats.language.category)
            display_names[stats.language] = f'{stats.language.name} ({cat_label.lower()})'
        else:
            display_names[stats.language] = stats.language.name
    return display_names


def active_categories(result: TallyResult, *, with_spaces: bool = False) -> list[CategoryStats]:
    """The categories with any lines, most shown lines first; ties keep CATEGORY_ORDER (the sort is stable)."""
    return sorted(
        (c for c in result.by_category if c.total_lines > 0),
        key=lambda c: c.shown_lines(with_spaces=with_spaces),
        reverse=True,
    )


CATEGORY_LANGUAGES_SHOWN = 3  # a category line names this many of its languages


def category_language_list(category: CategoryStats) -> str:
    """The languages a category line names in parentheses: the first CATEGORY_LANGUAGES_SHOWN, then ', etc'.

    *category.languages* is largest first, so the list names the category's biggest languages.
    """
    shown = ' + '.join(category.languages[:CATEGORY_LANGUAGES_SHOWN])
    return f'{shown}, etc' if len(category.languages) > CATEGORY_LANGUAGES_SHOWN else shown


@dataclass(frozen=True, slots=True)
class BarSegment:
    """One coloured block of the percentage bar, and its legend entry."""

    language: Optional[Language]  # None for the Other segment
    label: str  # display name, e.g. 'Markdown (specs)', or OTHER_LABEL
    color: str  # a Rich colour name: language.color, or OTHER_COLOR
    percent: float


def bar_segments(
    result: TallyResult, *, with_spaces: bool = False, max_languages: Optional[int] = None
) -> list[BarSegment]:
    """The bar's segments, largest first: each language at or above SMALL_LANGUAGE_THRESHOLD, then Other.

    Other holds the languages under the threshold, plus those past the first *max_languages* when that is given
    (the image card names at most five). It is always last, and left out when it would add up to nothing.
    Empty when no language has a line to show, so neither output draws a bar for nothing.
    """
    percentages = language_percentages(result, with_spaces=with_spaces)
    if not percentages:
        return []
    names = language_display_names(result)
    segments = [
        BarSegment(lang, names[lang], lang.color, pct) for lang, pct in percentages if pct >= SMALL_LANGUAGE_THRESHOLD
    ]
    other_pct = sum(pct for _, pct in percentages if pct < SMALL_LANGUAGE_THRESHOLD)
    if max_languages is not None and len(segments) > max_languages:
        other_pct += sum(s.percent for s in segments[max_languages:])
        segments = segments[:max_languages]
    if other_pct > 0:
        segments.append(BarSegment(None, OTHER_LABEL, OTHER_COLOR, other_pct))
    return segments


def segment_widths(percents: Sequence[float], total: int, minimum: int) -> list[int]:
    """Split *total* cells (or pixels) between segments in proportion to *percents*.

    Each segment gets at least *minimum*, unless len(percents) * minimum > total: then the minimum is lowered
    to total // len(percents), which is 0 when there are more segments than cells. The widths add up to *total*
    exactly, and spare cells go to the largest remainders, earliest first on ties.
    """
    percent_sum = sum(percents)
    if not percents or percent_sum <= 0:
        return []
    minimum = min(minimum, total // len(percents))
    # Divide by the sum, not 100, so floating-point error in the percentages can't leak into the widths
    ideal = [p / percent_sum * total for p in percents]
    widths = [max(minimum, math.floor(i)) for i in ideal]
    indexes = range(len(widths))
    while sum(widths) < total:  # hand out the cells flooring left over
        widths[max(indexes, key=lambda i: ideal[i] - widths[i])] += 1  # max() keeps the earliest on ties
    while sum(widths) > total:  # the minimum took cells: give them back from those furthest over their share
        spare = [i for i in indexes if widths[i] > minimum]
        widths[max(spare, key=lambda i: widths[i] - ideal[i])] -= 1
    return widths


def percent_label(percent: float) -> str:
    """A legend percentage: rounded, but never '0%' for a share that isn't nothing, nor '100%' for one short of all."""
    label = f'{percent:.0f}%'
    if label == '0%' and percent > 0:
        return '<1%'
    if label == '100%' and percent < 100:
        return '>99%'
    return label
