from __future__ import annotations

import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest

from tallyman.config import save_config
from tallyman.gitignore import GitIgnoreSpec
from tallyman.walker import WalkStats, _is_binary, inside_auto_spec_dir, walk_files, walk_project


class TestIsBinary:
    def test_text_file(self, tmp_path: Path) -> None:
        f = tmp_path / 'text.py'
        f.write_text('print("hello")\n')
        assert not _is_binary(f)

    def test_binary_file(self, tmp_path: Path) -> None:
        f = tmp_path / 'binary.bin'
        f.write_bytes(b'\x00\x01\x02\x03')
        assert _is_binary(f)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
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

    def test_yields_recognized_files(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'main.py' in paths
        assert 'lib.py' in paths
        assert 'app.py' in paths
        assert 'README.md' in paths

    def test_skips_binary_files(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'photo.png' not in paths

    def test_skips_unrecognized_extensions(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        (root / 'LICENSE').write_text('MIT License\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'LICENSE' not in paths

    def test_yields_solidity_files(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        contracts = root / 'contracts'
        contracts.mkdir()
        (contracts / 'Token.sol').write_text('contract Token {}\n')

        results = list(walk_project(root, set()))
        solidity_lang = next(lang for path, lang in results if path.name == 'Token.sol')
        assert solidity_lang.name == 'Solidity'
        assert solidity_lang.category == 'code'

    def test_respects_excluded_dirs(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        results = list(walk_project(root, {'src'}))
        paths = {r[0].name for r in results}
        assert 'app.py' not in paths
        assert 'main.py' in paths

    def test_respects_gitignore(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        (root / '.gitignore').write_text('src/\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'app.py' not in paths

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        root = self._setup_project(tmp_path)
        hidden = root / '.hidden'
        hidden.mkdir()
        (hidden / 'secret.py').write_text('x = 1\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'secret.py' not in paths

    def test_does_not_follow_symlinks(self, tmp_path: Path) -> None:
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
    def test_auto_detect_specs_dir(self, tmp_path: Path) -> None:
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

    def test_auto_detect_plans_dir(self, tmp_path: Path) -> None:
        """Directory named 'plans' auto-detects as spec directory."""
        plans = tmp_path / 'plans'
        plans.mkdir()
        (plans / 'phase1.md').write_text('# Phase 1\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_auto_detect_specifications_dir(self, tmp_path: Path) -> None:
        """Directory named 'specifications' auto-detects as spec directory."""
        specifications = tmp_path / 'specifications'
        specifications.mkdir()
        (specifications / 'req.md').write_text('# Requirements\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_auto_detect_agents_dir(self, tmp_path: Path) -> None:
        """Directory named 'agents' auto-detects as spec directory."""
        agents = tmp_path / 'agents'
        agents.mkdir()
        (agents / 'prompt.md').write_text('# Agent prompt\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_user_designated_spec_dir(self, tmp_path: Path) -> None:
        """User-designated spec dirs via spec_dirs parameter."""
        docs = tmp_path / 'docs' / 'architecture'
        docs.mkdir(parents=True)
        (docs / 'overview.md').write_text('# Architecture\n')

        results = list(walk_project(tmp_path, set(), spec_dirs={'docs/architecture'}))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_spec_cascades_to_subdirs(self, tmp_path: Path) -> None:
        """Spec status cascades to child directories."""
        sub = tmp_path / 'specs' / 'api'
        sub.mkdir(parents=True)
        (sub / 'endpoints.md').write_text('# Endpoints\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_non_docs_in_spec_dir_unchanged(self, tmp_path: Path) -> None:
        """Python files in spec dirs keep their 'code' category."""
        specs = tmp_path / 'specs'
        specs.mkdir()
        (specs / 'helper.py').write_text('x = 1\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'code'

    def test_spec_dir_name_case_insensitive(self, tmp_path: Path) -> None:
        """Auto-detection is case-insensitive."""
        specs = tmp_path / 'Specs'
        specs.mkdir()
        (specs / 'doc.md').write_text('# Doc\n')

        results = list(walk_project(tmp_path, set()))
        lang = results[0][1]
        assert lang.category == 'specs'

    def test_excluded_spec_dir_not_walked(self, tmp_path: Path) -> None:
        """An excluded spec dir is not walked at all."""
        specs = tmp_path / 'specs'
        specs.mkdir()
        (specs / 'doc.md').write_text('# Doc\n')

        results = list(walk_project(tmp_path, {'specs'}))
        assert len(results) == 0


class TestWalkProjectNestedConfigs:
    """Tests for discovering .tally-config.toml in subdirectories."""

    def test_nested_config_exclusions_applied(self, tmp_path: Path) -> None:
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

    def test_nested_config_spec_dirs_applied(self, tmp_path: Path) -> None:
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

    def test_root_config_not_reloaded(self, tmp_path: Path) -> None:
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

    def test_top_level_exclusion_preserved(self, tmp_path: Path) -> None:
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

    def test_deeply_nested_config(self, tmp_path: Path) -> None:
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

    def test_union_of_exclusions(self, tmp_path: Path) -> None:
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
    def test_dot_in_spec_dirs_makes_every_level_a_spec(self, tmp_path: Path) -> None:
        (tmp_path / 'top.md').write_text('# t\n')
        (tmp_path / 'sub').mkdir()
        (tmp_path / 'sub' / 'deep.md').write_text('# d\n')
        (tmp_path / 'code.py').write_text('x = 1\n')
        cats = {p.name: lang.category for p, lang in walk_project(tmp_path, set(), spec_dirs={'.'})}
        assert cats == {'top.md': 'specs', 'deep.md': 'specs', 'code.py': 'code'}

    def test_nested_config_marking_its_own_directory_as_specs(self, tmp_path: Path) -> None:
        sub = tmp_path / 'design'
        sub.mkdir()
        (sub / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        (sub / 'a.md').write_text('# a\n')
        (tmp_path / 'b.md').write_text('# b\n')
        cats = {p.name: lang.category for p, lang in walk_project(tmp_path, set())}
        assert cats['a.md'] == 'specs'
        assert cats['b.md'] == 'docs'

    def test_deeper_nested_config_wins_on_the_same_path(self, tmp_path: Path) -> None:
        """lib/ marks lib/notes as specs; lib/notes/ ignores itself. The deeper config wins, in both directions."""
        (tmp_path / 'lib' / 'notes').mkdir(parents=True)
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        (tmp_path / 'lib' / 'notes' / 'n.md').write_text('# n\n')
        assert _categories(tmp_path) == {'lib/notes/n.md': 'docs'}
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        assert _categories(tmp_path) == {'lib/notes/n.md': 'specs'}

    def test_nested_config_beats_the_scan_roots_setting_on_the_same_path(self, tmp_path: Path) -> None:
        (tmp_path / 'lib').mkdir()
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        (tmp_path / 'lib' / 'n.md').write_text('# n\n')
        assert _categories(tmp_path, spec_dirs={'lib'}) == {'lib/n.md': 'docs'}

    @pytest.mark.parametrize('payload', [b'not toml [\n', b'[exclude]\ndirectories = ["caf\xe9"]\n'])
    def test_malformed_nested_config_is_skipped(self, tmp_path: Path, payload: bytes) -> None:
        """A broken config inside the scanned tree (often third-party) must not stop the scan."""
        sub = tmp_path / 'vendor'
        sub.mkdir()
        (sub / '.tally-config.toml').write_bytes(payload)
        (sub / 'v.py').write_text('x = 1\n')
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'v.py'}


class TestInsideAutoSpecDir:
    def test_subdirectory_of_plans(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'plans' / 'sub').mkdir(parents=True)
        assert inside_auto_spec_dir(tmp_path / 'plans')
        assert inside_auto_spec_dir(tmp_path / 'plans' / 'sub')
        assert not inside_auto_spec_dir(tmp_path)

    def test_repo_named_like_a_spec_dir_is_not_specs(self, tmp_path: Path) -> None:
        repo = tmp_path / 'agents'
        (repo / '.git').mkdir(parents=True)
        assert not inside_auto_spec_dir(repo)

    def test_outside_a_repo(self, tmp_path: Path) -> None:
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

    def test_ignore_suppresses_auto_detection_for_the_whole_subtree(self, tree: Path) -> None:
        cats = _categories(tree, non_spec_dirs={'plans'})
        assert cats['plans/a.md'] == cats['plans/sub/b.md'] == cats['plans/agents/c.md'] == 'docs'
        assert cats['agents/e.md'] == cats['agents/plans/d.md'] == 'specs'  # untouched elsewhere

    def test_a_deeper_explicit_spec_still_wins(self, tree: Path) -> None:
        cats = _categories(tree, spec_dirs={'agents/plans'}, non_spec_dirs={'agents'})
        assert cats['agents/e.md'] == 'docs'
        assert cats['agents/plans/d.md'] == 'specs'

    def test_a_deeper_ignore_wins_over_an_explicit_spec(self, tree: Path) -> None:
        cats = _categories(tree, spec_dirs={'.'}, non_spec_dirs={'agents'})
        assert cats['f.md'] == cats['plans/a.md'] == 'specs'
        assert cats['agents/e.md'] == cats['agents/plans/d.md'] == 'docs'

    def test_dot_turns_off_auto_detection_everywhere(self, tree: Path) -> None:
        assert set(_categories(tree, non_spec_dirs={'.'}).values()) == {'docs'}

    def test_nested_config_ignore_is_translated(self, tree: Path) -> None:
        (tree / 'agents' / '.tally-config.toml').write_text('[specs]\nignore = ["plans"]\n')
        cats = _categories(tree)
        assert cats['agents/plans/d.md'] == 'docs'
        assert cats['agents/e.md'] == 'specs'


class TestFileSelection:
    def test_skips_generated_files(self, tmp_path: Path) -> None:
        names = ['.tally-config.toml', 'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'app.min.js']
        for name in [*names, 'site.MIN.css', 'Package-Lock.json', 'sub/deep/package-lock.json', 'sub/x.min.js']:
            (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / name).write_text('{}\n')
        (tmp_path / 'package.json').write_text('{}\n')
        (tmp_path / 'app.js').write_text('x\n')
        (tmp_path / 'pyproject.toml').write_text('[x]\n')
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'package.json', 'app.js', 'pyproject.toml'}

    @pytest.mark.skipif(sys.platform == 'win32', reason='creating symlinks needs privileges on Windows')
    def test_symlinked_file_is_not_counted_twice(self, tmp_path: Path) -> None:
        (tmp_path / 'real.py').write_text('x = 1\n')
        (tmp_path / 'link.py').symlink_to(tmp_path / 'real.py')
        (tmp_path / 'broken.py').symlink_to(tmp_path / 'missing.py')
        outside = tmp_path.parent / f'{tmp_path.name}-outside.md'
        outside.write_text('# o\n')
        (tmp_path / 'outside.md').symlink_to(outside)  # content lives elsewhere: not counted here
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'real.py'}

    def test_utf16_file_is_text_not_binary(self, tmp_path: Path) -> None:
        (tmp_path / 'wide.sql').write_bytes('select 1;\n'.encode('utf-16'))
        assert {p.name for p, _ in walk_project(tmp_path, set())} == {'wide.sql'}

    def test_nul_after_the_first_8kb_is_not_binary(self, tmp_path: Path) -> None:
        f = tmp_path / 'late_nul.py'
        f.write_bytes(b'x = 1\n' * 2000 + b'\x00')  # NUL beyond the first 8 KB
        assert not _is_binary(f)


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _walk_with_patterns(
    root: Path, patterns: list[str], excluded: Optional[set[str]] = None, stats: Optional[WalkStats] = None
) -> set[str]:
    spec = GitIgnoreSpec.for_patterns(root)
    spec.add_rules(root, patterns)
    found = walk_project(root, excluded or set(), exclude_patterns=spec, stats=stats)
    return {p.relative_to(root).as_posix() for p, _ in found}


class TestExcludePatterns:
    def test_rust_unit_tests_beside_the_code(self, tmp_path: Path) -> None:
        """Issue #6: src/routing.rs counts, src/routing/tests.rs doesn't."""
        _tree(tmp_path, {'src/routing.rs': 'fn a() {}\n', 'src/routing/tests.rs': 'fn t() {}\n', 'src/lib.rs': ''})
        assert _walk_with_patterns(tmp_path, ['tests.rs', 'testing.rs']) == {'src/routing.rs', 'src/lib.rs'}

    def test_negation_cannot_bring_back_what_else_excluded(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'.gitignore': 'gen.py\n', 'gen.py': '', 'vendor/v.py': '', 'a.py': '', '.hidden/h.py': ''})
        walked = _walk_with_patterns(tmp_path, ['!gen.py', '!vendor/', '!vendor/v.py', '!.hidden/'], {'vendor'})
        assert walked == {'a.py'}

    def test_directory_pattern_prunes(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'a/fixtures/f.py': '', 'a/fixtures.py': '', 'b.py': ''})
        assert _walk_with_patterns(tmp_path, ['fixtures/']) == {'a/fixtures.py', 'b.py'}

    def test_nested_config_patterns_apply_only_beneath_it(self, tmp_path: Path) -> None:
        _tree(
            tmp_path,
            {
                'crate/.tally-config.toml': '[exclude]\npatterns = ["tests.rs"]\n',
                'crate/src/tests.rs': '',
                'other/tests.rs': '',
            },
        )
        found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        assert found == {'other/tests.rs'}

    def test_nested_config_can_re_include_a_parent_pattern(self, tmp_path: Path) -> None:
        _tree(
            tmp_path,
            {
                'crate/.tally-config.toml': '[exclude]\npatterns = ["!tests.rs"]\n',
                'crate/src/tests.rs': '',
                'other/tests.rs': '',
            },
        )
        assert _walk_with_patterns(tmp_path, ['tests.rs']) == {'crate/src/tests.rs'}

    def test_nested_pattern_can_match_its_own_children_directories(self, tmp_path: Path) -> None:
        _tree(
            tmp_path,
            {'pkg/.tally-config.toml': '[exclude]\npatterns = ["/gen/"]\n', 'pkg/gen/g.py': '', 'gen/g.py': ''},
        )
        found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        assert found == {'gen/g.py'}

    def test_stats_count_only_files_that_would_have_counted(self, tmp_path: Path) -> None:
        _tree(
            tmp_path, {'a/tests.rs': 'fn t() {}\n', 'b/tests.rs': '', 'tests.xyz': 'x', 'fixtures/f.py': '', 'k.rs': ''}
        )
        (tmp_path / 'bin').mkdir()
        (tmp_path / 'bin' / 'tests.rs').write_bytes(b'\x00\x01')
        stats = WalkStats()
        walked = _walk_with_patterns(tmp_path, ['tests.*', 'fixtures/'], stats=stats)
        assert walked == {'k.rs'}
        assert stats == WalkStats(pattern_files=2, pattern_dirs=1)  # not the .xyz, the binary, or fixtures/f.py

    def test_final_layer_beats_a_nested_negation_met_during_the_walk(self, tmp_path: Path) -> None:
        """--exclude: the CLI adds its layer before the walk, and the crate's '!' is added after it."""
        _tree(
            tmp_path,
            {
                'crate/.tally-config.toml': '[exclude]\npatterns = ["!tests.rs"]\n',
                'crate/src/tests.rs': 'fn t() {}\n',
                'crate/src/lib.rs': '',
            },
        )
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['tests.rs'], final=True)
        stats = WalkStats()
        walked = {
            s.path.relative_to(tmp_path).as_posix()
            for s in walk_files(tmp_path, set(), exclude_patterns=spec, stats=stats)
        }
        assert walked == {'crate/src/lib.rs'}
        assert stats == WalkStats(pattern_files=1)

    @pytest.mark.skipif(sys.platform == 'win32', reason='symlinks need privileges on Windows')
    def test_stats_skip_a_linked_directory(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'real/f.py': '', 'a.py': ''})
        (tmp_path / 'fixtures').symlink_to(tmp_path / 'real', target_is_directory=True)
        stats = WalkStats()
        _walk_with_patterns(tmp_path, ['fixtures/'], stats=stats)
        assert stats == WalkStats()


_NO_FIFO = pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes need os.mkfifo (not on Windows)')


class TestSpecialFiles:
    """Only regular files are opened: opening a FIFO blocks until something writes to it."""

    @_NO_FIFO
    def test_fifo_is_not_counted(self, tmp_path: Path, make_fifo: Callable[..., Path]) -> None:
        (tmp_path / 'a.py').write_text('x = 1\n')
        make_fifo(tmp_path / 'pipe.py')
        found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        assert found == {'a.py'}

    @_NO_FIFO
    def test_fifo_matched_by_a_pattern_is_not_counted_in_stats(
        self, tmp_path: Path, make_fifo: Callable[..., Path]
    ) -> None:
        make_fifo(tmp_path / 'pipe.py')
        stats = WalkStats()
        assert _walk_with_patterns(tmp_path, ['pipe.py'], stats=stats) == set()
        assert stats.pattern_files == 0

    @pytest.mark.skipif(not hasattr(socket, 'AF_UNIX'), reason='needs Unix domain sockets')
    def test_socket_is_not_counted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A guard test: old and new code behave the same, since opening a socket fails (ENXIO) and the
        binary check already skipped it. Now the regular-file check skips it before anything opens it."""
        (tmp_path / 'a.py').write_text('x = 1\n')
        # A relative name: tmp_path can exceed the 104-byte socket path limit on macOS
        monkeypatch.chdir(tmp_path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind('s.py')
            found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        finally:
            sock.close()
            (tmp_path / 's.py').unlink(missing_ok=True)  # no socket files left in pytest's tmp dirs
        assert found == {'a.py'}


class TestNestedReposKeepConfigSemantics:
    """Tallyman's own settings are not git rules, so they apply inside a nested repository as anywhere else."""

    @staticmethod
    def _repos(root: Path, files: dict[str, str]) -> None:
        for repo in (root, root / 'sub'):
            (repo / '.git').mkdir(parents=True)
        _tree(root, files)

    def test_patterns_apply_inside_nested_repo(self, tmp_path: Path) -> None:
        self._repos(tmp_path, {'sub/a.md': '# a\n', 'sub/b.py': 'x = 1\n'})
        assert _walk_with_patterns(tmp_path, ['*.md']) == {'sub/b.py'}

    def test_excluded_directory_inside_nested_repo(self, tmp_path: Path) -> None:
        self._repos(tmp_path, {'sub/vendor/x.py': 'x = 1\n', 'sub/y.py': 'x = 1\n'})
        found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, {'sub/vendor'})}
        assert found == {'sub/y.py'}

    def test_nested_config_inside_nested_repo(self, tmp_path: Path) -> None:
        self._repos(tmp_path, {'sub/gen/x.py': 'x = 1\n', 'sub/y.py': 'x = 1\n'})
        save_config(tmp_path / 'sub' / '.tally-config.toml', {'gen'}, set())
        found = {p.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        assert found == {'sub/y.py'}

    def test_spec_detection_crosses_repo_boundaries(self, tmp_path: Path) -> None:
        (tmp_path / '.git').mkdir()
        (tmp_path / 'plans' / 'sub' / '.git').mkdir(parents=True)
        _tree(tmp_path, {'plans/sub/a.md': '# a\n'})
        assert [lang.category for _, lang in walk_project(tmp_path, set())] == ['specs']


def _rust_flags(root: Path, exclude_rust_tests: bool = False) -> dict[str, bool]:
    return {
        f.path.relative_to(root).as_posix(): f.exclude_rust_tests
        for f in walk_files(root, set(), exclude_rust_tests=exclude_rust_tests)
    }


class TestRustTestSetting:
    """Which files [rust] exclude_test_modules applies to (issue #8)."""

    def test_scan_root_value_on_every_file(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'src/lib.rs': '', 'src/a/b.rs': '', 'main.rs': ''})
        assert _rust_flags(tmp_path, True) == {'main.rs': True, 'src/a/b.rs': True, 'src/lib.rs': True}
        assert set(_rust_flags(tmp_path).values()) == {False}

    def test_nested_config_turns_it_on_for_one_crate_only(self, tmp_path: Path) -> None:
        """A sibling walked after the crate keeps the root's value: the setting must not leak."""
        _tree(
            tmp_path,
            {
                'a/.tally-config.toml': '[rust]\nexclude_test_modules = true\n',
                'a/src/lib.rs': '',
                'b/src/lib.rs': '',
                'c.rs': '',
            },
        )
        assert _rust_flags(tmp_path) == {'a/src/lib.rs': True, 'b/src/lib.rs': False, 'c.rs': False}

    def test_nested_config_turns_it_off(self, tmp_path: Path) -> None:
        _tree(
            tmp_path,
            {'vendor/.tally-config.toml': '[rust]\nexclude_test_modules = false\n', 'vendor/v.rs': '', 'lib.rs': ''},
        )
        assert _rust_flags(tmp_path, True) == {'lib.rs': True, 'vendor/v.rs': False}

    def test_nested_config_without_the_key_inherits(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'a/.tally-config.toml': '[exclude]\ndirectories = ["gen"]\n', 'a/x.rs': ''})
        assert _rust_flags(tmp_path, True) == {'a/x.rs': True}

    def test_nested_config_inside_a_nested_config(self, tmp_path: Path) -> None:
        _tree(
            tmp_path,
            {
                'a/.tally-config.toml': '[rust]\nexclude_test_modules = true\n',
                'a/b/.tally-config.toml': '[rust]\nexclude_test_modules = false\n',
                'a/b/c/x.rs': '',
                'a/d/y.rs': '',  # walked after a/b
                'a/z.rs': '',
            },
        )
        assert _rust_flags(tmp_path) == {'a/b/c/x.rs': False, 'a/d/y.rs': True, 'a/z.rs': True}

    def test_setting_crosses_into_a_nested_repo(self, tmp_path: Path) -> None:
        """Tallyman settings cross repo boundaries on the way down; the nested repo's own config can change it."""
        (tmp_path / '.git').mkdir()
        (tmp_path / 'inner' / '.git').mkdir(parents=True)
        (tmp_path / 'other' / '.git').mkdir(parents=True)
        _tree(
            tmp_path,
            {
                'inner/.tally-config.toml': '[rust]\nexclude_test_modules = false\n',
                'inner/a.rs': '',
                'other/b.rs': '',
                'c.rs': '',
            },
        )
        assert _rust_flags(tmp_path, True) == {'c.rs': True, 'inner/a.rs': False, 'other/b.rs': True}

    def test_walk_project_yields_the_same_files(self, tmp_path: Path) -> None:
        _tree(tmp_path, {'a/.tally-config.toml': '[rust]\nexclude_test_modules = true\n', 'a/x.rs': '', 'y.py': ''})
        pairs = list(walk_project(tmp_path, set()))
        assert pairs == [(f.path, f.language) for f in walk_files(tmp_path, set())]
        assert all(len(pair) == 2 for pair in pairs)
