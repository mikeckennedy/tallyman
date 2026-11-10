from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from tallyman.paths import relative_posix


class TestRelativePosix:
    def test_same_path_is_empty(self):
        assert relative_posix(PurePosixPath('/a/b'), PurePosixPath('/a/b')) == ''

    def test_posix_child(self):
        assert relative_posix(PurePosixPath('/a/b/c/d'), PurePosixPath('/a')) == 'b/c/d'

    def test_windows_paths_use_forward_slashes(self):
        """Config and gitignore paths are '/'-separated, so Windows paths must be converted."""
        assert relative_posix(PureWindowsPath('C:\\proj\\src\\vendor'), PureWindowsPath('C:\\proj')) == 'src/vendor'
