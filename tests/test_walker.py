from pathlib import Path

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
        (root / 'Makefile').write_text('all:\n\techo hi\n')
        results = list(walk_project(root, set()))
        paths = {r[0].name for r in results}
        assert 'Makefile' not in paths

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
        assert 'mod.py' not in paths or all(
            not str(r[0]).startswith(str(root / 'link')) for r in results
        )
