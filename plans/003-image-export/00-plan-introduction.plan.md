# Image Export Feature - Build Plan

## Problem

Tallyman produces great terminal output, but there's no way to share it visually on social media, GitHub READMEs, or project pages. A `--image` flag that generates a polished PNG would make tallyman results shareable.

## What We're Building

A new `--image` CLI flag that generates a **PNG image** of the tallyman summary card. The image is a graphical version of the category totals + percentage bar + legend, designed to look better than a terminal screenshot. Output goes to the user's Desktop with the project name as the filename.

## Visual Design

The image uses a **card-style layout** at 1200px wide, with height that adjusts to content:

```
+--------------------------------------------------------------+
|                                                              |
|   Report for talk-python-training-courses                    |
|                                                              |
|   Code:      56,920 lines  (Python + JavaScript + Shell)     |
|   Specs:     49,621 lines  (Markdown)                        |
|   Docs:      23,375 lines  (Markdown)                        |
|   Design:    13,188 lines  (HTML + CSS)                      |
|   Data:         820 lines  (JSON + TOML)                     |
|   DevOps:       162 lines  (Docker)                          |
|   Combined: 144,086 lines                                    |
|                                                              |
|   [========== colored percentage bar ===========]            |
|   Python 35%  ·  Markdown (specs) 34%  ·  ...               |
|                                                              |
|                                  tallyman v0.x.x             |
+--------------------------------------------------------------+
```

**Dark theme** (default): Dark blue-gray background (#1e1e2e), light text (#cdd6f4), with a subtle card area. **Light theme**: White background, dark text, light card area.

Key visual improvements over terminal output:

- Anti-aliased text with a proper monospace font
- Rounded corners on the percentage bar segments
- Better spacing and padding
- Richer RGB colors (not limited to 256-color terminal palette)
- Clean, social-media-ready dimensions

## Technical Approach

### Library: Pillow (PIL)

Pillow gives full programmatic control over the image. It's a pure Python install (wheels for all platforms), no system dependencies like Cairo. We draw text, rectangles, and rounded shapes directly.

**New dependency**: `Pillow>=10.0.0` added to `pyproject.toml`.

### Color Mapping: Rich Color Names to RGB

The `Language.color` field uses Rich color names (`'yellow'`, `'dodger_blue'`, etc.). We use Rich's built-in `Color.parse(name).get_truecolor()` to convert these to RGB tuples for Pillow. This is already a dependency, so no extra code to maintain a color table.

However, for the image we can optionally enhance certain colors (e.g. make `'yellow'` a richer gold instead of terminal yellow) since we're not constrained by terminal palette. We'll build a small override map for colors that look better in a graphical context.

### Font: Bundled Monospace Font

For consistent, high-quality rendering across all platforms, we'll bundle a monospace font as package data. **JetBrains Mono** (OFL-licensed, freely redistributable) is an excellent choice -- Regular and Bold weights, approximately 180KB total.

Files stored at `src/tallyman/fonts/JetBrainsMono-Regular.ttf` and `src/tallyman/fonts/JetBrainsMono-Bold.ttf`, included via `pyproject.toml` package data configuration.

Fallback: if font loading fails for any reason, attempt system fonts (Menlo, Consolas, DejaVu Sans Mono) before Pillow's built-in default.

### Desktop Path Detection

Cross-platform desktop detection:

```python
desktop = Path.home() / 'Desktop'
```

If `~/Desktop` doesn't exist, fall back to the current working directory with a warning message.

### Filename: Slugified Project Name

```python
slug = re.sub(r'[^a-z0-9]+', '-', directory_name.lower()).strip('-')
# e.g. "Talk Python Training" -> "talk-python-training"
```

If `talk-python-training.png` already exists, try `talk-python-training-1.png`, `talk-python-training-2.png`, etc.

## CLI Interface

| Flag            | Effect                                         |
| --------------- | ---------------------------------------------- |
| `--image`       | Generate PNG with dark theme, save to Desktop  |
| `--image-light` | Generate PNG with light theme, save to Desktop |

Both flags run the normal terminal display AND generate the image. After generating, print the output path: `Image saved to ~/Desktop/project-name.png`

In [cli.py](../../src/tallyman/cli.py), add two new arguments and call image generation after `display_results()`:

```python
parser.add_argument('--image', action='store_true', help='Generate a summary image on the Desktop')
parser.add_argument('--image-light', action='store_true', help='Generate a light-themed summary image on the Desktop')
```

## Files Changed

| File                                               | Changes                                                                          |
| -------------------------------------------------- | -------------------------------------------------------------------------------- |
| [src/tallyman/image.py](../../src/tallyman/image.py)     | **New module** -- image generation logic, theme definitions, drawing functions   |
| [src/tallyman/cli.py](../../src/tallyman/cli.py)         | Add `--image` and `--image-light` args, call image generation after display      |
| [src/tallyman/fonts/](../../src/tallyman/fonts/)         | **New directory** -- bundled JetBrains Mono font files (Regular + Bold)          |
| [pyproject.toml](../../pyproject.toml)                   | Add `Pillow>=10.0.0` dependency, configure font package data                     |
| [tests/test_image.py](../../tests/test_image.py)         | **New test module** -- image generation, filename slugification, theme rendering |
| [plans/003-image-export/](.) | **Plan document** stored per project conventions                                 |

## Implementation Phases

### Phase 1: Image rendering module (`image.py`)

Core rendering engine:

- Theme dataclass with colors for background, text, dimmed text, bar background, card background
- Dark and light theme presets
- `generate_image(result, directory, output_path, theme)` main entry point
- Helper functions: draw header, draw category rows, draw percentage bar, draw legend, draw attribution
- Font loading with fallback chain
- Rich color name to RGB conversion using `rich.color.Color`
- Percentage bar with rounded rectangle segments using `ImageDraw.rounded_rectangle()`

### Phase 2: CLI integration and file output

- `--image` and `--image-light` argument parsing in [cli.py](../../src/tallyman/cli.py)
- `_resolve_image_path(directory_name)` -- Desktop detection, slugification, numeric suffix
- Wire into pipeline: after `display_results()`, conditionally call `generate_image()`
- Print confirmation message with the saved file path

### Phase 3: Font bundling and packaging

- Download JetBrains Mono Regular + Bold OFL font files
- Place in `src/tallyman/fonts/` with an `__init__.py` for package access
- Update `pyproject.toml` to include font files as package data
- Add Pillow to dependencies

### Phase 4: Tests

- Test slugification (spaces, special chars, unicode)
- Test numeric suffix logic (no conflict, conflict with 1, conflict with multiple)
- Test desktop path resolution (exists vs fallback)
- Test image generation produces valid PNG (check file header bytes)
- Test dark and light themes produce different images
- Test with empty results (no recognized files)
- Test color conversion from Rich names to RGB

## Notes

- The image module should be designed so Pillow is only imported when `--image` is actually used, avoiding import overhead for normal runs.
- Image generation reuses the same `TallyResult` that display uses -- no re-scanning needed.
- The `_language_display_names()` logic from [display.py](../../src/tallyman/display.py) should be extracted or shared so image.py can use the same name disambiguation.
