"""Textual TUI for first-run directory selection setup."""

from __future__ import annotations

from pathlib import Path

import pathspec
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode


class SetupTree(Tree[dict[str, object]]):
    """Tree subclass for tallyman setup."""


class SetupApp(App[set[str] | None]):
    """First-run setup: choose which directories to include in tallyman counts."""

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
        Binding('left', 'collapse_node', 'Collapse', show=False),
        Binding('right', 'expand_node', 'Expand', show=False),
    ]

    def __init__(
        self,
        root: Path,
        gitignore_spec: pathspec.PathSpec,
        existing_exclusions: set[str],
    ) -> None:
        super().__init__()
        self.root = root
        self.title = f'Setup Tallyman for {root.name}'
        self.gitignore_spec = gitignore_spec
        self.user_excluded: set[str] = set(existing_exclusions)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            'Use [bold]←/→[/bold] to expand/collapse, '
            '[bold]x[/bold] to toggle directories.',
            id='instructions',
        )
        tree: SetupTree = SetupTree(self.root.name)
        tree.root.data = {'path': '', 'gitignored': False, 'excluded': False}
        self._populate(tree.root, self.root, '')
        tree.root.expand_all()
        tree.show_root = True
        yield tree
        with Horizontal(id='buttons'):
            yield Button('Save & Run', id='save', variant='primary')
            yield Button('Cancel', id='cancel')
        yield Footer()

    def _populate(self, parent_node: TreeNode[dict[str, object]], dir_path: Path, rel_path: str) -> None:
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

            label = self._make_label(entry.name, is_gitignored, is_excluded)
            node = parent_node.add(
                label,
                data={
                    'path': child_rel,
                    'gitignored': is_gitignored,
                    'excluded': is_excluded,
                },
            )

            # Don't recurse into gitignored dirs
            if not is_gitignored:
                self._populate(node, entry, child_rel)

    @staticmethod
    def _make_label(name: str, gitignored: bool, excluded: bool) -> str:
        if gitignored:
            return f'[dim]{name} (gitignored)[/dim]'
        if excluded:
            return f'[red]✗[/red] [dim]{name}[/dim]'
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
        else:
            self.user_excluded.discard(rel_path)

        # Update label
        name = Path(rel_path).name if rel_path else self.root.name
        gitignored = bool(node.data['gitignored'])  # type: ignore[index]
        node.set_label(self._make_label(name, gitignored, excluded))

        # Cascade to children
        for child in node.children:
            if child.data and not child.data['gitignored']:
                self._set_excluded(child, excluded)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'save':
            cleaned = self._clean_exclusions(self.user_excluded)
            self.exit(cleaned)
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
    gitignore_spec: pathspec.PathSpec,
    existing_exclusions: set[str],
) -> set[str] | None:
    """Launch the TUI setup app.

    Returns the set of excluded directory paths, or None if the user quit without saving.
    """
    app = SetupApp(root, gitignore_spec, existing_exclusions)
    return app.run()
