# Phase 5 - Hygiene and Coverage

Covers H17, H18, H19 and H20 from `00-plan-introduction.plan.md`.

## Goal

Lint and format checks pass, there is one source of truth for Ruff settings, the untested modules have a safety net, and the project docs describe the code as it is.

## H17 - lint and format failures

- `ruff check src/ tests/` reports one E501 at `src/tallyman/languages.py:57`, the HTML entry with twelve template extensions. The table is inside `# fmt: off`, which stops the formatter but not the linter. Break the extensions tuple across lines, or add `# noqa: E501` to that line. Prefer breaking the tuple.
- `ruff format --check src/ tests/` wants to reformat `src/tallyman/display.py`. Run `ruff format src/tallyman/display.py` and review the diff. `except UnicodeEncodeError, LookupError:` in that file is valid on Python 3.14 (PEP 758); leave the semantics alone.

## H18 - duplicate Ruff configuration

`ruff.toml` exists, so Ruff ignores `[tool.ruff]` in `pyproject.toml` entirely. The two disagree: `pyproject.toml` selects `E, F, W, I` and sets `src = ["src"]`; `ruff.toml` selects `E, F, I`.

Change: keep `ruff.toml`, move over anything worth keeping (`W` in `lint.select`, `src = ["src"]`), and delete the `[tool.ruff]`, `[tool.ruff.lint]` and `[tool.ruff.format]` tables from `pyproject.toml`. Fix any new `W` findings.

## H19 - test coverage for cli, display and TUI

Phases 2, 3 and 4 add `tests/test_cli.py`, `tests/test_setup_app.py` and `tests/test_display.py` for the behaviour they change. This phase fills in the baseline around them.

`tests/test_cli.py`:

- A path that is not a directory exits 1 with a message on stderr.
- `--version` prints the version.
- `--no-color` and `NO_COLOR` produce output with no ANSI escapes.
- `--with-spaces` changes the category totals to total lines.
- An existing config is honoured end to end (an excluded directory does not appear in the output).

`tests/test_display.py`:

- A result with no languages prints the "No recognized source files" line.
- A language with a comment marker prints "excluding comments and blank lines"; one without prints "excluding blank lines".
- The same language name in two categories is labelled with its category, for example `Markdown (specs)`.
- The percentage bar is exactly `BAR_WIDTH` characters for a few distributions, including many small languages grouped as Other.
- A category with more than three languages ends its list with `, etc`.

`display_results()` builds its own `Console`. To capture output, accept an optional `console` parameter that defaults to the current behaviour.

## H20 - stale docs

`CLAUDE.md`:

- Test count in the Quick Reference and the Test Structure table (128 at the time of the review; recount after this plan's additions).
- Add `image.py`, `fonts/` and `tests/test_image.py` to the Module Map and Test Structure.
- Add the DevOps category wherever the categories are listed.
- Add `--image`, `--image-light` and `--with-spaces` to the Quick Reference.
- Add Pillow to the Tech Stack.
- Update Key Design Decisions for whatever phases 1-3 changed (gitignore handling, config search, spec ignore list).

`README.md`:

- The "How it works" section lists `;` as a supported comment style; no language in the registry uses it. Remove it or add a language that does.
- Recount the "N languages" claims against `LANGUAGES` and the per-category tables.
- Document `specs.ignore` and the no-TTY behaviour if those landed.

Local environment, for information only: the project `venv` reported tallyman v0.3.2 while `pyproject.toml` says 0.3.3, and was created with Python 3.14.3 while the interpreter is now 3.14.10. Recreate it and reinstall (`uv venv` then `uv pip install -e ".[dev]"`) before trusting version output.

## Done when

- `ruff check src/ tests/` and `ruff format --check src/ tests/` are clean with a single Ruff config.
- `pytest` passes with the new test modules in place.
- `CLAUDE.md` and `README.md` match the code.
