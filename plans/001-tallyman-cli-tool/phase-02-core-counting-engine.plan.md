# Phase 2: Core Counting Engine

## Goal

Implement the engine that walks a directory, identifies source files by language, counts lines (total, comments, blanks, code), and aggregates results by language and category. At the end of this phase, `tallyman` produces correct counts and prints them as plain text (color and formatting come in Phase 4).

## Steps

### 2.1  -  Language Registry (`languages.py`)

Define a `Language` dataclass and a registry dict mapping file extensions to languages.

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Language:
    name: str
    category: str            # 'code', 'design', 'docs', 'data'
    color: str               # Rich color name for terminal output
    single_line_comment: str | None   # e.g. '#', '//', '--'
    extensions: tuple[str, ...]       # e.g. ('.py',)
```

**Fields explained:**
- `single_line_comment`  -  The marker that starts a single-line comment. `None` for languages where we skip comment detection in this phase (Markdown, JSON, HTML, CSS  -  these use block comments or have none).
- `category`  -  One of `'code'`, `'design'`, `'docs'`, `'data'`.
- `color`  -  A Rich color name. Chosen to roughly match the GitHub language color wheel where possible.

**Initial language set:**

| Language | Extensions | Comment | Category | Color |
|----------|-----------|---------|----------|-------|
| Python | `.py` | `#` | code | `yellow` |
| Rust | `.rs` | `//` | code | `dark_orange` |
| Go | `.go` | `//` | code | `cyan` |
| JavaScript | `.js`, `.jsx`, `.mjs` | `//` | code | `bright_yellow` |
| TypeScript | `.ts`, `.tsx` | `//` | code | `dodger_blue` |
| Java | `.java` | `//` | code | `orange3` |
| C | `.c`, `.h` | `//` | code | `steel_blue` |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx` | `//` | code | `bright_blue` |
| C# | `.cs` | `//` | code | `green3` |
| Swift | `.swift` | `//` | code | `orange_red1` |
| Kotlin | `.kt`, `.kts` | `//` | code | `medium_purple` |
| Ruby | `.rb` | `#` | code | `red` |
| Shell | `.sh`, `.bash`, `.zsh` | `#` | code | `bright_green` |
| Lua | `.lua` | `--` | code | `blue` |
| PHP | `.php` | `//` | code | `medium_purple3` |
| Perl | `.pl`, `.pm` | `#` | code | `grey62` |
| R | `.r`, `.R` | `#` | code | `bright_blue` |
| Dart | `.dart` | `//` | code | `cyan3` |
| Scala | `.scala` | `//` | code | `red3` |
| Elixir | `.ex`, `.exs` | `#` | code | `dark_violet` |
| Zig | `.zig` | `//` | code | `orange1` |
| CSS | `.css` | None | design | `magenta` |
| SCSS | `.scss` | `//` | design | `hot_pink` |
| LESS | `.less` | `//` | design | `magenta3` |
| HTML | `.html`, `.htm` | None | design | `dark_orange` |
| SVG | `.svg` | None | design | `gold1` |
| Markdown | `.md`, `.mdx` | None | docs | `white` |
| reStructuredText | `.rst` | None | docs | `grey70` |
| TOML | `.toml` | `#` | data | `grey50` |
| YAML | `.yml`, `.yaml` | `#` | data | `light_pink3` |
| JSON | `.json` | None | data | `green_yellow` |
| XML | `.xml` | None | data | `grey58` |
| SQL | `.sql` | `--` | data | `bright_cyan` |

Build a module-level dict: `EXTENSION_MAP: dict[str, Language]` that maps every extension string to its `Language`. This is the lookup table used by the walker.

Provide a helper function:

```python
def identify_language(path: Path) -> Language | None:
    """Return the Language for a file path, or None if unrecognized."""
    return EXTENSION_MAP.get(path.suffix.lower())
```

### 2.2  -  File Walker (`walker.py`)

Walk a project directory tree and yield files that should be counted.

**Responsibilities:**
1. Recursively walk the directory.
2. Skip directories matching gitignore patterns (using `pathspec`).
3. Skip directories excluded in `.tally-config.toml` (loaded via `config.py`, but for this phase pass exclusions as a `set[str]` of relative directory paths).
4. Skip files that aren't recognized by the language registry.
5. Skip binary files (check first 8192 bytes for null bytes).
6. Do not follow symlinks.

**Interface:**

```python
from pathlib import Path
from collections.abc import Iterator

def walk_project(
    root: Path,
    excluded_dirs: set[str],
) -> Iterator[tuple[Path, Language]]:
    """
    Yield (file_path, language) for every countable source file under root.

    excluded_dirs: set of directory paths relative to root that should be skipped
                   (e.g. {'static/external', 'vendor'}).
    """
```

**Gitignore loading:**
- Read `root/.gitignore` if it exists.
- Read `root/.git/info/exclude` if it exists.
- Parse both with `pathspec.PathSpec.from_lines('gitwildmatch', lines)`.
- For each directory encountered during the walk, check if it matches the pathspec or is in `excluded_dirs`. If so, skip the entire subtree.
- Also check individual files against the pathspec.

**Binary detection helper:**

```python
def _is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary."""
    try:
        chunk = path.read_bytes()[:8192]
        return b'\x00' in chunk
    except OSError:
        return True
```

**Walk implementation notes:**
- Use `os.walk()` with `topdown=True` so we can modify the `dirs` list in-place to prune excluded subtrees (this is the standard Python pattern for prunable walks).
- Sort `dirs` in-place for deterministic output.
- Convert paths to `Path` objects for the language lookup.

### 2.3  -  Line Counter (`counter.py`)

Classify each line of a source file.

**Data structure for results:**

```python
from dataclasses import dataclass


@dataclass(slots=True)
class FileCount:
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
```

**Counting function:**

```python
def count_lines(path: Path, language: Language) -> FileCount:
    """
    Read a file and classify each line.

    For languages with a single_line_comment marker:
        - Blank: line.strip() is empty
        - Comment: stripped line starts with the comment marker
        - Code: everything else

    For languages without a single_line_comment marker (HTML, CSS, Markdown, JSON, etc.):
        - Blank: line.strip() is empty
        - Code: everything else
        - comment_lines stays 0

    Handles encoding errors by replacing bad characters (errors='replace').
    """
```

**Implementation notes:**
- Open with `encoding='utf-8', errors='replace'`  -  good enough for line counting.
- The `stripped.startswith(comment_marker)` check is intentionally naive. It will miscount comments inside strings and miss block comments. That's fine for v1. The README already notes multi-line comment detection is a future enhancement.
- For Markdown, there's no concept of "comment lines"  -  just blank vs. content. This matches the sketch output ("2,102 lines / 1,932 excluding blank lines" with no mention of comments).

### 2.4  -  Aggregator (`aggregator.py`)

Collect per-file counts into per-language and per-category summaries.

**Data structures:**

```python
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
        """Lines excluding blank lines (for docs that have no comment concept)."""
        return self.total_lines - self.blank_lines


@dataclass
class CategoryStats:
    name: str          # 'Code', 'Design', 'Docs', 'Data'
    total_lines: int = 0
    languages: list[str] = field(default_factory=list)


@dataclass
class TallyResult:
    by_language: list[LanguageStats]    # Sorted by total_lines descending
    by_category: list[CategoryStats]    # Code, Design, Docs, Data
    grand_total_lines: int = 0
```

**Aggregation function:**

```python
def aggregate(file_results: Iterator[tuple[Language, FileCount]]) -> TallyResult:
    """
    Consume per-file results and produce aggregated stats.

    - Groups by language name.
    - Sorts languages by total_lines descending.
    - Computes category totals.
    - Computes grand total.
    """
```

**Percentage calculation** (used by display in Phase 4):

```python
def language_percentages(result: TallyResult) -> list[tuple[str, str, float]]:
    """
    Return [(language_name, color, percentage), ...] sorted by percentage descending.
    Percentage is of total lines across all languages.
    """
```

### 2.5  -  Wire it all together in `cli.py`

Update `cli.py` to call the real engine:

```python
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.path).resolve()

    if not root.is_dir():
        print(f'Error: {root} is not a directory', file=sys.stderr)
        sys.exit(1)

    # Load config (Phase 3  -  for now, empty set)
    excluded_dirs: set[str] = set()

    # Walk and count
    file_results = []
    for file_path, language in walk_project(root, excluded_dirs):
        counts = count_lines(file_path, language)
        file_results.append((language, counts))

    # Aggregate
    result = aggregate(iter(file_results))

    # Display (Phase 4  -  for now, plain text)
    for stats in result.by_language:
        print(f'{stats.language.name}: {stats.total_lines:,} lines, '
              f'{stats.non_blank_non_comment:,} excluding comments and blank lines')
```

This gives us a working tool with plain-text output. Phases 3 and 4 layer config and formatting on top.

### 2.6  -  Tests

Write tests for the core logic. Use `tmp_path` fixtures to create small file trees.

**`test_languages.py`:**
- `identify_language` returns correct Language for known extensions.
- `identify_language` returns None for unknown extensions.
- Every extension in the registry maps to exactly one language.

**`test_counter.py`:**
- Python file with comments, blanks, and code → correct counts.
- JavaScript file with `//` comments → correct counts.
- Markdown file → blank_lines and total correct, comment_lines is 0.
- JSON file → no comments counted.
- Empty file → all zeros.
- File with encoding issues → doesn't crash.

**`test_walker.py`:**
- Walks a directory with mixed files → yields only recognized languages.
- Respects a `.gitignore` file (create one in tmp_path with a pattern, verify those files are skipped).
- Skips directories in `excluded_dirs`.
- Doesn't yield binary files.
- Doesn't follow symlinks.

**`test_aggregator.py`:**
- Feed known FileCount results → verify LanguageStats totals.
- Verify sort order is by total_lines descending.
- Verify category grouping is correct.
- Verify percentages sum to ~100%.

## Acceptance Criteria

- [ ] `tallyman /path/to/project` scans the directory and prints per-language line counts
- [ ] Gitignored files and directories are automatically excluded
- [ ] Binary files are skipped
- [ ] Symlinks are not followed
- [ ] At least 30 languages are recognized
- [ ] Line counts distinguish blank, comment, and code lines for languages with single-line comment markers
- [ ] Languages without comment markers report blank vs. non-blank only
- [ ] Results are sorted by total lines descending
- [ ] Category totals (Code, Design, Docs, Data) are computed
- [ ] All tests pass
- [ ] Ruff passes with no errors
