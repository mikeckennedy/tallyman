# Phase 2: TUI S Key  -  Interactive Spec Directory Designation

## Goal

Add the S key to the Textual TUI so users can designate directories as specification directories. After this phase, the TUI shows spec status alongside include/exclude status, auto-detected spec dirs are visually indicated, and user choices are persisted alongside exclusions.

## Directory States

Each directory node now has one of four possible states:

| State | Set by | Visual | Toggleable |
|-------|--------|--------|------------|
| Included | Default | `[green]✓[/green] name` | X → Excluded, S → Spec |
| Excluded | User (X key) | `[red]✗[/red] [dim]name[/dim]` | X → Included |
| Spec (user) | User (S key) | `[bright_cyan]S[/bright_cyan] name` | S → Included, X → Excluded |
| Spec (auto) | Name detection | `[bright_cyan]S[/bright_cyan] [dim]name (specs)[/dim]` | Not toggleable via S |
| Gitignored | .gitignore | `[dim]name (gitignored)[/dim]` | Not toggleable |

**State transitions:**

```
         X            S
Included ──→ Excluded    Included ──→ Spec
Excluded ──→ Included    Spec     ──→ Included
Spec     ──→ Excluded    Excluded ──→ (no effect)
```

Pressing S on an excluded directory does nothing  -  the user must first un-exclude it (press X) before marking it as spec. This avoids confusing "is it excluded or is it a spec?" ambiguity.

Pressing X on a spec directory excludes it (removes spec status). The directory is now fully skipped.

Auto-detected spec directories (named `specs`, `specifications`, `plans`) cannot be toggled via S. They are always spec directories. They CAN be excluded via X (which takes precedence  -  if you exclude it, nothing is counted regardless of spec status).

## Steps

### 2.1  -  Update Node Data Model

Add a `'spec'` boolean and an `'auto_spec'` boolean to each tree node's data dict:

```python
data={
    'path': child_rel,
    'gitignored': is_gitignored,
    'excluded': is_excluded,
    'spec': is_spec,           # User-designated spec directory
    'auto_spec': is_auto_spec, # Auto-detected by directory name
}
```

During `_populate`, detect auto-spec directories:

```python
SPEC_DIR_NAMES: frozenset[str] = frozenset({'specs', 'specifications', 'plans'})

# In _populate:
is_auto_spec = entry.name.lower() in SPEC_DIR_NAMES and not is_gitignored
is_spec = child_rel in self.user_spec_dirs or is_auto_spec
```

### 2.2  -  Update SetupApp Constructor

Accept and track spec dirs alongside exclusions:

```python
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
```

### 2.3  -  Add S Key Binding

```python
BINDINGS = [
    Binding('x', 'toggle_node', 'Toggle include/exclude', show=True),
    Binding('s', 'toggle_spec', 'Toggle spec directory', show=True),
    Binding('left', 'collapse_node', 'Collapse', show=False),
    Binding('right', 'expand_node', 'Expand', show=False),
]
```

Update the instructions text:

```python
yield Static(
    'Use [bold]←/→[/bold] to expand/collapse, '
    '[bold]x[/bold] to toggle include/exclude, '
    '[bold]s[/bold] to toggle spec directory.',
    id='instructions',
)
```

### 2.4  -  Implement `action_toggle_spec`

```python
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

    # Can't toggle auto-detected spec dirs
    if node.data['auto_spec']:
        return

    new_state = not node.data['spec']
    self._set_spec(node, new_state)
```

### 2.5  -  Implement `_set_spec` with Cascading

Mirror the `_set_excluded` pattern  -  when a directory is marked as spec, all its children cascade:

```python
def _set_spec(self, node: TreeNode[dict[str, object]], spec: bool) -> None:
    """Set spec state on a node and cascade to all children."""
    node.data['spec'] = spec
    rel_path = str(node.data['path'])

    if spec:
        self.user_spec_dirs.add(rel_path)
    else:
        self.user_spec_dirs.discard(rel_path)

    # Update label
    name = Path(rel_path).name if rel_path else self.root.name
    gitignored = bool(node.data['gitignored'])
    excluded = bool(node.data['excluded'])
    auto_spec = bool(node.data['auto_spec'])
    node.set_label(self._make_label(name, gitignored, excluded, spec, auto_spec))

    # Cascade to children
    for child in node.children:
        if child.data and not child.data['gitignored'] and not child.data['auto_spec']:
            self._set_spec(child, spec)
```

### 2.6  -  Update `_make_label` for Spec States

Extend the label builder to handle spec states:

```python
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
```

**Priority order:** gitignored > excluded > auto_spec > user spec > included. This matches the existing pattern where gitignored takes highest visual priority.

### 2.7  -  Update `_set_excluded` to Clear Spec Status

When a directory is excluded, any spec status should be cleared:

```python
def _set_excluded(self, node: TreeNode[dict[str, object]], excluded: bool) -> None:
    """Set excluded state on a node and cascade to all children."""
    node.data['excluded'] = excluded
    rel_path = str(node.data['path'])

    if excluded:
        self.user_excluded.add(rel_path)
        # Clear spec status when excluding
        node.data['spec'] = False
        self.user_spec_dirs.discard(rel_path)
    else:
        self.user_excluded.discard(rel_path)

    # Update label
    name = Path(rel_path).name if rel_path else self.root.name
    gitignored = bool(node.data['gitignored'])
    auto_spec = bool(node.data['auto_spec'])
    spec = bool(node.data['spec'])
    node.set_label(self._make_label(name, gitignored, excluded, spec, auto_spec))

    # Cascade to children
    for child in node.children:
        if child.data and not child.data['gitignored']:
            self._set_excluded(child, excluded)
```

### 2.8  -  Update `_make_label` Call Sites

All existing calls to `_make_label` pass only 3 arguments. Update them to pass the new `spec` and `auto_spec` parameters. This affects:

- `_populate` (line 95 in current code)
- `_set_excluded` (line 173 in current code)
- `action_toggle_node` path through `_set_excluded`

### 2.9  -  Update Save and Return

The TUI currently returns `set[str] | None` (excluded dirs). Change it to return both sets:

```python
class SetupApp(App[tuple[set[str], set[str]] | None]):
    """First-run setup: choose which directories to include/exclude and designate specs."""

    # ...

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'save':
            cleaned_excluded = self._clean_exclusions(self.user_excluded)
            cleaned_specs = self._clean_exclusions(self.user_spec_dirs)
            self.exit((cleaned_excluded, cleaned_specs))
        elif event.button.id == 'cancel':
            self.exit(None)
```

The `_clean_exclusions` method works for spec dirs too  -  if a parent is marked as spec, children don't need separate entries (the walker cascades spec status).

### 2.10  -  Update `run_setup` Signature

```python
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
```

### 2.11  -  Update CLI Integration (`cli.py`)

Wire the new TUI return type into the CLI flow:

```python
if existing_config and not args.setup:
    config = load_config(existing_config)
    excluded_dirs = config.excluded_dirs
    spec_dirs = config.spec_dirs
else:
    existing = load_config(existing_config) if existing_config else TallyConfig(set(), set())
    result = run_setup(root, gitignore_spec, existing.excluded_dirs, existing.spec_dirs)
    if result is None:
        print('Setup cancelled.')
        sys.exit(0)
    excluded_dirs, spec_dirs = result
    save_config(config_path, excluded_dirs, spec_dirs)

# Walk and count
for file_path, language in walk_project(root, excluded_dirs, gitignore_spec, spec_dirs):
    counts = count_lines(file_path, language)
    file_results.append((language, counts))
```

## Acceptance Criteria

- [ ] S key binding appears in footer alongside X
- [ ] Instructions text mentions S key
- [ ] Pressing S on an included directory marks it as spec with cyan `S` indicator
- [ ] Pressing S again on a spec directory returns it to included (green `✓`)
- [ ] Pressing S on an excluded directory does nothing
- [ ] Pressing S on a gitignored directory does nothing
- [ ] Pressing S on an auto-detected spec directory does nothing
- [ ] Pressing X on a spec directory excludes it and clears spec status
- [ ] Auto-detected spec dirs (`specs`, `specifications`, `plans`) show as `S name (specs)`
- [ ] Spec status cascades to all children when toggled
- [ ] Save & Run returns both excluded and spec dir sets
- [ ] `_clean_exclusions` deduplicates spec dirs (parent covers children)
- [ ] Config file saves both `[exclude]` and `[specs]` sections
- [ ] Existing configs without `[specs]` continue to work
