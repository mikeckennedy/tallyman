"""Textual TUI for first-run directory selection setup."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from tallyman.walker import SPEC_DIR_NAMES, GitIgnoreSpec


class SetupTree(Tree[dict[str, object]]):
    """Tree subclass for tallyman setup."""


class SetupApp(App[tuple[set[str], set[str]] | None]):
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
    ) -> None:
        super().__init__()
        self.root = root
        self.title = f'Setup Tallyman for {root.name}'
        self.gitignore_spec = gitignore_spec
        self.user_excluded: set[str] = set(existing_exclusions)
        self.user_spec_dirs: set[str] = set(existing_specs)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            'Use [bold]←/→[/bold] to expand/collapse, '
            '[bold]x[/bold] to toggle include/exclude, '
            '[bold]s[/bold] to toggle spec directory.',
            id='instructions',
        )
        tree: SetupTree = SetupTree(self.root.name)
        tree.root.data = {
            'path': '',
            'gitignored': False,
            'excluded': False,
            'spec': False,
            'auto_spec': False,
        }
        self._populate(tree.root, self.root, '')
        tree.root.expand_all()
        if self.user_excluded:
            self._collapse_excluded(tree.root)
        tree.show_root = True
        yield tree
        with Horizontal(id='buttons'):
            yield Button('Save & Run', id='save', variant='primary')
            yield Button('Cancel', id='cancel')
        yield Footer()

    def _populate(
        self,
        parent_node: TreeNode[dict[str, object]],
        dir_path: Path,
        rel_path: str,
        parent_is_spec: bool = False,
    ) -> None:
        """Recursively add subdirectories to the tree."""
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            return

        for entry in entries:
            if not entry.is_dir(follow_symlinks=False) or entry.name.startswith('.'):
                continue

            child_rel = f'{rel_path}/{entry.name}'.lstrip('/')
            is_gitignored = self.gitignore_spec.match_file(child_rel + '/')
            is_excluded = child_rel in self.user_excluded or is_gitignored
            is_auto_spec = entry.name.lower() in SPEC_DIR_NAMES and not is_gitignored
            inherited_spec = parent_is_spec and not is_gitignored
            is_spec = child_rel in self.user_spec_dirs or is_auto_spec or inherited_spec
            show_auto = is_auto_spec or inherited_spec

            label = self._make_label(entry.name, is_gitignored, is_excluded, is_spec, show_auto)
            node = parent_node.add(
                label,
                data={
                    'path': child_rel,
                    'gitignored': is_gitignored,
                    'excluded': is_excluded,
                    'spec': is_spec,
                    'auto_spec': show_auto,
                },
            )

            # Don't recurse into gitignored dirs
            if not is_gitignored:
                self._populate(node, entry, child_rel, parent_is_spec=is_spec)

    @staticmethod
    def _collapse_excluded(node: TreeNode[dict[str, object]]) -> None:
        """Collapse nodes that are excluded so they start folded."""
        for child in node.children:
            if child.data and child.data.get('excluded'):
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
    ) -> str:
        if gitignored:
            return f'[dim]{name} (gitignored)[/dim]'
        if excluded:
            return f'[red]✗[/red] [dim]{name}[/dim]'
        if auto_spec:
            return f'[bright_cyan]S[/bright_cyan] [dim]{name} (specs)[/dim]'
        if spec:
            return f'[bright_cyan]S[/bright_cyan] {name}'
        return f'[green]✓[/green] {name}'

    def action_toggle_node(self) -> None:
        tree = self.query_one(SetupTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        # Can't toggle gitignored dirs
        if node.data['gitignored']:
            return

        new_state = not node.data['excluded']
        self._set_excluded(node, new_state)

    def action_toggle_spec(self) -> None:
        """Toggle spec status on the focused directory."""
        tree = self.query_one(SetupTree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return

        # Can't toggle gitignored dirs
        if node.data['gitignored']:
            return

        # Can't toggle excluded dirs  -  un-exclude first
        if node.data['excluded']:
            return

        new_state = not node.data['spec']
        self._set_spec(node, new_state)

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

    def _set_excluded(self, node: TreeNode[dict[str, object]], excluded: bool) -> None:
        """Set excluded state on a node and cascade to all children."""
        node.data['excluded'] = excluded  # type: ignore[index]
        rel_path = str(node.data['path'])  # type: ignore[index]

        if excluded:
            self.user_excluded.add(rel_path)
            # Clear spec status when excluding
            node.data['spec'] = False  # type: ignore[index]
            self.user_spec_dirs.discard(rel_path)
        else:
            self.user_excluded.discard(rel_path)

        # Update label
        name = Path(rel_path).name if rel_path else self.root.name
        gitignored = bool(node.data['gitignored'])  # type: ignore[index]
        auto_spec = bool(node.data['auto_spec'])  # type: ignore[index]
        spec = bool(node.data['spec'])  # type: ignore[index]
        node.set_label(self._make_label(name, gitignored, excluded, spec, auto_spec))

        # Cascade to children
        for child in node.children:
            if child.data and not child.data['gitignored']:
                self._set_excluded(child, excluded)

    def _set_spec(self, node: TreeNode[dict[str, object]], spec: bool) -> None:
        """Set spec state on a node and cascade to all children."""
        node.data['spec'] = spec  # type: ignore[index]
        if not spec:
            node.data['auto_spec'] = False  # type: ignore[index]
        rel_path = str(node.data['path'])  # type: ignore[index]

        if spec:
            self.user_spec_dirs.add(rel_path)
        else:
            self.user_spec_dirs.discard(rel_path)

        # Update label
        name = Path(rel_path).name if rel_path else self.root.name
        gitignored = bool(node.data['gitignored'])  # type: ignore[index]
        excluded = bool(node.data['excluded'])  # type: ignore[index]
        auto_spec = bool(node.data['auto_spec'])  # type: ignore[index]
        node.set_label(self._make_label(name, gitignored, excluded, spec, auto_spec))

        # Cascade to children
        for child in node.children:
            if child.data and not child.data['gitignored']:
                self._set_spec(child, spec)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'save':
            cleaned_excluded = self._clean_exclusions(self.user_excluded)
            cleaned_specs = self._clean_exclusions(self.user_spec_dirs)
            self.exit((cleaned_excluded, cleaned_specs))
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
) -> tuple[set[str], set[str]] | None:
    """Launch the TUI setup app.

    Returns (excluded_dirs, spec_dirs), or None if the user quit without saving.
    """
    app = SetupApp(root, gitignore_spec, existing_exclusions, existing_specs)
    return app.run()
