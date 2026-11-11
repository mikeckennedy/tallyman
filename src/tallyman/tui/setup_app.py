"""Textual TUI for first-run directory selection setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from tallyman.config import SELF, TallyConfig, merge_configs
from tallyman.gitignore import GitIgnoreSpec
from tallyman.walker import SpecState, root_spec_state, spec_state

# (excluded_dirs, spec_dirs, non_spec_dirs) chosen in setup
SetupResult = tuple[set[str], set[str], set[str]]

# The entry a directory can carry in the config: none, a spec entry, or an ignore entry
_UNSET, _SPEC, _IGNORE = 'unset', 'spec', 'ignore'


@dataclass(slots=True)
class NodeInfo:
    """What the tree knows about one directory.

    Everything but path, gitignored and pattern_excluded is derived by _refresh().
    """

    path: str  # relative to the scan root; '' for the root
    gitignored: bool = False
    pattern_excluded: bool = False  # matched by an [exclude] pattern in some config
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
        Binding('left', 'collapse_node', 'Collapse', show=False),
        Binding('right', 'expand_node', 'Expand', show=False),
    ]

    def __init__(
        self,
        root: Path,
        gitignore_spec: GitIgnoreSpec,
        existing_exclusions: set[str],
        existing_specs: set[str],
        existing_non_specs: Optional[set[str]] = None,
        nested: Optional[TallyConfig] = None,
        root_auto_spec: bool = False,
        inherited: Optional[TallyConfig] = None,
        exclude_patterns: Optional[GitIgnoreSpec] = None,
    ) -> None:
        """*existing_** are the editable settings saved at the scan root. *nested* holds settings from
        .tally-config.toml files below it, and *inherited* the merged settings of those above it, rebased
        onto the scan root. Tallyman reads those files on every run, so their settings are shown but can't be
        changed here, and are not saved. *root_auto_spec* says the scan root is inside an auto-detected
        spec directory (see walker.inside_auto_spec_dir). *exclude_patterns* holds the ``[exclude] patterns``
        of every config that applies (see GitIgnoreSpec.for_patterns); directories they match are shown
        excluded and locked, since setup doesn't edit patterns."""
        super().__init__()
        self.root = root
        self.title = f'Setup Tallyman for {root.name}'
        self.gitignore_spec = gitignore_spec
        self.user_excluded: set[str] = set(existing_exclusions)
        self.user_spec_dirs: set[str] = set(existing_specs)
        self.user_non_spec_dirs: set[str] = set(existing_non_specs or ())
        self.nested = nested or TallyConfig()
        self.inherited = inherited or TallyConfig()
        self.exclude_patterns = exclude_patterns or GitIgnoreSpec.for_patterns(root)
        self.root_auto_spec = root_auto_spec
        # Each directory's entry when setup opened, so toggling twice restores it exactly
        self._original_entry = {d: _SPEC for d in self.user_spec_dirs} | {d: _IGNORE for d in self.user_non_spec_dirs}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            'Use [bold]←/→[/bold] to expand/collapse, '
            '[bold]x[/bold] to toggle include/exclude, '
            '[bold]s[/bold] to toggle spec directory.',
            id='instructions',
        )
        tree: SetupTree = SetupTree(Text(self.root.name))
        tree.root.data = NodeInfo('')
        self._populate(tree.root, self.root, '')
        self._refresh(tree.root)
        tree.root.expand_all()
        self._collapse_excluded(tree.root)
        tree.show_root = True
        yield tree
        with Horizontal(id='buttons'):
            yield Button('Save & Run', id='save', variant='primary')
            yield Button('Cancel', id='cancel')
        yield Footer()

    def _populate(self, parent_node: TreeNode[NodeInfo], dir_path: Path, rel_path: str) -> None:
        """Recursively add subdirectories to the tree. Labels and states are filled in by _refresh()."""
        # This directory's own .gitignore governs its children, matching walk_project(). It is also where a
        # nested git repository's own rules start, so this must run before its children are judged.
        self.gitignore_spec.add_directory(rel_path, dir_path)
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            return

        for entry in entries:
            if not entry.is_dir(follow_symlinks=False) or entry.name.startswith('.'):
                continue
            child_rel = f'{rel_path}/{entry.name}'.lstrip('/')
            is_gitignored = self.gitignore_spec.match_file(child_rel + '/')
            # The walker checks patterns only for entries gitignore lets through
            by_pattern = not is_gitignored and self.exclude_patterns.match_file(child_rel + '/')
            info = NodeInfo(child_rel, gitignored=is_gitignored, pattern_excluded=by_pattern)
            node = parent_node.add(Text(entry.name), data=info)
            # Don't recurse into gitignored or pattern-excluded dirs: the walker never enters them
            if not is_gitignored and not by_pattern:
                self._populate(node, entry, child_rel)

    # --- deriving state -------------------------------------------------------------------------------------------

    def _spec_sets(self) -> tuple[set[str], set[str]]:
        """Spec and ignore entries as the walker will see them: parent configs, then these settings, then nested
        configs, each deeper one winning on the same path."""
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

    def _derive(self, info: NodeInfo, parent: Optional[NodeInfo]) -> None:
        """Fill in *info*'s exclusion and spec status from the current settings, exactly as the walker decides."""
        specs, non_specs = self._spec_sets()
        if parent is None:
            info.state = root_spec_state(specs, non_specs, auto=self.root_auto_spec)
            info.spec = info.state.is_spec
            info.excluded = info.parent_excluded = False
            self._lock(info)
            return
        info.parent_excluded = parent.excluded
        excluded_here = (
            info.path in self.user_excluded
            or info.path in self.nested.excluded_dirs
            or info.path in self.inherited.excluded_dirs
        )
        info.excluded = info.gitignored or info.pattern_excluded or excluded_here or parent.excluded
        info.state = spec_state(info.path, Path(info.path).name, parent.state, specs, non_specs)
        info.spec = info.state.is_spec and not info.excluded
        self._lock(info)

    def _refresh(self, node: TreeNode[NodeInfo]) -> None:
        """Recompute state and label for *node* and everything beneath it."""
        info = node.data
        assert info is not None
        parent = node.parent.data if node.parent is not None else None
        self._derive(info, parent)
        node.set_label(self._label_for(info))
        for child in node.children:
            self._refresh(child)

    def _label_for(self, info: NodeInfo) -> Text:
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
        specs, non_specs = self._spec_sets()
        explicit_spec = info.path in specs
        label = self._make_label(
            Path(info.path).name,
            gitignored=info.gitignored,
            pattern_excluded=info.pattern_excluded,
            excluded=info.excluded,
            spec=info.spec,
            auto_spec=info.spec and not explicit_spec,
            not_spec=info.path in non_specs,
        )
        # Once excluded here, a spec setting from another config no longer matters, so don't credit it
        unchangeable = info.gitignored or info.pattern_excluded
        if info.locked_by is not None and not unchangeable and (info.exclude_locked or not info.excluded):
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
        if node is None or node.data is None or node.data.gitignored or node.data.pattern_excluded:
            return None  # gitignored dirs, and dirs a pattern excludes, can't be changed here
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
        self._derive(probe, node.parent.data if node.parent is not None else None)
        return probe.spec

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
            excluded = self._clean_exclusions(self.user_excluded)
            self.exit((excluded, set(self.user_spec_dirs), set(self.user_non_spec_dirs)))
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


def run_setup(
    root: Path,
    gitignore_spec: GitIgnoreSpec,
    existing_exclusions: set[str],
    existing_specs: set[str],
    existing_non_specs: Optional[set[str]] = None,
    nested: Optional[TallyConfig] = None,
    root_auto_spec: bool = False,
    inherited: Optional[TallyConfig] = None,
    exclude_patterns: Optional[GitIgnoreSpec] = None,
) -> Optional[SetupResult]:
    """Launch the TUI setup app.

    Returns the (excluded_dirs, spec_dirs, non_spec_dirs) to save at the scan root, or None if the user
    quit without saving. Settings from parent and nested configs are never included: those files keep them.
    """
    app = SetupApp(
        root,
        gitignore_spec,
        existing_exclusions,
        existing_specs,
        existing_non_specs,
        nested,
        root_auto_spec,
        inherited,
        exclude_patterns,
    )
    return app.run()
