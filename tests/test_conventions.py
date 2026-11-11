"""Code conventions that no linter enforces: CLAUDE.md's `Optional[X]` rule."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_name(node: ast.expr, name: str) -> bool:
    """*node* is `name` or `<module>.name` (`Union`, `typing.Union`)."""
    return (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name)


def _parse_quoted(text: str) -> Optional[ast.expr]:
    """A quoted annotation as an expression, or None if it isn't one."""
    try:
        return ast.parse(text.strip(), mode='eval').body
    except SyntaxError:  # IndentationError is a SyntaxError too
        return None


def _none_unions(annotation: ast.expr, quoted_line: Optional[int] = None) -> list[int]:
    """Lines of each `X | None`, `None | X` or `Union[X, None]` in *annotation*, nested or quoted.

    A quoted part (`'X | None'`, `list['X | None']`) is parsed and checked too, and reported at the string's line,
    since its own nodes count lines from 1. Strings in `Literal[...]` and `Annotated[...]` metadata are values, not
    types, so they are skipped.
    """
    lines: list[int] = []
    stack: list[ast.AST] = [annotation]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parsed = _parse_quoted(node.value)
            if parsed is not None:
                lines += _none_unions(parsed, quoted_line or node.lineno)
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if _is_none(node.left) or _is_none(node.right):
                lines.append(quoted_line or node.lineno)
        elif isinstance(node, ast.Subscript):
            if _is_name(node.value, 'Literal'):
                continue
            members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if _is_name(node.value, 'Annotated'):
                stack.append(members[0])
                continue
            if _is_name(node.value, 'Union') and any(_is_none(m) for m in members):
                lines.append(quoted_line or node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return sorted(lines)


def _type_param_exprs(type_params: list[ast.type_param]) -> list[ast.expr]:
    """PEP 695 bounds and defaults: `def f[T: X | None]`, `class C[T = X | None]`."""
    found: list[ast.expr] = []
    for param in type_params:
        if isinstance(param, ast.TypeVar) and param.bound is not None:
            found.append(param.bound)
        if isinstance(param, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple)) and param.default_value is not None:
            found.append(param.default_value)
    return found


def _annotations(tree: ast.AST) -> list[ast.expr]:
    """Every annotation in *tree*: parameters, returns, annotated assignments, `type` statements, type parameters.

    `X: TypeAlias = ...`, plain alias assignments and `cast()` arguments are expressions, not annotations, and are
    left alone, as are runtime unions such as `isinstance(x, int | None)`.
    """
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if arg is not None and arg.annotation is not None:
                    found.append(arg.annotation)
            if node.returns is not None:
                found.append(node.returns)
            found += _type_param_exprs(node.type_params)
        elif isinstance(node, ast.ClassDef):
            found += _type_param_exprs(node.type_params)
        elif isinstance(node, ast.TypeAlias):
            found.append(node.value)
            found += _type_param_exprs(node.type_params)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    return found


def test_optional_not_pipe_none() -> None:
    """CLAUDE.md: `Optional[X]` from `typing`, never `X | None` (Ruff's UP045 would enforce the opposite)."""
    hits: list[str] = []
    for path in sorted([*(ROOT / 'src').rglob('*.py'), *(ROOT / 'tests').rglob('*.py')]):
        tree = ast.parse(path.read_bytes(), filename=str(path))  # BOMs and coding cookies, as Python reads them
        for annotation in _annotations(tree):
            hits += [f'{path.relative_to(ROOT).as_posix()}:{line}' for line in _none_unions(annotation)]
    assert hits == [], 'use Optional[X], not X | None:\n' + '\n'.join(hits)
