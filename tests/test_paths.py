from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from tallyman.paths import canonical_case, relative_posix


class TestRelativePosix:
    def test_same_path_is_empty(self):
        assert relative_posix(PurePosixPath('/a/b'), PurePosixPath('/a/b')) == ''

    def test_posix_child(self):
        assert relative_posix(PurePosixPath('/a/b/c/d'), PurePosixPath('/a')) == 'b/c/d'

    def test_windows_paths_use_forward_slashes(self):
        """Config and gitignore paths are '/'-separated, so Windows paths must be converted."""
        assert relative_posix(PureWindowsPath('C:\\proj\\src\\vendor'), PureWindowsPath('C:\\proj')) == 'src/vendor'


def _case_insensitive(directory: Path) -> bool:
    probe = directory / 'CaseProbe'
    probe.mkdir()
    return (directory / 'caseprobe').exists()


class TestCanonicalCase:
    def test_existing_spelling_is_unchanged(self, tmp_path: Path):
        (tmp_path / 'Src').mkdir()
        assert canonical_case(tmp_path / 'Src') == tmp_path / 'Src'

    def test_missing_path_is_kept_as_typed(self, tmp_path: Path):
        assert canonical_case(tmp_path / 'nope' / 'deeper') == tmp_path / 'nope' / 'deeper'

    def test_mistyped_case_is_corrected(self, tmp_path: Path):
        if not _case_insensitive(tmp_path):
            pytest.skip('filesystem is case-sensitive')
        (tmp_path / 'src' / 'App').mkdir(parents=True)
        assert canonical_case(tmp_path / 'SRC' / 'app') == tmp_path / 'src' / 'App'
