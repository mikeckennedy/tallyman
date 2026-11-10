from __future__ import annotations

from pathlib import Path

import pytest

from tallyman.config import (
    CONFIG_FILENAME,
    ConfigError,
    TallyConfig,
    discover_nested_configs,
    find_configs,
    load_config,
    load_config_chain,
    merge_configs,
    prefixed,
    rebase_config,
    save_config,
    without_inherited,
)
from tallyman.tui.setup_app import SetupApp


class TestFindConfigs:
    def test_returns_path_when_exists(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        assert find_configs(tmp_path) == [config]

    def test_returns_empty_when_missing(self, tmp_path: Path):
        assert find_configs(tmp_path) == []

    def test_finds_config_in_parent_directory(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = []\n')
        sub = tmp_path / 'src' / 'app'
        sub.mkdir(parents=True)
        assert find_configs(sub) == [config]

    def test_finds_every_config_shallowest_first(self, tmp_path: Path):
        (tmp_path / '.git').mkdir()
        root_config = tmp_path / CONFIG_FILENAME
        root_config.write_text('[exclude]\ndirectories = ["root"]\n')
        (tmp_path / 'mid' / 'sub').mkdir(parents=True)
        mid_config = tmp_path / 'mid' / CONFIG_FILENAME
        mid_config.write_text('[exclude]\ndirectories = []\n')
        sub_config = tmp_path / 'mid' / 'sub' / CONFIG_FILENAME
        sub_config.write_text('[exclude]\ndirectories = ["sub"]\n')
        assert find_configs(tmp_path / 'mid' / 'sub') == [root_config, mid_config, sub_config]

    def test_stops_at_git_root(self, tmp_path: Path):
        """A stray config above the repo (say, in ~) must not apply to the project."""
        (tmp_path / CONFIG_FILENAME).write_text('[exclude]\ndirectories = ["src"]\n')
        repo = tmp_path / 'repo'
        (repo / '.git').mkdir(parents=True)
        (repo / 'src').mkdir()
        assert find_configs(repo / 'src') == []

    def test_outside_a_repo_checks_only_the_root(self, tmp_path: Path):
        (tmp_path / CONFIG_FILENAME).write_text('[exclude]\ndirectories = []\n')
        sub = tmp_path / 'sub'
        sub.mkdir()
        assert find_configs(sub) == []
        (sub / CONFIG_FILENAME).write_text('[exclude]\ndirectories = []\n')
        assert find_configs(sub) == [sub / CONFIG_FILENAME]


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

    def test_malformed_toml_raises_config_error(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('not toml [\n')
        with pytest.raises(ConfigError):
            load_config(config)

    @pytest.mark.parametrize(
        'text',
        [
            'exclude = "vendor"\n',
            '[exclude]\ndirectories = "vendor"\n',
            '[exclude]\ndirectories = [1, 2]\n',
            '[specs]\ndirectories = [true]\n',
        ],
    )
    def test_wrong_shape_raises_config_error(self, tmp_path: Path, text: str):
        config = tmp_path / CONFIG_FILENAME
        config.write_text(text)
        with pytest.raises(ConfigError):
            load_config(config)

    def test_unreadable_file_raises_config_error(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.mkdir()  # a directory where the file should be
        with pytest.raises(ConfigError):
            load_config(config)

    def test_normalizes_hand_edited_paths(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["vendor/", "./static", "a//b", "/top", "", ".", "./"]\n')
        assert load_config(config).excluded_dirs == {'vendor', 'static', 'a/b', 'top'}

    @pytest.mark.parametrize(('windows', 'expected'), [(False, {'a\\b'}), (True, {'a/b'})])
    def test_backslash_is_a_separator_only_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool, expected: set[str]
    ):
        monkeypatch.setattr('tallyman.config._WINDOWS', windows)
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["a\\\\b"]\n')
        assert load_config(config).excluded_dirs == expected

    def test_resolves_dot_segments_and_drops_escapes(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["a/./b", "a/../c", "a/.", "../x", "..", "d/../../y"]\n')
        assert load_config(config).excluded_dirs == {'a/b', 'c', 'a'}

    def test_dot_means_this_directory_for_specs_only(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["."]\n\n[specs]\ndirectories = [".", "./"]\n')
        result = load_config(config)
        assert result.excluded_dirs == set()
        assert result.spec_dirs == {'.'}

    @pytest.mark.parametrize('payload', [b'[exclude]\ndirectories = ["caf\xe9"]\n', b'a = ' + b'[' * 100_000])
    def test_undecodable_or_pathological_file_raises_config_error(self, tmp_path: Path, payload: bytes):
        """Non-UTF-8 bytes raise UnicodeDecodeError and deep nesting RecursionError inside tomllib."""
        config = tmp_path / CONFIG_FILENAME
        config.write_bytes(payload)
        with pytest.raises(ConfigError):
            load_config(config)

    def test_loads_spec_ignore(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[specs]\ndirectories = ["design"]\nignore = ["src/agents/", "."]\n')
        result = load_config(config)
        assert result.spec_dirs == {'design'}
        assert result.non_spec_dirs == {'src/agents', '.'}

    def test_config_without_ignore_has_no_non_spec_dirs(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[exclude]\ndirectories = ["vendor"]\n\n[specs]\ndirectories = ["plans"]\n')
        assert load_config(config) == TallyConfig({'vendor'}, {'plans'}, set())

    def test_spec_ignore_must_be_a_list_of_strings(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        config.write_text('[specs]\nignore = "plans"\n')
        with pytest.raises(ConfigError, match='specs.ignore'):
            load_config(config)


class TestRebaseConfig:
    def _rebase(self, tmp_path: Path, config: TallyConfig, scan: str) -> TallyConfig:
        (tmp_path / scan).mkdir(parents=True, exist_ok=True)
        return rebase_config(config, tmp_path, tmp_path / scan)

    def test_same_directory_is_unchanged(self, tmp_path: Path):
        config = TallyConfig({'vendor'}, {'plans'})
        assert rebase_config(config, tmp_path, tmp_path) == config

    def test_entries_below_the_scan_root_keep_their_tail(self, tmp_path: Path):
        result = self._rebase(tmp_path, TallyConfig({'src/vendor', 'src/a/b'}, {'src/design'}), 'src')
        assert result == TallyConfig({'vendor', 'a/b'}, {'design'})

    def test_entries_outside_the_scan_root_are_dropped(self, tmp_path: Path):
        """The bug this fixes: 'docs' meant proj/docs, not proj/src/docs."""
        result = self._rebase(tmp_path, TallyConfig({'docs', 'srcx/vendor'}, {'plans'}), 'src')
        assert result == TallyConfig(set(), set())

    def test_excluded_scan_root_or_ancestor_is_dropped(self, tmp_path: Path):
        """Scanning a directory explicitly overrides an exclusion of it or of a parent."""
        assert self._rebase(tmp_path, TallyConfig({'src'}, set()), 'src').excluded_dirs == set()
        assert self._rebase(tmp_path, TallyConfig({'src'}, set()), 'src/app').excluded_dirs == set()

    def test_spec_scan_root_or_ancestor_becomes_self(self, tmp_path: Path):
        assert self._rebase(tmp_path, TallyConfig(set(), {'design'}), 'design').spec_dirs == {'.'}
        assert self._rebase(tmp_path, TallyConfig(set(), {'design', 'design/v2/a'}), 'design/v2').spec_dirs == {
            '.',
            'a',
        }
        assert self._rebase(tmp_path, TallyConfig(set(), {'.'}), 'src').spec_dirs == {'.'}
        assert self._rebase(tmp_path, TallyConfig(set(), {'design'}), 'src').spec_dirs == set()

    def test_ignore_entries_are_rebased(self, tmp_path: Path):
        result = self._rebase(tmp_path, TallyConfig(set(), set(), {'src/agents', 'lib'}), 'src')
        assert result.non_spec_dirs == {'agents'}

    def test_deeper_ignore_covering_the_root_wins(self, tmp_path: Path):
        result = self._rebase(tmp_path, TallyConfig(set(), {'design'}, {'design/v2'}), 'design/v2/x')
        assert (result.spec_dirs, result.non_spec_dirs) == (set(), {'.'})

    def test_deeper_spec_covering_the_root_wins(self, tmp_path: Path):
        result = self._rebase(tmp_path, TallyConfig(set(), {'a/b'}, {'a'}), 'a/b/c')
        assert (result.spec_dirs, result.non_spec_dirs) == ({'.'}, set())


class TestMergeConfigs:
    def test_exclusions_add_up(self):
        merged = merge_configs(TallyConfig({'a'}), TallyConfig({'b'}))
        assert merged.excluded_dirs == {'a', 'b'}

    def test_deeper_wins_on_the_same_path(self):
        assert merge_configs(TallyConfig(spec_dirs={'x'}), TallyConfig(non_spec_dirs={'x'})) == TallyConfig(
            non_spec_dirs={'x'}
        )
        assert merge_configs(TallyConfig(non_spec_dirs={'x'}), TallyConfig(spec_dirs={'x'})) == TallyConfig(
            spec_dirs={'x'}
        )

    def test_different_paths_are_kept(self):
        merged = merge_configs(TallyConfig(spec_dirs={'x'}), TallyConfig(non_spec_dirs={'x/y'}))
        assert merged == TallyConfig(spec_dirs={'x'}, non_spec_dirs={'x/y'})

    def test_inputs_are_not_modified(self):
        shallow = TallyConfig({'a'}, {'x'}, set())
        merge_configs(shallow, TallyConfig(non_spec_dirs={'x'}))
        assert shallow == TallyConfig({'a'}, {'x'}, set())


class TestWithoutInherited:
    def test_drops_exact_copies(self):
        local = TallyConfig({'a', 'b'}, {'s'}, {'i'})
        inherited = TallyConfig({'a'}, {'s'}, {'i', 'other'})
        assert without_inherited(local, inherited) == TallyConfig({'b'})

    def test_keeps_a_contradictory_local_pair(self):
        """docs listed as both specs and ignored locally: specs wins now, and must still win after the save."""
        local = TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'docs'})
        assert without_inherited(local, TallyConfig(spec_dirs={'docs'})) == local


class TestPrefixed:
    def test_self_becomes_the_directory(self):
        assert prefixed(TallyConfig({'b'}, {'.'}, {'c'}), 'app') == TallyConfig({'app/b'}, {'app'}, {'app/c'})

    def test_empty_prefix_copies(self):
        config = TallyConfig({'b'}, {'.'}, set())
        copy = prefixed(config, '')
        assert copy == config
        copy.excluded_dirs.add('z')
        assert config.excluded_dirs == {'b'}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestLoadConfigChain:
    def test_no_configs(self, tmp_path: Path):
        chain = load_config_chain([], tmp_path)
        assert chain.effective == TallyConfig()
        assert chain.paths == []

    def test_parent_and_local_both_apply(self, tmp_path: Path):
        parent = _write(tmp_path / CONFIG_FILENAME, '[exclude]\ndirectories = ["app/vendor", "other"]\n')
        local = _write(tmp_path / 'app' / CONFIG_FILENAME, '[exclude]\ndirectories = ["build"]\n')
        chain = load_config_chain([parent, local], tmp_path / 'app')
        assert chain.inherited == TallyConfig({'vendor'})
        assert chain.local == TallyConfig({'build'})
        assert chain.effective.excluded_dirs == {'vendor', 'build'}
        assert chain.paths == [parent, local]

    def test_local_config_wins_on_the_same_path(self, tmp_path: Path):
        parent = _write(tmp_path / CONFIG_FILENAME, '[specs]\nignore = ["app/plans"]\n')
        local = _write(tmp_path / 'app' / CONFIG_FILENAME, '[specs]\ndirectories = ["plans"]\n')
        effective = load_config_chain([parent, local], tmp_path / 'app').effective
        assert effective.spec_dirs == {'plans'}
        assert effective.non_spec_dirs == set()

    def test_middle_config_wins_over_the_top_one(self, tmp_path: Path):
        top = _write(tmp_path / CONFIG_FILENAME, '[specs]\ndirectories = ["a/b"]\n')
        mid = _write(tmp_path / 'a' / CONFIG_FILENAME, '[specs]\nignore = ["b"]\n')
        (tmp_path / 'a' / 'b' / 'c').mkdir(parents=True)
        chain = load_config_chain([top, mid], tmp_path / 'a' / 'b' / 'c')
        assert chain.inherited == TallyConfig(non_spec_dirs={'.'})

    def test_deeper_cover_of_the_scan_root_wins(self, tmp_path: Path):
        """The top config marks a/ as specs; a middle config ignores a/b. Scanning a/b/c: not specs."""
        top = _write(tmp_path / CONFIG_FILENAME, '[specs]\ndirectories = ["a"]\n')
        mid = _write(tmp_path / 'a' / CONFIG_FILENAME, '[specs]\nignore = ["b"]\n')
        (tmp_path / 'a' / 'b' / 'c').mkdir(parents=True)
        chain = load_config_chain([top, mid], tmp_path / 'a' / 'b' / 'c')
        assert chain.inherited == TallyConfig(non_spec_dirs={'.'})

    def test_malformed_config_names_its_file(self, tmp_path: Path):
        top = _write(tmp_path / CONFIG_FILENAME, '[exclude]\ndirectories = []\n')
        mid = _write(tmp_path / 'a' / CONFIG_FILENAME, 'not toml [\n')
        with pytest.raises(ConfigError) as exc:
            load_config_chain([top, mid], tmp_path / 'a')
        assert exc.value.path == mid

    def test_wrong_shape_names_its_file(self, tmp_path: Path):
        bad = _write(tmp_path / CONFIG_FILENAME, '[exclude]\ndirectories = "vendor"\n')
        with pytest.raises(ConfigError) as exc:
            load_config_chain([bad], tmp_path)
        assert exc.value.path == bad

    def test_on_error_skips_the_bad_file(self, tmp_path: Path):
        top = _write(tmp_path / CONFIG_FILENAME, 'not toml [\n')
        local = _write(tmp_path / 'a' / CONFIG_FILENAME, '[exclude]\ndirectories = ["x"]\n')
        errors: list[ConfigError] = []
        chain = load_config_chain([top, local], tmp_path / 'a', on_error=errors.append)
        assert [e.path for e in errors] == [top]
        assert chain.paths == [local]
        assert chain.effective.excluded_dirs == {'x'}


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

    @pytest.mark.parametrize('name', ['we"ird', 'back\\slash', 'caf\u00e9', 'tab\there', 'ctl\x01\x7f', 'sp ace '])
    def test_round_trip_awkward_names(self, tmp_path: Path, name: str):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {name, f'{name}/sub'}, {name})
        loaded = load_config(config)
        assert loaded.excluded_dirs == {name, f'{name}/sub'}
        assert loaded.spec_dirs == {name}

    def test_round_trip_with_spec_ignore(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, {'vendor'}, set(), {'plans', 'src/agents'})
        assert load_config(config) == TallyConfig({'vendor'}, set(), {'plans', 'src/agents'})

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
