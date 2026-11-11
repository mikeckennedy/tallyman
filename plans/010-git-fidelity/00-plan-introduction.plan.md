# Plan 010 - Git Fidelity - Introduction

## Context

The architect review of main @ 75dd0fd (2026-11-10) found three places where tallyman's gitignore handling disagrees with git:

- **Item 4.** `info/exclude` is skipped in git worktrees and submodules. There, `.git` is a file (`gitdir: ...`), not a directory, so `git_root / '.git' / 'info' / 'exclude'` doesn't exist. `find_git_root()` accepts the file, so everything else works and the gap is silent.
- **Item 5.** Nested git repositories are walked with the outer repo's rules. With `*.md` in the outer `.gitignore` and a nested repo holding `a.md` and `b.py`, tallyman counts `b.py` and drops `a.md`, and the nested repo's own `info/exclude` is never read.
- **Item 9.** A pattern ending in a lone, unescaped backslash (`a\`, `*.py\`, `\`) matches nothing in git. Tallyman treats the backslash as a literal character.

The review also flagged doc drift: `gitignore.py`'s "Known differences" docstring doesn't mention the global excludes file (the README does), and neither mentions any of the above.

This plan fixes all three and the docs. Plans 008 (output hardening) and 009 (spec colours) land before it, 011 (setup TUI) and 012 (housekeeping) after it. See "Overlap with other plans" below.

## Verified while planning (git 2.54.0, throwaway repos in the session scratchpad)

- **Item 4 confirmed.** Main repo with `.git/info/exclude` listing `secret.py`, `git worktree add wt`: `tallyman wt` counts `wt/secret.py`; git doesn't list it. Submodule (`git -c protocol.file.allow=always submodule add <local path> sub`): `sub/.git` is `gitdir: ../.git/modules/sub` (relative), and git honours `.git/modules/sub/info/exclude`; tallyman doesn't.
- **Worktrees read only the common dir's `info/exclude`.** The worktree's gitdir (`.git/worktrees/wt`) has a `commondir` file containing `../..`. A file at `.git/worktrees/wt/info/exclude` is **not** read by git. Only `<commondir>/info/exclude` is.
- **Item 5 confirmed, and git's model is clear.** `git ls-files -o` in the outer repo lists a nested repo as one entry (`sub/`) and never looks inside. Run inside `sub`, git applies only `sub`'s rules: the outer `*.md` doesn't apply, and `sub/.git/info/exclude` does. This holds recursively (a repo inside a nested repo is again its own world) and for submodules and worktrees placed inside a repo.
- **An outer rule that ignores the nested repo's directory keeps it out.** With `sub/` in the outer `.gitignore`, git doesn't list `sub/` at all.
- **Git only treats a valid repository as nested.** An empty `.git` directory, or a `.git` file whose `gitdir:` target is missing, is an ordinary directory to git, and the outer rules apply inside it. Tallyman's `find_git_root()` accepts any `.git` that exists, and 39 test sites fake a repo with `(tmp_path / '.git').mkdir()`. See decision 6 and open question 1.
- **Item 9 confirmed**, plus its mirror image: with `*` then `!a\`, git keeps `a\` ignored (the negation matches nothing) while tallyman re-includes it. `a\/` (dir-only) also matches nothing in git. `a\\` (escaped backslash) agrees today.
- **New, same area: an escaped backslash before trailing spaces.** In git, `c\\ ` (escaped backslash, then an unescaped space) has its trailing space stripped and matches `c\`. Tallyman's `line.endswith('\\ ')` test reads the space as escaped, so it matches `c\ ` instead. Git's `trim_trailing_spaces()` scans left to right, and a backslash escapes exactly the next character. `c\\\ ` (escaped backslash, escaped space) agrees today. Fixed in phase 1 with item 9.
- **The review's `fuzz.py`** reports 29 diffs today. Three are item 9. The rest are expected and stay: 20 with names containing `/` (`check-ignore --no-index` reports a parent directory's match; `match_file()` judges one entry and assumes its parents were checked, by design), and 6 with `é` (the documented byte-versus-character difference).
- **A prototype of the phase 2 design** (a `GitIgnoreSpec` subclass in the scratchpad that registers nested repo roots in `add_directory()`) matched a recursive "run git in every repo" view exactly on: nested repos with outer `*.md`, outer subdirectory `.gitignore` above a nested repo, a repo inside a nested repo, inner `info/exclude`, an outer-ignored nested repo, a submodule from outside and inside, and a worktree inside its main repo and outside it.

## The code today

- `gitignore.find_git_root(start)` walks up until `(current / '.git').exists()`. Directory or file, valid or not.
- `GitIgnoreSpec.for_root(root)` registers `<git-root>/.git/info/exclude`, `<git-root>/.gitignore` and every `.gitignore` between the git root and the scan root. Layers are `(base, _IgnoreFile)`, with `base` relative to the git root (the *anchor*), sorted shallowest first. `_is_ignored()` lets the deepest layer with an opinion win.
- `GitIgnoreSpec.add_directory(rel_dir, dir_path)` registers `dir_path/.gitignore` as the walk enters a directory. Both `walker.walk_project()` and `SetupApp._populate()` call it on a directory before judging that directory's children. That shared entry point is what keeps the walker and TUI in step.
- `GitIgnoreSpec.for_patterns()` + `add_rules()` hold `[exclude] patterns` in a second instance. `add_directory()` is never called on it.
- `_parse_line()` trims trailing spaces with `while line.endswith(' ') and not line.endswith('\\ ')`. `_glob_to_regex()` emits a literal `\` when the backslash is the last character.
- `config.find_configs()` stops at `find_git_root()`, the nearest repo root. `walker.inside_auto_spec_dir()` uses the same root.

## Decisions

From the review (Michael, 2026-11-10):

1. **Keep counting nested repos, but apply the inner repo's own rules inside them** (its `.gitignore` stack and its `info/exclude`), as if git were run there.

Proposed here, following from decision 1 and git's behaviour (open questions below cover the ones that are Michael's call):

2. **`info/exclude` is found the way git finds it.** `.git` directory: `.git/info/exclude`. `.git` file: read `gitdir: <path>` (relative to the directory holding the `.git` file), then, if that gitdir has a `commondir` file, use `<commondir>/info/exclude` (relative to the gitdir). A per-worktree `info/exclude` is not read, matching git. A malformed or dangling `.git` file means no `info/exclude`, never an error.
3. **A nested repo's own directory entry is judged by the enclosing repo's rules.** The entry lives in the enclosing tree. If the outer `.gitignore` or `info/exclude` ignores `sub/`, it stays excluded and is never entered, as with git.
4. **Inside a nested repo, only its own rules apply.** That means its `info/exclude` (decision 2), its root `.gitignore` and the `.gitignore` files beneath it. Every enclosing layer stops at its root: the outer `info/exclude`, the outer root `.gitignore`, and any `.gitignore` in directories between the outer root and the nested one. An outer `!pattern` can't reach in either. This applies recursively.
5. **Submodules and worktrees inside the tree are nested repos.** They are directories with a `.git` file, and decision 2 finds their `info/exclude`.
6. **Nested-repo detection uses the same test as `find_git_root()`: `.git` exists** (directory or file). Scanning `sub` directly and scanning its parent then agree on where `sub`'s rules start. Git is stricter (it requires a valid repository); the difference is documented. Open question 1.
7. **Scanning from inside a nested repo doesn't change.** `find_git_root()` already returns the nearest root, so the nested repo is the git root and the outer repo plays no part, matching git run there. One visible consequence, the same as git: if the outer repo ignores `sub/`, `tallyman outer` skips it but `tallyman outer/sub` counts it.
8. **Outside any repo, child repos get their own rules too.** The scan root keeps standing in for the git root (today's behaviour). The scan root's `.gitignore` stops at each child repo. This is the "folder of checkouts" case, and probably the commonest real nested-repo layout.
9. **Tallyman's own settings ignore repo boundaries; their semantics don't change.** That covers `[exclude] directories`, `[exclude] patterns` (the second `GitIgnoreSpec` never calls `add_directory()`, so it never learns about repo roots), `[specs] directories` / `[specs] ignore`, spec auto-detection by name, hidden-directory skipping and the default skips. The config chain still stops at the nearest git root (`find_configs()`). A `.tally-config.toml` inside a nested repo below the scan root is a nested config like any other. Scanning from inside a nested repo makes it the git root, so outer configs don't apply; that is today's behaviour. Open question 2.
10. **One spec, repo roots inside it.** `GitIgnoreSpec` records the nested repo roots it meets in `add_directory()`. `_is_ignored()` uses only the layers at or below the deepest repo root strictly above the entry. The walker, the TUI, `cli.py` and `config.py` don't change. A spec per repo with a stack in the walker was considered and rejected: the walker and the TUI would each need the stack logic, which is exactly the kind of duplication that lets them drift apart.

## Phases

| Phase | File | Covers |
|-------|------|--------|
| 1 | `phase-01-gitdir-and-escapes.plan.md` | Item 4 (decision 2), item 9 and the escaped-backslash-space case; parity tests for a worktree and a submodule scanned from inside |
| 2 | `phase-02-nested-repos.plan.md` | Item 5 (decisions 1, 3-10): repo roots in `GitIgnoreSpec`; unit, git-parity and walker/TUI agreement tests |
| 3 | `phase-03-docs.plan.md` | README gitignore notes, `CLAUDE.md` decision 7 and module map, final pass on the "Known differences" docstring |

Phase 1 goes first because phase 2's nested repos use phase 1's `info/exclude` lookup for submodules and worktrees.

## Workflow

- All of plans 008-012 land on one feature branch, `architect-review-fixes`. Claude owns the branch and commits after each phase, so the history shows how the work evolved. **Never push** (unlike plan 007), never commit to `main`, never force-push, and leave merging to Michael.
- After each phase, run an architect review with the `architect-tallyman` sub-agent (`.claude/agents/architect-tallyman.md`). Point it at the phase file and the diff. Address its valid findings, then commit.
- The review's line numbers are from 75dd0fd. Plans 008 and 009 land first and shift them, so find code by function name.

## Rules for every phase

- Follow `CLAUDE.md`: single quotes, `from __future__ import annotations`, type hints, 120-char lines.
- New or changed annotations use `Optional[X]`, not `X | None`. New test functions get `-> None` (Michael's decision on review item 14; plan 012 sweeps the rest).
- Each behaviour change lands with a test that fails before the change and passes after.
- Git-dependent tests skip cleanly when git is missing, like `test_matches_git` (`@pytest.mark.skipif(shutil.which('git') is None, ...)`). They run git with `_git_env()`, so no global or system config leaks in. Build repos under `tmp_path`, never in the project.
- Finish each phase with `pytest`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `uvx ty check` and `uvx pyrefly check` all clean.
- Add entries under the existing `0.4.3 - UNRELEASED` heading in `change-log.md`, with `Files:` and `Plan:` lines in the existing style. No version bump.
- Update the `CLAUDE.md` test table and the "all N tests" count in Quick Reference. Recount with `pytest --collect-only -q`, since plans 008 and 009 change the counts first.
- What the setup TUI shows must match what the walker does, at every commit.

## Overlap with other plans

- **008 output hardening.** It replaces `is_symlink()` with one `lstat()` / `S_ISREG` check in the walker's file loop. This plan doesn't touch the walker's loops at all (decision 10), so there is no conflict beyond shifted line numbers. Rebase phase 2's walker docstring edit onto whatever 008 leaves.
- **011 setup TUI** has real overlap. It plans lazy tree population and pruning `discover_nested_configs()` with the walker's `GitIgnoreSpec`. 011 should assume:
  - Nested repo roots are discovered inside `GitIgnoreSpec.add_directory()`. Any traversal gets nested-repo semantics for free if it calls `add_directory(rel_dir, dir_path)` on a directory **before** calling `match_file()` on that directory's children, which is the same rule as for nested `.gitignore` files today. A lazily populated node must do that when it is expanded, not when it is created.
  - Calling `match_file()` for an entry inside a nested repo before `add_directory()` ran for the repo's root gives the outer repo's answer. That is the same hazard as a not-yet-registered `.gitignore`, and the same discipline avoids it.
  - Use one spec instance, built by `load_gitignore()` / `GitIgnoreSpec.for_root()`, for the TUI and the walker. Don't build a second spec per subtree. Registration is idempotent, so sharing it with the walker afterwards stays safe.
  - Pruning `discover_nested_configs()` with that spec means a config inside a nested repo that the outer repo ignores is no longer discovered, which matches the walker. Configs inside a nested repo that isn't ignored are still nested configs (decision 9).
  - 011's walker/TUI agreement tests should include a nested-repo tree. Phase 2 adds `TestNestedRepos.test_tui_and_walker_agree_across_nested_repos` in `tests/test_setup_app.py`, which 011 can extend.
- **012 housekeeping.** The review's doc-drift item on the "Known differences" docstring belongs to this plan (phases 1-3), so 012 should skip it. The `Optional` sweep of `walker.py`'s `gitignore_spec: GitIgnoreSpec | None` stays with 012; this plan doesn't change that signature.
- **009 spec colours.** No overlap.

## Open questions (Michael's call; defaults are what the phases implement)

1. **Strict or lenient nested-repo detection?** Git treats a `.git` that isn't a valid repository (an empty `.git` directory, a `.git` file pointing nowhere) as an ordinary directory, so the outer rules continue inside. *Default: lenient*, the same `.git`-exists test as `find_git_root()` (decision 6). Scanning a directory directly and scanning its parent then agree. The tests' fake `(tmp_path / '.git').mkdir()` repos keep working. The case is rare (a half-deleted checkout, a stale worktree after its main repo moved). Going strict would mean validating `HEAD`, `objects/` and `refs/` the way git's `is_git_directory()` does, in both `find_git_root()` and nested detection, and rewriting the 39 fake-repo test sites.
2. **Should the config chain also stop at nested repo boundaries?** Scanning `outer`, a pattern such as `*.md` in `outer/.tally-config.toml` still excludes `outer/sub/a.md` inside the nested repo `sub`. *Default: yes, configs keep applying* (decision 9). They are the user's instructions for this scan, not git rules, and Michael's decision covers git's rules only. Scanning from inside `sub` already ignores outer configs, because `find_configs()` stops at the nearest git root.
3. **Show nested repos in the setup TUI?** A dim `(git repo)` suffix would explain why an outer rule no longer applies beneath a directory. *Default: no label change in this plan.* If Michael wants it, it fits better in 011, which rebuilds labels as `Text`.
4. **Read the global excludes file now?** git also reads `core.excludesFile` (default `$XDG_CONFIG_HOME/git/ignore`). *Default: no.* Counts stay the same on every machine, and the README already says so. It stays in "Known differences".
