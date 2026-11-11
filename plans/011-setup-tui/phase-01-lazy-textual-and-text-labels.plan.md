# Phase 1 - Lazy Textual Import and `Text` Labels

Covers decisions 1 and 5 from `00-plan-introduction.plan.md` (review item 11 and the "Textual imported on every plain run" concern).

## Goal

A plain `tallyman` run never imports Textual. Setup shows every directory name exactly as it is on disk, including `:rocket:`, `foo\` and `[tag]`.

## Lazy Textual import

### `src/tallyman/cli.py`

- Remove the module-level `from tallyman.tui.setup_app import run_setup`.
- Add a module-level wrapper with the **same name**, so `tests/test_cli.py`'s `monkeypatch.setattr(cli, 'run_setup', fake_setup)` keeps working unchanged:

  ```python
  if TYPE_CHECKING:
      from tallyman.tui.setup_app import SetupResult


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
      """Launch the setup TUI. Textual is imported here, so a run that doesn't set up never loads it."""
      from tallyman.tui.setup_app import run_setup as launch

      return launch(root, gitignore_spec, ...)  # pass every argument through by name
  ```

  Mirror `tui.setup_app.run_setup()`'s signature exactly, so ty and pyrefly check the call in `main()`. Phase 3 drops `nested` from both.
- Nothing else on the plain path may import `tallyman.tui`. Today nothing does (`grep -rn "tui" src/tallyman/*.py` shows only `cli.py`). Check again after 008-010.
- Expected effect: `python -X importtime -c "import tallyman.cli"` goes from about 78 ms to about 30 ms. Report the measured numbers in the phase review.

### Tests (`tests/test_cli.py`, class `TestRealProcess`)

`test_plain_run_imports_neither_textual_nor_pillow`, parametrized over two trees: one with a `.tally-config.toml` (normal run) and one without (the no-terminal defaults path). Run a real subprocess, as `_run_process` does, with `stdin=subprocess.DEVNULL`:

```python
code = (
    'import sys; from tallyman import cli; sys.argv = ["tallyman", sys.argv[1]]; cli.main(); '
    'print(sorted({m.split(".")[0] for m in sys.modules} & {"textual", "PIL"}), file=sys.stderr)'
)
result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, timeout=60)
```

Assert `result.returncode == 0` and that the last stderr line is `[]`. It has to be a subprocess, because pytest has already imported Textual for the pilot tests. The `PIL` half covers the lazy-Pillow rule in `CLAUDE.md`, which no test checks today.

## `Text` labels

### `src/tallyman/tui/setup_app.py`

- Import `from rich.text import Text`, and drop `from rich.markup import escape`.
- `_make_label()` returns `Text`, built with `Text.assemble()`. Pass the directory name as a plain `str` part or as a `(str, style)` tuple, never through markup. Same wording and styles as today:

  | Case | Today's markup | `Text` |
  |---|---|---|
  | gitignored | `[dim]{name} (gitignored)[/dim]` | `Text(f'{name} (gitignored)', style='dim')` |
  | pattern | `[dim]{name} (excluded by pattern)[/dim]` | `Text(f'{name} (excluded by pattern)', style='dim')` |
  | excluded | `[red]✗[/red] [dim]{name}[/dim]` | `Text.assemble(('✗', 'red'), ' ', (name, 'dim'))` |
  | auto spec | `[bright_cyan]S[/bright_cyan] [dim]{name} (specs)[/dim]` | `Text.assemble(('S', 'bright_cyan'), ' ', (f'{name} (specs)', 'dim'))` |
  | spec | `[bright_cyan]S[/bright_cyan] {name}` | `Text.assemble(('S', 'bright_cyan'), ' ', name)` |
  | not spec | `[green]✓[/green] {name} [dim](not specs)[/dim]` | `Text.assemble(('✓', 'green'), ' ', name, ' ', ('(not specs)', 'dim'))` |
  | plain | `[green]✓[/green] {name}` | `Text.assemble(('✓', 'green'), ' ', name)` |

- `_label_for()` returns `Text`. The root label is `Text(self.root.name)`, plus `(' (specs)', 'dim')` when the root is specs. The lock suffix is `label.append(f' (set in a {info.locked_by} config)', style='dim')`.
- `compose()`: `SetupTree(Text(self.root.name))`.
- Plain text stays byte-for-byte what it is today for ordinary names, so every existing label assertion (they compare `str(node.label)`, which is `Text.plain`) passes unchanged.
- Known limit, out of scope: Textual's `Tree.process_label()` keeps only the first line of a label, so a directory name containing a newline (legal on Linux and macOS) is cut short. Note it in a comment; don't fix it here.

### Tests (`tests/test_setup_app.py`)

Extend `Session._record()` to keep the label objects too (`self.texts: dict[str, Text]`, plus `self.root_text`). Plan 010 adds `self.excluded` to the same method; keep both.

In `TestLabels`:

- `test_emoji_codes_are_shown_literally`: directory `:rocket:` is labelled `✓ :rocket:`.
- `test_trailing_backslash_is_not_doubled` (`skipif(os.name == 'nt')`, since `\` is a separator there): directory `foo\` is labelled `✓ foo\`. Directory `baz\` with `inherited=TallyConfig(spec_dirs={'baz\\'})` is labelled `S baz\ (set in a parent config)`, which is the "text follows the name" case that doubles today.
- `test_markup_like_names_are_shown_literally`: `[b]x`, `a\[b]`, `x[`, `]`. Keep the existing `test_directory_names_are_not_read_as_markup` as is.
- `test_root_name_is_shown_literally`: scan roots `tmp_path / ':rocket:'` and `tmp_path / '[bold]x'` give `root_label` equal to the name.
- `test_label_styles`: one excluded and one spec directory. `[(t.plain[s.start:s.end], str(s.style)) for s in t.spans]` includes `('✗', 'red')` and `('S', 'bright_cyan')`. This guards against labels turning into plain strings (which would lose colour) or markup (which would bring the bug back).

## Docs

- `CLAUDE.md`, Tech Stack: `textual` - TUI framework for the setup wizard, imported only when setup runs. Module map, `cli.py` row: add "imports the setup TUI only when it runs".
- Architect persona, both copies (`.claude/agents/architect-tallyman.md` line 90, `plans/006-tallyman-architect.plan.md` line 140 at 75dd0fd): "Rich and Textual are already loaded on every run" becomes "Rich loads on every run; Textual only when setup runs (`cli.run_setup()` imports it). Don't add heavy module-level imports to the CLI path."
- `change-log.md` under `0.4.3 - UNRELEASED`:
  - `### Changed`: a plain run no longer imports Textual, which roughly halves start-up time (import of `tallyman.cli` about 78 ms to about 30 ms).
  - `### Fixed`: setup shows directory names literally. `:rocket:` no longer turns into an emoji, and a trailing backslash is no longer doubled, in the tree and on the root.
  - `Files:` and `Plan:` lines.
- `CLAUDE.md` test table: `test_cli.py` and `test_setup_app.py` counts, and the Quick Reference total.

## Done when

- The new subprocess test passes. Removing the lazy import, or adding a top-level `import textual` anywhere on the plain path, fails it.
- The label tests pass. On 75dd0fd's `setup_app.py`, the emoji, backslash and root tests fail.
- All checks in the introduction's rules are clean.
