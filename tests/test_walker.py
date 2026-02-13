from __future__ import annotations

from pathlib import Path

from tallyman.config import save_config
from tallyman.walker import _is_binary, find_git_root, load_gitignore, walk_project


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
