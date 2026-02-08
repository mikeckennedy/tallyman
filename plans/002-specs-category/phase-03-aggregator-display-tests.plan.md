# Phase 3: Aggregator, Display & Tests

## Goal

Make the Specs category render correctly in the output report and add comprehensive test coverage for the entire feature. After this phase, the feature is complete and production-ready.

## Steps

### 3.1  -  Add Specs to Category Constants (`aggregator.py`)

Add `'specs'` to both the display name mapping and the ordering:

```python
CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    'code': 'Code',
    'design': 'Design',
    'docs': 'Docs',
    'specs': 'Specs',
    'data': 'Data',
}

CATEGORY_ORDER: list[str] = ['code', 'design', 'docs', 'specs', 'data']
```

Specs appears between Docs and Data  -  logically it's documentation-adjacent but distinct.

### 3.2  -  Change Aggregation Grouping Key (`aggregator.py`)

**Problem:** The current aggregator groups by `language.name`. When Markdown appears in both `docs` and `specs` categories (via `as_spec()`), both would merge into one `LanguageStats` entry, losing the category distinction.

**Solution:** Group by the `Language` object itself. Since `Language` is frozen with slots, it's hashable. Two Language instances with the same name but different categories are distinct keys.

Change the `aggregate` function:

```python
def aggregate(file_results: Iterable[tuple[Language, FileCount]]) -> TallyResult:
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

    # Build category stats (unchanged  -  already uses stats.language.category)
    # ...
```

The rest of the function (category stats building, grand total) works unchanged because it already reads `stats.language.category` from each `LanguageStats`.

### 3.3  -  Detect Duplicate Language Names for Display

When the same language name appears in multiple categories (e.g., Markdown in both docs and specs), the per-language display section needs to distinguish them. Add a helper to detect this:

```python
def _language_display_names(result: TallyResult) -> dict[Language, str]:
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
```

Import `CATEGORY_DISPLAY_NAMES` from `aggregator` in `display.py`.

### 3.4  -  Update Per-Language Display (`display.py`)

Use the display name helper in `_display_languages`:

```python
def _display_languages(console: Console, result: TallyResult) -> None:
    display_names = _language_display_names(result)

    for stats in result.by_language:
        lang = stats.language
        name = display_names[lang]

        console.print(_language_header(name, lang.color))

        total_str = f'{stats.total_lines:,}'

        if lang.single_line_comment is not None:
            effective_str = f'{stats.non_blank_non_comment:,}'
            console.print(f'  {total_str:>10} lines of code')
            console.print(f'  {effective_str:>10} excluding comments and blank lines')
        else:
            non_blank_str = f'{stats.non_blank:,}'
            console.print(f'  {total_str:>10} lines')
            console.print(f'  {non_blank_str:>10} excluding blank lines')
```

**When there's only Markdown in docs (no specs), the header reads `Markdown` as before  -  no suffix.**

**When Markdown appears in both docs and specs:**
```
──────────  Markdown (docs)  ──────────
       500 lines
       420 excluding blank lines
──────────  Markdown (specs)  ──────────
     3,200 lines
     2,800 excluding blank lines
```

### 3.5  -  Update `language_percentages` (`aggregator.py`)

The percentage bar function also needs to use display-aware names. Currently it returns `language.name`, which would be duplicated. Two options:

**Option A:** Return the Language object instead of the name string, and let the display layer resolve names.

**Option B:** Deduplicate in the percentage function itself.

Go with **Option A** for clean separation:

```python
def language_percentages(result: TallyResult) -> list[tuple[Language, float]]:
    """Return [(Language, percentage), ...] sorted by percentage descending."""
    if result.grand_total_lines == 0:
        return []
    return [
        (s.language, s.total_lines / result.grand_total_lines * 100)
        for s in result.by_language
    ]
```

Update `_display_percentage_bar` in `display.py` to use `Language` objects and resolve display names:

```python
def _display_percentage_bar(console: Console, result: TallyResult) -> None:
    if result.grand_total_lines == 0:
        return

    console.print()

    display_names = _language_display_names(result)
    percentages = language_percentages(result)

    # Group small languages into "Other"
    main_langs = [(lang, pct) for lang, pct in percentages if pct >= SMALL_LANGUAGE_THRESHOLD]
    other_pct = sum(pct for _, pct in percentages if pct < SMALL_LANGUAGE_THRESHOLD)
    if other_pct > 0:
        main_langs.append((None, other_pct))  # None signals "Other"

    # Build the colored bar
    bar = Text()
    chars_used = 0
    for i, (lang, pct) in enumerate(main_langs):
        color = lang.color if lang else 'grey50'
        if i == len(main_langs) - 1:
            segment_width = BAR_WIDTH - chars_used
        else:
            segment_width = max(1, round(pct / 100 * BAR_WIDTH))
            segment_width = min(segment_width, BAR_WIDTH - chars_used)
        if segment_width > 0:
            bar.append('█' * segment_width, style=color)
            chars_used += segment_width

    console.print('  ', end='')
    console.print(bar)

    # Legend line
    legend_parts = []
    for lang, pct in main_langs:
        if lang is None:
            legend_parts.append(f'[grey50]Other[/grey50] {pct:.0f}%')
        else:
            name = display_names.get(lang, lang.name)
            legend_parts.append(f'[{lang.color}]{name}[/{lang.color}] {pct:.0f}%')
    legend = '  ·  '.join(legend_parts)
    console.print(f'  {legend}')
```

### 3.6  -  Tests

#### `test_languages.py`  -  Add spec variant tests

```python
def test_as_spec_creates_spec_category():
    md = identify_language(Path('test.md'))
    spec_md = as_spec(md)
    assert spec_md.category == 'specs'
    assert spec_md.name == 'Markdown'
    assert spec_md.color == md.color
    assert spec_md.extensions == md.extensions

def test_as_spec_caching():
    md = identify_language(Path('test.md'))
    assert as_spec(md) is as_spec(md)  # Same object

def test_as_spec_rejects_non_docs():
    py = identify_language(Path('test.py'))
    with pytest.raises(ValueError):
        as_spec(py)

def test_as_spec_rst():
    rst = identify_language(Path('test.rst'))
    spec_rst = as_spec(rst)
    assert spec_rst.category == 'specs'
    assert spec_rst.name == 'reStructuredText'
```

#### `test_config.py`  -  Add spec config tests

```python
def test_save_load_with_specs(tmp_path):
    config_path = tmp_path / '.tally-config.toml'
    save_config(config_path, {'vendor'}, {'plans', 'docs/arch'})
    config = load_config(config_path)
    assert config.excluded_dirs == {'vendor'}
    assert config.spec_dirs == {'plans', 'docs/arch'}

def test_load_config_without_specs_section(tmp_path):
    """Backward compatibility: configs without [specs] return empty spec_dirs."""
    config_path = tmp_path / '.tally-config.toml'
    config_path.write_text('[exclude]\ndirectories = ["vendor"]\n')
    config = load_config(config_path)
    assert config.excluded_dirs == {'vendor'}
    assert config.spec_dirs == set()

def test_save_config_no_specs_omits_section(tmp_path):
    """When spec_dirs is empty, [specs] section is not written."""
    config_path = tmp_path / '.tally-config.toml'
    save_config(config_path, {'vendor'}, set())
    content = config_path.read_text()
    assert '[specs]' not in content
```

#### `test_walker.py`  -  Add spec directory detection tests

```python
def test_auto_detect_specs_dir(tmp_path):
    """Directory named 'specs' auto-detects as spec directory."""
    specs = tmp_path / 'specs'
    specs.mkdir()
    (specs / 'design.md').write_text('# Design spec\n')
    (tmp_path / 'README.md').write_text('# README\n')

    results = list(walk_project(tmp_path, set()))
    readme_lang = next(lang for path, lang in results if path.name == 'README.md')
    spec_lang = next(lang for path, lang in results if path.name == 'design.md')

    assert readme_lang.category == 'docs'
    assert spec_lang.category == 'specs'

def test_auto_detect_plans_dir(tmp_path):
    """Directory named 'plans' auto-detects as spec directory."""
    plans = tmp_path / 'plans'
    plans.mkdir()
    (plans / 'phase1.md').write_text('# Phase 1\n')

    results = list(walk_project(tmp_path, set()))
    lang = next(lang for _, lang in results if True)
    assert lang.category == 'specs'

def test_user_designated_spec_dir(tmp_path):
    """User-designated spec dirs via spec_dirs parameter."""
    docs = tmp_path / 'docs' / 'architecture'
    docs.mkdir(parents=True)
    (docs / 'overview.md').write_text('# Architecture\n')

    results = list(walk_project(tmp_path, set(), spec_dirs={'docs/architecture'}))
    lang = next(lang for _, lang in results if True)
    assert lang.category == 'specs'

def test_spec_cascades_to_subdirs(tmp_path):
    """Spec status cascades to child directories."""
    sub = tmp_path / 'specs' / 'api'
    sub.mkdir(parents=True)
    (sub / 'endpoints.md').write_text('# Endpoints\n')

    results = list(walk_project(tmp_path, set()))
    lang = next(lang for _, lang in results if True)
    assert lang.category == 'specs'

def test_non_docs_in_spec_dir_unchanged(tmp_path):
    """Python files in spec dirs keep their 'code' category."""
    specs = tmp_path / 'specs'
    specs.mkdir()
    (specs / 'helper.py').write_text('x = 1\n')

    results = list(walk_project(tmp_path, set()))
    lang = next(lang for _, lang in results if True)
    assert lang.category == 'code'

def test_spec_dir_name_case_insensitive(tmp_path):
    """Auto-detection is case-insensitive."""
    specs = tmp_path / 'Specs'
    specs.mkdir()
    (specs / 'doc.md').write_text('# Doc\n')

    results = list(walk_project(tmp_path, set()))
    lang = next(lang for _, lang in results if True)
    assert lang.category == 'specs'

def test_excluded_spec_dir_not_walked(tmp_path):
    """An excluded spec dir is not walked at all."""
    specs = tmp_path / 'specs'
    specs.mkdir()
    (specs / 'doc.md').write_text('# Doc\n')

    results = list(walk_project(tmp_path, {'specs'}))
    assert len(results) == 0
```

#### `test_aggregator.py`  -  Add specs category tests

```python
def test_specs_category_in_output():
    """Spec-category languages produce a Specs category in results."""
    md = Language('Markdown', 'docs', 'white', None, ('.md',))
    spec_md = Language('Markdown', 'specs', 'white', None, ('.md',))

    results = [
        (md, FileCount(total_lines=100, blank_lines=20)),
        (spec_md, FileCount(total_lines=500, blank_lines=50)),
    ]

    tally = aggregate(results)

    # Should have two separate LanguageStats entries
    assert len(tally.by_language) == 2

    # Should have both Docs and Specs categories
    cat_names = [c.name for c in tally.by_category]
    assert 'Docs' in cat_names
    assert 'Specs' in cat_names

    docs_cat = next(c for c in tally.by_category if c.name == 'Docs')
    specs_cat = next(c for c in tally.by_category if c.name == 'Specs')
    assert docs_cat.effective_lines == 80   # 100 - 20 blank
    assert specs_cat.effective_lines == 450  # 500 - 50 blank

def test_aggregation_groups_by_language_object():
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
```

### 3.7  -  Run Full Test Suite and Lint

After all changes:

```bash
python -m pytest tests/ -v
ruff check src/ tests/
ruff format --check src/ tests/
```

Fix any failures or lint issues before considering the phase complete.

## Acceptance Criteria

- [ ] `'specs'` appears in `CATEGORY_ORDER` between `'docs'` and `'data'`
- [ ] `CATEGORY_DISPLAY_NAMES` maps `'specs'` → `'Specs'`
- [ ] Aggregator groups by `Language` object, not `language.name`
- [ ] Markdown appearing in both docs and specs produces two separate `LanguageStats`
- [ ] Category totals show Specs line with correct effective line count
- [ ] Per-language headers show `Markdown (docs)` / `Markdown (specs)` only when both exist
- [ ] Per-language headers show just `Markdown` when only one category has Markdown
- [ ] Percentage bar handles disambiguated names correctly
- [ ] All new tests pass
- [ ] All existing tests pass (no regressions)
- [ ] Ruff check and format pass
