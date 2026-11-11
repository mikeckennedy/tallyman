# Phase 1 - Type Hints

Covers decisions 1 to 4 from `00-plan-introduction.plan.md`, and records plan 006, step 4 as done.

## Goal

No `X | None` anywhere in `src/` or `tests/`. Every function signature, test functions included, is fully annotated. Ruff, Pyrefly and one new test keep it that way.

Set a scratch variable first and take the before report (see the introduction's rules); every scratch file in this phase goes there, never in the repo:

```bash
SCRATCH=<the session scratchpad directory>
rm -rf "$SCRATCH/snapshot" && mkdir "$SCRATCH/snapshot" && git archive HEAD | tar -x -C "$SCRATCH/snapshot"
venv/bin/tallyman --no-color "$SCRATCH/snapshot" > "$SCRATCH/report-before.txt" 2>&1
```

## Step 1 - The `Optional` test, then the sweep

### `tests/test_conventions.py` (new)

Write the test first and watch it fail, listing every site. This was tried on a copy of the repo: it reports exactly the 7 sites at 75dd0fd, and 0 after the sweep.

```python
"""Code conventions that no linter enforces: CLAUDE.md's `Optional[X]` rule."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_union_name(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == 'Union') or (
        isinstance(node, ast.Attribute) and node.attr == 'Union'
    )


def _none_unions(annotation: ast.expr) -> list[int]:
    """Lines of each `X | None`, `None | X` or `Union[X, None]` in *annotation*, nested or quoted."""
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode='eval').body
        except SyntaxError:
            return []
    lines: list[int] = []
    for node in ast.walk(annotation):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if _is_none(node.left) or _is_none(node.right):
                lines.append(node.lineno)
        elif isinstance(node, ast.Subscript) and _is_union_name(node.value):
            members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if any(_is_none(m) for m in members):
                lines.append(node.lineno)
    return lines


def _annotations(tree: ast.AST) -> list[ast.expr]:
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if arg is not None and arg.annotation is not None:
                    found.append(arg.annotation)
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    return found


def test_optional_not_pipe_none() -> None:
    """CLAUDE.md: `Optional[X]` from `typing`, never `X | None` (Ruff's UP045 would enforce the opposite)."""
    hits: list[str] = []
    for path in sorted([*(ROOT / 'src').rglob('*.py'), *(ROOT / 'tests').rglob('*.py')]):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for annotation in _annotations(tree):
            hits += [f'{path.relative_to(ROOT).as_posix()}:{line}' for line in _none_unions(annotation)]
    assert hits == [], 'use Optional[X], not X | None:\n' + '\n'.join(hits)
```

Notes:

- It reads annotations only: parameters, returns and annotated assignments, at any nesting (`list[tuple[Optional[Language], float]]`). Runtime uses such as `isinstance(x, int | None)` are not annotations and are left alone.
- With `from __future__ import annotations` the annotations are still ordinary AST nodes. A wholly quoted annotation (`'X | None'`) is parsed too.
- If a later plan adds a `type X = ...` alias or a `TypeAlias` assignment with `| None`, extend `_annotations()`; there are none today.

### The sweep

Run `pytest tests/test_conventions.py` and convert every site it lists. Cross-check with a grep (it also matches the new test's own docstrings and message, which are fine):

```bash
grep -rnE '\|\s*None\b|\bNone\s*\|' src/ tests/ | grep -v '^tests/test_conventions.py'
grep -rnE 'Union\[[^]]*None' src/ tests/
```

For each site: `X | None` becomes `Optional[X]`, and the module imports `Optional` from `typing` if it doesn't already. At 75dd0fd, `walker.py`, `display.py` and `languages.py` already import it; `image.py` needs it added to `from typing import TYPE_CHECKING, Union`; `tests/test_aggregator.py` and `tests/test_counter.py` need `from typing import Optional`. Let `ruff check --fix` sort the imports.

Confirm `ruff.toml` still has no `UP` in `lint.select`. Leave a one-line comment there saying why (below).

## Step 2 - Ruff's `ANN` rules and `-> None` everywhere

### `ruff.toml`

```toml
# pycodestyle errors (E) and warnings (W), Pyflakes (F), isort (I), annotations (ANN), tests included.
# No UP: UP045 rewrites Optional[X] to X | None, the opposite of CLAUDE.md; tests/test_conventions.py enforces Optional.
lint.select = ["E", "F", "W", "I", "ANN"]
```

No `per-file-ignores` for tests: Michael wants `-> None` on every test function, and fixtures and helpers are already annotated. Then measure:

```bash
ruff check --statistics src/ tests/
```

Expect `ANN201` for every test function that lacks `-> None` (330 at 75dd0fd, more after plans 008 to 011), the 15 `ANN001` arguments and the `ANN202` on `_load_font()`, plus whatever plans 008 to 011 added.

### Test functions: the scripted fix

Ruff can't infer return types in general, but for a function with no `return` value its unsafe fix adds `-> None`, which is what every test function needs. Keep a copy of `tests/` to check against, and scope the fix to `tests/` and the two return-type rules only:

```bash
rm -rf "$SCRATCH/tests-before" && cp -R tests "$SCRATCH/tests-before"
ruff check --select ANN201,ANN202 --unsafe-fixes --fix tests/
```

Then prove the fix only added `-> None`. Save this to `$SCRATCH/only_none_added.py` (not in the repo) and run it **before any hand edits** in this step:

```python
"""Usage: python only_none_added.py OLD_TESTS_DIR NEW_TESTS_DIR. Passes when NEW differs from OLD only by `-> None`."""

import ast
import sys
from pathlib import Path

old_root, new_root = Path(sys.argv[1]), Path(sys.argv[2])
added = 0
for new in sorted(new_root.rglob('*.py')):
    old = old_root / new.relative_to(new_root)
    a, b = ast.parse(old.read_text()), ast.parse(new.read_text())
    fa = [n for n in ast.walk(a) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    fb = [n for n in ast.walk(b) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(fa) == len(fb), new
    for x, y in zip(fa, fb):
        if x.returns is None and y.returns is not None:
            assert isinstance(y.returns, ast.Constant) and y.returns.value is None, f'{new}:{y.lineno} got a non-None type'
            y.returns = None
            added += 1
    assert ast.dump(a) == ast.dump(b), f'{new}: more than -> None changed'
print(f'OK: only -> None added, {added} functions')
```

```bash
python "$SCRATCH/only_none_added.py" "$SCRATCH/tests-before" tests
```

The count it prints must equal the `ANN201` + `ANN202` count Ruff reported for `tests/`. If it reports a non-`None` type, a function returns a value (a helper someone forgot to annotate, probably from plans 008 to 011): revert that line and annotate it by hand with its real type. Because the check compares ASTs, it doesn't care about the line wrapping `ruff format` does next.

### By hand

- `tests/test_image.py`: annotate `tmp_path: Path` and `monkeypatch: pytest.MonkeyPatch` (add `import pytest`; `Path` is already imported).
- `tests/test_gitignore.py`, the nested `collect(node)`: `node: TreeNode[NodeInfo]`. Import `TreeNode` from `textual.widgets.tree` and add `NodeInfo` to the `tallyman.tui.setup_app` import, as `tests/test_setup_app.py` does. (A test module importing Textual is fine even after plan 011 makes the CLI's import lazy; this module already imports `SetupApp`.)
- `src/tallyman/image.py`, `_load_font()`: `-> Union[FreeTypeFont, ImageFont]`, the type `_fit_text()` already takes. `ImageFont.truetype()` returns `FreeTypeFont` and `load_default()` returns either. With `from __future__ import annotations` the annotation resolves to the `TYPE_CHECKING` import of the class, not the `PIL.ImageFont` module imported inside the function; ty and Pyrefly both accepted this on the trial copy.
- Anything else `ruff check --select ANN src/ tests/` still reports.

Then:

```bash
ruff check --fix src/ tests/     # import order
ruff format src/ tests/          # wraps the signatures that grew past 120 characters (8 at 75dd0fd)
ruff check src/ tests/           # now includes ANN: must be clean
```

## Step 3 - The Pyrefly warnings

- `tests/test_setup_app.py`, in `_record()` (lines 91 and 93 at 75dd0fd; after plan 011, find it with `uvx pyrefly check --min-severity=warn`): `path = node.data.path` and `self.flags[path] = node.data.spec`. Both fields are already `str` and `bool`. Leave `str(node.label)` alone; the label is a `Text`, so that `str()` is needed.
- `pyrefly.toml`, `[errors]`: replace the "empty table" comment and add the kind, so a new redundant conversion fails `uvx pyrefly check`:

```toml
[errors]
# all errors are on by default; this promotes a warning that would otherwise only show with --min-severity=warn
unnecessary-type-conversion = "error"
```

Prove it bites: with the setting in place and before the two edits, `uvx pyrefly check` exits 1 with 2 errors (checked on a copy of the repo with Pyrefly 1.4.1). After the edits, `uvx pyrefly check --min-severity=warn` ends with `0 diagnostics (1 suppressed)`. The suppressed one is the deliberate `# type: ignore` in `tests/test_languages.py`.

## Step 4 - Docs for the new rules

### `CLAUDE.md`

- Code Conventions:
  - "Type hints on all function signatures" becomes "Type hints on all function signatures, including `-> None` on every test (Ruff's `ANN` rules)".
  - "Use `Optional[X]` from `typing` for optional types, not `X | None`" gains "(`tests/test_conventions.py` checks it; Ruff's `UP` rules stay off because `UP045` enforces the opposite)".
- Test Structure: add a row, `tests/test_conventions.py | 1 | Code conventions no linter checks: Optional[X], not X | None`. Phase 2 recounts the rest.

### The persona, and its copy in plan 006

Edit `.claude/agents/architect-tallyman.md`, then make the same edits in the copy in `plans/006-tallyman-architect.plan.md`:

- The Never rule on `X | None`: add "`tests/test_conventions.py` fails on any."
- Tech stack, Dev tooling: "rules `E`, `F`, `W`, `I`" becomes "rules `E`, `F`, `W`, `I`, `ANN`", and add that Pyrefly promotes `unnecessary-type-conversion` to an error.

Leave the `match` wording for phase 2. Check the copy with the `diff` command in the introduction.

### Plan 006

- Status: "Step 4: deferred (decision 5)" becomes "Step 4: done in plan 012, phase 1, after Michael chose in the 2026-11-10 architect review to do the sweep now. `tests/test_conventions.py` now enforces it, and Ruff's `UP` rules are still off."
- Decision 5: append "Superseded for step 4 on 2026-11-10: the sweep is plan 012, phase 1."
- Done when: the third bullet is now met; no change to its wording.

## Tests

- `tests/test_conventions.py::test_optional_not_pipe_none`: fails before step 1's sweep, listing each site; passes after.
- No other new tests. The `ANN` rules and the Pyrefly setting are the enforcement, and each was shown to fail on the old code.

## Done when

- `pytest tests/test_conventions.py` passes, and fails if any `X | None` is put back (try one, then revert).
- `ruff check src/ tests/` is clean with `ANN` selected. That is the proof every test has `-> None`; a line grep for `def test_` misses the signatures `ruff format` wrapped.
- `only_none_added.py` reported the same number of functions Ruff reported as fixable.
- `uvx pyrefly check --min-severity=warn` shows no warnings.
- `venv/bin/tallyman --no-color "$SCRATCH/snapshot" 2>&1 | diff "$SCRATCH/report-before.txt" -` prints nothing.
- `CLAUDE.md`, the persona and plan 006 describe the new rules, and the persona's copy matches.
- All checks in the introduction's rules are clean.
