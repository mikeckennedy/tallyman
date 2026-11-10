# Phase 2 - `[exclude] patterns`

Covers decisions 3-8 from `00-plan-introduction.plan.md`.

## Goal

`.tally-config.toml` accepts a gitignore-style pattern list. Patterns are matched relative to the config that declares them, layer like nested `.gitignore` files, and survive `--setup`. The TUI shows what they exclude.

```toml
[exclude]
directories = ["vendor"]
# Gitignore-style patterns, relative to this file's directory
patterns = [
    "tests.rs",
    "testing.rs",
    "!src/keep/tests.rs",
]
```

## Changes

### `config.py`

- `TallyConfig` gains `patterns: list[str]` (default empty). It holds raw lines in file order, relative to that config's own directory.
- `load_config()` reads `exclude.patterns` and validates it as a list of strings, with the same `ConfigError` message style as `_directories`. Patterns are **not** normalised: gitignore syntax gives a leading `/`, a trailing `/` and `\` their meaning, and the matcher already handles blanks and `#` comments.
- Patterns never go through `rebase_config()`, `prefixed()` or `merge_configs()`. Those return `patterns=[]`, because patterns stay attached to the file they came from. Say so in their docstrings.
- `ConfigChain` (phase 1) carries the pattern layers it loaded: `pattern_layers: list[tuple[Path, list[str]]]`, one per config in the chain that has patterns, shallowest first.
- `discover_nested_configs()` also returns the nested configs' pattern layers, as `(rel_dir, patterns)`. Change its return type to a small dataclass, or return them alongside.
- `save_config()` takes `patterns: Sequence[str] = ()` and writes them after `directories` in `[exclude]`, in order, each through `_toml_string()`, under the comment line shown above. The key is omitted when the list is empty.

### `gitignore.py`

Config patterns use a **second** `GitIgnoreSpec` instance, so gitignore and patterns never interact (decision 5). Add:

- `GitIgnoreSpec.for_patterns(root) -> GitIgnoreSpec`: an empty spec bound to *root* with the same prefix as `for_root()` (the scan root relative to the git root, or `''` outside a repo). It registers no files and never sets `_ignore_all`. Patterns from ancestor configs therefore can't exclude the scan root or anything above it (decision 7).
- `add_rules(config_dir: Path, lines: list[str])`: register lines as one layer scoped to *config_dir*, which must be the scan root, an ancestor inside the git root, or a descendant. Compute the git-root-relative base from it. Deduplicate on `(base, CONFIG_FILENAME)` like `_add_file` does, so the walker and the TUI can both register the same nested config. To avoid importing `config` from `gitignore`, take the dedupe key as a parameter or use a fixed tag such as `'<config>'`.

Precedence then comes for free: layers sort shallowest first, and the deepest layer with an opinion wins, so a nested config's `!tests.rs` beats a parent's `tests.rs` (decision 4).

### `walker.py`

`walk_project()` takes `exclude_patterns: Optional[GitIgnoreSpec] = None` and `stats: Optional[WalkStats] = None`.

- `WalkStats` is a small mutable dataclass with `pattern_files: int = 0` and `pattern_dirs: int = 0`. Phase 3 displays it; it lives here so the walker can fill it.
- When a nested config is loaded on entering a directory, register its patterns with `exclude_patterns.add_rules(dirpath, ...)` **before** filtering that directory's children, at the same point as `gitignore_spec.add_directory()`.
- Directories: after the existing hidden, config-excluded and gitignore checks, a child matching `exclude_patterns.match_file(child_rel + '/')` is pruned, and `stats.pattern_dirs` goes up by one.
- Files: after the existing gitignore, generated and symlink checks, check the pattern. A matching file is skipped. It increments `stats.pattern_files` only if `identify_language()` recognises it and `_is_binary()` is false. That keeps the count to files that would otherwise have been counted, and the binary read happens only for matched files.

### `cli.py`

- Build `exclude_patterns = GitIgnoreSpec.for_patterns(root)` and register `chain.pattern_layers`, shallowest first.
- Normal run: pass it to `walk_project()`.
- `--setup`:
  - Also register the nested configs' pattern layers from `discover_nested_configs()`, so the TUI sees them.
  - Pass the spec to the TUI.
  - Save with `patterns=chain.local.patterns`, unchanged and in order (decision 8). If the scan-root config was malformed and skipped, there are no patterns to keep; today's warning already says a new config will be written.
  - Then pass the same spec to the walker. Registration is idempotent.

### `tui/setup_app.py`

- `SetupApp` / `run_setup()` take `exclude_patterns: Optional[GitIgnoreSpec] = None`.
- `NodeInfo` gains `pattern_excluded: bool`. In `_populate()`, set it from `exclude_patterns.match_file(child_rel + '/')`, and don't recurse into a pattern-excluded directory, as with gitignored ones, since the walker never enters it.
- Label: `[dim]name (excluded by pattern)[/dim]`. The node is locked: `_cursor()` returns None for it, like a gitignored node.
- `_derive()` treats `pattern_excluded` like `gitignored` for `excluded`.
- The TUI does not edit patterns. The instructions line doesn't change.

## Tests

`tests/test_config.py`:

- `exclude.patterns` loads in order. A non-list or a non-string item raises `ConfigError`.
- Round trip: `save_config(..., patterns=[...])` then `load_config()` gives the same list, in order, including `!`, leading `/`, a `"` and a `\`.
- `rebase_config()` and `merge_configs()` return no patterns.

`tests/test_gitignore.py`:

- `for_patterns()` and `add_rules()` at the scan root: `tests.rs` matches at any depth, `/tests.rs` only at the top, `fixtures/` only directories.
- An ancestor layer: anchored patterns resolve relative to the ancestor, and nothing ever matches the scan root.
- A deeper layer's `!tests.rs` re-includes over a shallower `tests.rs`.
- Registering the same config directory twice is a no-op.

`tests/test_walker.py`:

- The Rust case: `src/routing.rs` is counted and `src/routing/tests.rs` is not.
- A pattern can't re-include a gitignored file or a config-excluded directory (`!` in patterns, entry excluded elsewhere).
- A nested config's patterns apply only beneath it and can `!` a parent's pattern.
- `WalkStats`: counts a matched `.rs` file, ignores a matched unrecognised `.xyz` file, and counts a pruned directory once without counting its files.

`tests/test_cli.py`:

- **`--setup` keeps hand-written patterns** in order and byte-for-byte in the rewritten file. This is the regression test for the biggest risk in this plan.
- A parent config's patterns apply when scanning a subdirectory, anchored to the parent's directory.
- A parent pattern that matches the scan root's own name doesn't empty the scan.

`tests/test_setup_app.py`: a directory matched by `fixtures/` is labelled `(excluded by pattern)`, `x` does nothing on it, and its children aren't listed.

## Done when

- The Rust case from issue #6 behaves as described.
- `--setup` round-trips a config with patterns unchanged.
- All checks in the introduction's rules are clean.
