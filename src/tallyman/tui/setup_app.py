"""Textual TUI for first-run directory selection setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from tallyman.config import (
    CONFIG_FILENAME,
    SELF,
    TallyConfig,
    load_nested_config,
    merge_configs,
    rust_setting,
    without_copies,
)
from tallyman.gitignore import GitIgnoreSpec
from tallyman.languages import RUST, identify_language
from tallyman.walker import SpecState, root_spec_state, spec_state


class SetupResult(NamedTuple):
    """The scan root's own settings, chosen in setup, to save in its config (or, with ``save=False``, to use once)."""

    excluded_dirs: set[str]
    spec_dirs: set[str]
    non_spec_dirs: set[str]
    rust_exclude_test_modules: Optional[bool]  # [rust] exclude_test_modules; None writes no [rust] table


# Spec and ignore entries as the walker will see them (see SetupApp._spec_sets)
_SpecSets = tuple[set[str], set[str]]

# The entry a directory can carry in the config: none, a spec entry, or an ignore entry
_UNSET, _SPEC, _IGNORE = 'unset', 'spec', 'ignore'


@dataclass(slots=True)
class NodeInfo:
    """What the tree knows about one directory.

    Everything but path, gitignored and pattern_excluded is derived by _refresh(). Those two are fixed when the
    tree is built and mean "gitignore or a pattern would exclude it if no config did": the walker checks a
    config's exclusion first, so config_excluded explains an exclusion before either of them.

    A directory that gitignore, a pattern, or a parent or nested config excludes is a leaf: the walker never
    enters it, and setup can't change those. One only the scan root's own config excludes keeps its children,
    since the user can lift that exclusion here.
    """

    path: str  # relative to the scan root; '' for the root
    gitignored: bool = False
    pattern_excluded: bool = False  # matched by an [exclude] pattern in some config
    config_excluded: bool = False  # excluded by this config, a parent or a nested one
    excluded: bool = False
    parent_excluded: bool = False
    spec: bool = False
    state: SpecState = SpecState(False, False)
    locked_by: Optional[Literal['parent', 'nested']] = None  # its setting comes from another .tally-config.toml
    exclude_locked: bool = False  # another config excludes it, so 'x' can't change it
    spec_locked: bool = False  # another config sets its spec status, so 's' can't change it


class SetupTree(Tree[NodeInfo]):
    """Tree subclass for tallyman setup."""


class SetupApp(App[Optional[SetupResult]]):
    """First-run setup: choose which directories to include/exclude and designate specs."""

    CSS = """
    #instructions {
        margin: 1 2;
        color: $text-muted;
    }

    SetupTree {
        margin: 0 2;
    }

    #rust {
        margin: 1 2 0 2;
    }

    #buttons {
        margin: 1 2;
        height: auto;
    }

    #buttons Button {
        margin-right: 2;
    }
    """

    BINDINGS = [
        Binding('x', 'toggle_node', 'Toggle include/exclude', show=True),
        Binding('s', 'toggle_spec', 'Toggle spec directory', show=True),
        Binding('r', 'toggle_rust_tests', 'Toggle Rust test code', show=True),  # only with Rust: check_action()
        Binding('left', 'collapse_node', 'Collapse', show=False),
        Binding('right', 'expand_node', 'Expand', show=False),
    ]

    def __init__(
        self,
        root: Path,
        gitignore_spec: GitIgnoreSpec,
        existing_exclusions: set[str],
        existing_specs: set[str],
        *,
        existing_non_specs: Optional[set[str]] = None,
        root_auto_spec: bool = False,
        inherited: Optional[TallyConfig] = None,
        exclude_patterns: Optional[GitIgnoreSpec] = None,
        existing_rust: Optional[bool] = None,
        save: bool = True,
    ) -> None:
        """*existing_** are the editable settings saved at the scan root (*existing_rust* is its
        ``[rust] exclude_test_modules``, offered with 'r' only when the tree holds Rust code). *inherited* holds
        the merged settings of the .tally-config.toml files above it, rebased onto the scan root, and their
        ``[rust]`` value in ``inherited.rust_exclude_test_modules``. The configs below it (nested configs) are read
        while the tree is built, wherever the walker would read them, and also beneath the scan root's own
        exclusions, which the user can lift here. Tallyman reads all those files on every run, so their settings
        are shown but can't be changed here, and are not saved. *root_auto_spec* says the scan root is
        inside an auto-detected spec directory (see walker.inside_auto_spec_dir). *exclude_patterns* holds the
        ``[exclude] patterns`` of the configs at and above the scan root (see GitIgnoreSpec.for_patterns); nested
        configs' patterns are added to it as the tree is built. Directories they match are shown excluded and
        locked, since setup doesn't edit patterns. With *save* False (``--no-save``) the choices are used for one run
        and never written, and the screen says so."""
        super().__init__()
        self.root = root
        self.title = f'Setup Tallyman for {root.name}'
        self.save = save
        if not save:
            self.sub_title = 'Not saved: this run only'  # short: the header cuts it off at 80 columns
        self.gitignore_spec = gitignore_spec
        self.user_excluded: set[str] = set(existing_exclusions)
        self.user_spec_dirs: set[str] = set(existing_specs)
        self.user_non_spec_dirs: set[str] = set(existing_non_specs or ())
        self.nested = TallyConfig()  # every nested config read so far, merged: filled in by _populate()
        self.inherited = inherited or TallyConfig()
        self.exclude_patterns = exclude_patterns or GitIgnoreSpec.for_patterns(root)
        self.root_auto_spec = root_auto_spec
        # Each directory's entry when setup opened, so toggling twice restores it exactly (see _drop_copies())
        self._original_entry: dict[str, str] = {}
        self.user_rust: Optional[bool] = existing_rust
        self._original_rust = existing_rust
        # Set by _populate(): a countable Rust file the scan root's [rust] value governs, and one a nested
        # config's own [rust] value governs instead ('r' can't change that one; it is edited in that file)
        self.has_rust = False
        self.has_nested_rust = False

    def compose(self) -> ComposeResult:
        # The tree is built first: whether it holds Rust code decides what the instructions offer
        tree: SetupTree = SetupTree(Text(self.root.name))
        tree.root.data = NodeInfo('')
        self._populate(tree.root, self.root, '')
        self._drop_copies()
        self._refresh(tree.root)
        tree.root.expand_all()
        self._collapse_excluded(tree.root)
        tree.show_root = True
        yield Header()
        rust_key = ', [bold]r[/bold] to count or leave out Rust test code' if self.has_rust else ''
        yield Static(
            'Use [bold]←/→[/bold] to expand/collapse, '
            '[bold]x[/bold] to toggle include/exclude, '
            f'[bold]s[/bold] to toggle spec directory{rust_key}.',
            id='instructions',
        )
        yield tree
        if self.has_rust or self.has_nested_rust:
            yield Static(self._rust_label(), id='rust')
        with Horizontal(id='buttons'):
            yield Button('Save & Run' if self.save else 'Run', id='save', variant='primary')
            yield Button('Cancel', id='cancel')
        yield Footer()

    def _populate(
        self, parent_node: TreeNode[NodeInfo], dir_path: Path, rel_path: str, nested_rust: Optional[bool] = None
    ) -> None:
        """Recursively add subdirectories to the tree, reading nested configs on the way, in walk_project()'s order.
        Labels and states are filled in by _refresh(). *nested_rust* is the ``[rust]`` value a nested config sets
        for *dir_path*, None while the scan root's value governs it, as in the walker's per-directory map."""
        # This directory's own .gitignore governs its children, matching walk_project(). It is also where a
        # nested git repository's own rules start, so this must run before its children are judged.
        self.gitignore_spec.add_directory(rel_path, dir_path)
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            # os.walk never yields a directory it can't list, so the walker never reads its config: nor does setup
            return
        # So does its config. Pre-order is enough: a config only names paths beneath its own directory, so every
        # config that can name a child is merged before the child is judged, and a deeper one merges later and wins.
        config_file = dir_path / CONFIG_FILENAME
        if rel_path and config_file.is_file() and (loaded := load_nested_config(config_file, rel_path)) is not None:
            # A malformed config is None: skipped silently, as in the walker
            self.nested = merge_configs(self.nested, loaded.config)
            self.exclude_patterns.add_rules(dir_path, loaded.patterns)
            if loaded.rust_exclude_test_modules is not None:
                nested_rust = loaded.rust_exclude_test_modules  # this directory and below follow that config

        for entry in entries:
            if identify_language(entry) is RUST and not self._rust_seen(nested_rust):
                if self._counted_file(entry, rel_path):
                    if nested_rust is None:
                        self.has_rust = True
                    else:
                        self.has_nested_rust = True
            if not entry.is_dir(follow_symlinks=False) or entry.name.startswith('.'):
                continue
            child_rel = f'{rel_path}/{entry.name}'.lstrip('/')
            is_gitignored = self.gitignore_spec.match_file(child_rel + '/')
            # The walker checks patterns only for entries gitignore lets through
            by_pattern = not is_gitignored and self.exclude_patterns.match_file(child_rel + '/')
            # Excluded by a parent or nested config: setup can't lift that, so it is a leaf
            locked_out = child_rel in self.inherited.excluded_dirs or child_rel in self.nested.excluded_dirs
            info = NodeInfo(child_rel, gitignored=is_gitignored, pattern_excluded=by_pattern)
            node = parent_node.add(Text(entry.name), data=info)
            # Don't recurse where the walker never goes. The scan root's own exclusions are entered: the user
            # can lift them here, and then the walker enters them and reads their configs.
            if not is_gitignored and not by_pattern and not locked_out:
                self._populate(node, entry, child_rel, nested_rust)

    def _rust_seen(self, nested_rust: Optional[bool]) -> bool:
        """Whether a Rust file governed like this one was already found, so another needn't be checked."""
        return self.has_rust if nested_rust is None else self.has_nested_rust

    def _counted_file(self, entry: Path, rel_path: str) -> bool:
        """Whether the walker would count the file *entry* in *rel_path*, as far as its rules go: a regular file
        (not a symlink), not gitignored, not matched by a pattern. Its content isn't read, so a binary ``.rs``
        file the walker skips still counts here: harmless, and rare."""
        file_rel = f'{rel_path}/{entry.name}'.lstrip('/')
        return (
            entry.is_file(follow_symlinks=False)
            and not self.gitignore_spec.match_file(file_rel)
            and not self.exclude_patterns.match_file(file_rel)
        )

    def _drop_copies(self) -> None:
        """Drop the scan-root entries that a parent or nested config already has (see config.without_copies).

        Older versions copied parent and nested settings into the scan root's config. Those files are read on
        every run, so the copies change nothing but would stay locked here and be saved again. Done when setup
        opens, so the labels, the locks and the 's' round trips all start from what will be saved.
        """
        user = TallyConfig(self.user_excluded, self.user_spec_dirs, self.user_non_spec_dirs)
        local = without_copies(user, self.inherited, self.nested)
        # An exclusion beneath a dropped one was redundant in this config, as Save would have found: drop it too.
        # Only these: an exclusion beneath one of this config's own stays, so un-excluding the outer one reveals it.
        dropped = user.excluded_dirs - local.excluded_dirs
        self.user_excluded = {e for e in local.excluded_dirs if not any(e.startswith(d + '/') for d in dropped)}
        self.user_spec_dirs, self.user_non_spec_dirs = local.spec_dirs, local.non_spec_dirs
        self._original_entry = {d: _SPEC for d in self.user_spec_dirs} | {d: _IGNORE for d in self.user_non_spec_dirs}

    # --- deriving state -------------------------------------------------------------------------------------------

    def _spec_sets(self) -> _SpecSets:
        """Spec and ignore entries as the walker will see them: parent configs, then these settings, then nested
        configs, each deeper one winning on the same path. Only a toggle changes them, and every toggle ends in
        _refresh(), which computes them once for the whole subtree."""
        user = TallyConfig(set(), self.user_spec_dirs, self.user_non_spec_dirs)
        merged = merge_configs(merge_configs(self.inherited, user), self.nested)
        return merged.spec_dirs, merged.non_spec_dirs

    def _lock(self, info: NodeInfo) -> None:
        """Mark which of *info*'s settings come from another config. The deepest source names the lock."""
        key = info.path or SELF
        nested_spec = key in self.nested.spec_dirs | self.nested.non_spec_dirs
        # A parent's spec setting is locked unless this config overrode it when setup opened
        parent_spec = key in self.inherited.spec_dirs | self.inherited.non_spec_dirs and key not in self._original_entry
        nested_excl = key in self.nested.excluded_dirs
        parent_excl = key in self.inherited.excluded_dirs
        info.exclude_locked = nested_excl or parent_excl
        info.spec_locked = nested_spec or parent_spec
        if nested_spec or nested_excl:
            info.locked_by = 'nested'
        elif parent_spec or parent_excl:
            info.locked_by = 'parent'
        else:
            info.locked_by = None

    def _derive(self, info: NodeInfo, parent: Optional[NodeInfo], sets: _SpecSets) -> None:
        """Fill in *info*'s exclusion and spec status from the current settings (*sets* is _spec_sets()),
        exactly as the walker decides."""
        specs, non_specs = sets
        if parent is None:
            info.state = root_spec_state(specs, non_specs, auto=self.root_auto_spec)
            info.spec = info.state.is_spec
            info.excluded = info.parent_excluded = False
            self._lock(info)
            return
        info.parent_excluded = parent.excluded
        info.config_excluded = (
            info.path in self.user_excluded
            or info.path in self.nested.excluded_dirs
            or info.path in self.inherited.excluded_dirs
        )
        # Same order as walk_project(): a config exclusion is checked first, then gitignore, then patterns
        info.excluded = info.config_excluded or info.gitignored or info.pattern_excluded or parent.excluded
        info.state = spec_state(info.path, Path(info.path).name, parent.state, specs, non_specs)
        info.spec = info.state.is_spec and not info.excluded
        self._lock(info)

    def _refresh(self, node: TreeNode[NodeInfo]) -> None:
        """Recompute state and label for *node* and everything beneath it."""
        self._refresh_tree(node, self._spec_sets())

    def _refresh_tree(self, node: TreeNode[NodeInfo], sets: _SpecSets) -> None:
        info = node.data
        assert info is not None
        parent = node.parent.data if node.parent is not None else None
        self._derive(info, parent, sets)
        node.set_label(self._label_for(info, sets))
        for child in node.children:
            self._refresh_tree(child, sets)

    def _label_for(self, info: NodeInfo, sets: _SpecSets) -> Text:
        """*info*'s label. Labels are Text, never markup, so a directory name always shows exactly as it is on disk.

        Known limit: Textual's Tree shows only a label's first line, so a name containing a newline is cut short.
        """
        if not info.path:
            label = Text(self.root.name)
            if info.spec:
                label.append(' (specs)', style='dim')
            if info.locked_by is not None:
                label.append(f' (set in a {info.locked_by} config)', style='dim')
            return label
        specs, non_specs = sets
        explicit_spec = info.path in specs
        label = self._make_label(
            Path(info.path).name,
            gitignored=info.gitignored and not info.config_excluded,
            pattern_excluded=info.pattern_excluded and not info.config_excluded,
            excluded=info.excluded,
            spec=info.spec,
            auto_spec=info.spec and not explicit_spec,
            not_spec=info.path in non_specs,
        )
        # Once excluded here, a spec setting from another config no longer matters, so don't credit it
        if info.locked_by is not None and not _rule_excluded(info) and (info.exclude_locked or not info.excluded):
            label.append(f' (set in a {info.locked_by} config)', style='dim')
        return label

    @staticmethod
    def _collapse_excluded(node: TreeNode[NodeInfo]) -> None:
        """Collapse nodes that are excluded so they start folded."""
        for child in node.children:
            if child.data and child.data.excluded:
                child.collapse()
            else:
                SetupApp._collapse_excluded(child)

    @staticmethod
    def _make_label(
        name: str,
        gitignored: bool,
        excluded: bool,
        spec: bool = False,
        auto_spec: bool = False,
        not_spec: bool = False,
        pattern_excluded: bool = False,
    ) -> Text:
        # The name is always plain text: it may look like markup ([bold]) or an emoji code (:rocket:), or end in '\'
        if gitignored:
            return Text(f'{name} (gitignored)', style='dim')
        if pattern_excluded:
            return Text(f'{name} (excluded by pattern)', style='dim')
        if excluded:
            return Text.assemble(('✗', 'red'), ' ', (name, 'dim'))
        if auto_spec:
            return Text.assemble(('S', 'bright_cyan'), ' ', (f'{name} (specs)', 'dim'))
        if spec:
            return Text.assemble(('S', 'bright_cyan'), ' ', name)
        if not_spec:
            return Text.assemble(('✓', 'green'), ' ', name, ' ', ('(not specs)', 'dim'))
        return Text.assemble(('✓', 'green'), ' ', name)

    # --- toggles --------------------------------------------------------------------------------------------------

    def _cursor(self) -> Optional[tuple[TreeNode[NodeInfo], NodeInfo]]:
        node = self.query_one(SetupTree).cursor_node
        if node is None or node.data is None or _rule_excluded(node.data):
            return None  # gitignore and patterns can't be changed here; a config's exclusion of the dir can
        return node, node.data

    def action_toggle_node(self) -> None:
        cursor = self._cursor()
        if cursor is None:
            return
        node, info = cursor
        if info.exclude_locked:
            return  # excluded by a parent or nested config: change it in that file
        # The root can't be excluded, and inside an excluded directory nothing is walked: un-exclude the parent
        if not info.path or info.parent_excluded:
            return
        if info.path in self.user_excluded:
            self.user_excluded.discard(info.path)
        else:
            self.user_excluded.add(info.path)
        self._refresh(node)

    def action_toggle_spec(self) -> None:
        """Flip the focused directory between specs and not specs, with the smallest change to the config."""
        cursor = self._cursor()
        if cursor is None:
            return
        node, info = cursor
        if info.excluded or info.spec_locked:
            return  # un-exclude first; a spec setting from another config is changed in that file
        rel = SELF if not info.path else info.path
        wanted = not info.spec
        # Prefer the entry the directory had when setup opened, then no entry, then an explicit one,
        # so pressing 's' twice always returns to where it started
        candidates = [self._original_entry.get(rel, _UNSET), _UNSET, _SPEC if wanted else _IGNORE]
        for entry in candidates:
            self._set_entry(rel, entry)
            if self._would_be_spec(node) == wanted:
                break
        self._refresh(node)

    def _set_entry(self, rel: str, entry: str) -> None:
        self.user_spec_dirs.discard(rel)
        self.user_non_spec_dirs.discard(rel)
        if entry == _SPEC:
            self.user_spec_dirs.add(rel)
        elif entry == _IGNORE:
            self.user_non_spec_dirs.add(rel)

    def _would_be_spec(self, node: TreeNode[NodeInfo]) -> bool:
        """Whether *node* is a spec directory under the current settings."""
        assert node.data is not None
        probe = NodeInfo(node.data.path, gitignored=node.data.gitignored, pattern_excluded=node.data.pattern_excluded)
        self._derive(probe, node.parent.data if node.parent is not None else None, self._spec_sets())
        return probe.spec

    # --- Rust test code -------------------------------------------------------------------------------------------

    def _rust_effective(self) -> bool:
        """[rust] exclude_test_modules at the scan root with the current choice, as the CLI will count."""
        return rust_setting(self.user_rust, self.inherited.rust_exclude_test_modules)

    def _rust_label(self) -> Text:
        if not self.has_rust:
            # Every Rust file is under a nested config that sets [rust]: 'r' can't change them
            return Text.assemble('Rust test code: ', ('set in a nested config', 'dim'))
        if self._rust_effective():
            label = Text.assemble('Rust test code: ', ('excluded', 'bold'), (' (#[cfg(test)] items left out)', 'dim'))
        else:
            label = Text.assemble('Rust test code: ', ('counted', 'bold'))
        if self.user_rust is None and self.inherited.rust_exclude_test_modules is not None:
            label.append(' (set in a parent config)', style='dim')
        if self.has_nested_rust:
            label.append(' (some directories set their own in a nested config)', style='dim')
        return label

    def check_action(self, action: str, parameters: tuple[object, ...]) -> Optional[bool]:
        """'r' exists only when the tree holds Rust code the scan root's value governs."""
        if action == 'toggle_rust_tests' and not self.has_rust:
            return False
        return True

    def action_toggle_rust_tests(self) -> None:
        """Flip Rust test code between counted and left out, with the smallest change to the config."""
        if not self.has_rust:
            return
        wanted = not self._rust_effective()
        # As with 's': the value setup opened with, then no entry (the parents' value), then an explicit one,
        # so pressing 'r' twice returns to where it started and a value that only repeats the parents' isn't saved
        for value in (self._original_rust, None, wanted):
            self.user_rust = value
            if self._rust_effective() == wanted:
                break
        self.query_one('#rust', Static).update(self._rust_label())

    # --- navigation and buttons -----------------------------------------------------------------------------------

    def action_collapse_node(self) -> None:
        tree = self.query_one(SetupTree)
        node = tree.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            tree.select_node(node.parent)
            node.parent.collapse()

    def action_expand_node(self) -> None:
        tree = self.query_one(SetupTree)
        node = tree.cursor_node
        if node is None:
            return
        if not node.is_expanded and node.children:
            node.expand()
        elif node.is_expanded and node.children:
            tree.select_node(node.children[0])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'save':
            user = TallyConfig(self._clean_exclusions(self.user_excluded), self.user_spec_dirs, self.user_non_spec_dirs)
            # Dropped when setup opened; again here, so no toggle can ever save another config's setting
            local = without_copies(user, self.inherited, self.nested)
            self.exit(SetupResult(local.excluded_dirs, local.spec_dirs, local.non_spec_dirs, self.user_rust))
        elif event.button.id == 'cancel':
            self.exit(None)

    @staticmethod
    def _clean_exclusions(excluded: set[str]) -> set[str]:
        """Remove child paths when a parent is already excluded."""
        sorted_paths = sorted(excluded)
        cleaned: set[str] = set()
        for path in sorted_paths:
            if not any(path.startswith(p + '/') for p in cleaned):
                cleaned.add(path)
        return cleaned


def _rule_excluded(info: NodeInfo) -> bool:
    """Whether gitignore or a pattern excludes *info* and no config does: setup can't change that."""
    return (info.gitignored or info.pattern_excluded) and not info.config_excluded


def run_setup(
    root: Path,
    gitignore_spec: GitIgnoreSpec,
    existing_exclusions: set[str],
    existing_specs: set[str],
    *,
    existing_non_specs: Optional[set[str]] = None,
    root_auto_spec: bool = False,
    inherited: Optional[TallyConfig] = None,
    exclude_patterns: Optional[GitIgnoreSpec] = None,
    existing_rust: Optional[bool] = None,
    save: bool = True,
) -> Optional[SetupResult]:
    """Launch the TUI setup app.

    Returns the settings to save at the scan root (a :class:`SetupResult`), or None if the user
    quit without saving. With *save* False the screen says the choices apply to this run only; the caller
    then doesn't write them. Settings from parent and nested configs are never included, not even as copies an
    earlier version wrote into the scan root's config: those files keep them. Nested configs are read by the
    TUI itself (see SetupApp).
    """
    app = SetupApp(
        root,
        gitignore_spec,
        existing_exclusions,
        existing_specs,
        existing_non_specs=existing_non_specs,
        root_auto_spec=root_auto_spec,
        inherited=inherited,
        exclude_patterns=exclude_patterns,
        existing_rust=existing_rust,
        save=save,
    )
    return app.run()
