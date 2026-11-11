from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest
from textual.widgets.tree import TreeNode

from tallyman.gitignore import GitIgnoreSpec, _read_path_file, find_git_root, load_gitignore
from tallyman.tui.setup_app import NodeInfo, SetupApp, SetupTree
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
    def test_finds_git_root(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        assert find_git_root(tmp_path) == tmp_path

    def test_finds_git_root_from_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        assert find_git_root(sub) == tmp_path

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        assert find_git_root(tmp_path) is None


class TestLoadGitignore:
    def test_loads_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / '.gitignore').write_text('node_modules/\n*.log\n')
        spec = load_gitignore(tmp_path)
        assert spec.match_file('node_modules/')
        assert spec.match_file('error.log')
        assert not spec.match_file('main.py')

    def test_no_gitignore(self, tmp_path: Path) -> None:
        spec = load_gitignore(tmp_path)
        assert not spec.match_file('anything.py')

    def test_loads_git_info_exclude(self, tmp_path: Path) -> None:
        git_info = tmp_path / '.git' / 'info'
        git_info.mkdir(parents=True)
        (git_info / 'exclude').write_text('secret/\n')
        spec = load_gitignore(tmp_path)
        assert spec.match_file('secret/')

    def test_loads_gitignore_from_parent_repo(self, tmp_path: Path) -> None:
        """Running from a subdirectory should find the repo root .gitignore."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.gitignore').write_text('node_modules/\n*.log\n')
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        spec = load_gitignore(sub)
        assert spec.match_file('node_modules/')
        assert spec.match_file('error.log')

    def test_loads_intermediate_gitignore(self, tmp_path: Path) -> None:
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

    def test_add_directory_is_idempotent(self, tmp_path: Path) -> None:
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

    def test_gitignore_does_not_apply_to_its_own_directory(self, tmp_path: Path) -> None:
        sub = tmp_path / 'sub'
        sub.mkdir()
        (sub / '.gitignore').write_text('*\n')
        spec = load_gitignore(tmp_path)
        spec.add_directory('sub', sub)
        assert not spec.match_file('sub/')
        assert spec.match_file('sub/anything.py')

    def test_unreadable_gitignore_is_skipped(self, tmp_path: Path) -> None:
        """A .gitignore that can't be read (here, a directory by that name) must not abort the walk."""
        (tmp_path / 'sub' / '.gitignore').mkdir(parents=True)
        (tmp_path / 'sub' / 'a.py').write_text(X)
        assert _walked(tmp_path) == {'sub/a.py'}

    @pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes need os.mkfifo (not on Windows)')
    def test_fifo_gitignore_is_not_read(self, tmp_path: Path, make_fifo: Callable[..., Path]) -> None:
        """Opening a FIFO blocks until something writes to it; only regular files are read."""
        sub = tmp_path / 'sub'
        make_fifo(sub / '.gitignore', payload=b'a.py\n')
        (sub / 'a.py').write_text(X)
        spec = load_gitignore(tmp_path)
        spec.add_directory('sub', sub)
        assert not spec.match_file('sub/a.py')

    def test_bom_does_not_break_first_pattern(self, tmp_path: Path) -> None:
        (tmp_path / '.gitignore').write_text('\ufeff*.md\n')
        (tmp_path / 'a.md').write_text('# a\n')
        (tmp_path / 'a.py').write_text(X)
        assert _walked(tmp_path) == {'a.py'}


_HEAD = 'ref: refs/heads/main\n'  # a gitdir: target is used only if it holds a HEAD, as git requires


def _worktree_layout(tmp_path: Path, commondir: Optional[str] = None) -> tuple[Path, Path]:
    """A worktree by hand: ``main/.git`` holds the shared ``info/exclude``; ``wt/.git`` points at its gitdir."""
    main, wt = tmp_path / 'main', tmp_path / 'wt'
    gitdir = main / '.git' / 'worktrees' / 'wt'
    _make(
        tmp_path,
        {'main/.git/info/exclude': 'secret.py\n', 'wt/.git': f'gitdir: {gitdir}\n', f'{gitdir}/HEAD': _HEAD},
    )
    (gitdir / 'commondir').write_text(commondir if commondir is not None else '../..\n')
    return main, wt


class TestInfoExcludeLocation:
    """``info/exclude`` is found the way git finds it: through a ``.git`` file's ``gitdir:`` and ``commondir``."""

    def test_git_directory(self, tmp_path: Path) -> None:
        _make(tmp_path, {'repo/.git/info/exclude': 'secret.py\n'})
        assert load_gitignore(tmp_path / 'repo').match_file('secret.py')

    def test_gitdir_file_absolute(self, tmp_path: Path) -> None:
        store = tmp_path / 'store'
        _make(tmp_path, {'store/info/exclude': 'secret.py\n', 'store/HEAD': _HEAD, 'repo/.git': f'gitdir: {store}\n'})
        spec = load_gitignore(tmp_path / 'repo')
        assert spec.match_file('secret.py')
        assert not spec.match_file('ok.py')

    @pytest.mark.parametrize('newline', ['\n', '\r\n', ''])
    def test_gitdir_file_relative(self, tmp_path: Path, newline: str) -> None:
        """The submodule layout: ``sub/.git`` points into the superproject's ``.git/modules``."""
        _make(
            tmp_path,
            {
                'outer/.git/modules/sub/info/exclude': 'secret.py\n',
                'outer/.git/modules/sub/HEAD': _HEAD,
                'outer/sub/.git': f'gitdir: ../.git/modules/sub{newline}',
            },
        )
        assert load_gitignore(tmp_path / 'outer' / 'sub').match_file('secret.py')

    def test_commondir_relative(self, tmp_path: Path) -> None:
        _, wt = _worktree_layout(tmp_path)
        assert load_gitignore(wt).match_file('secret.py')

    def test_commondir_absolute(self, tmp_path: Path) -> None:
        _, wt = _worktree_layout(tmp_path, commondir=f'{tmp_path / "main" / ".git"}\r\n')
        assert load_gitignore(wt).match_file('secret.py')

    def test_per_worktree_info_exclude_is_not_read(self, tmp_path: Path) -> None:
        """git 2.54 reads only the common dir's info/exclude, not one in the worktree's own gitdir."""
        main, wt = _worktree_layout(tmp_path)
        _make(main, {'.git/worktrees/wt/info/exclude': 'ok.py\n'})
        spec = load_gitignore(wt)
        assert spec.match_file('secret.py')
        assert not spec.match_file('ok.py')

    def test_unreadable_commondir_falls_back_to_the_gitdir(self, tmp_path: Path) -> None:
        """Git refuses to run in this state; tallyman falls back to the worktree's own git dir rather than fail."""
        main, wt = _worktree_layout(tmp_path)
        commondir = main / '.git' / 'worktrees' / 'wt' / 'commondir'
        commondir.unlink()
        commondir.mkdir()  # a directory by that name can't be read
        _make(main, {'.git/worktrees/wt/info/exclude': 'ok.py\n'})
        spec = load_gitignore(wt)
        assert spec.match_file('ok.py')
        assert not spec.match_file('secret.py')

    @pytest.mark.parametrize(
        'contents',
        [
            'nonsense\n',
            'gitdir: /does/not/exist\n',
            'GITDIR: x\n',
            'gitdir:x\n',
            'gitdir: \n',
            '',
            'gitdir: .\n',
            'gitdir: ..\n',
        ],
        ids=['nonsense', 'dangling', 'wrong-case', 'no-space', 'empty-value', 'empty-file', 'self', 'parent'],
    )
    def test_malformed_git_file_is_harmless(self, tmp_path: Path, contents: str) -> None:
        """No error, and no info/exclude read from a target that isn't a git directory (no HEAD), even one that exists.

        Git refuses to run in such a checkout. Without the check, ``gitdir: ..`` would read an ``info/exclude``
        outside the repo.
        """
        _make(
            tmp_path,
            {
                'repo/.git': contents,
                'repo/.gitignore': 'a.py\n',
                'repo/info/exclude': 'b.py\n',
                'info/exclude': 'b.py\n',
            },
        )
        spec = load_gitignore(tmp_path / 'repo')
        assert spec.match_file('a.py')
        assert not spec.match_file('b.py')

    @pytest.mark.parametrize(('size', 'read'), [(1 << 20, True), ((1 << 20) + 1, False)])
    def test_git_file_over_one_megabyte_is_absent(self, tmp_path: Path, size: int, read: bool) -> None:
        """Git refuses a ``.git`` file over 1 MB; so does tallyman, without reading the rest of it."""
        store = tmp_path / 'store'
        line = f'gitdir: {store}'
        _make(tmp_path, {'store/info/exclude': 'secret.py\n', 'store/HEAD': _HEAD})
        (tmp_path / 'repo').mkdir()
        (tmp_path / 'repo' / '.git').write_bytes(line.encode() + b'\n' * (size - len(line.encode())))
        assert (tmp_path / 'repo' / '.git').stat().st_size == size
        assert load_gitignore(tmp_path / 'repo').match_file('secret.py') is read

    def test_non_utf8_gitdir_round_trips(self, tmp_path: Path) -> None:
        """A path that isn't UTF-8 (legal on Linux) keeps its bytes, so it can still be opened."""
        dot_git = tmp_path / '.git'
        dot_git.write_bytes(b'gitdir: /x/st\xffore\n')
        contents = _read_path_file(dot_git)
        assert contents is not None
        assert os.fsencode(contents) == b'gitdir: /x/st\xffore'

    def test_non_utf8_gitdir_target_is_found(self, tmp_path: Path) -> None:
        name = os.fsdecode(b'st\xffore')
        try:
            (tmp_path / name).mkdir()
        except OSError:
            pytest.skip('this filesystem rejects names that are not UTF-8')
        _make(tmp_path / name, {'info/exclude': 'secret.py\n', 'HEAD': _HEAD})
        (tmp_path / 'repo').mkdir()
        (tmp_path / 'repo' / '.git').write_bytes(b'gitdir: ../st\xffore\n')
        assert load_gitignore(tmp_path / 'repo').match_file('secret.py')

    @pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes need os.mkfifo (not on Windows)')
    @pytest.mark.parametrize('fifo', ['wt/.git', 'main/.git/worktrees/wt/commondir', 'main/.git/info/exclude'])
    def test_fifo_on_the_way_is_not_read(self, tmp_path: Path, make_fifo: Callable[..., Path], fifo: str) -> None:
        """A FIFO named ``.git``, ``commondir`` or ``exclude`` must not block; it is treated as absent.

        Each FIFO, if read anyway, would deliver what makes ``secret.py`` ignored, so a blocking read fails the test.
        """
        _, wt = _worktree_layout(tmp_path)
        (tmp_path / fifo).unlink()
        payloads = {
            'wt/.git': f'gitdir: {tmp_path}/main/.git/worktrees/wt\n'.encode(),
            'main/.git/worktrees/wt/commondir': b'../..\n',
            'main/.git/info/exclude': b'secret.py\n',
        }
        make_fifo(tmp_path / fifo, payload=payloads[fifo])
        (wt / '.gitignore').write_text('a.py\n')
        spec = load_gitignore(wt)
        assert spec.match_file('a.py')
        assert not spec.match_file('secret.py')

    def test_scan_below_worktree_root(self, tmp_path: Path) -> None:
        _, wt = _worktree_layout(tmp_path)
        (wt / 'src').mkdir()
        assert load_gitignore(wt / 'src').match_file('secret.py')


class TestNestedGitignore:
    """Each .gitignore applies to its own directory, at any depth, as git does."""

    def test_nested_gitignore_below_root(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'app.py': X, 'sub/.gitignore': 'generated/\n', 'sub/generated/big.py': X})
        assert _walked(tmp_path) == {'app.py'}

    def test_self_ignoring_directory(self, tmp_path: Path) -> None:
        """uv and virtualenv write a '*' .gitignore inside the venv they create."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'venv2/.gitignore': '*\n', 'venv2/lib/x.py': X, 'venv2/top.py': X})
        assert _walked(tmp_path) == set()

    def test_intermediate_anchored_pattern(self, tmp_path: Path) -> None:
        """'/build' in sub/.gitignore means sub/build, not sub/sub/build."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path, {'sub/.gitignore': '/build\n', 'sub/build/out.py': X, 'sub/sub/build/x.py': X, 'sub/keep.py': X}
        )
        assert _walked(tmp_path / 'sub') == {'keep.py', 'sub/build/x.py'}

    def test_intermediate_pattern_anchored_to_its_own_directory(self, tmp_path: Path) -> None:
        """'/sub/keep.py' in sub/.gitignore means sub/sub/keep.py, so sub/keep.py stays."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.gitignore': '/sub/keep.py\n', 'sub/keep.py': X})
        assert _walked(tmp_path / 'sub') == {'keep.py'}

    def test_lazy_gitignore_below_a_subdirectory_scan(self, tmp_path: Path) -> None:
        """Scanning repo/sub, a .gitignore in sub/inner is scoped to sub/inner."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/inner/.gitignore': '/gen/\n', 'sub/inner/gen/a.py': X, 'sub/gen/b.py': X})
        assert _walked(tmp_path / 'sub') == {'gen/b.py'}

    def test_deeper_gitignore_re_includes(self, tmp_path: Path) -> None:
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

    def test_root_gitignore_outranks_info_exclude(self, tmp_path: Path) -> None:
        (tmp_path / '.git' / 'info').mkdir(parents=True)
        (tmp_path / '.git' / 'info' / 'exclude').write_text('*.py\n')
        _make(tmp_path, {'.gitignore': '!keep.py\n', 'keep.py': X, 'drop.py': X})
        assert _walked(tmp_path) == {'keep.py'}

    def test_nested_gitignore_without_git_repo(self, tmp_path: Path) -> None:
        _make(tmp_path, {'app.py': X, 'sub/.gitignore': 'generated/\n', 'sub/generated/big.py': X})
        assert _walked(tmp_path) == {'app.py'}


class TestNegation:
    """Negations judge only the entry they match, never what lies beneath it."""

    def test_whitelist_style(self, tmp_path: Path) -> None:
        """'*' then '!*/' then '!*.py' keeps every .py file at any depth."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': '*\n!*/\n!*.py\n', 'a.py': X, 'a.md': X, 'sub/b.py': X, 'sub/b.md': X})
        assert _walked(tmp_path) == {'a.py', 'sub/b.py'}

    def test_whitelist_named_directory(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': '*\n!src/\n!*.py\n', 'src/b.py': X, 'src/b.md': X, 'other/c.py': X})
        assert _walked(tmp_path) == {'src/b.py'}

    def test_deeper_negated_directory_does_not_re_include_its_contents(self, tmp_path: Path) -> None:
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

    def test_deeper_negated_name_does_not_re_include_its_contents(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path, {'.gitignore': '*.md\n', 'pkg/.gitignore': '!docs\n', 'pkg/docs/notes.md': X, 'pkg/docs/a.py': X}
        )
        assert _walked(tmp_path) == {'pkg/docs/a.py'}

    def test_scan_root_inside_ignored_directory(self, tmp_path: Path) -> None:
        """Git never looks inside an ignored directory, so a .gitignore there can't re-include."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'.gitignore': 'build/\n', 'build/.gitignore': '!*.py\n', 'build/a.py': X})
        assert _walked(tmp_path / 'build') == set()


class TestNestedRepos:
    """A git repository below the scan root is walked with its own rules, as if git were run inside it."""

    def test_outer_gitignore_stops_at_nested_repo(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {'.gitignore': '*.md\n', 'top.md': X, 'top.py': X, 'sub/a.md': X, 'sub/b.py': X})
        assert _walked(tmp_path) == {'top.py', 'sub/a.md', 'sub/b.py'}

    def test_outer_subdirectory_gitignore_stops_too(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'a' / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {'a/.gitignore': '*.py\n', 'a/y.py': X, 'a/sub/x.py': X})
        assert _walked(tmp_path) == {'a/sub/x.py'}

    def test_outer_info_exclude_stops_at_nested_repo(self, tmp_path: Path) -> None:
        (tmp_path / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {'.git/info/exclude': '*.md\n', 'top.md': X, 'sub/a.md': X})
        assert _walked(tmp_path) == {'sub/a.md'}

    def test_nested_repo_reads_its_own_info_exclude(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.git/info/exclude': 'b.py\n', 'sub/b.py': X, 'sub/c.py': X, 'b.py': X})
        assert _walked(tmp_path) == {'b.py', 'sub/c.py'}

    def test_nested_repo_gitignore_outranks_its_info_exclude(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.git/info/exclude': '*.py\n', 'sub/.gitignore': '!b.py\n', 'sub/b.py': X, 'sub/c.py': X})
        assert _walked(tmp_path) == {'sub/b.py'}

    def test_nested_repo_gitignore_stack_is_scoped_to_it(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'sub' / '.git').mkdir(parents=True)
        _make(
            tmp_path,
            {
                'sub/.gitignore': '/gen/\n',
                'sub/lib/.gitignore': '*.md\n',
                'sub/gen/a.py': X,
                'sub/lib/b.md': X,
                'sub/lib/c.py': X,
                'sub/d.md': X,
                'gen/e.py': X,
            },
        )
        assert _walked(tmp_path) == {'sub/lib/c.py', 'sub/d.md', 'gen/e.py'}

    def test_outer_negation_cannot_reach_into_nested_repo(self, tmp_path: Path) -> None:
        """Guards against over-filtering, not a regression: the deeper ``*.py`` wins either way."""
        (tmp_path / '.git').mkdir()
        (tmp_path / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {'.gitignore': '!sub/keep.py\n', 'sub/.gitignore': '*.py\n', 'sub/keep.py': X})
        assert _walked(tmp_path) == set()

    @pytest.mark.parametrize(
        ('ignore_file', 'rule'),
        [('.gitignore', 'sub/\n'), ('.gitignore', 'sub\n'), ('.git/info/exclude', 'sub/\n')],
    )
    def test_nested_repo_ignored_by_outer_stays_out(self, tmp_path: Path, ignore_file: str, rule: str) -> None:
        """The nested repo's own entry lives in the outer tree, so the outer rules judge it."""
        (tmp_path / '.git').mkdir()
        (tmp_path / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {ignore_file: rule, 'sub/.gitignore': '!*\n', 'sub/a.py': X, 'top.py': X})
        assert _walked(tmp_path) == {'top.py'}

    def test_repo_inside_nested_repo(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'deep' / 'inner' / '.git').mkdir(parents=True)
        (tmp_path / 'deep' / '.git').mkdir()
        _make(tmp_path, {'deep/.gitignore': '*.py\n', 'deep/d.py': X, 'deep/inner/e.py': X})
        assert _walked(tmp_path) == {'deep/inner/e.py'}

    def test_submodule_style_git_file(self, tmp_path: Path) -> None:
        _make(
            tmp_path,
            {
                '.gitignore': '*.md\n',
                '.git/modules/sub/HEAD': _HEAD,
                '.git/modules/sub/info/exclude': 'secret.py\n',
                'sub/.git': 'gitdir: ../.git/modules/sub\n',
                'sub/secret.py': X,
                'sub/a.md': X,
            },
        )
        assert _walked(tmp_path) == {'sub/a.md'}

    def test_child_repos_of_a_plain_directory(self, tmp_path: Path) -> None:
        """A folder of checkouts: no repo at the scan root, and each child repo keeps its own rules."""
        (tmp_path / 'proj' / '.git').mkdir(parents=True)
        _make(tmp_path, {'.gitignore': '*.md\n', 'proj/a.md': X, 'notes/b.md': X})
        assert _walked(tmp_path) == {'proj/a.md'}

    def test_scan_inside_ignored_directory_skips_nested_repo(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'build' / 'sub' / '.git').mkdir(parents=True)
        _make(tmp_path, {'.gitignore': 'build/\n', 'build/sub/x.py': X})
        assert _walked(tmp_path / 'build') == set()

    def test_nested_repo_registration_is_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {'.gitignore': '*.md\nsub/\n', 'sub/.git/info/exclude': 'b.py\n', 'sub/.gitignore': '!keep.py\n'},
        )
        spec = load_gitignore(tmp_path)
        for _ in range(2):
            spec.add_directory('sub', tmp_path / 'sub')
            assert spec.match_file('sub/b.py')
            assert not spec.match_file('sub/a.md')
            assert spec.match_file('top.md')
            assert spec.match_file('sub/')  # the repo's own entry is strictly outside it: the outer rules judge it


def _tui_labels(root: Path) -> dict[str, str]:
    """Every directory label the setup TUI shows for *root*, by path."""

    async def labels() -> dict[str, str]:
        app = SetupApp(root, load_gitignore(root), set(), set())
        async with app.run_test(size=(100, 30)):
            found: dict[str, str] = {}

            def collect(node: TreeNode[NodeInfo]) -> None:
                if node.data:
                    found[node.data.path] = str(node.label)
                for child in node.children:
                    collect(child)

            collect(app.query_one(SetupTree).root)
            return found

    return asyncio.run(labels())


class TestSetupTuiAgrees:
    def test_tui_marks_nested_gitignored_directory(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'sub/.gitignore': 'generated/\n', 'sub/generated/a.py': X, 'sub/src/b.py': X})
        result = _tui_labels(tmp_path)
        assert result['sub/generated'].endswith('(gitignored)')
        assert not result['sub/src'].endswith('(gitignored)')

    def test_tui_applies_nested_repo_rules(self, tmp_path: Path) -> None:
        for repo in ('', 'sub', 'skipped'):
            (tmp_path / repo / '.git').mkdir(parents=True)
        _make(
            tmp_path,
            {
                '.gitignore': 'gen/\nskipped/\n',
                'sub/.gitignore': 'out/\n',
                'gen/x.py': X,
                'sub/gen/x.py': X,
                'sub/out/x.py': X,
                'skipped/inner/x.py': X,
            },
        )
        result = _tui_labels(tmp_path)
        assert result['gen'].endswith('(gitignored)')
        assert not result['sub/gen'].endswith('(gitignored)')
        assert result['sub/out'].endswith('(gitignored)')
        assert result['skipped'].endswith('(gitignored)')
        assert 'skipped/inner' not in result  # never populated, as the walker never enters it


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
    ('a\\', 'a\\', False),  # a trailing lone backslash matches nothing
    ('\\', '\\', False),
    ('*.py\\', 'x.py\\', False),
    ('a\\/', 'a\\/', False),
    ('a\\\\\\', 'a\\\\', False),  # escaped backslash, then a lone one
    ('a\\\\', 'a\\', True),  # an escaped backslash is fine
    ('c\\\\ ', 'c\\', True),  # escaped backslash: the space after it is trailing and stripped
    ('c\\\\ ', 'c\\ ', False),
    ('c\\\\\\ ', 'c\\ ', True),  # escaped backslash, escaped space
]


@pytest.mark.parametrize(('pattern', 'entry', 'ignored'), _PATTERN_CASES)
def test_pattern_compiler(tmp_path: Path, pattern: str, entry: str, ignored: bool) -> None:
    """Each gitignore pattern judges an entry as git does, with no crash or warning on odd input."""
    (tmp_path / '.gitignore').write_text(pattern + '\n')
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert load_gitignore(tmp_path).match_file(entry) is ignored


def test_only_newline_separates_patterns(tmp_path: Path) -> None:
    """str.splitlines() would split on the form feed; git does not."""
    (tmp_path / '.gitignore').write_bytes(b'a\x0cb.py\r\n')
    spec = load_gitignore(tmp_path)
    assert spec.match_file('a\x0cb.py')
    assert not spec.match_file('b.py')


def test_negated_trailing_backslash_reincludes_nothing(tmp_path: Path) -> None:
    """'!a\\' is invalid in git, so it can't bring back what '*' ignored."""
    (tmp_path / '.gitignore').write_text('*\n!a\\\n')
    assert load_gitignore(tmp_path).match_file('a\\')


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
    env.update(
        GIT_AUTHOR_NAME='t',
        GIT_AUTHOR_EMAIL='t@example.com',
        GIT_COMMITTER_NAME='t',
        GIT_COMMITTER_EMAIL='t@example.com',
    )
    return env


def _git(env: dict[str, str], *args: str) -> str:
    """Run git quietly (hints and progress go to the captured stderr) and return its stdout."""
    return subprocess.run(['git', *args], check=True, env=env, capture_output=True, text=True).stdout


def _git_view(scan: Path, env: dict[str, str]) -> set[str]:
    """The .py and .md files git shows under *scan*, tracked or untracked and not ignored, as if run in every repo.

    Git lists an untracked nested repo as ``sub/`` and a submodule as the gitlink ``sub``; both are recursed into,
    with git run there. Fixtures never commit a file an ignore rule matches, since tallyman can't see the index.
    """
    seen: set[str] = set()
    for entry in _git(env, '-C', str(scan), 'ls-files', '-c', '-o', '--exclude-standard', '-z', '.').split('\0'):
        if not entry:
            continue
        name = entry.rstrip('/')
        if (scan / name).is_dir() and (scan / name / '.git').exists():
            seen |= {f'{name}/{inner}' for inner in _git_view(scan / name, env)}
        elif entry.endswith(('.py', '.md')):
            seen.add(entry)
    return seen


def _git_common_dir(repo: Path, env: dict[str, str]) -> Path:
    """Where git keeps *repo*'s shared state, including ``info/exclude``; git's own answer, not a guessed layout."""
    return repo / _git(env, '-C', str(repo), 'rev-parse', '--git-common-dir').strip()


def _write_exclude(repo: Path, env: dict[str, str], text: str) -> None:
    exclude = _git_common_dir(repo, env) / 'info' / 'exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(text)


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


needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')


@needs_git
@pytest.mark.parametrize(('files', 'scan', 'exclude'), _GIT_CASES)
def test_matches_git(tmp_path: Path, files: dict[str, str], scan: str, exclude: Optional[str]) -> None:
    """walk_project() yields exactly the untracked files git does not ignore."""
    repo = tmp_path / 'repo'
    _make(repo, files)
    env = _git_env(tmp_path)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True, env=env)
    if exclude is not None:
        (repo / '.git' / 'info' / 'exclude').write_text(exclude)
    assert _walked(repo / scan) == _git_untracked(repo / scan, env)


@needs_git
def test_worktree_matches_git(tmp_path: Path) -> None:
    """A worktree's ``.git`` is a file; its info/exclude is the main repo's, found through ``commondir``."""
    env = _git_env(tmp_path)
    main, wt = tmp_path / 'main', tmp_path / 'wt'
    _make(main, {'.gitignore': '*.md\n', 'kept.py': X})
    _git(env, 'init', '-q', str(main))
    _git(env, '-C', str(main), 'add', '.')
    _git(env, '-C', str(main), 'commit', '-q', '-m', 'init')
    _write_exclude(main, env, 'secret.py\n')
    _git(env, '-C', str(main), 'worktree', 'add', '-q', str(wt))
    _make(wt, {'secret.py': X, 'ok.py': X, 'a.md': X})
    assert (wt / '.git').is_file()
    assert _walked(wt) == _git_view(wt, env) == {'kept.py', 'ok.py'}


@needs_git
def test_submodule_matches_git(tmp_path: Path) -> None:
    """Scanned from inside, a submodule uses its own info/exclude (in the superproject's ``.git/modules``)."""
    env = _git_env(tmp_path)
    subsrc, outer = tmp_path / 'subsrc', tmp_path / 'outer'
    _make(subsrc, {'.gitignore': '*.log\n', 'kept.py': X})
    _make(outer, {'.gitignore': '*.md\n', 'top.py': X})
    for repo in (subsrc, outer):
        _git(env, 'init', '-q', str(repo))
        _git(env, '-C', str(repo), 'add', '.')
        _git(env, '-C', str(repo), 'commit', '-q', '-m', 'init')
    # Local-path submodules need protocol.file.allow since git 2.38.1; older gits ignore the unknown key
    _git(env, '-C', str(outer), '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(subsrc), 'sub')
    sub = outer / 'sub'
    _write_exclude(sub, env, 'secret.py\n')
    _make(sub, {'secret.py': X, 'b.py': X, 'a.md': X})
    assert (sub / '.git').is_file()
    assert _walked(sub) == _git_view(sub, env) == {'kept.py', 'b.py', 'a.md'}


_OUTER_RULES_STOP = {'.gitignore': '*.md\n', 'top.md': X, 'top.py': X, 'sub/a.md': X, 'sub/b.py': X}
_OUTER_SUBDIR_GITIGNORE = {'a/.gitignore': '*.py\n', 'a/y.py': X, 'a/sub/x.py': X, 'a/sub/z.md': X}

# (files, repos to `git init` below the outer repo, shallowest first, scan, {repo: info/exclude text})
_NESTED_GIT_CASES = [
    pytest.param(_OUTER_RULES_STOP, ['sub'], '', {}, id='outer-rules-stop'),
    pytest.param(_OUTER_SUBDIR_GITIGNORE, ['a/sub'], '', {}, id='outer-subdir-gitignore-stops'),
    pytest.param({'top.md': X, 'sub/a.md': X}, ['sub'], '', {'': '*.md\n'}, id='outer-info-exclude-stops'),
    pytest.param({'b.py': X, 'sub/b.py': X, 'sub/c.py': X}, ['sub'], '', {'sub': 'b.py\n'}, id='inner-info-exclude'),
    pytest.param(
        {'.gitignore': 'sub/\n', 'sub/a.py': X, 'top.py': X}, ['sub'], '', {}, id='ignored-by-outer-gitignore'
    ),
    pytest.param({'sub/a.py': X, 'top.py': X}, ['sub'], '', {'': 'sub/\n'}, id='ignored-by-outer-info-exclude'),
    pytest.param(
        {'sub/.gitignore': '!b.py\n', 'sub/b.py': X, 'sub/c.py': X},
        ['sub'],
        '',
        {'sub': '*.py\n'},
        id='inner-gitignore-outranks-inner-info-exclude',
    ),
    # Guards against over-filtering, not a regression: the deeper *.py wins either way
    pytest.param(
        {'.gitignore': '!sub/keep.py\n', 'sub/.gitignore': '*.py\n', 'sub/keep.py': X, 'sub/n.md': X},
        ['sub'],
        '',
        {},
        id='outer-negation-cannot-reach-in',
    ),
    pytest.param(
        {
            '.gitignore': '*.md\n',
            'deep/.gitignore': '*.py\n',
            'deep/d.py': X,
            'deep/inner/e.py': X,
            'deep/inner/f.md': X,
        },
        ['deep', 'deep/inner'],
        '',
        {},
        id='repo-in-repo',
    ),
    pytest.param(_OUTER_RULES_STOP, ['sub'], 'sub', {}, id='scan-from-inside'),
    pytest.param(_OUTER_SUBDIR_GITIGNORE, ['a/sub'], 'a', {}, id='scan-subdir-holding-repo'),
    pytest.param(
        {'.gitignore': 'sub/\n', 'sub/a.py': X, 'top.py': X},
        ['sub'],
        'sub',
        {},
        id='scan-inside-repo-the-outer-ignores',
    ),
    pytest.param(
        {
            '.gitignore': '*.md\n',
            'proj/.gitignore': '*.py\n',
            'proj/a.md': X,
            'proj/b.py': X,
            'proj/sub/c.py': X,
            'proj/sub/d.py': X,
        },
        ['proj', 'proj/sub'],
        'proj',
        {'proj/sub': 'c.py\n'},
        id='scan-repo-holding-repo',
    ),
]


@needs_git
@pytest.mark.parametrize(('files', 'repos', 'scan', 'excludes'), _NESTED_GIT_CASES)
def test_nested_repos_match_git(
    tmp_path: Path, files: dict[str, str], repos: list[str], scan: str, excludes: dict[str, str]
) -> None:
    """Inside a nested repository only its own rules apply, exactly as git run in each repository reports."""
    env = _git_env(tmp_path)
    outer = tmp_path / 'repo'
    _make(outer, files)
    for repo in ['', *repos]:
        _git(env, 'init', '-q', str(outer / repo))
    for repo, text in excludes.items():
        _write_exclude(outer / repo, env, text)
    assert _walked(outer / scan) == _git_view(outer / scan, env)


def _commit_all(env: dict[str, str], repo: Path) -> None:
    _git(env, '-C', str(repo), 'add', '.')
    _git(env, '-C', str(repo), 'commit', '-q', '-m', 'init')


def _add_submodule(env: dict[str, str], repo: Path, source: Path, path: str) -> None:
    # Local-path submodules need protocol.file.allow since git 2.38.1; older gits ignore the unknown key
    _git(env, '-C', str(repo), '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(source), path)


@needs_git
def test_submodule_from_outer_matches_git(tmp_path: Path) -> None:
    """Scanned from the superproject, a submodule keeps its own info/exclude and the outer ``*.md`` stops at it."""
    env = _git_env(tmp_path)
    subsrc, outer = tmp_path / 'subsrc', tmp_path / 'outer'
    _make(subsrc, {'.gitignore': '*.log\n', 'kept.py': X})
    _make(outer, {'.gitignore': '*.md\n', 'top.py': X})
    for repo in (subsrc, outer):
        _git(env, 'init', '-q', str(repo))
        _commit_all(env, repo)
    _add_submodule(env, outer, subsrc, 'sub')
    sub = outer / 'sub'
    _write_exclude(sub, env, 'secret.py\n')
    _make(sub, {'secret.py': X, 'b.py': X, 'a.md': X})
    expected = {'top.py', 'sub/kept.py', 'sub/b.py', 'sub/a.md'}
    assert _git_view(outer, env) == expected  # literal too, so a _git_view bug can't hide a regression
    assert _walked(outer) == expected


@needs_git
def test_submodule_inside_submodule_matches_git(tmp_path: Path) -> None:
    """``mid/leaf``'s git dir is ``../../.git/modules/mid/modules/leaf``; each repo reads only its own info/exclude."""
    env = _git_env(tmp_path)
    leafsrc, midsrc, outer = tmp_path / 'leaf', tmp_path / 'mid', tmp_path / 'outer'
    _make(leafsrc, {'l.py': X})
    _make(midsrc, {'m.py': X})
    _make(outer, {'.gitignore': '*.md\n', 'top.py': X})
    for repo in (leafsrc, midsrc, outer):
        _git(env, 'init', '-q', str(repo))
        _commit_all(env, repo)
    _add_submodule(env, midsrc, leafsrc, 'leaf')
    _commit_all(env, midsrc)
    _add_submodule(env, outer, midsrc, 'mid')
    _git(env, '-C', str(outer), '-c', 'protocol.file.allow=always', 'submodule', 'update', '--init', '--recursive')
    mid, leaf = outer / 'mid', outer / 'mid' / 'leaf'
    assert (leaf / '.git').read_text().strip() == 'gitdir: ../../.git/modules/mid/modules/leaf'
    _write_exclude(mid, env, 'secret.py\n')
    _write_exclude(leaf, env, 'deep.py\n')
    _make(mid, {'secret.py': X, 'a.md': X})
    _make(leaf, {'deep.py': X, 'secret.py': X})
    from_mid = {'m.py', 'a.md', 'leaf/l.py', 'leaf/secret.py'}
    assert _git_view(mid, env) == from_mid
    assert _walked(mid) == from_mid
    from_outer = {'top.py', 'mid/m.py', 'mid/a.md', 'mid/leaf/l.py', 'mid/leaf/secret.py'}
    assert _git_view(outer, env) == from_outer
    assert _walked(outer) == from_outer


@needs_git
def test_worktree_inside_repo_matches_git(tmp_path: Path) -> None:
    """A worktree placed inside its main repo is a nested repo that shares the main repo's info/exclude.

    The anchored ``/secret.py`` reaches ``wt/secret.py`` only as the worktree's own rule, and the uncommitted
    ``ok.py`` in main's .gitignore must not reach ``wt/ok.py``: outer rules alone would get both wrong.
    """
    env = _git_env(tmp_path)
    main = tmp_path / 'main'
    _make(main, {'.gitignore': '*.md\n', 'kept.py': X})
    _git(env, 'init', '-q', str(main))
    _commit_all(env, main)
    _write_exclude(main, env, '/secret.py\n')
    _git(env, '-C', str(main), 'worktree', 'add', '-q', str(main / 'wt'))
    with (main / '.gitignore').open('a') as f:
        f.write('ok.py\n')  # after the commit, so the worktree's checked-out .gitignore doesn't have it
    _make(main, {'wt/secret.py': X, 'wt/ok.py': X, 'wt/a.md': X, 'top.py': X})
    assert (main / 'wt' / '.git').is_file()
    assert _walked(main) == _git_view(main, env) == {'kept.py', 'top.py', 'wt/kept.py', 'wt/ok.py'}


def test_tui_shows_every_directory_as_spec_when_root_is_spec(tmp_path: Path) -> None:
    """spec_dirs containing '.' (the scan root) makes the walker count everything as specs; the TUI must agree."""
    _make(tmp_path, {'a/b/x.md': '# x\n'})

    async def labels() -> list[str]:
        app = SetupApp(tmp_path, load_gitignore(tmp_path), set(), {'.'})
        async with app.run_test(size=(100, 30)):
            root = app.query_one(SetupTree).root
            return [str(root.children[0].label), str(root.children[0].children[0].label)]

    assert all(label.startswith('S ') for label in asyncio.run(labels()))


class TestConfigPatterns:
    """[exclude] patterns: a second GitIgnoreSpec, one layer per config, scoped to that config's directory."""

    def test_patterns_at_the_scan_root(self, tmp_path: Path) -> None:
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['tests.rs', '/top.rs', 'fixtures/'])
        assert spec.match_file('tests.rs')
        assert spec.match_file('src/routing/tests.rs')  # no slash: any depth
        assert spec.match_file('top.rs')
        assert not spec.match_file('src/top.rs')  # leading slash: only beside the config
        assert spec.match_file('src/fixtures/')
        assert not spec.match_file('src/fixtures')  # trailing slash: directories only

    def test_ancestor_layer_is_anchored_to_its_own_directory(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'app' / 'src').mkdir(parents=True)
        spec = GitIgnoreSpec.for_patterns(tmp_path / 'app')
        spec.add_rules(tmp_path, ['/app/gen/', 'app'])
        assert spec.match_file('gen/')  # repo/app/gen, written relative to the repo root
        assert not spec.match_file('src/gen/')
        assert spec.match_file('src/app')  # 'app' matches below the scan root, but never the scan root itself

    def test_deeper_layer_can_re_include(self, tmp_path: Path) -> None:
        (tmp_path / 'crate').mkdir()
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path / 'crate', ['!tests.rs'])
        spec.add_rules(tmp_path, ['tests.rs'])  # registration order doesn't matter: depth does
        assert spec.match_file('other/tests.rs')
        assert not spec.match_file('crate/src/tests.rs')

    def test_registering_a_directory_twice_is_a_no_op(self, tmp_path: Path) -> None:
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['a.rs'])
        spec.add_rules(tmp_path, ['!a.rs'])
        assert spec.match_file('a.rs')

    def test_directory_outside_the_anchor_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / 'scan').mkdir()
        spec = GitIgnoreSpec.for_patterns(tmp_path / 'scan')  # no repo: the scan root is the anchor
        spec.add_rules(tmp_path, ['*'])
        assert not spec.match_file('a.rs')

    def test_patterns_do_not_mix_with_gitignore(self, tmp_path: Path) -> None:
        """A pattern's '!' can't bring back a gitignored file."""
        _make(tmp_path, {'.gitignore': 'gen.py\n', 'gen.py': X, 'a.py': X})
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['!gen.py'])
        assert {p.name for p, _ in walk_project(tmp_path, set(), exclude_patterns=spec)} == {'a.py'}

    def test_trailing_backslash_pattern_matches_nothing(self, tmp_path: Path) -> None:
        """Config patterns are compiled by the same parser, so a lone trailing backslash is invalid here too."""
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['a\\', 'c\\\\ '])
        assert not spec.match_file('a\\')
        assert spec.match_file('c\\')

    def test_add_rules_needs_an_anchored_spec(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            GitIgnoreSpec().add_rules(tmp_path, ['a.rs'])
