from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest
from rich.text import Text
from textual.widgets import Static
from textual.widgets.tree import TreeNode

from tallyman import walker
from tallyman.config import NestedConfig, TallyConfig, load_nested_config, merge_configs
from tallyman.gitignore import GitIgnoreSpec, load_gitignore
from tallyman.languages import RUST
from tallyman.tui import setup_app
from tallyman.tui.setup_app import NodeInfo, SetupApp, SetupResult, SetupTree
from tallyman.walker import SpecState, WalkStats, root_spec_state, spec_state, walk_project

TREE = ['plans/sub', 'src/vendor', 'src/agents/inner', 'docs', 'lib']


def _make_tree(root: Path, dirs: list[str] = TREE) -> None:
    """Create each directory with a Markdown file at every level, so the walker classifies every directory."""
    for d in dirs:
        parts = d.split('/')
        for i in range(1, len(parts) + 1):
            level = root.joinpath(*parts[:i])
            level.mkdir(exist_ok=True)
            (level / 'notes.md').write_text('# n\n')


def _find(node: TreeNode[NodeInfo], path: str) -> TreeNode[NodeInfo]:
    if node.data and node.data.path == path:
        return node
    for child in node.children:
        try:
            return _find(child, path)
        except LookupError:
            pass
    raise LookupError(path)


_Dirs = tuple[set[str], set[str], set[str]]  # (excluded, specs, non-specs): what Session.run() returns


class Session:
    """Drives SetupApp headlessly: press keys on named directories, then save."""

    def __init__(
        self,
        root: Path,
        excluded: Optional[set[str]] = None,
        specs: Optional[set[str]] = None,
        non_specs: Optional[set[str]] = None,
        root_auto_spec: bool = False,
        inherited: Optional[TallyConfig] = None,
        patterns: Optional[list[str]] = None,
        rust: Optional[bool] = None,
    ) -> None:
        exclude_patterns = GitIgnoreSpec.for_patterns(root)
        exclude_patterns.add_rules(root, patterns or [])
        self.app = SetupApp(
            root,
            load_gitignore(root),
            excluded or set(),
            specs or set(),
            existing_non_specs=non_specs,
            root_auto_spec=root_auto_spec,
            inherited=inherited,
            exclude_patterns=exclude_patterns,
            existing_rust=rust,
        )
        self.result: Optional[SetupResult] = None
        self.rust_line: Optional[str] = None  # the 'Rust test code' line just before saving; None if not shown
        self.instructions = ''
        self.footer_keys: list[str] = []
        self.labels: dict[str, str] = {}
        self.texts: dict[str, Text] = {}  # the label objects, to check their styles
        self.flags: dict[str, bool] = {}
        self.excluded: dict[str, bool] = {}
        self.root_label = ''
        self.root_text = Text()

    def run(self, actions: list[tuple[str, str]], save: bool = True) -> Optional[_Dirs]:
        """*actions* are (directory path, key); '' is the root. Records labels just before saving.

        Returns the directory settings saved; the whole :class:`SetupResult` is ``self.result``.
        """

        async def go() -> None:
            async with self.app.run_test(size=(100, 50)) as pilot:
                tree = self.app.query_one(SetupTree)
                tree.focus()
                for path, key in actions:
                    tree.move_cursor(_find(tree.root, path))
                    await pilot.press(key)
                await pilot.pause()
                self._record(tree.root)
                self.instructions = str(self.app.query_one('#instructions', Static).render())
                rust = self.app.query('#rust')
                self.rust_line = str(rust.first(Static).render()) if rust else None
                self.footer_keys = [str(getattr(key, 'description', '')) for key in self.app.query('FooterKey')]
                await pilot.click('#save' if save else '#cancel')

        asyncio.run(go())
        self.result = self.app.return_value
        if self.result is None:
            return None
        return self.result.excluded_dirs, self.result.spec_dirs, self.result.non_spec_dirs

    def _record(self, node: TreeNode[NodeInfo]) -> None:
        label = node.label
        assert isinstance(label, Text)  # typed str | Text; setup always passes Text
        if node.data and not node.data.path:
            self.root_label = str(label)
            self.root_text = label
        if node.data and node.data.path:
            path = node.data.path
            self.labels[path] = str(label)
            self.texts[path] = label
            self.flags[path] = node.data.spec
            self.excluded[path] = node.data.excluded
        for child in node.children:
            self._record(child)


def _walk_categories(root: Path, result: _Dirs) -> dict[str, str]:
    excluded, specs, non_specs = result
    found = walk_project(root, excluded, load_gitignore(root), spec_dirs=specs, non_spec_dirs=non_specs)
    return {p.parent.relative_to(root).as_posix(): lang.category for p, lang in found if p.suffix == '.md'}


class TestSpecToggles:
    def test_untouched_save(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([]) == (set(), set(), set())
        assert session.labels['plans'] == 'S plans (specs)'
        assert session.labels['plans/sub'] == 'S sub (specs)'
        assert session.labels['src/agents'] == 'S agents (specs)'

    def test_turning_off_an_auto_detected_spec_dir_sticks(self, tmp_path: Path) -> None:
        """H4: the walker must honour it, not re-detect 'plans' by name."""
        _make_tree(tmp_path)
        session = Session(tmp_path)
        result = session.run([('plans', 's')])
        assert result == (set(), set(), {'plans'})
        assert session.labels['plans'] == '✓ plans (not specs)'
        assert session.labels['plans/sub'] == '✓ sub'
        assert result is not None
        categories = _walk_categories(tmp_path, result)
        assert categories['plans'] == categories['plans/sub'] == 'docs'

    def test_turning_it_back_on_removes_the_override(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('plans', 's'), ('plans', 's')]) == (set(), set(), set())

    def test_marking_a_plain_directory(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path)
        result = session.run([('docs', 's')])
        assert result == (set(), {'docs'}, set())
        assert session.labels['docs'] == 'S docs'

    def test_explicit_spec_below_an_ignored_directory(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['agents/plans', 'agents/plans/deep', 'agents/code'])
        session = Session(tmp_path, non_specs={'agents'})
        session.run([])
        assert session.labels['agents/plans'] == '✓ plans'  # auto-detection is off below an ignored dir
        result = Session(tmp_path, non_specs={'agents'}).run([('agents/plans', 's')])
        assert result == (set(), {'agents/plans'}, {'agents'})
        assert result is not None
        categories = _walk_categories(tmp_path, result)
        assert categories == {
            'agents': 'docs',
            'agents/plans': 'specs',
            'agents/plans/deep': 'specs',
            'agents/code': 'docs',
        }


class TestExcludeToggles:
    def test_root_cannot_be_excluded(self, tmp_path: Path) -> None:
        """H10: 'x' on the root used to write "" into the config and exclude everything below."""
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('', 'x')]) == (set(), set(), set())

    def test_explicitly_excluded_child_of_an_excluded_parent_keeps_its_entry(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src/vendor'}).run([('src', 'x'), ('src/vendor', 'x'), ('src', 'x')])
        assert result == ({'src/vendor'}, set(), set())

    def test_children_of_an_excluded_directory_show_excluded(self, tmp_path: Path) -> None:
        """H11: reopening setup with src excluded used to show src/vendor with a green check."""
        _make_tree(tmp_path)
        session = Session(tmp_path, excluded={'src'})
        result = session.run([('src/vendor', 'x')])  # no-op: it's excluded through its parent
        assert result is not None
        assert result[0] == {'src'}
        assert session.labels['src/vendor'] == '✗ vendor'
        assert session.labels['src/agents/inner'] == '✗ inner'

    def test_exclude_then_include_restores_spec_status(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([('plans', 'x'), ('plans', 'x')]) == (set(), set(), set())
        assert session.labels['plans'] == 'S plans (specs)'

    def test_excluding_a_parent_keeps_a_childs_own_exclusion(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src/vendor'}).run([('src', 'x'), ('src', 'x')])
        assert result == ({'src/vendor'}, set(), set())

    def test_cancel_returns_none(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('docs', 's')], save=False) is None

    def test_saving_drops_exclusions_below_an_excluded_directory(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src/vendor', 'src/agents/inner'}).run([('src', 'x')])
        assert result == ({'src'}, set(), set())

    def test_saving_drops_a_chain_of_nested_exclusions(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src', 'src/agents', 'src/agents/inner'}).run([])
        assert result == ({'src'}, set(), set())

    def test_sibling_and_prefix_named_exclusions_are_kept(self, tmp_path: Path) -> None:
        """src2 starts with src, but it isn't beneath it."""
        _make_tree(tmp_path, ['src', 'src2', 'lib'])
        assert Session(tmp_path, excluded={'src', 'src2', 'lib'}).run([]) == ({'src', 'src2', 'lib'}, set(), set())


class TestLabels:
    def test_directory_names_are_not_read_as_markup(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['[bold]x', 'a[red]'])
        session = Session(tmp_path)
        session.run([])
        assert session.labels['[bold]x'] == '✓ [bold]x'
        assert session.labels['a[red]'] == '✓ a[red]'

    def test_emoji_codes_are_shown_literally(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, [':rocket:'])
        session = Session(tmp_path)
        session.run([])
        assert session.labels[':rocket:'] == '✓ :rocket:'

    @pytest.mark.skipif(os.name == 'nt', reason='a backslash is a path separator on Windows')
    def test_trailing_backslash_is_not_doubled(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['foo\\', 'baz\\'])
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'baz\\'}))
        session.run([])
        assert session.labels['foo\\'] == '✓ foo\\'
        # Text after the name is where markup used to double the backslash
        assert session.labels['baz\\'] == 'S baz\\ (set in a parent config)'

    def test_markup_like_names_are_shown_literally(self, tmp_path: Path) -> None:
        names = ['[b]x', 'a\\[b]', 'x[', ']']
        if os.name == 'nt':
            names.remove('a\\[b]')
        _make_tree(tmp_path, names)
        session = Session(tmp_path)
        session.run([])
        for name in names:
            assert session.labels[name] == f'✓ {name}', name

    @pytest.mark.parametrize('name', [':rocket:', '[bold]x'])
    def test_root_name_is_shown_literally(self, tmp_path: Path, name: str) -> None:
        root = tmp_path / name
        root.mkdir()
        _make_tree(root, ['docs'])
        session = Session(root)
        session.run([])
        assert session.root_label == name

    def test_label_styles(self, tmp_path: Path) -> None:
        """Labels keep their colours: a plain string would lose them, and markup would bring back the bugs above."""
        _make_tree(tmp_path, ['gone', 'lib'])
        session = Session(tmp_path, excluded={'gone'}, specs={'lib'})
        session.run([])
        styles = {
            path: [(t.plain[s.start : s.end], str(s.style)) for s in t.spans] for path, t in session.texts.items()
        }
        assert ('✗', 'red') in styles['gone']
        assert ('S', 'bright_cyan') in styles['lib']


_CONFIGS: list[tuple[set[str], set[str], set[str]]] = [
    (set(), set(), set()),
    (set(), set(), {'plans'}),
    (set(), {'lib'}, {'src'}),
    (set(), {'src/agents/inner'}, {'src'}),
    (set(), {'.'}, {'src/agents'}),
    (set(), set(), {'.'}),
    ({'src'}, {'docs'}, set()),
]


@pytest.mark.parametrize(('excluded', 'specs', 'non_specs'), _CONFIGS)
def test_tui_and_walker_agree(tmp_path: Path, excluded: set[str], specs: set[str], non_specs: set[str]) -> None:
    """Every directory the TUI labels as specs is exactly where the walker counts Markdown as specs."""
    _make_tree(tmp_path)
    session = Session(tmp_path, excluded, specs, non_specs)
    result = session.run([])
    assert result is not None
    walked = _walk_categories(tmp_path, result)
    assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d, spec in session.flags.items() if spec}
    for directory, label in session.labels.items():
        if directory in walked:
            assert label.startswith('S ') == (walked[directory] == 'specs'), (directory, label)


class TestRootSpec:
    def test_s_on_the_root_marks_everything(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([('', 's')]) == (set(), {'.'}, set())
        assert session.labels['docs'] == 'S docs (specs)'

    def test_root_inside_an_auto_spec_dir_shows_specs_and_can_be_turned_off(self, tmp_path: Path) -> None:
        """Setup run from inside plans/ must show what the run will count, and offer a way out."""
        _make_tree(tmp_path)
        session = Session(tmp_path, root_auto_spec=True)
        assert session.run([]) == (set(), set(), set())  # the implicit state is not written to the config
        assert session.labels['docs'] == 'S docs (specs)'
        session = Session(tmp_path, root_auto_spec=True)
        assert session.run([('', 's')]) == (set(), set(), {'.'})
        assert session.labels['docs'] == '✓ docs'


class TestRoundTrips:
    def test_s_twice_keeps_an_ignore_that_exists_for_the_children(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        assert Session(tmp_path, non_specs={'src'}).run([('src', 's'), ('src', 's')]) == (set(), set(), {'src'})

    @pytest.mark.parametrize(
        ('specs', 'non_specs'), [(set(), set()), (set(), {'src'}), ({'lib'}, {'plans'}), ({'.'}, {'src/agents'})]
    )
    def test_s_twice_on_any_directory_changes_nothing(
        self, tmp_path: Path, specs: set[str], non_specs: set[str]
    ) -> None:
        _make_tree(tmp_path)
        dirs = ['', 'plans', 'plans/sub', 'src', 'src/agents', 'src/agents/inner', 'docs', 'lib']
        result = Session(tmp_path, set(), set(specs), set(non_specs)).run([(d, 's') for d in dirs for _ in range(2)])
        assert result == (set(), specs, non_specs)


class TestNestedConfigs:
    @pytest.fixture
    def tree(self, tmp_path: Path) -> Path:
        _make_tree(tmp_path, ['plans/p', 'lib/l', 'vendor/y', 'docs'])
        (tmp_path / 'plans' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        (tmp_path / 'vendor' / '.tally-config.toml').write_text('[exclude]\ndirectories = ["y"]\n')
        return tmp_path

    def test_nested_settings_are_shown_locked_and_not_saved(self, tree: Path) -> None:
        session = Session(tree)
        result = session.run([('plans', 's'), ('lib', 's'), ('vendor/y', 'x')])
        assert result == (set(), set(), set())
        assert session.labels['plans'] == '✓ plans (not specs) (set in a nested config)'
        assert session.labels['lib'] == 'S lib (set in a nested config)'
        assert session.labels['vendor/y'] == '✗ y (set in a nested config)'

    def test_tui_and_walker_agree_with_nested_configs(self, tree: Path) -> None:
        session = Session(tree)
        result = session.run([('docs', 's')])
        assert result is not None
        walked = _walk_categories(tree, result)
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}


class TestNestedConfigPrecedence:
    def test_deeper_nested_config_wins_and_tui_matches_walker(self, tmp_path: Path) -> None:
        """lib/ marks notes as specs; lib/notes/ ignores itself. The deeper config wins in the TUI too."""
        _make_tree(tmp_path, ['lib/notes'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        session = Session(tmp_path)
        result = session.run([])
        assert result is not None
        assert session.labels['lib/notes'] == '✓ notes (not specs) (set in a nested config)'
        walked = _walk_categories(tmp_path, result)
        assert walked['lib/notes'] == 'docs'
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}

    def test_excluding_a_dir_whose_spec_setting_is_nested_drops_the_credit(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['lib/l'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        session = Session(tmp_path)
        assert session.run([('lib', 'x')]) == ({'lib'}, set(), set())
        assert session.labels['lib'] == '✗ lib'


class TestParentConfigs:
    """Settings inherited from configs above the scan root are shown locked and never saved."""

    def test_inherited_exclusion_is_locked(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig({'src/vendor'}))
        result = session.run([('src/vendor', 'x'), ('src/vendor', 's')])
        assert result == (set(), set(), set())
        assert session.labels['src/vendor'] == '✗ vendor (set in a parent config)'

    def test_child_of_an_inherited_exclusion_is_not_listed(self, tmp_path: Path) -> None:
        """The walker never enters src, and setup can't un-exclude it, so its children aren't shown."""
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig({'src'}))
        assert session.run([('src', 'x')]) == (set(), set(), set())
        assert session.labels['src'] == '✗ src (set in a parent config)'
        assert not any(d.startswith('src/') for d in session.labels)

    def test_inherited_spec_settings_are_locked(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'plans'}))
        result = session.run([('docs', 's'), ('plans', 's')])
        assert result == (set(), set(), set())
        assert session.labels['docs'] == 'S docs (set in a parent config)'
        assert session.labels['plans'] == '✓ plans (not specs) (set in a parent config)'
        assert session.labels['plans/sub'] == '✓ sub'

    def test_inherited_root_spec_is_shown_on_the_root(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['docs'])
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'.'}))
        session.run([('', 's')])
        assert session.root_label == f'{tmp_path.name} (specs) (set in a parent config)'
        assert session.labels['docs'] == 'S docs (specs)'

    def test_a_local_override_of_a_parent_setting_stays_editable(self, tmp_path: Path) -> None:
        """The parent marks docs as specs, the local config ignores it: the local entry is the user's to change."""
        _make_tree(tmp_path, ['docs'])
        session = Session(tmp_path, non_specs={'docs'}, inherited=TallyConfig(spec_dirs={'docs'}))
        result = session.run([('docs', 's')])
        assert result == (set(), set(), set())  # dropping the override lets the parent's setting apply
        assert session.labels['docs'] == 'S docs'

    def test_nested_config_beats_an_inherited_setting(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['lib/l'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'lib'}))
        session.run([])
        assert session.labels['lib'] == '✓ lib (not specs) (set in a nested config)'

    def test_tui_and_walker_agree_with_parent_configs(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        inherited = TallyConfig({'lib'}, {'docs'}, {'src/agents'})
        session = Session(tmp_path, inherited=inherited)
        result = session.run([('plans', 's')])
        assert result is not None
        excluded, specs, non_specs = result
        effective = merge_configs(inherited, TallyConfig(excluded, specs, non_specs))
        walked = _walk_categories(tmp_path, (effective.excluded_dirs, effective.spec_dirs, effective.non_spec_dirs))
        assert 'lib' not in walked
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}


def _write_configs(root: Path, configs: dict[str, str]) -> None:
    """Write each nested .tally-config.toml: {directory: contents}."""
    for directory, content in configs.items():
        (root / directory / '.tally-config.toml').write_text(content)


_NOTHING: _Dirs = (set(), set(), set())

# (tree, nested configs on disk, excluded, specs, non-specs, inherited, what setup saves)
_COPY_CASES = [
    (['sub/gen', 'lib'], {'sub': '[exclude]\ndirectories = ["gen"]\n'}, {'sub/gen'}, set(), set(), None, _NOTHING),
    (['lib/l', 'docs'], {'lib': '[specs]\ndirectories = ["."]\n'}, set(), {'lib'}, set(), None, _NOTHING),
    (['plans/p', 'docs'], {'plans': '[specs]\nignore = ["."]\n'}, set(), set(), {'plans'}, None, _NOTHING),
    (['docs', 'lib'], {}, set(), {'docs'}, set(), TallyConfig(spec_dirs={'docs'}), _NOTHING),
    (['docs', 'lib'], {}, {'lib'}, set(), set(), TallyConfig({'lib'}), _NOTHING),
    (['docs', 'plans'], {}, set(), set(), {'plans'}, TallyConfig(non_spec_dirs={'plans'}), _NOTHING),
    # The parent lists docs as both (specs wins there), so the scan root's ignore is an override, not a copy
    (
        ['docs', 'lib'],
        {},
        set(),
        set(),
        {'docs'},
        TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'docs'}),
        (set(), set(), {'docs'}),
    ),
    # a/b only repeated what the copy of the parent's a already covered, so it goes with it
    (['a/b', 'lib'], {}, {'a', 'a/b'}, set(), set(), TallyConfig({'a'}), _NOTHING),
]


class TestCopies:
    """A scan-root entry that a parent or nested config already has in the same set is dropped when setup opens."""

    def test_copy_of_a_nested_exclusion_is_dropped(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['sub/gen'])
        _write_configs(tmp_path, {'sub': '[exclude]\ndirectories = ["gen"]\n'})
        session = Session(tmp_path, excluded={'sub/gen'})
        assert session.run([]) == (set(), set(), set())
        assert session.labels['sub/gen'] == '✗ gen (set in a nested config)'

    def test_copy_of_a_nested_spec_setting_is_dropped(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['lib/l'])
        _write_configs(tmp_path, {'lib': '[specs]\ndirectories = ["."]\n'})
        session = Session(tmp_path, specs={'lib'})
        assert session.run([]) == (set(), set(), set())
        assert session.labels['lib'] == 'S lib (set in a nested config)'

    def test_copy_of_a_parent_spec_setting_is_dropped_and_locked(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['docs'])
        session = Session(tmp_path, specs={'docs'}, inherited=TallyConfig(spec_dirs={'docs'}))
        assert session.run([('docs', 's')]) == (set(), set(), set())  # 's' does nothing: the node is locked
        assert session.labels['docs'] == 'S docs (set in a parent config)'

    def test_shadowed_entry_is_kept(self, tmp_path: Path) -> None:
        """The nested config ignores lib, which wins over the scan root's spec entry. Not a copy: it stays."""
        _make_tree(tmp_path, ['lib/l'])
        _write_configs(tmp_path, {'lib': '[specs]\nignore = ["."]\n'})
        session = Session(tmp_path, specs={'lib'})
        assert session.run([]) == (set(), {'lib'}, set())
        assert session.labels['lib'] == '✓ lib (not specs) (set in a nested config)'

    def test_override_of_a_contradictory_parent_is_kept(self, tmp_path: Path) -> None:
        """The parent lists docs as specs and as ignored, so specs wins there. The scan root's ignore decides it."""
        _make_tree(tmp_path, ['docs'])
        inherited = TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'docs'})
        session = Session(tmp_path, non_specs={'docs'}, inherited=inherited)
        assert session.run([]) == (set(), set(), {'docs'})
        assert session.labels['docs'] == '✓ docs (not specs)'

    def test_child_of_a_dropped_exclusion_is_dropped_too(self, tmp_path: Path) -> None:
        """a is a copy of the parent's exclusion; a/b, beneath it, would otherwise be saved and never be removable."""
        _make_tree(tmp_path, ['a/b'])
        session = Session(tmp_path, excluded={'a', 'a/b'}, inherited=TallyConfig({'a'}))
        assert session.run([]) == (set(), set(), set())
        assert session.labels['a'] == '✗ a (set in a parent config)'

    @pytest.mark.parametrize(
        ('dirs', 'configs', 'excluded', 'specs', 'non_specs', 'inherited', 'saved'),
        _COPY_CASES,
        ids=[
            'nested-exclusion',
            'nested-spec',
            'nested-ignore',
            'parent-spec',
            'parent-exclusion',
            'parent-ignore',
            'contradictory-parent',
            'below-a-copy',
        ],
    )
    def test_tui_and_walker_agree_after_dropping_copies(
        self,
        tmp_path: Path,
        dirs: list[str],
        configs: dict[str, str],
        excluded: set[str],
        specs: set[str],
        non_specs: set[str],
        inherited: Optional[TallyConfig],
        saved: _Dirs,
    ) -> None:
        """Dropping a copy never changes a count: the walk with the saved settings matches the original one."""
        _make_tree(tmp_path, dirs)
        _write_configs(tmp_path, configs)
        parent = inherited or TallyConfig()
        session = Session(tmp_path, set(excluded), set(specs), set(non_specs), inherited=parent)
        result = session.run([])
        assert result == saved
        assert result is not None

        def walk(config: TallyConfig) -> dict[str, str]:
            effective = merge_configs(parent, config)
            return _walk_categories(tmp_path, (effective.excluded_dirs, effective.spec_dirs, effective.non_spec_dirs))

        walked = walk(TallyConfig(*result))
        assert walked == walk(TallyConfig(excluded, specs, non_specs))
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}
        assert {d for d, ex in session.excluded.items() if not ex} == set(walked) - {'.'}


def _pattern_spec(root: Path, patterns: list[str]) -> GitIgnoreSpec:
    spec = GitIgnoreSpec.for_patterns(root)
    spec.add_rules(root, patterns)
    return spec


class TestExclusionPrecedence:
    """Same order as walk_project(): a config exclusion is checked first, then gitignore, then patterns."""

    def test_config_exclusion_outranks_a_pattern(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['vendor', 'lib'])
        session = Session(tmp_path, excluded={'vendor'}, patterns=['vendor/'])
        session.run([])
        assert session.labels['vendor'] == '✗ vendor'
        session = Session(tmp_path, excluded={'vendor'}, patterns=['vendor/'])
        assert session.run([('vendor', 'x')]) == (set(), set(), set())
        assert session.labels['vendor'] == 'vendor (excluded by pattern)'

    @pytest.mark.parametrize(('actions', 'expected'), [([], 1), ([('vendor', 'x')], 2)], ids=['as-opened', 'after-x'])
    def test_walker_counts_the_pattern_only_where_the_tui_shows_it(
        self, tmp_path: Path, actions: list[tuple[str, str]], expected: int
    ) -> None:
        _make_tree(tmp_path, ['vendor', 'fixtures', 'gen', 'lib'])
        patterns = ['vendor/', 'fixtures/', 'gen/']
        inherited = TallyConfig({'gen'})
        session = Session(tmp_path, excluded={'vendor'}, inherited=inherited, patterns=patterns)
        result = session.run(actions)
        assert result is not None
        effective = merge_configs(inherited, TallyConfig(*result))
        stats = WalkStats()
        walked = walk_project(
            tmp_path,
            effective.excluded_dirs,
            load_gitignore(tmp_path),
            exclude_patterns=_pattern_spec(tmp_path, patterns),
            stats=stats,
        )
        list(walked)  # fills stats
        shown = [
            d
            for d, label in session.labels.items()
            if '(excluded by pattern)' in label and not session.excluded.get(Path(d).parent.as_posix(), False)
        ]
        assert stats.pattern_dirs == len(shown) == expected

    def test_parent_exclusion_outranks_a_pattern(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['gen', 'lib'])
        session = Session(tmp_path, inherited=TallyConfig({'gen'}), patterns=['gen/'])
        assert session.run([('gen', 'x')]) == (set(), set(), set())
        assert session.labels['gen'] == '✗ gen (set in a parent config)'

    def test_config_exclusion_outranks_gitignore(self, tmp_path: Path) -> None:
        """A user exclusion of a since-gitignored directory can be removed; then gitignore's is locked."""
        _make_tree(tmp_path, ['build', 'lib'])
        (tmp_path / '.gitignore').write_text('build/\n')
        session = Session(tmp_path, excluded={'build'})
        session.run([])
        assert session.labels['build'] == '✗ build'
        session = Session(tmp_path, excluded={'build'})
        assert session.run([('build', 'x')]) == (set(), set(), set())
        assert session.labels['build'] == 'build (gitignored)'
        assert Session(tmp_path, excluded={'build'}).run([('build', 'x'), ('build', 'x')]) == (set(), set(), set())


class TestPatternExclusions:
    def test_pattern_excluded_directory_is_shown_locked(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['src/fixtures/deep', 'lib'])
        session = Session(tmp_path, patterns=['fixtures/'])
        result = session.run([('src/fixtures', 'x'), ('src/fixtures', 's')])
        assert result == (set(), set(), set())
        assert session.labels['src/fixtures'] == 'fixtures (excluded by pattern)'
        assert 'src/fixtures/deep' not in session.labels  # the walker never enters it either

    def test_tui_and_walker_agree_with_patterns(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['plans/sub', 'src/fixtures', 'docs'])
        session = Session(tmp_path, patterns=['fixtures/', '/plans/sub/'])
        result = session.run([])
        assert result is not None
        spec = GitIgnoreSpec.for_patterns(tmp_path)
        spec.add_rules(tmp_path, ['fixtures/', '/plans/sub/'])
        walked = {
            p.parent.relative_to(tmp_path).as_posix()
            for p, _ in walk_project(tmp_path, set(), load_gitignore(tmp_path), exclude_patterns=spec)
        }
        shown = {d for d, label in session.labels.items() if 'excluded by pattern' not in label}
        assert walked == shown


class TestNestedPatternLayers:
    def test_tui_and_walker_agree_with_nested_patterns(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['crate/gen', 'crate/src', 'gen'])
        (tmp_path / 'crate' / '.tally-config.toml').write_text('[exclude]\npatterns = ["/gen/"]\n')
        session = Session(tmp_path)
        session.run([])
        assert session.labels['crate/gen'] == 'gen (excluded by pattern)'
        walked = {p.parent.relative_to(tmp_path).as_posix() for p, _ in walk_project(tmp_path, set())}
        shown = {d for d, label in session.labels.items() if 'excluded by pattern' not in label}
        assert walked == shown


def _spy_on_nested_loads(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> list[str]:
    """Record the directory of every nested config *module* loads, in order, still loading it for real."""
    read: list[str] = []

    def spy(config_file: Path, rel_dir: str) -> Optional[NestedConfig]:
        read.append(rel_dir)
        return load_nested_config(config_file, rel_dir)

    monkeypatch.setattr(module, 'load_nested_config', spy)
    return read


class TestNestedConfigDiscovery:
    """Setup reads a nested config wherever the walker would, and also beneath the scan root's own exclusions."""

    def test_setup_reads_the_configs_the_walker_reads(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with_configs = ['a', 'node_modules/p', 'fixtures/f', 'vendor/v', 'b/gen', 'mine/m', '.hidden/h']
        _make_tree(tmp_path, [*with_configs, 'lib'])
        _write_configs(tmp_path, {d: '[specs]\nignore = []\n' for d in with_configs})
        _write_configs(tmp_path, {'b': '[exclude]\ndirectories = ["gen"]\n'})
        (tmp_path / '.gitignore').write_text('node_modules/\n')
        in_setup = _spy_on_nested_loads(monkeypatch, setup_app)
        in_walker = _spy_on_nested_loads(monkeypatch, walker)
        inherited = TallyConfig({'vendor'})
        session = Session(tmp_path, excluded={'mine'}, inherited=inherited, patterns=['fixtures/'])
        result = session.run([])
        assert result == ({'mine'}, set(), set())
        assert result is not None
        assert sorted(in_setup) == ['a', 'b', 'mine/m']

        def walk(excluded: set[str]) -> list[str]:
            in_walker.clear()
            effective = merge_configs(inherited, TallyConfig(excluded))
            spec = _pattern_spec(tmp_path, ['fixtures/'])
            list(walk_project(tmp_path, effective.excluded_dirs, load_gitignore(tmp_path), exclude_patterns=spec))
            return sorted(in_walker)

        assert walk(result[0]) == ['a', 'b']
        assert walk(result[0] - {'mine'}) == sorted(in_setup)  # the one setup reads beyond the walker, once lifted

    def test_directory_excluded_by_another_config_is_a_leaf(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['src/x', 'b/gen/y', 'lib'])
        _write_configs(tmp_path, {'b': '[exclude]\ndirectories = ["gen"]\n'})
        session = Session(tmp_path, inherited=TallyConfig({'src'}))
        assert session.run([]) == (set(), set(), set())
        assert session.labels['src'] == '✗ src (set in a parent config)'
        assert session.labels['b/gen'] == '✗ gen (set in a nested config)'
        assert {'src/x', 'b/gen/y'}.isdisjoint(session.labels)
        assert 'b' in session.labels  # the directory holding the config is listed as usual

    def test_user_exclusion_keeps_its_children(self, tmp_path: Path) -> None:
        """The scan root's own exclusion can be lifted here, and then the walker enters it: it isn't a leaf."""
        _make_tree(tmp_path, ['mine/m', 'lib'])
        session = Session(tmp_path, excluded={'mine'})
        session.run([])
        assert session.labels['mine/m'] == '✗ m'

    def test_nested_config_below_a_user_exclusion_applies_when_it_is_lifted(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, ['mine', 'lib'])
        _write_configs(tmp_path, {'mine': '[specs]\ndirectories = ["."]\n'})
        session = Session(tmp_path, excluded={'mine'})
        result = session.run([('mine', 'x')])
        assert result == (set(), set(), set())
        assert result is not None
        assert session.labels['mine'] == 'S mine (set in a nested config)'
        assert _walk_categories(tmp_path, result)['mine'] == 'specs'

    @pytest.mark.skipif(sys.platform == 'win32', reason='chmod does not restrict listing on Windows')
    @pytest.mark.skipif(hasattr(os, 'geteuid') and os.geteuid() == 0, reason='chmod does not restrict root')
    def test_config_in_an_unlistable_directory_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """os.walk never yields a directory it can't list, so the walker never reads its config, even though the
        file itself can be opened. Setup mustn't either, or the scan root's entry is dropped as a copy of it."""
        _make_tree(tmp_path, ['locked', 'lib'])
        _write_configs(tmp_path, {'locked': '[specs]\ndirectories = ["."]\n'})
        in_setup = _spy_on_nested_loads(monkeypatch, setup_app)
        in_walker = _spy_on_nested_loads(monkeypatch, walker)
        os.chmod(tmp_path / 'locked', 0o311)  # traversable, not listable
        try:
            session = Session(tmp_path, specs={'locked'})
            assert session.run([]) == (set(), {'locked'}, set())
            list(walk_project(tmp_path, set(), load_gitignore(tmp_path), spec_dirs={'locked'}))
        finally:
            os.chmod(tmp_path / 'locked', 0o755)
        assert in_setup == in_walker == []

    @pytest.mark.parametrize('payload', [b'not toml [\n', b'[exclude]\ndirectories = ["caf\xe9"]\n'])
    def test_malformed_nested_config_is_skipped(self, tmp_path: Path, payload: bytes) -> None:
        """As in the walker: silently, and the configs beneath it still apply."""
        _make_tree(tmp_path, ['vendor/v', 'lib'])
        (tmp_path / 'vendor' / '.tally-config.toml').write_bytes(payload)
        _write_configs(tmp_path, {'vendor/v': '[specs]\ndirectories = ["."]\n'})
        session = Session(tmp_path)
        assert session.run([]) == (set(), set(), set())
        assert session.labels['vendor'] == '✓ vendor'
        assert session.labels['vendor/v'] == 'S v (set in a nested config)'


class TestLabels2:
    def test_not_specs_shows_on_any_ignored_directory(self, tmp_path: Path) -> None:
        _make_tree(tmp_path)
        session = Session(tmp_path, specs={'.'}, non_specs={'docs'})
        session.run([])
        assert session.labels['docs'] == '✓ docs (not specs)'


_P = SpecState(True, False)
_N = SpecState(False, False)
_SUP = SpecState(False, True)


@pytest.mark.parametrize(
    ('rel', 'parent', 'specs', 'non_specs', 'expected'),
    [
        ('docs', _N, set(), set(), _N),
        ('plans', _N, set(), set(), _P),
        ('Plans', _N, set(), set(), _P),
        ('x/plans', _SUP, set(), set(), _SUP),
        ('x', _P, set(), set(), _P),
        ('x', _P, set(), {'x'}, _SUP),
        ('x', _SUP, {'x'}, set(), _P),
        ('x', _N, {'x'}, {'x'}, _P),  # both: the spec entry wins a tie
        ('plans', _N, set(), {'plans'}, _SUP),
    ],
)
def test_spec_state_rule(
    rel: str, parent: SpecState, specs: set[str], non_specs: set[str], expected: SpecState
) -> None:
    assert spec_state(rel, rel.rsplit('/', 1)[-1], parent, specs, non_specs) == expected


def test_root_spec_state_rule() -> None:
    assert root_spec_state(set(), set()) == _N
    assert root_spec_state(set(), set(), auto=True) == _P
    assert root_spec_state(set(), {'.'}, auto=True) == _SUP
    assert root_spec_state({'.'}, {'.'}) == _P


def _nested_repo_tree(root: Path) -> None:
    """Repos at the root, ``sub``, ``sub/deep`` and (submodule style) ``lib/sub2``, each with its own rules.

    Only directory rules, and an ``x.py`` in every directory, so the directories the walker enters are exactly
    the parents of the files it yields.
    """
    files = {
        '.gitignore': '*.md\nbuild/\n',
        '.git/info/exclude': 'vendor/\n',
        'sub/.gitignore': 'tmp/\n',
        'sub/deep/.git/info/exclude': 'cache/\n',
        'lib/sub2/.git': 'gitdir: ../../.git/modules/lib/sub2\n',
        '.git/modules/lib/sub2/HEAD': 'ref: refs/heads/main\n',
        '.git/modules/lib/sub2/info/exclude': 'out/\n',
    }
    dirs = ['', 'build', 'vendor', 'lib', 'sub', 'sub/build', 'sub/vendor', 'sub/tmp', 'sub/deep']
    dirs += ['sub/deep/tmp', 'sub/deep/cache', 'lib/sub2', 'lib/sub2/out']
    (root / 'sub' / '.git').mkdir(parents=True)
    for rel, content in files.items() | {(f'{d}/x.py'.lstrip('/'), 'x = 1\n') for d in dirs}:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


class TestNestedRepos:
    def test_tui_and_walker_agree_across_nested_repos(self, tmp_path: Path) -> None:
        _nested_repo_tree(tmp_path)
        session = Session(tmp_path)
        result = session.run([])
        assert result is not None
        excluded, specs, non_specs = result
        found = walk_project(tmp_path, excluded, load_gitignore(tmp_path), spec_dirs=specs, non_spec_dirs=non_specs)
        entered = {p.parent.relative_to(tmp_path).as_posix() for p, _ in found} - {'.'}
        assert {d for d, ex in session.excluded.items() if not ex} == entered
        assert entered == {'lib', 'lib/sub2', 'sub', 'sub/build', 'sub/vendor', 'sub/deep', 'sub/deep/tmp'}

    def test_nested_repo_labels_follow_its_rules(self, tmp_path: Path) -> None:
        _nested_repo_tree(tmp_path)
        session = Session(tmp_path)
        session.run([])
        assert session.labels['build'].endswith('(gitignored)')
        assert not session.labels['sub/build'].endswith('(gitignored)')
        assert session.labels['sub/tmp'].endswith('(gitignored)')
        assert not session.labels['sub/deep/tmp'].endswith('(gitignored)')

    def test_nested_configs_across_nested_repos(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A config inside a nested repo is a nested config; one inside a nested repo the outer rules ignore is
        never read, by setup or by the walker."""
        _nested_repo_tree(tmp_path)
        (tmp_path / '.gitignore').write_text('*.md\nbuild/\nskipped/\n')
        (tmp_path / 'skipped' / '.git').mkdir(parents=True)
        (tmp_path / 'skipped' / 'x.py').write_text('x = 1\n')
        _write_configs(tmp_path, {'sub': '[specs]\ndirectories = ["."]\n', 'skipped': '[specs]\ndirectories = ["."]\n'})
        (tmp_path / 'sub' / 'notes.md').write_text('# n\n')  # the outer *.md rule stops at the nested repo
        in_setup = _spy_on_nested_loads(monkeypatch, setup_app)
        in_walker = _spy_on_nested_loads(monkeypatch, walker)
        session = Session(tmp_path)
        result = session.run([])
        assert result == (set(), set(), set())
        assert session.labels['sub'] == 'S sub (set in a nested config)'
        assert session.labels['skipped'] == 'skipped (gitignored)'
        found = list(walk_project(tmp_path, set(), load_gitignore(tmp_path)))
        assert in_setup == in_walker == ['sub']
        entered = {p.parent.relative_to(tmp_path).as_posix() for p, _ in found} - {'.'}
        assert {d for d, ex in session.excluded.items() if not ex} == entered
        specs = {p.parent.relative_to(tmp_path).as_posix() for p, lang in found if lang.category == 'specs'}
        assert specs == {'sub'}
        assert {d for d, spec in session.flags.items() if spec} == {d for d in entered if d.partition('/')[0] == 'sub'}


class TestRustToggle:
    """'r' sets [rust] exclude_test_modules, and only shows when the tree holds Rust code (plan 013 phase 4)."""

    def _crate(self, root: Path, files: Optional[dict[str, str]] = None) -> None:
        for rel, text in (files if files is not None else {'src/lib.rs': 'fn a() {}\n'}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)

    def test_hidden_without_rust(self, tmp_path: Path) -> None:
        self._crate(tmp_path, {'src/app.py': 'x = 1\n'})
        session = Session(tmp_path)
        session.run([('', 'r')])
        assert session.rust_line is None
        assert 'Rust' not in session.instructions
        assert session.result is not None and session.result.rust_exclude_test_modules is None

    def test_hidden_without_rust_keeps_a_loaded_value(self, tmp_path: Path) -> None:
        self._crate(tmp_path, {'app.py': 'x = 1\n'})
        session = Session(tmp_path, rust=True)
        session.run([('', 'r')])
        assert session.result is not None and session.result.rust_exclude_test_modules is True

    @pytest.mark.parametrize('path', ['lib.rs', 'src/deep/lib.rs', 'vendor/v.rs', 'src/MAIN.RS'])
    def test_shown_with_rust(self, tmp_path: Path, path: str) -> None:
        """Also in a directory the scan root's config excludes, since it can be lifted here."""
        self._crate(tmp_path, {path: 'fn a() {}\n'})
        session = Session(tmp_path, excluded={'vendor'})
        session.run([])
        assert session.rust_line == 'Rust test code: counted'
        assert 'r to count or leave out Rust test code' in session.instructions

    @pytest.mark.parametrize(
        'files',
        [
            {'.gitignore': 'target/\n', 'target/gen.rs': ''},  # under a gitignored directory
            {'.gitignore': '*.rs\n', 'src/lib.rs': ''},  # a gitignored file
            {'.tally-config.toml': '[exclude]\npatterns = ["*.rs"]\n', 'lib.rs': ''},  # excluded by a pattern
        ],
    )
    def test_rust_the_walker_never_counts_doesnt_show_it(self, tmp_path: Path, files: dict[str, str]) -> None:
        (tmp_path / '.git').mkdir()
        self._crate(tmp_path, files)
        patterns = ['*.rs'] if '.tally-config.toml' in files else None
        session = Session(tmp_path, patterns=patterns)
        session.run([])
        assert session.rust_line is None

    def test_symlinked_rust_file_doesnt_show_it(self, tmp_path: Path) -> None:
        outside = tmp_path / 'outside'
        outside.mkdir()
        (outside / 'lib.rs').write_text('fn a() {}\n')
        project = tmp_path / 'project'
        project.mkdir()
        try:
            (project / 'lib.rs').symlink_to(outside / 'lib.rs')
        except OSError:
            pytest.skip('symlinks not available')
        session = Session(project)
        session.run([])
        assert session.rust_line is None

    def test_toggle_without_a_parent(self, tmp_path: Path) -> None:
        self._crate(tmp_path)
        session = Session(tmp_path)
        session.run([('', 'r')])
        assert session.rust_line == 'Rust test code: excluded (#[cfg(test)] items left out)'
        assert session.result is not None and session.result.rust_exclude_test_modules is True

    def test_toggle_twice_writes_nothing(self, tmp_path: Path) -> None:
        self._crate(tmp_path)
        session = Session(tmp_path)
        session.run([('', 'r'), ('', 'r')])
        assert session.rust_line == 'Rust test code: counted'
        assert session.result is not None and session.result.rust_exclude_test_modules is None

    @pytest.mark.parametrize('loaded', [True, False])
    def test_toggle_twice_returns_to_the_loaded_value(self, tmp_path: Path, loaded: bool) -> None:
        self._crate(tmp_path)
        session = Session(tmp_path, rust=loaded)
        session.run([('', 'r'), ('', 'r')])
        assert session.result is not None and session.result.rust_exclude_test_modules is loaded

    @pytest.mark.parametrize('loaded', [True, False, None])
    def test_untouched_keeps_the_loaded_value(self, tmp_path: Path, loaded: Optional[bool]) -> None:
        self._crate(tmp_path)
        session = Session(tmp_path, rust=loaded)
        session.run([])
        assert session.result is not None and session.result.rust_exclude_test_modules is loaded

    def test_under_a_parent_value(self, tmp_path: Path) -> None:
        self._crate(tmp_path)
        parent = TallyConfig(rust_exclude_test_modules=True)
        session = Session(tmp_path, inherited=parent)
        session.run([])
        assert session.rust_line == 'Rust test code: excluded (#[cfg(test)] items left out) (set in a parent config)'
        session = Session(tmp_path, inherited=parent)
        session.run([('', 'r')])
        assert session.rust_line == 'Rust test code: counted'
        assert session.result is not None and session.result.rust_exclude_test_modules is False
        session = Session(tmp_path, inherited=parent)
        session.run([('', 'r'), ('', 'r')])
        assert session.result is not None and session.result.rust_exclude_test_modules is None  # no copy

    @pytest.mark.parametrize(('files', 'offered'), [({'app.py': ''}, False), ({'lib.rs': ''}, True)])
    def test_footer_offers_r_only_with_rust(self, tmp_path: Path, files: dict[str, str], offered: bool) -> None:
        self._crate(tmp_path, files)
        session = Session(tmp_path)
        session.run([])
        assert 'Toggle include/exclude' in session.footer_keys
        assert ('Toggle Rust test code' in session.footer_keys) is offered

    def test_only_nested_configs_set_it(self, tmp_path: Path) -> None:
        """Every Rust file follows a crate's own [rust]: the line says so, and 'r' can't change it."""
        self._crate(tmp_path, {'crate/.tally-config.toml': '[rust]\nexclude_test_modules = true\n', 'crate/lib.rs': ''})
        session = Session(tmp_path)
        session.run([('', 'r')])
        assert session.rust_line == 'Rust test code: set in a nested config'
        assert 'Toggle Rust test code' not in session.footer_keys
        assert 'Rust' not in session.instructions
        assert session.result is not None and session.result.rust_exclude_test_modules is None

    def test_some_directories_set_their_own(self, tmp_path: Path) -> None:
        self._crate(
            tmp_path,
            {'lib.rs': '', 'crate/.tally-config.toml': '[rust]\nexclude_test_modules = false\n', 'crate/c.rs': ''},
        )
        session = Session(tmp_path)
        session.run([('', 'r')])
        assert session.rust_line == (
            'Rust test code: excluded (#[cfg(test)] items left out) (some directories set their own in a nested config)'
        )
        assert session.result is not None and session.result.rust_exclude_test_modules is True

    def test_nested_config_without_rust_key_leaves_it_to_the_scan_root(self, tmp_path: Path) -> None:
        self._crate(tmp_path, {'crate/.tally-config.toml': '[exclude]\ndirectories = []\n', 'crate/lib.rs': ''})
        session = Session(tmp_path)
        session.run([])
        assert session.rust_line == 'Rust test code: counted'


# Trees where setup must agree with the walker on whether there is countable Rust (it reads no file contents)
_RUST_PARITY = {
    'plain': {'src/lib.rs': ''},
    'hidden directory': {'.cargo/x.rs': ''},
    'hidden file': {'.x.rs': ''},
    'gitignored directory': {'.gitignore': 'target/\n', 'target/gen.rs': ''},
    'negated ignore': {'.gitignore': '*.rs\n!keep.rs\n', 'keep.rs': ''},
    'nested config pattern': {'crate/.tally-config.toml': '[exclude]\npatterns = ["*.rs"]\n', 'crate/lib.rs': ''},
    'nested config pattern on a directory': {
        'crate/.tally-config.toml': '[exclude]\npatterns = ["gen/"]\n',
        'crate/gen/x.rs': '',
    },
    'nested config excludes the directory': {
        'crate/.tally-config.toml': '[exclude]\ndirectories = ["gen"]\n',
        'crate/gen/x.rs': '',
    },
    'nested repo ignores its own rust': {'inner/.git/': '', 'inner/.gitignore': '*.rs\n', 'inner/lib.rs': ''},
    'outer ignore stops at a nested repo': {'.gitignore': '*.rs\n', 'inner/.git/': '', 'inner/lib.rs': ''},
    'outer repo ignores the nested repo': {'.gitignore': 'inner/\n', 'inner/.git/': '', 'inner/lib.rs': ''},
}


@pytest.mark.parametrize('files', _RUST_PARITY.values(), ids=_RUST_PARITY.keys())
def test_rust_detection_agrees_with_the_walker(tmp_path: Path, files: dict[str, str]) -> None:
    (tmp_path / '.git').mkdir()
    for rel, text in files.items():
        path = tmp_path / rel
        if rel.endswith('/'):
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    session = Session(tmp_path)
    session.run([])
    walked = any(lang is RUST for _, lang in walk_project(tmp_path, set(), load_gitignore(tmp_path)))
    assert (session.app.has_rust or session.app.has_nested_rust) is walked
