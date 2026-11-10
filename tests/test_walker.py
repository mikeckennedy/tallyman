from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

from tallyman.config import save_config
from tallyman.walker import _is_binary, inside_auto_spec_dir, walk_project


class TestIsBinary:
    def test_text_file(self, tmp_path: Path):
        f = tmp_path / 'text.py'
        f.write_text('print("hello")\n')
        assert not _is_binary(f)

    def test_binary_file(self, tmp_path: Path):
        f = tmp_path / 'binary.bin'
        f.write_bytes(b'\x00\x01\x02\x03')
        assert _is_binary(f)

    def test_nonexistent_file(self, tmp_path: Path):
        assert _is_binary(tmp_path / 'nope')


class TestWalkProject:
    def _setup_project(self, tmp_path: Path) -> Path:
        """Create a small project tree for testing."""
        (tmp_path / 'main.py').write_text('print("hello")\n')
        (tmp_path / 'lib.py').write_text('def foo(): pass\n')
        (tmp_path / 'README.md').write_text('# Hello\n')
        (tmp_path / 'photo.png').write_bytes(b'\x89PNG\x00')
        sub = tmp_path / 'src'
        sub.mkdir()
        (sub / 'app.py').write_text('import os\n')
        return tmp_path

    def test_yields_recognized_files(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'main.py' in paths
        assert 'lib.py' in paths
        assert 'app.py' in paths
        assert 'README.md' in paths

    def test_skips_binary_files(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'photo.png' not in paths

    def test_skips_unrecognized_extensions(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        (root / 'LICENSE').write_text('MIT License\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'LICENSE' not in paths

    def test_yields_solidity_files(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        contracts = root / 'contracts'
        contracts.mkdir()
        (contracts / 'Token.sol').write_text('contract Token {}\n')

        results = list(walk_project(root, set()))
        solidity_lang = next(lang for path, lang in results if path.name == 'Token.sol')
        assert solidity_lang.name == 'Solidity'
        assert solidity_lang.category == 'code'

    def test_respects_excluded_dirs(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, {'src'}))
        paths = {r[0].name for r in results}
        assert 'app.py' not in paths
        assert 'main.py' in paths

    def test_respects_gitignore(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        (root / '.gitignore').write_text('src/\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'app.py' not in paths

    def test_skips_hidden_directories(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        hidden = root / '.hidden'
        hidden.mkdir()
        (hidden / 'secret.py').write_text('x = 1\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'secret.py' not in paths

    def test_does_not_follow_symlinks(self, tmp_path: Path):
        root = self._setup_project(tmp_path)
        target = tmp_path / 'external'
        target.mkdir()
        (target / 'mod.py').write_text('y = 2\n')
        (root / 'link').symlink_to(target)
        results = list(walk_project(root, set()))
        # The symlinked directory should not be followed
        paths = {r[0].name for r in results}
        assert 'mod.py' not in paths or all(not str(r[0]).startswith(str(root / 'link')) for r in results)


class TestWalkProjectSpecs:
    def test_auto_detect_specs_dir(self, tmp_path: Path):
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

    def test_auto_detect_plans_dir(self, tmp_path: Path):
        """Directory named 'plans' auto-detects as spec directory."""
        plans = tmp_path / 'plans'
        plans.mkdir()
        (plans / 'phase1.md').write_text('# Phase 1\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_auto_detect_specifications_dir(self, tmp_path: Path):
        """Directory named 'specifications' auto-detects as spec directory."""
        specifications = tmp_path / 'specifications'
        specifications.mkdir()
        (specifications / 'req.md').write_text('# Requirements\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_auto_detect_agents_dir(self, tmp_path: Path):
        """Directory named 'agents' auto-detects as spec directory."""
        agents = tmp_path / 'agents'
        agents.mkdir()
        (agents / 'prompt.md').write_text('# Agent prompt\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_user_designated_spec_dir(self, tmp_path: Path):
        """User-designated spec dirs via spec_dirs parameter."""
        docs = tmp_path / 'docs' / 'architecture'
        docs.mkdir(parents=True)
        (docs / 'overview.md').write_text('# Architecture\n')

        results = list(walk_project(tmp_path, set(), spec_dirs={'docs/architecture'}))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_spec_cascades_to_subdirs(self, tmp_path: Path):
        """Spec status cascades to child directories."""
        sub = tmp_path / 'specs' / 'api'
        sub.mkdir(parents=True)
        (sub / 'endpoints.md').write_text('# Endpoints\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_non_docs_in_spec_dir_unchanged(self, tmp_path: Path):
        """Python files in spec dirs keep their 'code' category."""
        specs = tmp_path / 'specs'
        specs.mkdir()
        (specs / 'helper.py').write_text('x = 1\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'code'

    def test_spec_dir_name_case_insensitive(self, tmp_path: Path):
        """Auto-detection is case-insensitive."""
        specs = tmp_path / 'Specs'
        specs.mkdir()
        (specs / 'doc.md').write_text('# Doc\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_excluded_spec_dir_not_walked(self, tmp_path: Path):
        """An excluded spec dir is not walked at all."""
        specs = tmp_path / 'specs'
        specs.mkdir()
        (specs / 'doc.md').write_text('# Doc\n')

        results = list(walk_project(tmp_path, {'specs'}))
        assert len(results) == 0


class TestWalkProjectNestedConfigs:
    """Tests for discovering .tally-config.toml in subdirectories."""

    def test_nested_config_exclusions_applied(self, tmp_path: Path):
        """A nested config's excluded_dirs are applied within its subtree."""
        project = tmp_path / 'project1'
        project.mkdir()
        (project / 'app.py').write_text('x = 1\n')
        vendor = project / 'vendor'
        vendor.mkdir()
        (vendor / 'lib.py').write_text('y = 2\n')

        # project1/.tally-config.toml excludes vendor
        save_config(project / '.tally-config.toml', {'vendor'}, set())

        results = list(walk_project(tmp_path, set()))
        paths = {r[0].name for r in results}
        assert 'app.py' in paths
        assert 'lib.py' not in paths

    def test_nested_config_spec_dirs_applied(self, tmp_path: Path):
        """A nested config's spec_dirs mark docs files as specs."""
        project = tmp_path / 'project1'
        project.mkdir()
        docs = project / 'docs'
        docs.mkdir()
        (docs / 'design.md').write_text('# Design\n')
        (project / 'README.md').write_text('# Readme\n')

        # project1/.tally-config.toml designates docs as spec dir
        save_config(project / '.tally-config.toml', set(), {'docs'})

        results = list(walk_project(tmp_path, set()))
        design_lang = next(lang for path, lang in results if path.name == 'design.md')
        readme_lang = next(lang for path, lang in results if path.name == 'README.md')

        assert design_lang.category == 'specs'
        assert readme_lang.category == 'docs'

    def test_root_config_not_reloaded(self, tmp_path: Path):
        """A config at the walk root is not re-read (already loaded by cli)."""
        (tmp_path / 'app.py').write_text('x = 1\n')
        vendor = tmp_path / 'vendor'
        vendor.mkdir()
        (vendor / 'lib.py').write_text('y = 2\n')

        # Root config excludes vendor, but we pass empty excluded_dirs
        # to simulate cli having already loaded the config separately.
        # The walker should NOT re-read the root config.
        save_config(tmp_path / '.tally-config.toml', {'vendor'}, set())

        results = list(walk_project(tmp_path, set()))
        paths = {r[0].name for r in results}
        # vendor/lib.py should appear because root config is not re-loaded
        assert 'lib.py' in paths

    def test_top_level_exclusion_preserved(self, tmp_path: Path):
        """Top-level exclusions persist even when nested config does not exclude."""
        project = tmp_path / 'project1'
        project.mkdir()
        (project / 'app.py').write_text('x = 1\n')
        vendor = project / 'vendor'
        vendor.mkdir()
        (vendor / 'lib.py').write_text('y = 2\n')

        # Nested config does NOT exclude vendor
        save_config(project / '.tally-config.toml', set(), set())

        # But top-level passes project1/vendor as excluded
        results = list(walk_project(tmp_path, {'project1/vendor'}))
        paths = {r[0].name for r in results}
        assert 'app.py' in paths
        assert 'lib.py' not in paths

    def test_deeply_nested_config(self, tmp_path: Path):
        """Config inside folder/subfolder/project3/ is discovered and applied."""
        project = tmp_path / 'folder' / 'subfolder' / 'project3'
        project.mkdir(parents=True)
        (project / 'main.py').write_text('x = 1\n')
        generated = project / 'generated'
        generated.mkdir()
        (generated / 'output.py').write_text('y = 2\n')

        save_config(project / '.tally-config.toml', {'generated'}, set())

        results = list(walk_project(tmp_path, set()))
        paths = {r[0].name for r in results}
        assert 'main.py' in paths
        assert 'output.py' not in paths

    def test_union_of_exclusions(self, tmp_path: Path):
        """Both top-level and nested exclusions apply simultaneously."""
        project = tmp_path / 'project1'
        project.mkdir()
        (project / 'app.py').write_text('x = 1\n')
        vendor = project / 'vendor'
        vendor.mkdir()
        (vendor / 'v.py').write_text('v = 1\n')
        cache = project / 'cache'
        cache.mkdir()
        (cache / 'c.py').write_text('c = 1\n')

        # Nested config excludes vendor
        save_config(project / '.tally-config.toml', {'vendor'}, set())

        # Top-level excludes cache
        results = list(walk_project(tmp_path, {'project1/cache'}))
        paths = {r[0].name for r in results}
        assert 'app.py' in paths
        assert 'v.py' not in paths  # excluded by nested config
        assert 'c.py' not in paths  # excluded by top-level


class TestSpecRootAndNestedConfigs:
    def test_dot_in_spec_dirs_makes_every_level_a_spec(self, tmp_path: Path):
        (tmp_path / 'top.md').write_text('# t\n')
        (tmp_path / 'sub').mkdir()
        (tmp_path / 'sub' / 'deep.md').write_text('# d\n')
        (tmp_path / 'code.py').write_text('x = 1\n')
        cats = {p.name: lang.category for p, lang in walk_project(tmp_path, set(), spec_dirs={'.'})}
        assert cats == {'top.md': 'specs', 'deep.md': 'specs', 'code.py': 'code'}

    def test_nested_config_marking_its_own_directory_as_specs(self, tmp_path: Path):
        sub = tmp_path / 'design'
        sub.mkdir()
        (sub / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        (sub / 'a.md').write_text('# a\n')
        (tmp_path / 'b.md').write_text('# b\n')
        cats = {p.name: lang.category for p, lang in walk_project(tmp_path, set())}
        assert cats['a.md'] == 'specs'
        assert cats['b.md'] == 'docs'

    def test_deeper_nested_config_wins_on_the_same_path(self, tmp_path: Path):
        """lib/ marks lib/notes as specs; lib/notes/ ignores itself. The deeper config wins, in both directions."""
        (tmp_path / 'lib' / 'notes').mkdir(parents=True)
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        (tmp_path / 'lib' / 'notes' / 'n.md').write_text('# n\n')
        assert _categories(tmp_path) == {'lib/notes/n.md': 'docs'}
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        assert _categories(tmp_path) == {'lib/notes/n.md': 'specs'}

    def test_nested_config_beats_the_scan_roots_setting_on_the_same_path(self, tmp_path: Path):
        (tmp_path / 'lib').mkdir()
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        (tmp_path / 'lib' / 'n.md').write_text('# n\n')
        assert _categories(tmp_path, spec_dirs={'lib'}) == {'lib/n.md': 'docs'}

    @pytest.mark.parametrize('payload', [b'not toml [\n', b'[exclude]\ndirectories = ["caf\xe9"]\n'])
    def test_malformed_nested_config_is_skipped(self, tmp_path: Path, payload: bytes):
        """A broken config inside the scanned tree (often third-party) must not stop the scan."""
        sub = tmp_path / 'vendor'
        sub.mkdir()
        (sub / '.tally-config.toml').write_bytes(payload)
        (sub / 'v.py').write_text('x = 1\n')
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'v.py'}


class TestInsideAutoSpecDir:
    def test_subdirectory_of_plans(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        (tmp_path / 'plans' / 'sub').mkdir(parents=True)
        assert inside_auto_spec_dir(tmp_path / 'plans')
        assert inside_auto_spec_dir(tmp_path / 'plans' / 'sub')
        assert not inside_auto_spec_dir(tmp_path)

    def test_repo_named_like_a_spec_dir_is_not_specs(self, tmp_path: Path):
        repo = tmp_path / 'agents'
        (repo / '.git').mkdir(parents=True)
        assert not inside_auto_spec_dir(repo)

    def test_outside_a_repo(self, tmp_path: Path):
        (tmp_path / 'plans').mkdir()
        assert not inside_auto_spec_dir(tmp_path / 'plans')


def _categories(
    root: Path, spec_dirs: Optional[set[str]] = None, non_spec_dirs: Optional[set[str]] = None
) -> dict[str, str]:
    found = walk_project(root, set(), spec_dirs=spec_dirs, non_spec_dirs=non_spec_dirs)
    return {p.relative_to(root).as_posix(): lang.category for p, lang in found}


class TestSpecIgnore:
    """[specs] ignore: non_spec_dirs switch spec classification off for a subtree."""

    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        for rel in ['plans/a.md', 'plans/sub/b.md', 'plans/agents/c.md', 'agents/plans/d.md', 'agents/e.md', 'f.md']:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text('# x\n')
        return tmp_path

    def test_ignore_suppresses_auto_detection_for_the_whole_subtree(self, tree: Path):
        cats = _categories(tree, non_spec_dirs={'plans'})
        assert cats['plans/a.md'] == cats['plans/sub/b.md'] == cats['plans/agents/c.md'] == 'docs'
        assert cats['agents/e.md'] == cats['agents/plans/d.md'] == 'specs'  # untouched elsewhere

    def test_a_deeper_explicit_spec_still_wins(self, tree: Path):
        cats = _categories(tree, spec_dirs={'agents/plans'}, non_spec_dirs={'agents'})
        assert cats['agents/e.md'] == 'docs'
        assert cats['agents/plans/d.md'] == 'specs'

    def test_a_deeper_ignore_wins_over_an_explicit_spec(self, tree: Path):
        cats = _categories(tree, spec_dirs={'.'}, non_spec_dirs={'agents'})
        assert cats['f.md'] == cats['plans/a.md'] == 'specs'
        assert cats['agents/e.md'] == cats['agents/plans/d.md'] == 'docs'

    def test_dot_turns_off_auto_detection_everywhere(self, tree: Path):
        assert set(_categories(tree, non_spec_dirs={'.'}).values()) == {'docs'}

    def test_nested_config_ignore_is_translated(self, tree: Path):
        (tree / 'agents' / '.tally-config.toml').write_text('[specs]\nignore = ["plans"]\n')
        cats = _categories(tree)
        assert cats['agents/plans/d.md'] == 'docs'
        assert cats['agents/e.md'] == 'specs'


class TestFileSelection:
    def test_skips_generated_files(self, tmp_path: Path):
        names = ['.tally-config.toml', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'app.min.js']
        for name in [*names, 'site.MIN.css', 'Package-Lock.json', 'sub/deep/package-lock.json', 'sub/x.min.js']:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text('{}\n')
        (tmp_path / 'package.json').write_text('{}\n')
        (tmp_path / 'app.js').write_text('x\n')
        (tmp_path / 'pyproject.toml').write_text('[x]\n')
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'package.json', 'app.js', 'pyproject.toml'}

    @pytest.mark.skipif(sys.platform == 'win32', reason='creating symlinks needs privileges on Windows')
    def test_symlinked_file_is_not_counted_twice(self, tmp_path: Path):
        (tmp_path / 'real.py').write_text('x = 1\n')
        (tmp_path / 'link.py').symlink_to(tmp_path / 'real.py')
        (tmp_path / 'broken.py').symlink_to(tmp_path / 'missing.py')
        outside = tmp_path.parent / f'{tmp_path.name}-outside.md'
        outside.write_text('# o\n')
        (tmp_path / 'outside.md').symlink_to(outside)  # content lives elsewhere: not counted here
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'real.py'}

    def test_utf16_file_is_text_not_binary(self, tmp_path: Path):
        (tmp_path / 'wide.sql').write_bytes('select 1;\n'.encode('utf-16'))
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'wide.sql'}

    def test_nul_after_the_first_8kb_is_not_binary(self, tmp_path: Path):
        f = tmp_path / 'late_nul.py'
        f.write_bytes(b'x = 1\n' * 2000 + b'\x00')  # NUL beyond the first 8 KB
        assert not _is_binary(f)
