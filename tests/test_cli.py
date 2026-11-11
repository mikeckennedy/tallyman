from __future__ import annotations

import codecs
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest

from tallyman import __version__, cli
from tallyman.aggregator import TallyResult
from tallyman.config import CONFIG_FILENAME, TallyConfig, load_config
from tallyman.gitignore import GitIgnoreSpec


def _make(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


ECHO = 'echo'  # setup_result meaning: the user saved without changing anything


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *argv: str,
    interactive: bool = False,
    setup_result: object = None,
    setup_calls: Optional[list[tuple[set[str], set[str], set[str]]]] = None,
    inherited_calls: Optional[list[TallyConfig]] = None,
    pattern_calls: Optional[list[GitIgnoreSpec]] = None,
) -> Optional[TallyResult]:
    """Run tallyman's main() with *argv*; return the result it would have displayed (None if it exited first).

    The setup TUI is replaced. It records the (excluded, specs, non-specs) it was pre-filled with in
    *setup_calls*, and the locked parent settings it was given in *inherited_calls*, then returns
    *setup_result*: such a tuple, ECHO to save the pre-fill unchanged, or None to fail the test because
    setup should not have launched.
    """
    captured: list[TallyResult] = []
    monkeypatch.setattr(sys, 'argv', ['tallyman', *argv])
    monkeypatch.setattr(cli, '_is_interactive', lambda: interactive)
    monkeypatch.setattr(cli, 'display_results', lambda tally, **_: captured.append(tally))

    def fake_setup(
        _root: Path,
        _spec: object,
        excluded: set[str],
        specs: set[str],
        non_specs: set[str],
        inherited: Optional[TallyConfig] = None,
        exclude_patterns: Optional[GitIgnoreSpec] = None,
        **_kwargs: object,
    ) -> object:
        prefill = (set(excluded), set(specs), set(non_specs))
        if setup_calls is not None:
            setup_calls.append(prefill)
        if inherited_calls is not None:
            inherited_calls.append(inherited or TallyConfig())
        if pattern_calls is not None and exclude_patterns is not None:
            pattern_calls.append(exclude_patterns)
        if setup_result is None:
            raise AssertionError('the setup TUI must not launch here')
        return prefill if setup_result == ECHO else setup_result

    monkeypatch.setattr(cli, 'run_setup', fake_setup)
    cli.main()
    return captured[0] if captured else None


def _files_by_category(tally: TallyResult) -> dict[str, int]:
    return {f'{s.language.name}/{s.language.category}': s.file_count for s in tally.by_language}


class TestConfigFromParentDirectory:
    def test_parent_config_is_rebased_onto_the_scan_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Excluding 'src/vendor' and 'docs' at the repo root, then scanning src/."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\ndirectories = ["src/vendor", "docs"]\n',
                'src/app.py': 'x = 1\n',
                'src/vendor/lib.py': 'x = 1\n',
                'src/docs/conf.py': 'x = 1\n',
            },
        )
        tally = _run(monkeypatch, str(tmp_path / 'src'))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 2}  # app.py and docs/conf.py, not vendor/lib.py

    def test_parent_spec_dir_covering_the_scan_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\ndirectories = []\n\n[specs]\ndirectories = ["design"]\n',
                'design/top.md': '# t\n',
                'design/v2/deep.md': '# d\n',
            },
        )
        tally = _run(monkeypatch, str(tmp_path / 'design'))
        assert tally is not None
        assert _files_by_category(tally) == {'Markdown/specs': 2}

    def test_config_above_the_git_root_is_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _make(tmp_path, {CONFIG_FILENAME: '[exclude]\ndirectories = ["repo"]\n', 'repo/a.py': 'x = 1\n'})
        (tmp_path / 'repo' / '.git').mkdir()
        tally = _run(monkeypatch, str(tmp_path / 'repo'))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1}


class TestConfigWithByteOrderMark:
    def test_config_with_bom_applies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Some editors save a UTF-8 byte-order mark; the config must load, not fail with "Invalid statement"."""
        _make(tmp_path, {'a.py': 'x = 1\n', 'vendor/x.py': 'x = 1\n'})
        (tmp_path / CONFIG_FILENAME).write_bytes(codecs.BOM_UTF8 + b'[exclude]\ndirectories = ["vendor"]\n')
        tally = _run(monkeypatch, str(tmp_path))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1}


class TestErrors:
    def test_not_a_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        (tmp_path / 'file.py').write_text('x = 1\n')
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(tmp_path / 'file.py'))
        assert exc.value.code == 1
        assert 'is not a directory' in capsys.readouterr().err

    def test_malformed_root_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        _make(tmp_path, {CONFIG_FILENAME: 'not toml [\n', 'a.py': 'x = 1\n'})
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(tmp_path))
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert f'could not read {tmp_path / CONFIG_FILENAME}' in err
        assert 'tallyman --setup' in err
        assert 'Traceback' not in err

    def test_wrong_shape_root_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        _make(tmp_path, {CONFIG_FILENAME: '[exclude]\ndirectories = "vendor"\n'})
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(tmp_path))
        assert exc.value.code == 1
        assert 'must be a list of strings' in capsys.readouterr().err


class TestNoTerminal:
    def test_first_run_uses_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        _make(tmp_path, {'a.py': 'x = 1\n', 'plans/p.md': '# p\n'})
        tally = _run(monkeypatch, str(tmp_path))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1, 'Markdown/specs': 1}
        assert not (tmp_path / CONFIG_FILENAME).exists()
        assert 'tallyman --setup' in capsys.readouterr().err

    def test_setup_flag_needs_a_terminal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, '--setup', str(tmp_path))
        assert exc.value.code == 2
        assert 'interactive terminal' in capsys.readouterr().err

    def test_existing_config_needs_no_terminal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        _make(
            tmp_path,
            {CONFIG_FILENAME: '[exclude]\ndirectories = ["vendor"]\n', 'a.py': 'x = 1\n', 'vendor/v.py': 'x\n'},
        )
        tally = _run(monkeypatch, str(tmp_path))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1}  # vendor/v.py excluded, the config itself not counted
        assert capsys.readouterr().err == ''


class TestSetupRecovery:
    def test_setup_replaces_a_malformed_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        """The error message says to re-run --setup, so --setup must work on a broken config."""
        _make(tmp_path, {CONFIG_FILENAME: 'not toml [\n', 'a.py': 'x = 1\n', 'vendor/v.py': 'x = 1\n'})
        tally = _run(monkeypatch, '--setup', str(tmp_path), interactive=True, setup_result=({'vendor'}, set(), set()))
        assert tally is not None
        assert 'Warning: ignoring' in capsys.readouterr().err
        assert load_config(tmp_path / CONFIG_FILENAME).excluded_dirs == {'vendor'}


class TestSetupWithParentConfig:
    def test_setup_locks_parent_settings_instead_of_copying_them(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: (
                    '[exclude]\ndirectories = ["src/vendor", "docs"]\n\n[specs]\ndirectories = ["src/design"]\n'
                ),
                'src/pkg/.tally-config.toml': '[exclude]\ndirectories = ["gen"]\n',
                'src/app.py': 'x = 1\n',
                'src/vendor/v.py': 'x = 1\n',
            },
        )
        calls: list[tuple[set[str], set[str], set[str]]] = []
        inherited: list[TallyConfig] = []
        _run(
            monkeypatch,
            '--setup',
            str(tmp_path / 'src'),
            interactive=True,
            setup_result=ECHO,
            setup_calls=calls,
            inherited_calls=inherited,
        )
        assert calls == [(set(), set(), set())]  # nothing local to edit; src/pkg's config stays in its own file
        assert inherited == [TallyConfig({'vendor'}, {'design'}, set())]
        saved = load_config(tmp_path / 'src' / CONFIG_FILENAME)
        assert saved == TallyConfig()
        tally = _run(monkeypatch, str(tmp_path / 'src'))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1}  # the parent still excludes vendor

    def test_setup_drops_local_copies_of_parent_settings(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Older versions copied the parent's settings into the new config; setup clears those copies."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\ndirectories = ["src/vendor"]\n',
                'src/.tally-config.toml': '[exclude]\ndirectories = ["vendor", "build"]\n',
            },
        )
        calls: list[tuple[set[str], set[str], set[str]]] = []
        _run(monkeypatch, '--setup', str(tmp_path / 'src'), interactive=True, setup_result=ECHO, setup_calls=calls)
        assert calls == [({'vendor', 'build'}, set(), set())]
        assert load_config(tmp_path / 'src' / CONFIG_FILENAME).excluded_dirs == {'build'}

    def test_setup_keeps_a_spec_dir_that_covers_the_scan_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A no-op setup run must not change the numbers: design/ stays specs."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\ndirectories = ["design"]\n', 'design/a.md': '# a\n'})
        tally = _run(monkeypatch, '--setup', str(tmp_path / 'design'), interactive=True, setup_result=ECHO)
        assert tally is not None
        assert _files_by_category(tally)['Markdown/specs'] == 1
        assert 'Markdown/docs' not in _files_by_category(tally)
        assert load_config(tmp_path / 'design' / CONFIG_FILENAME).spec_dirs == set()  # the parent's config says so
        tally = _run(monkeypatch, str(tmp_path / 'design'))
        assert tally is not None
        assert _files_by_category(tally)['Markdown/specs'] == 1

    def test_unsavable_config_warns_and_still_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / CONFIG_FILENAME).mkdir()  # a directory where the file should go
        (tmp_path / 'a.py').write_text('x = 1\n')
        tally = _run(monkeypatch, '--setup', str(tmp_path), interactive=True, setup_result=(set(), set(), set()))
        assert tally is not None
        assert 'could not save' in capsys.readouterr().err


class TestScanInsideSpecDirectory:
    def test_scanning_inside_plans_counts_specs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """From the repo root plans/ is specs, so scanning plans/ or below it must say the same."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {'plans/p.md': '# p\n', 'plans/sub/q.md': '# q\n'})
        for scan in ('', 'plans', 'plans/sub'):
            tally = _run(monkeypatch, str(tmp_path / scan))
            assert tally is not None
            assert set(_files_by_category(tally)) == {'Markdown/specs'}, scan


class TestErrorHint:
    def test_hint_names_the_broken_configs_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: 'not toml [\n', 'src/a.py': 'x = 1\n'})
        with pytest.raises(SystemExit):
            _run(monkeypatch, str(tmp_path / 'src'))
        assert f'tallyman --setup {tmp_path}\n' in capsys.readouterr().err


_SRC = str(Path(__file__).resolve().parent.parent / 'src')

# An SGR sequence that sets a foreground or background colour (30-37, 38;..., 40-47, 90-97, 100-107)
_COLOUR_CODE = re.compile(r'\x1b\[(?:\d+;)*(?:3[0-8]|4[0-8]|9[0-7]|10[0-7])[;m]')


def _run_process(
    directory: Path, preexec_fn: Optional[Callable[[], None]] = None, env: Optional[dict[str, str]] = None
) -> subprocess.CompletedProcess[str]:
    """Run the real CLI in a subprocess with stdin at /dev/null: no monkeypatching, so the real terminal check runs.

    *env* is merged over the current environment. Output is decoded as UTF-8, with anything else shown as U+FFFD.
    """
    return subprocess.run(
        [sys.executable, '-m', 'tallyman', str(directory)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
        env={**os.environ, 'PYTHONPATH': _SRC, 'NO_COLOR': '1', **(env or {})},
        preexec_fn=preexec_fn,
    )


class TestRealProcess:
    def test_no_terminal_returns_promptly(self, tmp_path: Path):
        (tmp_path / 'a.py').write_text('x = 1\n')
        result = _run_process(tmp_path)
        assert result.returncode == 0, result.stderr
        assert 'tallyman --setup' in result.stderr
        assert not (tmp_path / CONFIG_FILENAME).exists()

    def test_pattern_note_is_printed(self, tmp_path: Path):
        (tmp_path / CONFIG_FILENAME).write_text('[exclude]\npatterns = ["tests.rs"]\n')
        (tmp_path / 'src' / 'routing').mkdir(parents=True)
        (tmp_path / 'src' / 'routing.rs').write_text('fn a() {}\n')
        (tmp_path / 'src' / 'routing' / 'tests.rs').write_text('fn t() {}\n')
        result = _run_process(tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.rstrip().endswith('Excluded by [exclude] patterns: 1 file')

    @pytest.mark.skipif(sys.platform == 'win32', reason='closing stdin in the child is POSIX-only')
    def test_closed_stdin(self, tmp_path: Path):
        (tmp_path / 'a.py').write_text('x = 1\n')
        result = _run_process(tmp_path, preexec_fn=lambda: os.close(0))
        assert result.returncode == 0, result.stderr
        assert 'Traceback' not in result.stderr

    @pytest.mark.parametrize('encoding', ['ascii', 'cp1252'])
    def test_narrow_stdout_encoding_does_not_crash(self, tmp_path: Path, encoding: str) -> None:
        """Characters stdout can't encode print as '?', and the report falls back to ASCII throughout."""
        project = tmp_path / '日本'
        try:
            project.mkdir()
        except OSError:
            pytest.skip('the filesystem refuses a non-ASCII directory name')
        (project / 'a.py').write_text('x = 1\n')
        (project / 'b.rs').write_text('fn a() {}\n')  # two languages, so the legend has a separator
        result = _run_process(project, env={'PYTHONIOENCODING': encoding})
        assert result.returncode == 0, result.stderr
        assert '??' in result.stdout  # the directory name
        assert '#' * 10 in result.stdout  # the ASCII bar
        assert '  |  ' in result.stdout  # the ASCII legend separator


class TestSpecIgnoreEndToEnd:
    def test_ignored_spec_dir_stays_docs_when_scanned_from_inside(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """[specs] ignore = ["plans"] must beat the scan-inside-plans rule."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\nignore = ["plans"]\n', 'plans/sub/q.md': '# q\n'})
        for scan in ('', 'plans', 'plans/sub'):
            tally = _run(monkeypatch, str(tmp_path / scan))
            assert tally is not None
            assert _files_by_category(tally).get('Markdown/docs') == 1, scan
            assert 'Markdown/specs' not in _files_by_category(tally), scan

    def test_setup_passes_a_parent_ignore_list_as_inherited(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\nignore = ["src/agents"]\n', 'src/agents/a.md': '# a\n'})
        calls: list[tuple[set[str], set[str], set[str]]] = []
        inherited: list[TallyConfig] = []
        _run(
            monkeypatch,
            '--setup',
            str(tmp_path / 'src'),
            interactive=True,
            setup_result=ECHO,
            setup_calls=calls,
            inherited_calls=inherited,
        )
        assert calls == [(set(), set(), set())]
        assert inherited[0].non_spec_dirs == {'agents'}
        assert load_config(tmp_path / 'src' / CONFIG_FILENAME).non_spec_dirs == set()

    def test_setup_prefill_and_save_carry_a_local_ignore_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\nignore = ["agents"]\n', 'agents/a.md': '# a\n'})
        calls: list[tuple[set[str], set[str], set[str]]] = []
        _run(monkeypatch, '--setup', str(tmp_path), interactive=True, setup_result=ECHO, setup_calls=calls)
        assert calls == [(set(), set(), {'agents'})]
        assert load_config(tmp_path / CONFIG_FILENAME).non_spec_dirs == {'agents'}


class TestConfigChain:
    def test_every_config_down_to_the_scan_root_applies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """repo/ excludes app/vendor, repo/app/ excludes build; scanning app/ must honour both."""
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\ndirectories = ["app/vendor"]\n',
                'app/.tally-config.toml': '[exclude]\ndirectories = ["build"]\n',
                'app/main.py': 'x = 1\n',
                'app/vendor/v.py': 'x = 1\n',
                'app/build/b.py': 'x = 1\n',
            },
        )
        tally = _run(monkeypatch, str(tmp_path / 'app'))
        assert tally is not None
        assert _files_by_category(tally) == {'Python/code': 1}

    def test_deeper_config_wins_on_the_same_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[specs]\nignore = ["app/plans"]\n',
                'app/.tally-config.toml': '[specs]\ndirectories = ["plans"]\n',
                'app/plans/p.md': '# p\n',
            },
        )
        tally = _run(monkeypatch, str(tmp_path / 'app'))
        assert tally is not None
        assert _files_by_category(tally) == {'Markdown/specs': 1}

    def test_malformed_parent_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: 'not toml [\n',
                'app/.tally-config.toml': '[exclude]\ndirectories = []\n',
                'app/a.py': '',
            },
        )
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(tmp_path / 'app'))
        assert exc.value.code == 1
        assert f'could not read {tmp_path / CONFIG_FILENAME}' in capsys.readouterr().err

    def test_setup_skips_a_malformed_parent_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: 'not toml [\n', 'app/a.py': 'x = 1\n'})
        tally = _run(monkeypatch, '--setup', str(tmp_path / 'app'), interactive=True, setup_result=ECHO)
        assert tally is not None
        assert 'its settings are skipped until it is fixed' in capsys.readouterr().err


class TestExcludePatterns:
    def test_setup_keeps_hand_written_patterns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Setup rewrites the file but never edits patterns: they must survive exactly, in order."""
        block = 'patterns = [\n    "tests.rs",\n    "!src/keep/tests.rs",\n    "/gen/",\n    "we\\"ird",\n]\n'
        _make(tmp_path, {CONFIG_FILENAME: '[exclude]\ndirectories = ["vendor"]\n' + block, 'a.rs': ''})
        patterns = ['tests.rs', '!src/keep/tests.rs', '/gen/', 'we"ird']
        assert load_config(tmp_path / CONFIG_FILENAME).patterns == patterns
        _run(monkeypatch, '--setup', str(tmp_path), interactive=True, setup_result=({'vendor', 'build'}, set(), set()))
        assert block in (tmp_path / CONFIG_FILENAME).read_text()
        saved = load_config(tmp_path / CONFIG_FILENAME)
        assert saved.patterns == patterns
        assert saved.excluded_dirs == {'vendor', 'build'}

    def test_setup_shows_parent_local_and_nested_patterns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\npatterns = ["/app/gen/"]\n',
                'app/.tally-config.toml': '[exclude]\npatterns = ["fixtures/"]\n',
                'app/crate/.tally-config.toml': '[exclude]\npatterns = ["/out/"]\n',
                'app/main.rs': '',
            },
        )
        specs: list[GitIgnoreSpec] = []
        _run(monkeypatch, '--setup', str(tmp_path / 'app'), interactive=True, setup_result=ECHO, pattern_calls=specs)
        assert len(specs) == 1
        assert specs[0].match_file('gen/')  # from the parent
        assert specs[0].match_file('x/fixtures/')  # from the scan root's own config
        assert specs[0].match_file('crate/out/')  # from a nested config
        assert not specs[0].match_file('out/')

    def test_patterns_apply_on_a_normal_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\npatterns = ["tests.rs"]\n',
                'src/routing.rs': 'fn a() {}\n',
                'src/routing/tests.rs': 'fn t() {}\n',
            },
        )
        tally = _run(monkeypatch, str(tmp_path))
        assert tally is not None
        assert _files_by_category(tally) == {'Rust/code': 1}

    def test_parent_patterns_are_anchored_to_the_parent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: '[exclude]\npatterns = ["/app/gen/", "tests.rs"]\n',
                'app/main.rs': '',
                'app/gen/g.rs': '',
                'app/src/gen/kept.rs': '',
                'app/src/tests.rs': '',
            },
        )
        tally = _run(monkeypatch, str(tmp_path / 'app'))
        assert tally is not None
        assert _files_by_category(tally) == {'Rust/code': 2}  # main.rs and src/gen/kept.rs

    def test_parent_pattern_never_excludes_the_scan_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[exclude]\npatterns = ["app/", "app"]\n', 'app/main.rs': ''})
        tally = _run(monkeypatch, str(tmp_path / 'app'))
        assert tally is not None
        assert _files_by_category(tally) == {'Rust/code': 1}

    def test_wrong_shape_patterns_exit_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        _make(tmp_path, {CONFIG_FILENAME: '[exclude]\npatterns = "tests.rs"\n'})
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, str(tmp_path))
        assert exc.value.code == 1
        assert 'exclude.patterns must be a list of strings' in capsys.readouterr().err


class TestFlags:
    def test_version(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
        monkeypatch.setattr(sys, 'argv', ['tallyman', '--version'])
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 0
        assert capsys.readouterr().out == f'tallyman {__version__}\n'

    @pytest.mark.parametrize(
        ('flag', 'env', 'coloured'),
        [
            (None, {}, True),  # guards the others: FORCE_COLOR really produces colour when nothing turns it off
            ('--no-color', {}, False),
            (None, {'NO_COLOR': '1'}, False),
            (None, {'NO_COLOR': ''}, True),  # no-color.org: an empty value does not disable colour
        ],
    )
    def test_colour_switches(self, tmp_path: Path, flag: Optional[str], env: dict[str, str], coloured: bool):
        """Colour codes only; bold and dim are styles, which no-color.org allows."""
        (tmp_path / 'a.py').write_text('x = 1\n')
        environment = {k: v for k, v in os.environ.items() if k != 'NO_COLOR'}
        # TERM=dumb would make Rich drop colour even with FORCE_COLOR, so pin a colour terminal
        environment |= {'PYTHONPATH': _SRC, 'FORCE_COLOR': '1', 'TERM': 'xterm-256color', **env}
        argv = [sys.executable, '-m', 'tallyman', str(tmp_path), *([flag] if flag else [])]
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=environment, timeout=60
        )
        assert result.returncode == 0, result.stderr
        assert 'Python' in result.stdout
        assert bool(_COLOUR_CODE.search(result.stdout)) is coloured

    def test_with_spaces_reaches_the_display(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / 'a.py').write_text('x = 1\n')
        seen: list[bool] = []
        monkeypatch.setattr(sys, 'argv', ['tallyman', '--with-spaces', str(tmp_path)])
        monkeypatch.setattr(cli, '_is_interactive', lambda: False)
        monkeypatch.setattr(cli, 'display_results', lambda tally, **kw: seen.append(kw['with_spaces']))
        cli.main()
        assert seen == [True]

    def test_with_spaces_reaches_the_image(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / 'a.py').write_text('x = 1\n')
        seen: list[bool] = []
        monkeypatch.setattr(sys, 'argv', ['tallyman', '--with-spaces', '--image', str(tmp_path)])
        monkeypatch.setattr(cli, '_is_interactive', lambda: False)
        monkeypatch.setattr(cli, 'display_results', lambda *a, **kw: None)
        monkeypatch.setattr('tallyman.image.generate_image', lambda *a, **kw: seen.append(kw['with_spaces']))
        monkeypatch.setattr('tallyman.image.resolve_image_path', lambda *a, **kw: tmp_path / 'out.png')
        cli.main()
        assert seen == [True]
