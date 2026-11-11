# Phase 3 - Docs

Covers the review's gitignore doc drift and the documentation for phases 1 and 2.

## Goal

The README, `CLAUDE.md` and `gitignore.py`'s docstring describe what tallyman does with worktrees, submodules and nested repositories, and list the differences from git that remain, consistently with each other.

## `src/tallyman/gitignore.py`

Audit the module docstring after phases 1 and 2. It should read as one coherent list, in this order:

1. A short paragraph saying repositories nest: nested repos, submodules and worktrees inside the tree are walked with their own rules, as if git were run inside each, and `info/exclude` is found through a `.git` file's `gitdir:` and `commondir`.
2. "Known differences from git":
   - case-sensitive matching (existing);
   - `?` and bracket expressions match a character, not a byte (existing);
   - tracked files under an ignored pattern are skipped (existing);
   - the global excludes file isn't read (phase 1);
   - any `.git` marks a repository root, even one git would reject (phase 2).

Check that every claim is still true against the code. No other source changes in this phase.

## `README.md`

The "Gitignore-aware" bullet in Features (line 44 at 75dd0fd) becomes, in substance:

> - **Gitignore-aware** - Tallyman follows the same rules as Git: every `.gitignore` in your tree, plus `.git/info/exclude` (in worktrees and submodules too), scoped and prioritised the way Git does it. Nested repositories and submodules are counted with their own rules, as if you ran Git inside each one; if the outer repository ignores one, it stays out. (Differences: matching is case-sensitive, the global excludes file isn't read, a tracked file under an ignored pattern is skipped, and any `.git` directory or file starts a nested repository, even one Git would reject.) It skips virtual environments, `node_modules`, build artifacts, and anything else you've already told Git to ignore.

If that reads too long for a Features bullet, keep the first sentence and the skip list there, and move the nested-repository sentence and the differences into a short "Git repositories inside your project" paragraph near "How it works" (line 167) or the "never counted" list (line 177).

- Say that `[exclude]` and `[specs]` settings apply across nested repositories (decision 9). One clause in the patterns section (around line 241) is enough: "Patterns, like directory excludes, apply inside nested repositories too; only Git's own ignore rules stop at a repository boundary."
- Check the README's examples and claims against the new behaviour. Nothing else in it describes gitignore scoping, but grep for `gitignore`, `info/exclude`, `submodule` and `nested` to be sure.

## `CLAUDE.md`

Key Design Decision 7 becomes:

> 7. **Gitignore follows git, entry by entry.** `info/exclude`, then every `.gitignore` from the repo root down, each scoped to its own directory; the deepest opinion wins. `info/exclude` is found through the `.git` directory, or a `.git` file's `gitdir:` and its `commondir` (worktrees, submodules). Nested files load lazily as the walker and TUI descend, and nothing inside an ignored directory is ever looked at. Callers pass directory paths with a trailing `/`. **Nested repos keep their own rules:** a directory below the scan root with a `.git` (directory or file, the same test as `find_git_root()`) starts a new repo in `GitIgnoreSpec.add_directory()`. Inside it only its own `info/exclude` and `.gitignore` stack apply, as if git ran there. Its own entry is still judged by the enclosing rules, so an outer `sub/` keeps it out. `[exclude]`, `[specs]` and the config chain ignore repo boundaries. Any traversal must call `add_directory()` on a directory before judging its children. `tests/test_gitignore.py` checks parity with real `git`, including worktrees, submodules and nested repos; its pattern-compiler table runs without git.

Also:

- Module Map, `gitignore.py` row: add "Finds `info/exclude` through `gitdir:`/`commondir`; nested repo roots start their own rules (`add_directory`)".
- Test Structure: update the `test_gitignore.py`, `test_walker.py`, `test_setup_app.py` and `test_cli.py` rows. Recount every row with `pytest --collect-only -q` rather than adding deltas, since earlier plans changed them. Add "worktrees, submodules, nested repos" to the `test_gitignore.py` "Covers" cell and "nested repos" to `test_setup_app.py`'s.
- Quick Reference: the "all N tests" count.

## `change-log.md`

Under `0.4.3 - UNRELEASED`, `### Fixed`:

- README, `CLAUDE.md` and `gitignore.py`'s docstring describe worktrees, submodules and nested repositories, and list the remaining differences from git, including the global excludes file.
- Files: `README.md`, `CLAUDE.md`, `src/tallyman/gitignore.py`
- Plan: `plans/010-git-fidelity/phase-03-docs.plan.md`

### Added after the phase 1 review

The "Known differences" audit should also say that the `GIT_DIR` and `GIT_COMMON_DIR` environment variables aren't read (git honours them, for example inside hooks).

## Done when

- The README, `CLAUDE.md` decision 7 and the `gitignore.py` docstring make the same claims, and each is true of the code.
- Test counts in `CLAUDE.md` match `pytest --collect-only -q`.
- All checks in the introduction's rules are clean.
