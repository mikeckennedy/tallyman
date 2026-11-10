from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import pytest
from textual.widgets.tree import TreeNode

from tallyman.config import TallyConfig, discover_nested_configs, merge_configs
from tallyman.gitignore import load_gitignore
from tallyman.tui.setup_app import NodeInfo, SetupApp, SetupResult, SetupTree
from tallyman.walker import SpecState, root_spec_state, spec_state, walk_project

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


class Session:
    """Drives SetupApp headlessly: press keys on named directories, then save."""

    def __init__(
        self,
        root: Path,
        excluded: Optional[set[str]] = None,
        specs: Optional[set[str]] = None,
        non_specs: Optional[set[str]] = None,
        nested: Optional[TallyConfig] = None,
        root_auto_spec: bool = False,
        inherited: Optional[TallyConfig] = None,
    ) -> None:
        self.app = SetupApp(
            root,
            load_gitignore(root),
            excluded or set(),
            specs or set(),
            non_specs,
            nested,
            root_auto_spec,
            inherited,
        )
        self.labels: dict[str, str] = {}
        self.flags: dict[str, bool] = {}
        self.root_label = ''

    def run(self, actions: list[tuple[str, str]], save: bool = True) -> Optional[SetupResult]:
        """*actions* are (directory path, key); '' is the root. Records labels just before saving."""

        async def go() -> None:
            async with self.app.run_test(size=(100, 50)) as pilot:
                tree = self.app.query_one(SetupTree)
                tree.focus()
                for path, key in actions:
                    tree.move_cursor(_find(tree.root, path))
                    await pilot.press(key)
                await pilot.pause()
                self._record(tree.root)
                await pilot.click('#save' if save else '#cancel')

        asyncio.run(go())
        return self.app.return_value

    def _record(self, node: TreeNode[NodeInfo]) -> None:
        if node.data and not node.data.path:
            self.root_label = str(node.label)
        if node.data and node.data.path:
            path = str(node.data.path)
            self.labels[path] = str(node.label)
            self.flags[path] = bool(node.data.spec)
        for child in node.children:
            self._record(child)


def _walk_categories(root: Path, result: SetupResult) -> dict[str, str]:
    excluded, specs, non_specs = result
    found = walk_project(root, excluded, load_gitignore(root), spec_dirs=specs, non_spec_dirs=non_specs)
    return {p.parent.relative_to(root).as_posix(): lang.category for p, lang in found if p.suffix == '.md'}


class TestSpecToggles:
    def test_untouched_save(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([]) == (set(), set(), set())
        assert session.labels['plans'] == 'S plans (specs)'
        assert session.labels['plans/sub'] == 'S sub (specs)'
        assert session.labels['src/agents'] == 'S agents (specs)'

    def test_turning_off_an_auto_detected_spec_dir_sticks(self, tmp_path: Path):
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

    def test_turning_it_back_on_removes_the_override(self, tmp_path: Path):
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('plans', 's'), ('plans', 's')]) == (set(), set(), set())

    def test_marking_a_plain_directory(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path)
        result = session.run([('docs', 's')])
        assert result == (set(), {'docs'}, set())
        assert session.labels['docs'] == 'S docs'

    def test_explicit_spec_below_an_ignored_directory(self, tmp_path: Path):
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
    def test_root_cannot_be_excluded(self, tmp_path: Path):
        """H10: 'x' on the root used to write "" into the config and exclude everything below."""
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('', 'x')]) == (set(), set(), set())

    def test_explicitly_excluded_child_of_an_excluded_parent_keeps_its_entry(self, tmp_path: Path):
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src/vendor'}).run([('src', 'x'), ('src/vendor', 'x'), ('src', 'x')])
        assert result == ({'src/vendor'}, set(), set())

    def test_children_of_an_excluded_directory_show_excluded(self, tmp_path: Path):
        """H11: reopening setup with src excluded used to show src/vendor with a green check."""
        _make_tree(tmp_path)
        session = Session(tmp_path, excluded={'src'})
        result = session.run([('src/vendor', 'x')])  # no-op: it's excluded through its parent
        assert result is not None
        assert result[0] == {'src'}
        assert session.labels['src/vendor'] == '✗ vendor'
        assert session.labels['src/agents/inner'] == '✗ inner'

    def test_exclude_then_include_restores_spec_status(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([('plans', 'x'), ('plans', 'x')]) == (set(), set(), set())
        assert session.labels['plans'] == 'S plans (specs)'

    def test_excluding_a_parent_keeps_a_childs_own_exclusion(self, tmp_path: Path):
        _make_tree(tmp_path)
        result = Session(tmp_path, excluded={'src/vendor'}).run([('src', 'x'), ('src', 'x')])
        assert result == ({'src/vendor'}, set(), set())

    def test_cancel_returns_none(self, tmp_path: Path):
        _make_tree(tmp_path)
        assert Session(tmp_path).run([('docs', 's')], save=False) is None


class TestLabels:
    def test_directory_names_are_not_read_as_markup(self, tmp_path: Path):
        _make_tree(tmp_path, ['[bold]x', 'a[red]'])
        session = Session(tmp_path)
        session.run([])
        assert session.labels['[bold]x'] == '✓ [bold]x'
        assert session.labels['a[red]'] == '✓ a[red]'


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
def test_tui_and_walker_agree(tmp_path: Path, excluded: set[str], specs: set[str], non_specs: set[str]):
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
    def test_s_on_the_root_marks_everything(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path)
        assert session.run([('', 's')]) == (set(), {'.'}, set())
        assert session.labels['docs'] == 'S docs (specs)'

    def test_root_inside_an_auto_spec_dir_shows_specs_and_can_be_turned_off(self, tmp_path: Path):
        """Setup run from inside plans/ must show what the run will count, and offer a way out."""
        _make_tree(tmp_path)
        session = Session(tmp_path, root_auto_spec=True)
        assert session.run([]) == (set(), set(), set())  # the implicit state is not written to the config
        assert session.labels['docs'] == 'S docs (specs)'
        session = Session(tmp_path, root_auto_spec=True)
        assert session.run([('', 's')]) == (set(), set(), {'.'})
        assert session.labels['docs'] == '✓ docs'


class TestRoundTrips:
    def test_s_twice_keeps_an_ignore_that_exists_for_the_children(self, tmp_path: Path):
        _make_tree(tmp_path)
        assert Session(tmp_path, non_specs={'src'}).run([('src', 's'), ('src', 's')]) == (set(), set(), {'src'})

    @pytest.mark.parametrize(
        ('specs', 'non_specs'), [(set(), set()), (set(), {'src'}), ({'lib'}, {'plans'}), ({'.'}, {'src/agents'})]
    )
    def test_s_twice_on_any_directory_changes_nothing(self, tmp_path: Path, specs: set[str], non_specs: set[str]):
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

    def test_nested_settings_are_shown_locked_and_not_saved(self, tree: Path):
        session = Session(tree, nested=discover_nested_configs(tree))
        result = session.run([('plans', 's'), ('lib', 's'), ('vendor/y', 'x')])
        assert result == (set(), set(), set())
        assert session.labels['plans'] == '✓ plans (not specs) (set in a nested config)'
        assert session.labels['lib'] == 'S lib (set in a nested config)'
        assert session.labels['vendor/y'] == '✗ y (set in a nested config)'

    def test_tui_and_walker_agree_with_nested_configs(self, tree: Path):
        session = Session(tree, nested=discover_nested_configs(tree))
        result = session.run([('docs', 's')])
        assert result is not None
        walked = _walk_categories(tree, result)
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}


class TestNestedConfigPrecedence:
    def test_deeper_nested_config_wins_and_tui_matches_walker(self, tmp_path: Path):
        """lib/ marks notes as specs; lib/notes/ ignores itself. The deeper config wins in the TUI too."""
        _make_tree(tmp_path, ['lib/notes'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["notes"]\n')
        (tmp_path / 'lib' / 'notes' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        session = Session(tmp_path, nested=discover_nested_configs(tmp_path))
        result = session.run([])
        assert result is not None
        assert session.labels['lib/notes'] == '✓ notes (not specs) (set in a nested config)'
        walked = _walk_categories(tmp_path, result)
        assert walked['lib/notes'] == 'docs'
        assert {d for d, cat in walked.items() if cat == 'specs'} == {d for d in walked if session.flags[d]}

    def test_excluding_a_dir_whose_spec_setting_is_nested_drops_the_credit(self, tmp_path: Path):
        _make_tree(tmp_path, ['lib/l'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\ndirectories = ["."]\n')
        session = Session(tmp_path, nested=discover_nested_configs(tmp_path))
        assert session.run([('lib', 'x')]) == ({'lib'}, set(), set())
        assert session.labels['lib'] == '✗ lib'


class TestParentConfigs:
    """Settings inherited from configs above the scan root are shown locked and never saved."""

    def test_inherited_exclusion_is_locked(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig({'src/vendor'}))
        result = session.run([('src/vendor', 'x'), ('src/vendor', 's')])
        assert result == (set(), set(), set())
        assert session.labels['src/vendor'] == '✗ vendor (set in a parent config)'

    def test_child_of_an_inherited_exclusion_is_excluded(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig({'src'}))
        session.run([('src/vendor', 'x')])
        assert session.labels['src/vendor'] == '✗ vendor'

    def test_inherited_spec_settings_are_locked(self, tmp_path: Path):
        _make_tree(tmp_path)
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'docs'}, non_spec_dirs={'plans'}))
        result = session.run([('docs', 's'), ('plans', 's')])
        assert result == (set(), set(), set())
        assert session.labels['docs'] == 'S docs (set in a parent config)'
        assert session.labels['plans'] == '✓ plans (not specs) (set in a parent config)'
        assert session.labels['plans/sub'] == '✓ sub'

    def test_inherited_root_spec_is_shown_on_the_root(self, tmp_path: Path):
        _make_tree(tmp_path, ['docs'])
        session = Session(tmp_path, inherited=TallyConfig(spec_dirs={'.'}))
        session.run([('', 's')])
        assert session.root_label == f'{tmp_path.name} (specs) (set in a parent config)'
        assert session.labels['docs'] == 'S docs (specs)'

    def test_a_local_override_of_a_parent_setting_stays_editable(self, tmp_path: Path):
        """The parent marks docs as specs, the local config ignores it: the local entry is the user's to change."""
        _make_tree(tmp_path, ['docs'])
        session = Session(tmp_path, non_specs={'docs'}, inherited=TallyConfig(spec_dirs={'docs'}))
        result = session.run([('docs', 's')])
        assert result == (set(), set(), set())  # dropping the override lets the parent's setting apply
        assert session.labels['docs'] == 'S docs'

    def test_nested_config_beats_an_inherited_setting(self, tmp_path: Path):
        _make_tree(tmp_path, ['lib/l'])
        (tmp_path / 'lib' / '.tally-config.toml').write_text('[specs]\nignore = ["."]\n')
        session = Session(tmp_path, nested=discover_nested_configs(tmp_path), inherited=TallyConfig(spec_dirs={'lib'}))
        session.run([])
        assert session.labels['lib'] == '✓ lib (not specs) (set in a nested config)'

    def test_tui_and_walker_agree_with_parent_configs(self, tmp_path: Path):
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


class TestLabels2:
    def test_not_specs_shows_on_any_ignored_directory(self, tmp_path: Path):
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
def test_spec_state_rule(rel: str, parent: SpecState, specs: set[str], non_specs: set[str], expected: SpecState):
    assert spec_state(rel, rel.rsplit('/', 1)[-1], parent, specs, non_specs) == expected


def test_root_spec_state_rule():
    assert root_spec_state(set(), set()) == _N
    assert root_spec_state(set(), set(), auto=True) == _P
    assert root_spec_state(set(), {'.'}, auto=True) == _SUP
    assert root_spec_state({'.'}, {'.'}) == _P
