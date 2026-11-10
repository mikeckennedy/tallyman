from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Optional

import pytest

from tallyman.gitignore import find_git_root, load_gitignore
from tallyman.tui.setup_app import SetupApp, SetupTree
from tallyman.walker import walk_project

X = 'x = 1\n'


def _make(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _walked(root: Path) -> set[str]:
    """Return the POSIX paths, relative to *root*, that walk_project yields."""
    return {p.relative_to(root).as_posix() for p, _ in walk_project(root, set())}


class TestFindGitRoot:
    def test_finds_git_root(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        assert find_git_root(tmp_path) == tmp_path

    def test_finds_git_root_from_subdirectory(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        assert find_git_root(sub) == tmp_path

    def test_returns_none_when_no_git(self, tmp_path: Path):
        assert find_git_root(tmp_path) is None


class TestLoadGitignore:
    def test_loads_gitignore(self, tmp_path: Path):
        (tmp_path / '.gitignore').write_text('node_modules/\n*.log\n')
        spec = load_gitignore(tmp_path)
        assert spec.match_file('node_modules/')
        assert spec.match_file('error.log')
        assert not spec.match_file('main.py')

    def test_no_gitignore(self, tmp_path: Path):
        spec = load_gitignore(tmp_path)
        assert not spec.match_file('anything.py')

    def test_loads_git_info_exclude(self, tmp_path: Path):
        git_info = tmp_path / '.git' / 'info'
        git_info.mkdir(parents=True)
        (git_info / 'exclude').write_text('secret/\n')
        spec = load_gitignore(tmp_path)
        assert spec.match_file('secret/')

    def test_loads_gitignore_from_parent_repo(self, tmp_path: Path):
        """Running from a subdirectory should find the repo root .gitignore."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.gitignore').write_text('node_modules/\n*.log\n')
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        spec = load_gitignore(sub)
        assert spec.match_file('node_modules/')
        assert spec.match_file('error.log')

    def test_loads_intermediate_gitignore(self, tmp_path: Path):
        """Collects .gitignore files between git root and analysis dir."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.gitignore').write_text('*.log\n')
        src = tmp_path / 'src'
        src.mkdir()
        (src / '.gitignore').write_text('vendor/\n')
        app = src / 'app'
        app.mkdir()
        spec = load_gitignore(app)
        assert spec.match_file('error.log')
        assert spec.match_file('vendor/')

    def test_add_directory_is_idempotent(self, tmp_path: Path):
        """A second registration of the same directory must not re-read its .gitignore."""
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / '.gitignore').write_text('*.log\n')
        spec = load_gitignore(tmp_path)
        spec.add_directory('sub', sub)
        (sub / '.gitignore').write_text('*.md\n')
        spec.add_directory('sub', sub)
        assert spec.match_file('sub/error.log')
        assert not spec.match_file('sub/notes.md')

    def test_gitignore_does_not_apply_to_its_own_directory(self, tmp_path: Path):
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / '.gitignore').write_text('*\n')
        spec = load_gitignore(tmp_path)
        spec.add_directory('sub', sub)
        assert not spec.match_file('sub/')
        assert spec.match_file('sub/anything.py')

    def test_unreadable_gitignore_is_skipped(self, tmp_path: Path):
        """A .gitignore that can't be read (here, a directory by that name) must not abort the walk."""
        (tmp_path / 'sub' / '.gitignore').mkdir(parents=True)
        (tmp_path / 'sub' / 'a.py').write_text(X)
        assert _walked(tmp_path) == {'sub/a.py'}

    def test_bom_does_not_break_first_pattern(self, tmp_path: Path):
        (tmp_path / '.gitignore').write_text('\ufeff*.md\n')
        (tmp_path / 'a.md').write_text('# a\n')
        (tmp_path / 'a.py').write_text(X)
        assert _walked(tmp_path) == {'a.py'}


class TestNestedGitignore:
    """Each .gitignore applies to its own directory, at any depth, as git does."""

    def test_nested_gitignore_below_root(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'app.py': X, 'sub/.gitignore': 'generated/\n', 'sub/generated/big.py': X})
        assert _walked(tmp_path) == {'app.py'}

    def test_self_ignoring_directory(self, tmp_path: Path):
        """uv and virtualenv write a '*' .gitignore inside the venv they create."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'venv2/.gitignore': '*\n', 'venv2/lib/x.py': X, 'venv2/top.py': X})
        assert _walked(tmp_path) == set()

    def test_intermediate_anchored_pattern(self, tmp_path: Path):
        """'/build' in sub/.gitignore means sub/build, not sub/sub/build."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path, {'sub/.gitignore': '/build\n', 'sub/build/out.py': X, 'sub/sub/build/x.py': X, 'sub/keep.py': X}
        )
        assert _walked(tmp_path / 'sub') == {'keep.py', 'sub/build/x.py'}

    def test_intermediate_pattern_anchored_to_its_own_directory(self, tmp_path: Path):
        """'/sub/keep.py' in sub/.gitignore means sub/sub/keep.py, so sub/keep.py stays."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.gitignore': '/sub/keep.py\n', 'sub/keep.py': X})
        assert _walked(tmp_path / 'sub') == {'keep.py'}

    def test_lazy_gitignore_below_a_subdirectory_scan(self, tmp_path: Path):
        """Scanning repo/sub, a .gitignore in sub/inner is scoped to sub/inner."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/inner/.gitignore': '/gen/\n', 'sub/inner/gen/a.py': X, 'sub/gen/b.py': X})
        assert _walked(tmp_path / 'sub') == {'gen/b.py'}

    def test_deeper_gitignore_re_includes(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                '.gitignore': '*.md\n',
                'docs/.gitignore': '!keep.md\n',
                'docs/keep.md': X,
                'docs/drop.md': X,
                'top.md': X,
            },
        )
        assert _walked(tmp_path) == {'docs/keep.md'}

    def test_root_gitignore_outranks_info_exclude(self, tmp_path: Path):
        (tmp_path / '.git' / 'info').mkdir(parents=True)
        (tmp_path / '.git' / 'info' / 'exclude').write_text('*.py\n')
        _make(tmp_path, {'.gitignore': '!keep.py\n', 'keep.py': X, 'drop.py': X})
        assert _walked(tmp_path) == {'keep.py'}

    def test_nested_gitignore_without_git_repo(self, tmp_path: Path):
        _make(tmp_path, {'app.py': X, 'sub/.gitignore': 'generated/\n', 'sub/generated/big.py': X})
        assert _walked(tmp_path) == {'app.py'}


class TestNegation:
    """Negations judge only the entry they match, never what lies beneath it."""

    def test_whitelist_style(self, tmp_path: Path):
        """'*' then '!*/' then '!*.py' keeps every .py file at any depth."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': '*\n!*/\n!*.py\n', 'a.py': X, 'a.md': X, 'sub/b.py': X, 'sub/b.md': X})
        assert _walked(tmp_path) == {'a.py', 'sub/b.py'}

    def test_whitelist_named_directory(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': '*\n!src/\n!*.py\n', 'src/b.py': X, 'src/b.md': X, 'other/c.py': X})
        assert _walked(tmp_path) == {'src/b.py'}

    def test_deeper_negated_directory_does_not_re_include_its_contents(self, tmp_path: Path):
        """'!dist/' re-includes the dist directory, but '*.md' still applies inside it."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                '.gitignore': '*.md\ndist/\n',
                'pkg/.gitignore': '!dist/\n',
                'pkg/dist/notes.md': X,
                'pkg/dist/deep/n.md': X,
                'pkg/dist/a.py': X,
            },
        )
        assert _walked(tmp_path) == {'pkg/dist/a.py'}

    def test_deeper_negated_name_does_not_re_include_its_contents(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path, {'.gitignore': '*.md\n', 'pkg/.gitignore': '!docs\n', 'pkg/docs/notes.md': X, 'pkg/docs/a.py': X}
        )
        assert _walked(tmp_path) == {'pkg/docs/a.py'}

    def test_scan_root_inside_ignored_directory(self, tmp_path: Path):
        """Git never looks inside an ignored directory, so a .gitignore there can't re-include."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': 'build/\n', 'build/.gitignore': '!*.py\n', 'build/a.py': X})
        assert _walked(tmp_path / 'build') == set()


class TestSetupTuiAgrees:
    def test_tui_marks_nested_gitignored_directory(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.gitignore': 'generated/\n', 'sub/generated/a.py': X, 'sub/src/b.py': X})

        async def labels() -> dict[str, str]:
            app = SetupApp(tmp_path, load_gitignore(tmp_path), set(), set())
            async with app.run_test(size=(100, 30)):
                found: dict[str, str] = {}

                def collect(node) -> None:
                    if node.data:
                        found[str(node.data['path'])] = node.label.plain
                    for child in node.children:
                        collect(child)

                collect(app.query_one(SetupTree).root)
                return found

        result = asyncio.run(labels())
        assert result['sub/generated'].endswith('(gitignored)')
        assert not result['sub/src'].endswith('(gitignored)')


# (pattern, entry, ignored). Entries ending in '/' are directories. Every row was checked against git.
_PATTERN_CASES = [
    ('*.py', 'a.py', True),
    ('*.py', 'sub/a.py', True),
    ('/a.py', 'sub/a.py', False),
    ('a/b.py', 'a/b.py', True),
    ('a/b.py', 'x/a/b.py', False),
    ('build/', 'build/', True),
    ('build/', 'build', False),
    ('d//', 'd/', False),
    ('a**b', 'axxb', True),
    ('**', 'anything', True),
    ('**/foo', 'x/y/foo', True),
    ('a/**/z', 'a/z', True),
    ('a/**/z', 'a/b/c/z', True),
    ('logs/**', 'logs/', False),
    ('logs/**', 'logs/a', True),
    ('?x', 'ax', True),
    ('?x', 'x', False),
    ('\\*', '*', True),
    ('\\*', 'a', False),
    ('\\#a', '#a', True),
    ('# c', '# c', False),
    ('\\!b', '!b', True),
    ('foo\\ ', 'foo ', True),
    ('bar  ', 'bar', True),
    ('[ab]x', 'ax', True),
    ('[ab]x', 'cx', False),
    ('[!a]x', 'bx', True),
    ('[!a]x', 'ax', False),
    ('[^a]x', 'bx', True),
    ('[]a]x', ']x', True),
    ('[a-c]x', 'bx', True),
    ('[a-]x', '-x', True),
    ('[-a]x', '-x', True),
    ('[z-a]x', 'zx', True),
    ('[z-a]x', 'ax', False),
    ('[c-a]q', 'bq', False),
    ('[--0]x', '.x', True),
    ('[+--]y', ',y', True),
    ('[[:digit:]]x', '1x', True),
    ('[[:digit:]]x', 'ax', False),
    ('[![:alpha:]]z', '1z', True),
    ('[![:alpha:]]z', 'az', False),
    ('[[:upper:][:digit:]]y', 'Ay', True),
    ('[[:upper:][:digit:]]y', '3y', True),
    ('[[:upper:][:digit:]]y', 'ay', False),
    ('[[:bogus:]]x', 'bx', False),
    ('foo[bar', 'foo[bar', False),
    ('[x', '[x', False),
    ('[]x', '[]x', False),
    ('a[/]b', 'a/b', False),
    ('/', 'a', False),
]


@pytest.mark.parametrize(('pattern', 'entry', 'ignored'), _PATTERN_CASES)
def test_pattern_compiler(tmp_path: Path, pattern: str, entry: str, ignored: bool):
    """Each gitignore pattern judges an entry as git does, with no crash or warning on odd input."""
    (tmp_path / '.gitignore').write_text(pattern + '\n')
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert load_gitignore(tmp_path).match_file(entry) is ignored


def test_only_newline_separates_patterns(tmp_path: Path):
    """str.splitlines() would split on the form feed; git does not."""
    (tmp_path / '.gitignore').write_bytes(b'a\x0cb.py\r\n')
    spec = load_gitignore(tmp_path)
    assert spec.match_file('a\x0cb.py')
    assert not spec.match_file('b.py')


# --- Parity with git itself -------------------------------------------------------------------------------------------

_GIT_CASES = [
    pytest.param(
        {'.gitignore': '*\n!*/\n!*.py\n', 'a.py': X, 'a.md': X, 'sub/b.py': X, 'sub/deep/c.md': X},
        '',
        None,
        id='whitelist',
    ),
    pytest.param(
        {'.gitignore': '*.md\ndist/\n', 'pkg/.gitignore': '!dist/\n', 'pkg/dist/n.md': X, 'pkg/dist/a.py': X},
        '',
        None,
        id='neg-dir-across-files',
    ),
    pytest.param(
        {'.gitignore': '*.md\n', 'docs/.gitignore': '!keep.md\n', 'docs/keep.md': X, 'docs/drop.md': X, 'top.md': X},
        '',
        None,
        id='neg-across-files',
    ),
    pytest.param(
        {'.gitignore': 'build/\n', 'build/a.py': X, 'src/build': X, 'src/build.py': X, 'x/build/b.py': X},
        '',
        None,
        id='dir-only',
    ),
    pytest.param(
        {
            '.gitignore': '**/gen/*.py\n!**/gen/keep.py\na/**/z.py\n',
            'gen/a.py': X,
            'gen/keep.py': X,
            'p/q/gen/a.py': X,
            'a/b/c/z.py': X,
            'b/a/z.py': X,
        },
        '',
        None,
        id='double-star',
    ),
    pytest.param(
        {
            '.gitignore': 'logs/**\n!logs/keep/\n!logs/keep/**\nabc/**/\n',
            'logs/a.py': X,
            'logs/keep/b.py': X,
            'abc/x.py': X,
            'abc/d/y.py': X,
        },
        '',
        None,
        id='trailing-double-star',
    ),
    pytest.param(
        {
            '.gitignore': 'a/b.py\n',
            'sub/.gitignore': 'c/d.py\n',
            'a/b.py': X,
            'x/a/b.py': X,
            'sub/c/d.py': X,
            'sub/x/c/d.py': X,
        },
        '',
        None,
        id='middle-slash',
    ),
    pytest.param(
        {'sub/.gitignore': '../top.py\n/sub\nsub/inner.py\n', 'top.py': X, 'sub/inner.py': X, 'sub/sub/inner.py': X},
        '',
        None,
        id='nested-cannot-reach-parent',
    ),
    pytest.param(
        {
            '.gitignore': '*.py\n',
            'a/.gitignore': '!*.py\n',
            'a/b/.gitignore': 'no.py\n',
            'x.py': X,
            'a/y.py': X,
            'a/b/no.py': X,
            'a/b/c/no.py': X,
        },
        'a/b',
        None,
        id='three-levels-from-subdir',
    ),
    pytest.param(
        {'.gitignore': '!keep.py\n', 'keep.py': X, 'drop.py': X}, '', '*.py\n', id='gitignore-outranks-exclude'
    ),
    pytest.param(
        {'sub/a.py': X, 'sub/sub/a.py': X, 'sub/b.py': X}, 'sub', '/sub/a.py\n', id='anchored-exclude-from-subdir'
    ),
    pytest.param(
        {'.gitignore': 'build/\n', 'build/.gitignore': '!*.py\n', 'build/a.py': X},
        'build',
        None,
        id='scan-inside-ignored',
    ),
    pytest.param(
        {
            '.gitignore': '\\#a.py\n\\!b.py\n# c.py\n[ab]x.py\nq?.py\nfoo\\ \nbar.py  \n',
            '#a.py': X,
            '!b.py': X,
            'c.py': X,
            'ax.py': X,
            'cx.py': X,
            'q1.py': X,
            'bar.py': X,
        },
        '',
        None,
        id='escapes-and-classes',
    ),
    pytest.param({'a/.gitignore': '*.py\n', 'a/x.py': X, 'ab/x.py': X, 'b/a/x.py': X}, '', None, id='sibling-scope'),
]


def _git_env(home: Path) -> dict[str, str]:
    """An environment where only the repo's own ignore files apply: no global excludes, no inherited GIT_*."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return env


def _git_untracked(scan: Path, env: dict[str, str]) -> set[str]:
    """The untracked, non-ignored .py and .md files git reports under *scan*."""
    out = subprocess.run(
        ['git', '-C', str(scan), 'ls-files', '-o', '--exclude-standard', '-z', '.'],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    ).stdout
    return {f for f in out.split('\0') if f.endswith(('.py', '.md'))}


@pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')
@pytest.mark.parametrize(('files', 'scan', 'exclude'), _GIT_CASES)
def test_matches_git(tmp_path: Path, files: dict[str, str], scan: str, exclude: Optional[str]):
    """walk_project() yields exactly the untracked files git does not ignore."""
    repo = tmp_path / 'repo'
    _make(repo, files)
    env = _git_env(tmp_path)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True, env=env)
    if exclude is not None:
        (repo / '.git' / 'info' / 'exclude').write_text(exclude)
    assert _walked(repo / scan) == _git_untracked(repo / scan, env)
