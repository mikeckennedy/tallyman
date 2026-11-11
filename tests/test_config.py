from __future__ import annotations

import codecs
import os
import sys
from collections.abc import Callable
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
    without_copies,
)


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


_BOM_TEXT = '[exclude]\ndirectories = ["vendor"]\n'


class TestByteOrderMark:
    """Some editors (and Windows PowerShell's ``>``) start a file with a byte-order mark; it picks the encoding."""

    @pytest.mark.parametrize(
        'payload',
        [
            codecs.BOM_UTF8 + _BOM_TEXT.encode('utf-8'),
            codecs.BOM_UTF16_LE + _BOM_TEXT.encode('utf-16-le'),
            codecs.BOM_UTF16_BE + _BOM_TEXT.encode('utf-16-be'),
            codecs.BOM_UTF32_LE + _BOM_TEXT.encode('utf-32-le'),
            codecs.BOM_UTF32_BE + _BOM_TEXT.encode('utf-32-be'),
        ],
        ids=['utf-8', 'utf-16-le', 'utf-16-be', 'utf-32-le', 'utf-32-be'],
    )
    def test_bom_is_accepted(self, tmp_path: Path, payload: bytes) -> None:
        config = tmp_path / CONFIG_FILENAME
        config.write_bytes(payload)
        assert load_config(config).excluded_dirs == {'vendor'}

    def test_invalid_utf8_still_raises(self, tmp_path: Path) -> None:
        config = tmp_path / CONFIG_FILENAME
        config.write_bytes(b'\xc3\x28')  # not b'\xff\xfe': that is a UTF-16 byte-order mark
        with pytest.raises(ConfigError) as info:
            load_config(config)
        assert info.value.path == config

    def test_setup_rewrite_drops_the_bom(self, tmp_path: Path) -> None:
        config = tmp_path / CONFIG_FILENAME
        config.write_bytes(codecs.BOM_UTF8 + _BOM_TEXT.encode('utf-8'))
        loaded = load_config(config)
        save_config(config, loaded.excluded_dirs, loaded.spec_dirs, loaded.non_spec_dirs, patterns=loaded.patterns)
        assert not config.read_bytes().startswith(codecs.BOM_UTF8)
        assert load_config(config) == loaded


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


class TestWithoutCopies:
    def test_drops_exact_copies(self):
        local = TallyConfig({'a', 'b'}, {'s'}, {'i'})
        inherited = TallyConfig({'a'}, {'s'}, {'i', 'other'})
        assert without_copies(local, inherited) == TallyConfig({'b'})

    def test_keeps_a_contradictory_local_pair(self):
        """docs listed as both specs and ignored locally: specs wins now, and must still win after the save."""
        local = TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'docs'})
        assert without_copies(local, TallyConfig(spec_dirs={'docs'})) == local

    def test_drops_copies_of_every_other_config(self) -> None:
        """A parent and a nested config: copies of either go, opposite-set entries and a contradictory pair stay."""
        local = TallyConfig(
            {'sub/gen', 'vendor', 'build'},
            {'docs', 'lib', 'both', 'notes'},
            {'plans', 'both', 'sub/plans'},
        )
        parent = TallyConfig({'vendor'}, {'docs', 'both', 'plans'}, {'notes'})
        nested = TallyConfig({'sub/gen'}, {'lib'}, {'sub/plans', 'both'})
        assert without_copies(local, parent, nested) == TallyConfig({'build'}, {'both', 'notes'}, {'plans', 'both'})

    def test_keeps_an_override_of_a_contradictory_other(self) -> None:
        """The parent lists docs as both, so specs wins there: the local ignore is an override, not a copy."""
        local = TallyConfig(spec_dirs={'lib'}, non_spec_dirs={'docs'})
        parent = TallyConfig(spec_dirs={'docs', 'lib'}, non_spec_dirs={'docs', 'lib'})
        assert without_copies(local, parent) == local

    def test_no_others_changes_nothing(self) -> None:
        local = TallyConfig({'a'}, {'s'}, {'i'})
        assert without_copies(local) == local


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


class TestPatterns:
    def test_loaded_in_order_as_written(self, tmp_path: Path):
        config = _write(
            tmp_path / CONFIG_FILENAME, '[exclude]\npatterns = ["tests.rs", "!keep/tests.rs", "/top/", "a\\\\b"]\n'
        )
        assert load_config(config).patterns == ['tests.rs', '!keep/tests.rs', '/top/', 'a\\b']

    @pytest.mark.parametrize('value', ['"tests.rs"', '[1]', '["a", 2]'])
    def test_wrong_shape(self, tmp_path: Path, value: str):
        config = _write(tmp_path / CONFIG_FILENAME, f'[exclude]\npatterns = {value}\n')
        with pytest.raises(ConfigError, match='exclude.patterns must be a list of strings'):
            load_config(config)

    def test_round_trip_keeps_order_and_awkward_characters(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        patterns = ['tests.rs', '!src/keep/tests.rs', '/gen/', 'we"ird', 'back\\slash', 'caf\u00e9', '# not a comment']
        save_config(config, {'vendor'}, set(), patterns=patterns)
        loaded = load_config(config)
        assert loaded.patterns == patterns
        assert loaded.excluded_dirs == {'vendor'}

    def test_no_patterns_key_when_empty(self, tmp_path: Path):
        config = tmp_path / CONFIG_FILENAME
        save_config(config, set(), set())
        assert 'patterns' not in config.read_text()

    def test_moving_and_merging_drop_patterns(self, tmp_path: Path):
        config = TallyConfig({'a/b'}, patterns=['x.rs'])
        assert rebase_config(config, tmp_path, tmp_path / 'a').patterns == []
        assert prefixed(config, 'p').patterns == []
        assert merge_configs(config, config).patterns == []
        assert without_copies(config, TallyConfig()).patterns == []

    def test_chain_keeps_one_layer_per_config(self, tmp_path: Path):
        top = _write(tmp_path / CONFIG_FILENAME, '[exclude]\npatterns = ["a.rs"]\n')
        mid = _write(tmp_path / 'm' / CONFIG_FILENAME, '[exclude]\ndirectories = ["x"]\n')
        local = _write(tmp_path / 'm' / 's' / CONFIG_FILENAME, '[exclude]\npatterns = ["b.rs", "!c.rs"]\n')
        chain = load_config_chain([top, mid, local], tmp_path / 'm' / 's')
        assert chain.pattern_layers == [
            (tmp_path.resolve(), ['a.rs']),
            ((tmp_path / 'm' / 's').resolve(), ['b.rs', '!c.rs']),
        ]
        assert chain.local.patterns == ['b.rs', '!c.rs']

    def test_nested_configs_report_their_layers(self, tmp_path: Path):
        _write(tmp_path / 'a' / CONFIG_FILENAME, '[exclude]\npatterns = ["x.rs"]\n')
        _write(tmp_path / 'a' / 'b' / CONFIG_FILENAME, '[exclude]\npatterns = ["y.rs"]\n')
        _write(tmp_path / 'c' / CONFIG_FILENAME, '[exclude]\ndirectories = ["z"]\n')
        layers: list[tuple[Path, list[str]]] = []
        discover_nested_configs(tmp_path, layers)
        assert layers == [(tmp_path / 'a', ['x.rs']), (tmp_path / 'a' / 'b', ['y.rs'])]


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

    @pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='named pipes need os.mkfifo (not on Windows)')
    def test_a_fifo_in_the_way_is_not_opened(self, tmp_path: Path, make_fifo: Callable[..., Path]) -> None:
        """Opening a FIFO for writing blocks until something reads it, so setup's save would hang."""
        config = make_fifo(tmp_path / CONFIG_FILENAME, for_writer=True)
        with pytest.raises(OSError, match='not a regular file'):
            save_config(config, {'vendor'}, set())

    @pytest.mark.skipif(sys.platform == 'win32', reason='creating symlinks needs privileges on Windows')
    def test_a_dangling_symlink_is_refused(self, tmp_path: Path) -> None:
        """Writing through it would create its target, which may be anywhere."""
        config = tmp_path / CONFIG_FILENAME
        config.symlink_to(tmp_path / 'elsewhere' / 'missing.toml')
        (tmp_path / 'elsewhere').mkdir()
        with pytest.raises(OSError, match='not a regular file'):
            save_config(config, {'vendor'}, set())
        assert not (tmp_path / 'elsewhere' / 'missing.toml').exists()

    @pytest.mark.skipif(sys.platform == 'win32', reason='creating symlinks needs privileges on Windows')
    def test_a_symlink_to_a_regular_file_is_written_through(self, tmp_path: Path) -> None:
        target = tmp_path / 'real.toml'
        target.write_text('')
        config = tmp_path / CONFIG_FILENAME
        config.symlink_to(target)
        save_config(config, {'vendor'}, set())
        assert config.is_symlink()
        assert load_config(target).excluded_dirs == {'vendor'}


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
