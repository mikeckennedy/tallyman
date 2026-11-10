# Phase 1 - Gitignore Correctness

Covers H1, H2 and H15 from `00-plan-introduction.plan.md`.

## Goal

Tallyman ignores exactly the files git would ignore based on `.gitignore` files and `.git/info/exclude`, at every level of the tree, whether the scan root is the git root or a subdirectory of it.

## Current behaviour

`load_gitignore()` in `src/tallyman/walker.py` reads the git-root `.gitignore`, `.git/info/exclude`, and every `.gitignore` between the git root and the scan root. It concatenates all lines into one `pathspec.PathSpec` and matches paths relative to the git root (via the `GitIgnoreSpec` prefix).

Two consequences:

- **H1:** `.gitignore` files in subdirectories of the scan root are never loaded.
- **H2:** patterns from an intermediate `.gitignore` are matched relative to the git root instead of the directory that file lives in. Anchored patterns (`/build`, `a/b`) miss their target or hit the wrong one.

## Reproductions

Turn each of these into a test in `tests/test_walker.py`. Each needs a `.git` directory at the repo root.

| Case | Layout | Scan root | Expected | Today |
|------|--------|-----------|----------|-------|
| Nested ignore | `sub/.gitignore` = `generated/`; `sub/generated/big.py` | repo | `big.py` skipped | counted |
| Self-ignoring dir | `venv2/.gitignore` = `*`; `venv2/lib/x.py` | repo | `x.py` skipped | counted |
| Anchored, intermediate | `sub/.gitignore` = `/build`; `sub/build/out.py`; `sub/sub/build/x.py` | `repo/sub` | `build/out.py` skipped, `sub/build/x.py` counted | both counted |
| Wrong anchor | `sub/.gitignore` = `/sub/keep.py`; `sub/keep.py` | `repo/sub` | `keep.py` counted | skipped |
| Deeper file re-includes | root `.gitignore` = `*.md`; `docs/.gitignore` = `!keep.md`; `docs/keep.md` | repo | `keep.md` counted | skipped |

## Design

Replace the single concatenated spec with a set of per-directory specs.

- `GitIgnoreSpec` holds an ordered list of `(base, PathSpec)` pairs, where `base` is the POSIX path of the directory that owns the patterns, relative to the git root (`''` for the root). When there is no git repo, the scan root plays the role of the git root.
- `match_file(path)` keeps its current signature (path relative to the scan root, directories passed with a trailing `/`) so the TUI keeps working. Internally:
  1. Convert to a git-root-relative path using the existing prefix.
  2. Walk the specs from shallowest to deepest. Skip any whose `base` is not an ancestor of the path.
  3. For each applicable spec, match the path relative to that `base`. The last spec that has an opinion wins, which gives deeper files precedence and makes negation (`!pattern`) work across files.
- "Has an opinion" needs a three-way result (ignored / re-included / no match). pathspec exposes this through `PathSpec.check_file()`, which returns a result whose `include` is `True`, `False` or `None`. Confirm that API against the installed pathspec version before relying on it, and raise the minimum in `pyproject.toml` if needed.
- Add `GitIgnoreSpec.add_directory(rel_dir, dir_path)`, which loads `dir_path/.gitignore` if present and registers it with the right base. It must be idempotent, since the TUI and the walker may both visit a directory.
- `load_gitignore(root)` registers the git-root `.gitignore` and `.git/info/exclude` at base `''`, then each intermediate `.gitignore` at its own base.
- `walk_project()` calls `add_directory()` on entering each directory, **before** filtering that directory's children and files.
- `SetupApp._populate()` in `src/tallyman/tui/setup_app.py` does the same before testing each directory's children, so the tree agrees with the walker.

Git does not re-include a file whose parent directory is ignored. The walker already prunes ignored directories and never descends into them, so that rule holds without extra work.

Out of scope: the global excludes file (`core.excludesFile`) and `.gitignore` files in nested repositories or submodules being treated as separate roots.

## H15 - path separators

While editing these lines, build every relative path string with `PurePath.as_posix()` instead of `str()`:

- `walker.py`: `rel_dir_str` in `walk_project()`, and `prefix` in `load_gitignore()`.
- `config.py`: `rel_dir_str` in `discover_nested_configs()`.

This cannot be run on Windows here. Cover it with a unit test on whichever small helper produces the string, using `PureWindowsPath` input.

## Tests

- The five reproduction cases above.
- Existing gitignore tests in `tests/test_walker.py` still pass unchanged.
- A scan root with no git repo and a nested `.gitignore` honours the nested file.
- `add_directory()` called twice for the same directory does not duplicate patterns.

## Done when

- All reproduction cases pass.
- Running `tallyman` on this repo still reports the same totals as before the change.
- `pytest`, `ruff check` and `ruff format --check` are clean.
