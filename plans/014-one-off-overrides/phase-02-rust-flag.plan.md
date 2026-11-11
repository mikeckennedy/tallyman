# Phase 2 - `--exclude-rust-tests` / `--no-exclude-rust-tests`

Covers decisions 8-10 from `00-plan-introduction.plan.md`.

## 1. Parsing (`cli.py`)

```python
parser.add_argument(
    '--exclude-rust-tests',
    action=argparse.BooleanOptionalAction,
    default=None,
    help='Leave Rust #[cfg(test)] code out of this run (or count it, with --no-...); overrides [rust] exclude_test_modules',
)
```

`default=None` means "no override". Check how argparse renders the help for a `BooleanOptionalAction` with `default=None` (it may append `(default: None)` on some versions); word the help so it reads well either way, or suppress the default.

## 2. The walker override (`walker.py`)

The flag wins everywhere (decision 9), so a nested config's `[rust]` must not change it.

- Add a keyword to `walk_files()`: `rust_tests_override: Optional[bool] = None`. When it isn't None, every `SourceFile` gets it, and nested configs' `rust_exclude_test_modules` values are not read into the per-directory map. When None, behaviour is exactly today's.
- Nested configs are still loaded for everything else (their exclusions, specs and patterns).
- Docstring: say what the override is for and that it beats nested configs.
- `walk_project()` needs no new parameter (it doesn't expose the Rust value); leave it alone unless the architect finds a caller that needs it.

Alternative considered: have the CLI pass `exclude_rust_tests=flag` and add a separate boolean "ignore nested". One Optional keyword is simpler and can't be half-set.

## 3. Wiring (`cli.py`)

- After the three-way config/setup block, where `exclude_rust_tests` is set:
  - pass `rust_tests_override=args.exclude_rust_tests` to `walk_files()`.
  - Leave `exclude_rust_tests` (the scan root's config value) as it is. With an override it is unused, which is fine.
- Setup: `run_setup(..., existing_rust=chain.local.rust_exclude_test_modules)` is unchanged, so setup shows and saves the config's value (decision 10). The count after setup uses the flag.
- The report's `Excluded Rust test code` note follows from the counts: with `--no-exclude-rust-tests` it disappears, with `--exclude-rust-tests` it appears for a project whose config never set `[rust]`.

## 4. Tests

`tests/test_walker.py`:

- `rust_tests_override=True` with no config: every Rust `SourceFile` has `exclude_rust_tests=True`.
- `rust_tests_override=False` beats a nested config's `true` in its crate, and `True` beats a nested `false`.
- `rust_tests_override=None` keeps today's per-directory behaviour (the existing sibling-leak test still passes; add one assertion with the keyword passed explicitly).
- With an override, a nested config's other settings (an `[exclude] directories` entry, a pattern) still apply.

`tests/test_cli.py` (extend `TestRustTestCode`, using `RUST_LIB`):

- `--exclude-rust-tests` with no `[rust]` in the config: the test module is left out and the note appears.
- `--no-exclude-rust-tests` with `[rust] exclude_test_modules = true`: everything counts and the note is absent.
- Under a parent config's `true` and a nested crate's `false`: `--exclude-rust-tests` leaves the crate's tests out too.
- Never saved: the config file is byte-for-byte unchanged after a run with either flag.
- With `--setup` through `_real_setup`: the setup line shows the config's value (not the flag's); untouched, the saved `[rust]` value is the config's; the count after setup uses the flag. Pressing `r` saves the toggled config value while the count still uses the flag.
- Both flags given: the last one wins (argparse's normal behaviour). One test pins it, so the behaviour is deliberate.
- `--help` lists `--exclude-rust-tests, --no-exclude-rust-tests`.

## 5. Docs

- `README.md`: in `### Leaving out Rust test code`, a short "For one run" paragraph: the two flags, beat every config including nested ones, never saved, ignored by `--setup`. Usage block: one line.
- `CLAUDE.md`: Quick Reference line, module map rows for `cli.py` and `walker.py` (`rust_tests_override`), decision 10 (the override beats the per-directory map; setup ignores it), test table and total.
- `.cursor/rules/*.mdc` and the architect persona copies: the same facts.
- `change-log.md`: a second `### Added` entry under `0.6.5 - UNRELEASED`, with `Files:` and `Plan:` lines.

## Done when

All checks in "Rules for every phase" are clean, the architect review (this time over the whole branch, `main...one-off-overrides`) has its valid findings addressed and recorded below, and the phase is committed: `Plan 014 phase 2: one-off Rust test-code flags`.

## Review findings (phase 2 and whole branch, 2026-11-11)

The architect checked the override against an independent count on a tree with a parent `true`, a crate `false`, a nested-nested `true` and a nested repo with its own `false` and a pattern: no flag 36 effective lines, `--exclude-rust-tests` 15, `--no-exclude-rust-tests` 50, all as expected, the nested repo's pattern still applied, and no config file changed. Every `main()` path counts with the flag, setup saw and saved the config's value on all four setup paths, and a plain run is byte-identical to `main`. Mutations: applying the override only at the root (M1) and ignoring it on the setup paths (M4) were caught.

Fixed:
- **Must fix: `test_setup_ignores_the_flag` couldn't fail.** Its flag agreed with the config, so a setup handed the flag's value (M2, M3) passed. It now runs five cases where the flag disagrees with what setup should see, first-run setup included; under M2, four fail (the fifth checks `r` toggles the config's value).
- **Abbreviations.** With `allow_abbrev` on, `--no` (which meant `--no-color` on `main`) and `--excl` are now ambiguous, and `tallyman --exclude-r tests/` parses as the Rust flag plus the path `tests/`. Kept abbreviations on (turning them off would break `--no-col`, `--with` and the like) and recorded the change under `### Changed` in the 0.6.5 changelog. A test pins that `--exclude` and `--exclude=x` parse exactly next to `--exclude-rust-tests`. Flagged in the PR for Michael.
- `--help` no longer breaks `--no-exclude-rust-tests` at a hyphen; the README feature bullet and usage line mention the flags; the walker's root/nested branches are one `if`; the walker override test covers a nested-nested config and a nested repo.
