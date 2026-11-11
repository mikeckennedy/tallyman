# Tallyman

**Know the shape of your project, not just the size.**

Tallyman is a command-line tool that gives you a real picture of your codebase - not just raw line counts, but where your effort actually lives. It groups results into meaningful categories like Code, Design, Docs, Specs, and Data, so you can see at a glance whether your project is mostly Python logic, CSS styling, or Markdown documentation.

[![PyPI](https://img.shields.io/pypi/v/tallyman-metrics?v=2)](https://pypi.org/project/tallyman-metrics/)
[![Python](https://img.shields.io/pypi/pyversions/tallyman-metrics?v=2)](https://pypi.org/project/tallyman-metrics/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![Tallyman output showing language breakdown with colored percentage bar for a Python web project](https://mkennedy-shared.nyc3.digitaloceanspaces.com/github/tallyman-for-commandbook.webp)

## Install

```bash
uv tool install tallyman-metrics
```

Then just point it at a project:

```bash
tallyman                    # analyze current directory
tallyman /path/to/project   # analyze a specific path
tallyman --setup            # re-run the interactive setup
tallyman --no-color         # disable colored output
tallyman --image            # save a PNG summary card to Desktop
tallyman --image-light      # light-themed PNG variant
tallyman --with-spaces      # use total lines (incl. comments/blanks) for totals
```

## Why Tallyman?

Tools like [cloc](https://github.com/AlDanial/cloc), [tokei](https://github.com/XAMPPRocky/tokei), and [scc](https://github.com/boyter/scc) are excellent at counting lines of code. If all you need is raw numbers, they're great choices.

But line counts alone don't tell you much about a project's *shape*. Is your codebase mostly application logic, or has the CSS layer quietly grown to rival your backend? Are those Markdown files general docs, or are they specifications driving your development? How much of your project is configuration and data files versus actual code?

**Tallyman answers these questions.** It organizes every recognized file into one of six categories - **Code**, **DevOps**, **Design**, **Docs**, **Specs**, and **Data** - and shows you both the raw line count and the "effective" line count (excluding comments and blank lines) for each.

A few things that set it apart:

- **Category-aware analysis** - Results grouped by intent, not just by file extension. You see *what kind* of work your project contains, not just how many lines of each language.
- **Automatic spec detection** - Markdown and reStructuredText files in directories like `specs/`, `plans/`, or `agents/` are automatically reclassified from Docs to Specs. If you're using planning documents to drive development (especially with AI-assisted workflows), Tallyman tracks that separately.
- **Interactive first-run setup** - The first time you run Tallyman in a project, before any `.tally-config.toml` applies, it launches a TUI where you can walk your project's directory tree and mark directories to exclude or flag as spec directories. Your choices are saved to `.tally-config.toml` so subsequent runs are instant.
- **Gitignore-aware** - Tallyman follows the same rules as Git: every `.gitignore` in your tree, plus the repository's `info/exclude` (in worktrees and submodules too), scoped and prioritised the way Git does it. Git repositories inside your project are counted with their own rules (see [Git repositories inside your project](#git-repositories-inside-your-project)). It skips virtual environments, `node_modules`, build artifacts, and anything else you've already told Git to ignore.
- **Visual composition bar** - A colored percentage bar at the bottom shows you the language distribution of your project in a single glance.


## Features

- **Dual line counts** - Total lines and effective lines (excluding comments and blanks) per language. Use `--with-spaces` to base summaries and percentages on total lines instead
- **Six categories** - Code, DevOps, Design, Docs, Specs, and Data, each with aggregated totals
- **43 languages** - From Python and Rust to Solidity, Terraform, and Docker, with full template support for HTML (Jinja, Nunjucks, Handlebars, and more)
- **Beautiful output** - Colored, formatted results with a language composition bar, powered by [Rich](https://github.com/Textualize/rich)
- **Realistic metrics** - Only counts files *you* wrote, not third-party dependencies or generated code
- **Persistent config** - Your setup choices are saved to `.tally-config.toml` and reused on every run
- **File patterns** - Gitignore-style `[exclude] patterns` for files a directory exclude can't reach, such as Rust tests beside the code they test
- **Rust test code** - Opt in with `[rust] exclude_test_modules` to leave inline `#[cfg(test)]` modules and helpers out of the count
- **Image export** - Generate a shareable PNG summary card with `--image` (dark) or `--image-light` (light theme)
- **Interactive TUI setup** - Visual directory tree for configuring exclusions and spec directories, powered by [Textual](https://github.com/Textualize/textual)

![Tallyman interactive TUI setup showing directory tree with include/exclude toggles and spec directory markers](https://mkennedy-shared.nyc3.digitaloceanspaces.com/github/tallyman-setup.webp)

## Image Export

Want to share your project's code stats in a README, a slide deck, or a social post? Use `--image` to generate a clean PNG summary card:

```bash
tallyman --image              # dark theme (default)
tallyman --image-light        # light theme
```

The image is saved to your Desktop (or the current directory if no Desktop is found) with a filename based on the project name. Here's an example from the [CommandBook macOS app](https://commandbookapp.com):

![Tallyman image export showing code stats for the CommandBook app - category breakdown with colored language composition bar](https://mkennedy-shared.nyc3.digitaloceanspaces.com/github/commandbookapp-code-stats-example.png)

The card includes category totals with effective line counts, a colored language composition bar, and a legend that marks each language with a swatch of its bar color - everything you need to show the shape of your project at a glance. The bar and legend name up to five of the largest languages (each at least 2% of the total) and group the rest as Other, and a legend too long for one row wraps onto more rows.

## Supported Languages

Tallyman recognizes **43 languages** across six categories:

| Category | Languages |
|----------|-----------|
| **Code** | Python, Rust, Go, JavaScript, TypeScript, Java, C, C/C++ Header, C++, C#, Swift, Kotlin, Ruby, Shell, Lua, PHP, Perl, R, Dart, Scala, Elixir, Zig, Haskell, Erlang, OCaml, Nim, V, Solidity |
| **DevOps** | Terraform, Makefile, Docker |
| **Design** | CSS, SCSS, LESS, HTML (+ 8 template extensions), SVG |
| **Docs** | Markdown, reStructuredText |
| **Specs** | Markdown and reStructuredText files auto-detected in spec directories |
| **Data** | TOML, YAML, JSON, XML, SQL |

<details>
<summary>Full language details with file extensions</summary>

Extensions match in any case, so `analysis.R` is R and `README.MD` is Markdown.

### Code

| Language | Extensions / Filenames |
|----------|----------------------|
| Python | `.py` |
| Rust | `.rs` |
| Go | `.go` |
| JavaScript | `.js`, `.jsx`, `.mjs` |
| TypeScript | `.ts`, `.tsx` |
| Java | `.java` |
| C | `.c` |
| C/C++ Header | `.h` |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx` |
| C# | `.cs` |
| Swift | `.swift` |
| Kotlin | `.kt`, `.kts` |
| Ruby | `.rb` |
| Shell | `.sh`, `.bash`, `.zsh` |
| Lua | `.lua` |
| PHP | `.php` |
| Perl | `.pl`, `.pm` |
| R | `.r` |
| Dart | `.dart` |
| Scala | `.scala` |
| Elixir | `.ex`, `.exs` |
| Zig | `.zig` |
| Haskell | `.hs` |
| Erlang | `.erl` |
| OCaml | `.ml`, `.mli` |
| Nim | `.nim`, `.nims` |
| V | `.v`, `.vv` |
| Solidity | `.sol` |

### DevOps

| Language | Extensions / Filenames |
|----------|----------------------|
| Terraform | `.tf`, `.tfvars` |
| Makefile | `.mk`, `Makefile`, `makefile`, `GNUmakefile` |
| Docker | `.dockerfile`, `Dockerfile`, `Dockerfile.*` / `Dockerfile-*` / `Dockerfile_*` (except a docs or data extension such as `Dockerfile.md` or `Dockerfile.json`, and `.txt` or `.dockerignore`), `docker-compose.yml/yaml`, `compose.yml/yaml` and variants such as `docker-compose.override.yml` |

### Design

| Language | Extensions |
|----------|-----------|
| CSS | `.css` |
| SCSS | `.scss` |
| LESS | `.less` |
| HTML | `.html`, `.htm`, `.xhtml`, `.shtml`, `.pt`, `.jinja`, `.jinja2`, `.j2`, `.njk`, `.hbs`, `.ejs`, `.mustache` |
| SVG | `.svg` |

### Docs

| Language | Extensions |
|----------|-----------|
| Markdown | `.md`, `.mdx` |
| reStructuredText | `.rst` |

### Data

| Language | Extensions |
|----------|-----------|
| TOML | `.toml` |
| YAML | `.yml`, `.yaml` |
| JSON | `.json` |
| XML | `.xml` |
| SQL | `.sql` |

</details>

## How It Works

Tallyman runs a simple pipeline:

1. **Walk** your project directory, respecting `.gitignore` and your config's exclusions and patterns
2. **Identify** each file's language by extension or filename
3. **Count** lines, classifying each as code, comment, or blank (with `[rust] exclude_test_modules`, Rust test-only code is left out first)
4. **Aggregate** results by language and category
5. **Display** a colored report with per-language stats, category totals, and a composition bar

Spec directories (`specs/`, `plans/`, `specifications/`, `agents/`) are auto-detected at any depth. Any Markdown or reStructuredText files inside them are reclassified from Docs to Specs, giving you a clear picture of how much of your project is specification-driven.

Lines end at `\n`, `\r\n` or a lone `\r`, and a last line without a newline still counts. Files with a UTF-8, UTF-16 or UTF-32 byte-order mark are decoded accordingly; anything else is read as UTF-8.

Some files are never counted, whatever your `.gitignore` says:

- Hidden directories such as `.git/`, `.venv/` and `.github/`
- Binary files (a NUL byte in the first 8 KB)
- Symlinks, so a linked file is never counted twice, and special files such as named pipes and sockets
- Generated files: `.tally-config.toml`, `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `*.min.js` and `*.min.css`

Comment detection covers single-line comment styles (`#`, `//`, `--`, `%`). Multi-line comment blocks (`/* */`, `""" """`) are not currently detected - lines inside them are counted as code.

### Git repositories inside your project

Tallyman counts Git repositories nested inside your project, including submodules and worktrees, with their own rules, as if you ran Git inside each one. A nested repository's own `.gitignore` files and `info/exclude` apply, and your outer repository's `.gitignore` stops at the nested repository's folder. If the outer repository ignores that folder itself, the nested repository stays out (`tallyman path/to/it` still counts it). A folder of checkouts that isn't a repository works the same way: its `.gitignore` stops at each repository inside it.

Your `.tally-config.toml` settings are different. `[exclude]`, `[specs]` and `[rust]` settings, and configs in subdirectories, apply inside nested repositories too, since they're your instructions for the scan, not Git's. Scanning inside a nested repository uses only its own configs (see "Which configs apply" under [Configuration](#configuration)).

Where Tallyman and Git differ:

- Matching is always case-sensitive, even where Git ignores case (the macOS default).
- Your global Git excludes file (`core.excludesFile`, usually `~/.config/git/ignore`) isn't read, so counts are the same on every machine.
- A tracked file under an ignored pattern is skipped. Git keeps files it already tracks, but Tallyman doesn't read Git's index.
- Any `.git` folder or file starts a nested repository, even an empty or broken one that Git would treat as an ordinary folder.
- A `.gitignore` that is a symlink is read. Git (2.32 and later) skips it with a warning.

## Configuration

When no `.tally-config.toml` applies yet, Tallyman starts with an interactive TUI where you can browse your project tree and configure which directories to exclude or mark as spec directories. Your choices are saved to `.tally-config.toml` in the directory you scanned. A config in the scanned directory or any directory above it (see **Which configs apply** below) means setup is skipped; one in a subdirectory doesn't. So once the repository root has a config, `tallyman src/` counts straight away, using it; run `tallyman --setup src/` to give `src/` its own config.

To re-run setup at any time:

```bash
tallyman --setup
```

In the TUI, `x` excludes or includes a directory, and `s` marks or unmarks it as specs. Pressing `s` on a directory Tallyman detected as specs (such as `plans/`) records that it isn't one.

The config is plain TOML, and you can edit it by hand:

```toml
[exclude]
directories = ["static/vendor", "docs/_build"]

[specs]
directories = ["design"]           # also count these as specs
ignore = ["src/myapp/agents"]      # never specs, even if named plans/, agents/, ...
```

- Paths are relative to the directory the config file lives in. An entry covers everything beneath it.
- A config saved with a byte-order mark (some Windows editors add one) is read fine.
- In `[specs]`, `"."` means that directory itself.
- When `directories` and `ignore` disagree, the deeper entry wins, so you can ignore `agents/` but still count `agents/plans/`. If both list the same directory, `directories` wins.

**Which configs apply.** Every `.tally-config.toml` from the root of the Git repository down to the directory you scan applies, not just the nearest one. That is the nearest repository, so scanning inside a nested repository doesn't pick up the outer project's configs. Outside a repository, Tallyman only looks in the scanned directory itself.

- Each config is applied relative to where it lives, so `tallyman src/` honours the project's exclusions as well as any config in `src/`.
- Exclusions from every config add up. For specs, the deeper entry wins, and when two configs name the same directory, the deeper config wins.
- A parent's exclusion of the directory you scan, or of one above it, is skipped: you asked to scan it.
- `tallyman --setup` edits only the config in the scanned directory. Settings from parent configs are shown as "(set in a parent config)", and those from configs in subdirectories as "(set in a nested config)". Neither can be changed there; they stay in their own file, so editing it later reaches every directory below it. Copies of either kind that earlier versions wrote into the scanned directory's config are removed the next time setup saves. A directory a parent or nested config excludes is shown without its contents.
- If your home directory is itself a Git repository, as some dotfiles setups are, a `~/.tally-config.toml` applies to every directory below it that isn't in its own repository.
- Configs in subdirectories are merged in as Tallyman walks into them. They can add exclusions but can't re-include a directory excluded above. Their spec settings follow the same deeper-wins rules, so a subdirectory's `ignore = ["."]` turns specs off for that subtree.
- A broken config at or above the directory you scan stops the run with a message naming the file. A broken config in a subdirectory is skipped without a message, so scanning from the repo root and scanning from inside that subdirectory can differ.

**Without a terminal**, such as in CI or a pipe, a first run counts with default settings, writes no config, and prints a one-line note. `--setup` needs an interactive terminal.

Tallyman also respects the `NO_COLOR` environment variable to disable colored output, following the [no-color.org](https://no-color.org) convention.

### Excluding files by pattern

Some files can't be reached by excluding a directory. Some Rust projects, for example, keep unit tests in files beside the code they test: `src/routing/tests.rs` next to `src/routing/handlers.rs`. Excluding `src/routing` would drop the real code too. For those, add gitignore-style patterns:

```toml
[exclude]
directories = ["target"]
patterns = [
    "tests.rs",
    "testing.rs",
    "!src/keep/tests.rs",
]
```

- Patterns use `.gitignore` syntax and are matched relative to the directory of the config that declares them.
- Patterns, like directory excludes, apply inside nested Git repositories too, when you scan from outside them.
- A pattern without a slash, like `tests.rs`, matches at any depth, so `**/tests.rs` isn't needed.
- A pattern with a slash at the start or in the middle, like `/tests.rs` or `src/routing/tests.rs`, is matched from the config's directory. Use `**/routing/tests.rs` to match at any depth.
- A trailing `/` matches directories only, such as `fixtures/`.
- Within one config, later lines win, so `!src/keep/tests.rs` after `tests.rs` keeps that one file. Order matters, and setup keeps it.
- Patterns layer like nested `.gitignore` files: a deeper config's `!tests.rs` brings back what a shallower config's `tests.rs` excluded.
- A `!` only undoes other patterns. It never brings back gitignored files, excluded or hidden directories, or the files Tallyman always skips. As in Git, it also can't bring back a file whose directory a pattern excluded: `fixtures/` plus `!fixtures/keep.py` keeps nothing.
- A parent config's patterns never exclude the directory you scan, so a parent's `app/` doesn't empty `tallyman app/`. A parent's `app/**` does, since it matches the files inside rather than the directory, just as it would in Git.
- Setup shows directories a pattern excludes as "(excluded by pattern)", unless a config's `directories` list excludes them too: that is checked first, so they show as excluded by that config, and an entry in the scanned directory's config can still be toggled off. It doesn't edit patterns, but keeps them, in order, when it rewrites the config. Because setup can't re-create them, re-running `tallyman --setup` to replace a broken config loses its patterns. Fix the file by hand if it has any.
- When patterns remove anything, the report ends with a line such as `Excluded by [exclude] patterns: 12 files, 1 directory`. It counts files Tallyman would otherwise have counted, plus the directories a pattern skipped. Files inside a skipped directory aren't looked at, so they aren't in the file count.

Inline Rust test modules (`#[cfg(test)] mod tests { ... }`) share a file with the code they test, so no pattern can reach them. For those, see the next section.

### Leaving out Rust test code

Rust keeps most unit tests in a module at the bottom of the file it tests. To count only the code that ships, turn this on:

```toml
[rust]
exclude_test_modules = true
```

With it on, the test module below drops out of the count, and the three lines of `parse` still count:

```rust
pub fn parse(input: &str) -> usize {
    input.len()
}

#[cfg(test)]          // from here to the closing brace: not counted
mod tests {
    #[test]
    fn parses() {
        assert_eq!(super::parse("ab"), 2);
    }
}
```

- **What counts as test code.** Any item marked `#[cfg(test)]`, not just `mod tests`: a test-only `fn`, `use`, `struct` or `impl`, and test-only methods inside an `impl` or `trait`. Doc comments and other attributes on that item go with it, and code after it still counts.
- `#[cfg(all(test, ...))]` counts too, since it is test-only. `#[cfg(any(test, ...))]` doesn't: that code also builds outside tests.
- A file or module that starts with `#![cfg(test)]` is test code from top to bottom.
- **What it leaves alone.**
  - `#[cfg(test)]` on a statement inside a function, on a struct field, an enum variant or a match arm, and inside `macro_rules!` bodies.
  - `#[cfg(test)] mod tests;`: only that declaration drops. The file it points at counts as usual, unless it starts with `#![cfg(test)]`. Otherwise exclude it with a pattern such as `patterns = ["tests.rs"]`.
  - Integration tests in `tests/`, benches and examples: exclude those directories.
- **Where it applies.** It applies by directory, like every other setting. A config in a crate's directory can turn it on or off for that crate, and `false` overrides a parent's `true`.
- **Setup.** `--setup` has no toggle for it. It keeps the value when it rewrites the config, but, as with patterns, re-running setup to replace a broken config loses it.
- When something is left out, the report ends with a line such as `Excluded Rust test code: 2,412 lines in 37 files`. It counts every line left out, blank and comment lines included, so the totals, which leave those out by default, drop by less. A file that was all test code isn't counted as a Rust file.
- If Tallyman can't follow a file (an unterminated string, brackets that don't balance), it counts the whole file. It may miss some test code, but it never leaves out real code.

## Requirements

- Python 3.14+

## Contributing

Contributions are welcome! Whether it's adding support for a new language, improving detection, or fixing a bug, we'd love the help.

**Before opening a PR, please [create an issue](../../issues/new) first** to discuss what you have in mind. This helps make sure your idea aligns with the direction of the project and saves everyone time. Once we've agreed on the approach, fire away with the pull request.

## License

MIT License - Created by [Michael Kennedy](https://mkennedy.codes)
