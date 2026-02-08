# Tallyman

**Know the shape of your project, not just the size.**

Tallyman is a command-line tool that gives you a real picture of your codebase - not just raw line counts, but where your effort actually lives. It groups results into meaningful categories like Code, Design, Docs, Specs, and Data, so you can see at a glance whether your project is mostly Python logic, CSS styling, or Markdown documentation.

[![PyPI](https://img.shields.io/pypi/v/tallyman-metrics?v=1)](https://pypi.org/project/tallyman-metrics/)
[![Python](https://img.shields.io/pypi/pyversions/tallyman-metrics?v=1)](https://pypi.org/project/tallyman-metrics/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

![Tallyman output showing language breakdown with colored percentage bar for a Python web project](https://mkennedy-shared.nyc3.digitaloceanspaces.com/github/tallyman-for-commandbook.webp)

## Install

```bash
uv tool install tallyman-metrics
```

Or with pip:

```bash
pip install tallyman-metrics
```

Then just point it at a project:

```bash
tallyman                    # analyze current directory
tallyman /path/to/project   # analyze a specific path
tallyman --setup            # re-run the interactive setup
tallyman --no-color         # disable colored output
```

## Why Tallyman?

Tools like [cloc](https://github.com/AlDanial/cloc), [tokei](https://github.com/XACode/tokei), and [scc](https://github.com/boyter/scc) are excellent at counting lines of code. If all you need is raw numbers, they're great choices.

But line counts alone don't tell you much about a project's *shape*. Is your codebase mostly application logic, or has the CSS layer quietly grown to rival your backend? Are those Markdown files general docs, or are they specifications driving your development? How much of your project is configuration and data files versus actual code?

**Tallyman answers these questions.** It organizes every recognized file into one of six categories - **Code**, **DevOps**, **Design**, **Docs**, **Specs**, and **Data** - and shows you both the raw line count and the "effective" line count (excluding comments and blank lines) for each.

A few things that set it apart:

- **Category-aware analysis** - Results grouped by intent, not just by file extension. You see *what kind* of work your project contains, not just how many lines of each language.
- **Automatic spec detection** - Markdown and reStructuredText files in directories like `specs/`, `plans/`, or `agents/` are automatically reclassified from Docs to Specs. If you're using planning documents to drive development (especially with AI-assisted workflows), Tallyman tracks that separately.
- **Interactive first-run setup** - On first run, Tallyman launches a TUI where you can walk your project's directory tree and mark directories to exclude or flag as spec directories. Your choices are saved to `.tally-config.toml` so subsequent runs are instant.
- **Gitignore-aware** - Tallyman reads your `.gitignore` and `.git/info/exclude` patterns automatically. It skips virtual environments, `node_modules`, build artifacts, and anything else you've already told Git to ignore.
- **Visual composition bar** - A colored percentage bar at the bottom shows you the language distribution of your project in a single glance.

![Tallyman interactive TUI setup showing directory tree with include/exclude toggles and spec directory markers](https://mkennedy-shared.nyc3.digitaloceanspaces.com/github/tallyman-setup.webp)

## Features

- **Dual line counts** - Total lines and effective lines (excluding comments and blanks) per language
- **Six categories** - Code, DevOps, Design, Docs, Specs, and Data, each with aggregated totals
- **40 languages** - From Python and Rust to Terraform and Docker, with full template support for HTML (Jinja, Nunjucks, Handlebars, and more)
- **Interactive TUI setup** - Visual directory tree for configuring exclusions and spec directories, powered by [Textual](https://github.com/Textualize/textual)
- **Beautiful output** - Colored, formatted results with a language composition bar, powered by [Rich](https://github.com/Textualize/rich)
- **Realistic metrics** - Only counts files *you* wrote, not third-party dependencies or generated code
- **Persistent config** - Your setup choices are saved to `.tally-config.toml` and reused on every run

## Supported Languages

Tallyman recognizes **40 languages** across six categories:

| Category | Languages |
|----------|-----------|
| **Code** | Python, Rust, Go, JavaScript, TypeScript, Java, C, C++, C#, Swift, Kotlin, Ruby, Shell, Lua, PHP, Perl, R, Dart, Scala, Elixir, Zig, Haskell, Erlang, OCaml, Nim, V |
| **DevOps** | Terraform, Makefile, Docker |
| **Design** | CSS, SCSS, LESS, HTML (+ 12 template formats), SVG |
| **Docs** | Markdown, reStructuredText |
| **Specs** | Markdown and reStructuredText files auto-detected in spec directories |
| **Data** | TOML, YAML, JSON, XML, SQL |

<details>
<summary>Full language details with file extensions</summary>

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
| C Header | `.h` |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx` |
| C# | `.cs` |
| Swift | `.swift` |
| Kotlin | `.kt`, `.kts` |
| Ruby | `.rb` |
| Shell | `.sh`, `.bash`, `.zsh` |
| Lua | `.lua` |
| PHP | `.php` |
| Perl | `.pl`, `.pm` |
| R | `.r`, `.R` |
| Dart | `.dart` |
| Scala | `.scala` |
| Elixir | `.ex`, `.exs` |
| Zig | `.zig` |
| Haskell | `.hs` |
| Erlang | `.erl` |
| OCaml | `.ml`, `.mli` |
| Nim | `.nim`, `.nims` |
| V | `.v`, `.vv` |

### DevOps

| Language | Extensions / Filenames |
|----------|----------------------|
| Terraform | `.tf`, `.tfvars` |
| Makefile | `.mk`, `Makefile`, `makefile`, `GNUmakefile` |
| Docker | `.dockerfile`, `Dockerfile*`, `docker-compose.yml/yaml`, `compose.yml/yaml` |

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

1. **Walk** your project directory, respecting gitignore patterns and your config exclusions
2. **Identify** each file's language by extension (O(1) lookup)
3. **Count** lines, classifying each as code, comment, or blank
4. **Aggregate** results by language and category
5. **Display** a colored report with per-language stats, category totals, and a composition bar

Spec directories (`specs/`, `plans/`, `specifications/`, `agents/`) are auto-detected. Any Markdown or reStructuredText files inside them are reclassified from Docs to Specs, giving you a clear picture of how much of your project is specification-driven.

Comment detection covers single-line comment styles (`#`, `//`, `--`, `%`, `;`). Multi-line comment blocks (`/* */`, `""" """`) are not currently detected - lines inside them are counted as code.

## Configuration

On first run, Tallyman launches an interactive TUI where you can browse your project tree and configure which directories to exclude or mark as spec directories. Your choices are saved to `.tally-config.toml` in the project root.

To re-run setup at any time:

```bash
tallyman --setup
```

Tallyman also respects the `NO_COLOR` environment variable to disable colored output, following the [no-color.org](https://no-color.org) convention.

## Requirements

- Python 3.14+

## Contributing

Contributions are welcome! Whether it's adding support for a new language, improving detection, or fixing a bug, we'd love the help.

**Before opening a PR, please [create an issue](../../issues/new) first** to discuss what you have in mind. This helps make sure your idea aligns with the direction of the project and saves everyone time. Once we've agreed on the approach, fire away with the pull request.

## License

MIT License - Created by [Michael Kennedy](https://mastodon.social/@mkennedy)
