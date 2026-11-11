# Phase 1 - `info/exclude` Through `gitdir:` and `commondir`, and Line-End Escapes

Covers review items 4 and 9 and decision 2 from `00-plan-introduction.plan.md`, plus the escaped-backslash-before-trailing-space case found while planning.

## Goal

Scanning a git worktree or a submodule honours the same `info/exclude` git does. Patterns that end in backslashes are compiled the way git compiles them, in `.gitignore`, `info/exclude` and `[exclude] patterns` alike, since all three go through `_parse_line()`.

## Current behaviour

- `GitIgnoreSpec.for_root()` registers `git_root / '.git' / 'info' / 'exclude'`. In a worktree (`.git` is `gitdir: /abs/main/.git/worktrees/wt`) or a submodule (`gitdir: ../.git/modules/sub`) that path is a file's child, `read_bytes()` raises, and the layer is silently skipped.
- `_glob_to_regex('a\\')` emits a literal backslash for the final `\`, so `a\` matches an entry named `a\`. In git it matches nothing, and `!a\` re-includes nothing.
- `_parse_line('c\\\\ ')` (the four characters `c`, `\`, `\`, space) keeps the space, because the line ends with `\ `. In git the first backslash escapes the second, the space is unescaped and trailing, and it is stripped.

## Changes

### `src/tallyman/gitignore.py`

Add three small module-private helpers next to `find_git_root()`:

- `_has_git(directory: Path) -> bool`: `(directory / '.git').exists()`. `find_git_root()` switches to it. Phase 2's nested-repo detection uses it too, so the two can never disagree (decision 6).
- `_git_dir(repo_root: Path) -> Optional[Path]`: the repository's git directory.
  - `.git` is a directory: return it.
  - `.git` is a file: read its bytes and decode as UTF-8 with `errors='replace'`. It must start with `gitdir: ` (exactly; git's prefix is case-sensitive and the space is required). Strip trailing `\n` and `\r` as git does, and resolve the rest against `repo_root` (an absolute value stays absolute: `repo_root / value`). Return `None` if the prefix is missing.
  - `OSError` anywhere: return `None`.
- `_info_exclude(repo_root: Path) -> Optional[Path]`: `<common>/info/exclude`, where `common` is `_git_dir(repo_root)`, or, when that git dir holds a `commondir` file, that file's content with trailing `\n`/`\r` stripped, resolved against the git dir. An unreadable `commondir` falls back to the git dir itself. Returns `None` when `_git_dir()` does. Docstring: worktrees share the main repo's `info/exclude` through `commondir`, and git does not read a per-worktree `info/exclude`; checked against git 2.54.

Don't validate that the target is a real repository (open question 1, default lenient). A missing target just makes `_add_file()` treat the exclude file as absent.

In `GitIgnoreSpec.for_root()`, replace `spec._add_file('', git_root / '.git' / 'info' / 'exclude')` with:

```python
if (exclude := _info_exclude(git_root)) is not None:
    spec._add_file('', exclude)
```

Update the `for_root()` docstring's first bullet to "the repo's ``info/exclude`` (found through a ``.git`` file's ``gitdir:`` and ``commondir`` in worktrees and submodules)". The class docstring's "``.git/info/exclude`` ranks below every ``.gitignore``" becomes "``info/exclude``".

Escapes at the end of a line:

- `_glob_to_regex()`: when `c == '\\'` and it is the last character, return `None`. The pattern then matches nothing, including as a `!` negation. Keep the existing `i + 1 < len(glob)` branch for every other backslash. Comment: "a trailing unescaped backslash makes the whole pattern invalid in git".
- `_parse_line()`: replace the trailing-space loop with a helper `_trim_trailing_spaces(line: str) -> str` that follows git's `trim_trailing_spaces()`. Scan left to right, remembering where the current run of spaces started. A backslash escapes the next character, so skip that character and reset the run. If the line ends in a lone backslash, return the line untrimmed (the glob is then rejected above). At the end, cut the line at the start of the final run, if there is one. Results:
  - `bar  ` → `bar`
  - `foo\ ` → `foo\ ` (escaped space kept)
  - `c\\ ` → `c\\` (escaped backslash; the space is trailing)
  - `c\\\ ` → `c\\\ `
  - `a\` → `a\`
- Order inside `_parse_line()` stays as git's: trim trailing spaces, then `!`, then one trailing `/`. So `a\/` becomes dir-only `a\`, which `_glob_to_regex()` rejects, matching git.

Module docstring, "Known differences": add the global excludes file now (the README already lists it):

```
- Only the repo's own ignore files are read: ``info/exclude`` and the
  ``.gitignore`` files. The global excludes file (``core.excludesFile``,
  by default ``~/.config/git/ignore``) is not, so counts don't depend on the
  machine.
```

Phase 2 adds the nested-repo note, and phase 3 audits the whole list.

## Tests

### `tests/test_gitignore.py`, no git needed

New rows in `_PATTERN_CASES`. Every row was checked against git 2.54 with `git check-ignore --no-index` while planning. Python literals:

```python
    ('a\\', 'a\\', False),  # a trailing lone backslash matches nothing
    ('\\', '\\', False),
    ('*.py\\', 'x.py\\', False),
    ('a\\/', 'a\\/', False),
    ('a\\\\\\', 'a\\\\', False),  # escaped backslash, then a lone one
    ('a\\\\', 'a\\', True),  # an escaped backslash is fine
    ('c\\\\ ', 'c\\', True),  # escaped backslash: the space after it is trailing and stripped
    ('c\\\\ ', 'c\\ ', False),
    ('c\\\\\\ ', 'c\\ ', True),  # escaped backslash, escaped space
```

`test_negated_trailing_backslash_reincludes_nothing() -> None`: `.gitignore` is `'*\n!a\\\n'`; `load_gitignore(tmp_path).match_file('a\\')` is True.

New class `TestInfoExcludeLocation`. Each test builds the layout by hand under `tmp_path` and asserts with `load_gitignore(...).match_file(...)`:

- `test_git_directory`: `repo/.git/info/exclude` lists `secret.py`: ignored. Regression guard for the common case.
- `test_gitdir_file_absolute`: `repo/.git` is `f'gitdir: {store}\n'`, with `store/info/exclude` listing `secret.py`: ignored; `ok.py` isn't.
- `test_gitdir_file_relative`: `outer/sub/.git` is `'gitdir: ../.git/modules/sub\n'`, with `outer/.git/modules/sub/info/exclude` listing `secret.py`. Scanning `outer/sub`: ignored. This is the submodule layout.
- `test_gitdir_file_crlf`: the same with `\r\n`: still found.
- `test_commondir_relative`: worktree layout. `main/.git/worktrees/wt/commondir` is `'../..\n'`, `wt/.git` is `f'gitdir: {main}/.git/worktrees/wt\n'`, and `main/.git/info/exclude` lists `secret.py`. Scanning `wt`: ignored.
- `test_commondir_absolute`: `commondir` holds an absolute path: same result.
- `test_per_worktree_info_exclude_is_not_read`: as `test_commondir_relative`, plus `main/.git/worktrees/wt/info/exclude` listing `ok.py`. `ok.py` is not ignored (git 2.54 doesn't read it).
- `test_malformed_git_file_is_harmless` (parametrize): `.git` contents `'nonsense\n'`, `'gitdir: /does/not/exist\n'`, `'GITDIR: x\n'`, and an empty file. No exception; `repo/.gitignore` listing `a.py` still applies; `b.py` isn't ignored.
- `test_scan_below_worktree_root`: scanning `wt/src` in the worktree layout still finds `secret.py` through the common dir (`match_file('secret.py')` relative to `wt/src`, with `secret.py` an unanchored pattern).

### `tests/test_gitignore.py`, parity with git

Shared helpers, next to `_git_env()`:

- `_git_env()` also sets `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL` after dropping inherited `GIT_*` variables, so the tests can commit. The existing parity tests are unaffected.
- `_git(env: dict[str, str], *args: str) -> str`: `subprocess.run(['git', *args], check=True, env=env, capture_output=True, text=True).stdout`. Capturing keeps git's hints out of the test output.
- `_git_view(scan: Path, env: dict[str, str]) -> set[str]`: what git shows as countable under *scan*, as if git were run in every repository. Run `git -C <scan> ls-files -c -o --exclude-standard -z .`. For each entry, if `scan / entry.rstrip('/')` is a directory containing `.git` (git lists an untracked nested repo as `sub/` and a submodule as the gitlink `sub`), recurse into it and prefix the results. Otherwise keep the entry if it ends in `.py` or `.md`. `-c` is included because worktree and submodule files are committed. Fixtures never commit a file that an ignore rule matches: tallyman can't see the index, a known difference. This phase only scans from inside one repo, so the recursion first matters in phase 2.
- `needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')`. Use it on the new tests; optionally switch `test_matches_git` to it.

Tests, each `@needs_git`:

- `test_worktree_matches_git(tmp_path) -> None`:
  - `git init` `main`, commit a `.gitignore` of `*.md` and `kept.py`.
  - Write `secret.py` into `info/exclude`. Find the path with `git -C main rev-parse --git-common-dir`, so the test doesn't hard-code git's layout.
  - `git -C main worktree add -q <tmp>/wt`, outside `main`; phase 2 covers a worktree inside it.
  - Add untracked `wt/secret.py`, `wt/ok.py` and `wt/a.md`.
  - Assert `_walked(wt) == _git_view(wt, env)` and `'secret.py' not in _walked(wt)`.
- `test_submodule_matches_git(tmp_path) -> None`:
  - `git init` `subsrc`, commit `kept.py` and a `.gitignore` of `*.log`.
  - `git init` `outer`, commit a `.gitignore` of `*.md` and `top.py`.
  - `git -C outer -c protocol.file.allow=always submodule add -q <tmp>/subsrc sub`. `protocol.file.allow` is needed for local-path submodules since git 2.38.1; older gits ignore the unknown key.
  - Write `secret.py` into the submodule's exclude file, located with `git -C outer/sub rev-parse --git-common-dir`.
  - Add untracked `outer/sub/secret.py`, `outer/sub/b.py` and `outer/sub/a.md`.
  - Assert `_walked(outer / 'sub') == _git_view(outer / 'sub', env)`, which includes `a.md` (the outer `*.md` doesn't apply when scanning from inside) and excludes `secret.py`.

## Changelog

Under `0.4.3 - UNRELEASED`, `### Fixed`:

- `.git/info/exclude` is now honoured in git worktrees and submodules, where `.git` is a file pointing at the real git directory. Worktrees use the main repository's `info/exclude`, as git does.
- A gitignore or `[exclude]` pattern ending in a lone backslash (`a\`) now matches nothing, as in git, instead of matching a name ending in `\`. An escaped backslash before trailing spaces (`a\\ `) no longer keeps the spaces.
- Files: `src/tallyman/gitignore.py`, `tests/test_gitignore.py`
- Plan: `plans/010-git-fidelity/phase-01-gitdir-and-escapes.plan.md`

## Done when

- The review's `parity.py` worktree case (`worktree-info-exclude`) and its `trailing-backslash` case print `OK`.
- The review's `fuzz.py` reports no diffs except names containing `/` (the parent-directory artefact) and the `é` byte/character cases. Today that is 26 of 29.
- Scanning an ordinary repo gives byte-identical output to before: the existing tests pass unchanged.
- All checks in the introduction's rules are clean, and the `CLAUDE.md` test counts are updated.
