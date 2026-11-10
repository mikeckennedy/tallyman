from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest

from tallyman import cli
from tallyman.aggregator import TallyResult
from tallyman.config import CONFIG_FILENAME, load_config


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
) -> Optional[TallyResult]:
    """Run tallyman's main() with *argv*; return the result it would have displayed (None if it exited first).

    The setup TUI is replaced. It records the (excluded, specs, non-specs) it was pre-filled with in
    *setup_calls*, then returns *setup_result*: such a tuple, ECHO to save the pre-fill unchanged, or None
    to fail the test because setup should not have launched.
    """
    captured: list[TallyResult] = []
    monkeypatch.setattr(sys, 'argv', ['tallyman', *argv])
    monkeypatch.setattr(cli, '_is_interactive', lambda: interactive)
    monkeypatch.setattr(cli, 'display_results', lambda tally, **_: captured.append(tally))

    def fake_setup(
        _root: Path, _spec: object, excluded: set[str], specs: set[str], non_specs: set[str], **_kwargs: object
    ) -> object:
        prefill = (set(excluded), set(specs), set(non_specs))
        if setup_calls is not None:
            setup_calls.append(prefill)
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
        assert (
            _files_by_category(tally)['Python/code'] == 1
        )  # vendor/v.py excluded (phase 4 stops the config counting as TOML)
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
    def test_setup_prefills_the_rebased_parent_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(
            tmp_path,
            {
                CONFIG_FILENAME: (
                    '[exclude]\ndirectories = ["src/vendor", "docs"]\n\n[specs]\ndirectories = ["src/design"]\n'
                ),
                'src/pkg/.tally-config.toml': '[exclude]\ndirectories = ["gen"]\n',
                'src/app.py': 'x = 1\n',
            },
        )
        calls: list[tuple[set[str], set[str], set[str]]] = []
        _run(monkeypatch, '--setup', str(tmp_path / 'src'), interactive=True, setup_result=ECHO, setup_calls=calls)
        assert calls == [({'vendor'}, {'design'}, set())]  # src/pkg's own config stays in its own file
        saved = load_config(tmp_path / 'src' / CONFIG_FILENAME)
        assert saved.excluded_dirs == {'vendor'}
        assert saved.spec_dirs == {'design'}

    def test_setup_keeps_a_spec_dir_that_covers_the_scan_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A no-op setup run must not change the numbers: design/ stays specs."""
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\ndirectories = ["design"]\n', 'design/a.md': '# a\n'})
        tally = _run(monkeypatch, '--setup', str(tmp_path / 'design'), interactive=True, setup_result=ECHO)
        assert tally is not None
        assert _files_by_category(tally)['Markdown/specs'] == 1
        assert 'Markdown/docs' not in _files_by_category(tally)
        assert load_config(tmp_path / 'design' / CONFIG_FILENAME).spec_dirs == {'.'}
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


def _run_process(directory: Path, preexec_fn: Optional[Callable[[], None]] = None) -> subprocess.CompletedProcess[str]:
    """Run the real CLI in a subprocess with stdin at /dev/null: no monkeypatching, so the real terminal check runs."""
    return subprocess.run(
        [sys.executable, '-m', 'tallyman', str(directory)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, 'PYTHONPATH': _SRC, 'NO_COLOR': '1'},
        preexec_fn=preexec_fn,
    )


class TestRealProcess:
    def test_no_terminal_returns_promptly(self, tmp_path: Path):
        (tmp_path / 'a.py').write_text('x = 1\n')
        result = _run_process(tmp_path)
        assert result.returncode == 0, result.stderr
        assert 'tallyman --setup' in result.stderr
        assert not (tmp_path / CONFIG_FILENAME).exists()

    @pytest.mark.skipif(sys.platform == 'win32', reason='closing stdin in the child is POSIX-only')
    def test_closed_stdin(self, tmp_path: Path):
        (tmp_path / 'a.py').write_text('x = 1\n')
        result = _run_process(tmp_path, preexec_fn=lambda: os.close(0))
        assert result.returncode == 0, result.stderr
        assert 'Traceback' not in result.stderr


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

    def test_setup_prefill_and_save_carry_the_ignore_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / '.git').mkdir()
        _make(tmp_path, {CONFIG_FILENAME: '[specs]\nignore = ["src/agents"]\n', 'src/agents/a.md': '# a\n'})
        calls: list[tuple[set[str], set[str], set[str]]] = []
        _run(monkeypatch, '--setup', str(tmp_path / 'src'), interactive=True, setup_result=ECHO, setup_calls=calls)
        assert calls == [(set(), set(), {'agents'})]
        assert load_config(tmp_path / 'src' / CONFIG_FILENAME).non_spec_dirs == {'agents'}
