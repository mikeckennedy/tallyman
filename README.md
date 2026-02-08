# Tallyman

A command-line tool that summarizes the size of a codebase by language, showing lines of code with and without comments and blank lines.

## Overview

Point Tallyman at any project directory and get a quick breakdown of what's in it. It counts lines across languages  -  Python, Rust, JavaScript, CSS, HTML, Markdown, and more  -  and reports both the raw line count and the count excluding comments and blank lines. Results are grouped into categories (Code, Design, Docs) so you can see the shape of your project at a glance.

Tallyman automatically skips things that aren't your code: virtual environments, `node_modules`, build artifacts, `.git`, and generated or minified files. What you get back is a realistic picture of the code *you* wrote.

## Example Output

```
$ tallyman

  Python:
          10,213 lines of code
           9,100 excluding comments and blank lines

  CSS:
           5,000 lines of code
           4,500 excluding comments and blank lines

  Rust:
           1,200 lines of code
             900 excluding comments and blank lines

  Markdown:
           2,102 lines
           1,932 excluding blank lines

  ----------------------------------------------------------
  Totals:
  Code:   11,413 lines (Python + Rust + JS, etc)
  Design:  9,302 (CSS + HTML)
  Docs:    2,102 lines (markdown)
```

## Features

- **Dual line counts**  -  Total lines and lines excluding comments and blank lines, per language
- **Category totals**  -  Aggregated summaries across Code, Design, and Docs
- **Multi-language support**  -  Python, Rust, JavaScript, TypeScript, CSS, HTML, Markdown, and more
- **Smart exclusions**  -  Automatically ignores:
  - Virtual environments (`venv/`, `.venv/`, `env/`)
  - Node modules (`node_modules/`)
  - Build artifacts and caches
  - Version control directories (`.git/`)
  - Generated and minified files
- **Colorful terminal output**  -  Clean, readable formatting in the terminal
- **Realistic metrics**  -  Only counts the code you wrote, not third-party dependencies

## Language Categories

Tallyman groups languages into three categories for the summary totals:

| Category | Languages |
|----------|-----------|
| **Code** | Python, Rust, JavaScript, TypeScript, etc. |
| **Design** | CSS, HTML |
| **Docs** | Markdown |

## Installation

```bash
git clone https://github.com/mk/tallyman.git
cd tallyman

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

uv pip install -r requirements.txt
```

## Usage

```bash
# Analyze current directory
tallyman

# Analyze a specific path
tallyman /path/to/project

# Show help
tallyman --help
```

## Requirements

- Python 3.14+

## License

MIT License
