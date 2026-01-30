from pathlib import Path

from tallyman.config import CONFIG_FILENAME, find_config, load_config, save_config
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
        assert result == {'vendor', 'static/external'}

    def test_empty_directories(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        result = load_config(config)
        assert result == set()

    def test_no_exclude_section(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('# empty config\n')
        result = load_config(config)
        assert result == set()


class TestSaveConfig:
    def test_round_trip(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        original = {'vendor', 'static/external', 'docs/_build'}
        save_config(config, original)
        loaded = load_config(config)
        assert loaded == original

    def test_sorted_output(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {'z_last', 'a_first', 'm_middle'})
        text = config.read_text()
        lines = [line.strip() for line in text.splitlines() if line.strip().startswith('"')]
        assert lines == ['"a_first",', '"m_middle",', '"z_last",']

    def test_empty_exclusions(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, set())
        loaded = load_config(config)
        assert loaded == set()


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
