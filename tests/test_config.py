from __future__ import annotations

from pathlib import Path

from tallyman.config import CONFIG_FILENAME, discover_nested_configs, find_config, load_config, save_config
from tallyman.tui.setup_app import SetupApp


class TestFindConfig:
    def test_returns_path_when_exists(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        assert find_config(tmp_path) == config

    def test_returns_none_when_missing(self, tmp_path: Path):
        assert find_config(tmp_path) is None

    def test_finds_config_in_parent_directory(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        assert find_config(sub) == config

    def test_finds_nearest_config(self, tmp_path: Path):
        root_config = tmp_path / CONFIG_FILENAME
        root_config.write_text('[exclude]\ndirectories = ["root"]\n')
        sub = tmp_path / 'sub'
        sub.mkdir()
        sub_config = sub / CONFIG_FILENAME
        sub_config.write_text('[exclude]\ndirectories = ["sub"]\n')
        # From sub, should find sub's config (nearest)
        assert find_config(sub) == sub_config


class TestLoadConfig:
    def test_loads_excluded_directories(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["vendor", "static/external"]\n')
        result = load_config(config)
        assert result.excluded_dirs == {'vendor', 'static/external'}

    def test_empty_directories(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        result = load_config(config)
        assert result.excluded_dirs == set()

    def test_no_exclude_section(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('# empty config\n')
        result = load_config(config)
        assert result.excluded_dirs == set()

    def test_loads_spec_directories(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text(
            '[exclude]\ndirectories = ["vendor"]\n\n[specs]\ndirectories = ["docs/arch", "project/reqs"]\n'
        )
        result = load_config(config)
        assert result.excluded_dirs == {'vendor'}
        assert result.spec_dirs == {'docs/arch', 'project/reqs'}

    def test_no_specs_section_returns_empty(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["vendor"]\n')
        result = load_config(config)
        assert result.excluded_dirs == {'vendor'}
        assert result.spec_dirs == set()


class TestSaveConfig:
    def test_round_trip(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        original = {'vendor', 'static/external', 'docs/_build'}
        save_config(config, original, set())
        loaded = load_config(config)
        assert loaded.excluded_dirs == original

    def test_sorted_output(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {'z_last', 'a_first', 'm_middle'}, set())
        text = config.read_text()
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith('"')]
        assert lines == ['"a_first",', '"m_middle",', '"z_last",']

    def test_empty_exclusions(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, set(), set())
        loaded = load_config(config)
        assert loaded.excluded_dirs == set()

    def test_round_trip_with_specs(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {'vendor'}, {'plans', 'docs/arch'})
        loaded = load_config(config)
        assert loaded.excluded_dirs == {'vendor'}
        assert loaded.spec_dirs == {'plans', 'docs/arch'}

    def test_no_specs_omits_section(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {'vendor'}, set())
        content = config.read_text()
        assert '[specs]' not in content


class TestDiscoverNestedConfigs:
    def test_finds_nested_exclusions(self, tmp_path: Path):
        """Exclusions from a nested config are translated to root-relative paths."""
        project = tmp_path / 'project1'
        project.mkdir()
        save_config(project / CONFIG_FILENAME, {'vendor', 'static/external'}, set())

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == {'project1/vendor', 'project1/static/external'}

    def test_finds_nested_spec_dirs(self, tmp_path: Path):
        """Spec dirs from a nested config are translated to root-relative paths."""
        project = tmp_path / 'project1'
        project.mkdir()
        save_config(project / CONFIG_FILENAME, set(), {'docs/arch'})

        result = discover_nested_configs(tmp_path)
        assert result.spec_dirs == {'project1/docs/arch'}

    def test_ignores_root_config(self, tmp_path: Path):
        """A config at the root directory itself is not included."""
        save_config(tmp_path / CONFIG_FILENAME, {'vendor'}, set())

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == set()
        assert result.spec_dirs == set()

    def test_multiple_nested_configs(self, tmp_path: Path):
        """Multiple nested configs are all discovered and merged."""
        p1 = tmp_path / 'project1'
        p1.mkdir()
        save_config(p1 / CONFIG_FILENAME, {'vendor'}, set())

        p2 = tmp_path / 'project2'
        p2.mkdir()
        save_config(p2 / CONFIG_FILENAME, {'node_modules'}, {'docs'})

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == {'project1/vendor', 'project2/node_modules'}
        assert result.spec_dirs == {'project2/docs'}

    def test_deeply_nested_config(self, tmp_path: Path):
        """Config found deep in the tree is translated correctly."""
        deep = tmp_path / 'org' / 'repos' / 'myapp'
        deep.mkdir(parents=True)
        save_config(deep / CONFIG_FILENAME, {'typings'}, set())

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == {'org/repos/myapp/typings'}

    def test_skips_hidden_directories(self, tmp_path: Path):
        """Configs inside hidden directories are not discovered."""
        hidden = tmp_path / '.hidden'
        hidden.mkdir()
        save_config(hidden / CONFIG_FILENAME, {'vendor'}, set())

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == set()

    def test_malformed_config_skipped(self, tmp_path: Path):
        """A malformed config file is silently skipped."""
        project = tmp_path / 'project1'
        project.mkdir()
        (project / CONFIG_FILENAME).write_text('this is not valid toml {{{')

        result = discover_nested_configs(tmp_path)
        assert result.excluded_dirs == set()
        assert result.spec_dirs == set()


class TestCleanExclusions:
    def test_removes_children_of_excluded_parents(self):
        excluded = {'vendor', 'vendor/sub1', 'vendor/sub2', 'other'}
        cleaned = SetupApp._clean_exclusions(excluded)
        assert cleaned == {'vendor', 'other'}

    def test_no_redundancy(self):
        excluded = {'src', 'tests'}
        cleaned = SetupApp._clean_exclusions(excluded)
        assert cleaned == {'src', 'tests'}

    def test_empty(self):
        assert SetupApp._clean_exclusions(set()) == set()

    def test_nested_depth(self):
        excluded = {'a', 'a/b', 'a/b/c'}
        cleaned = SetupApp._clean_exclusions(excluded)
        assert cleaned == {'a'}
