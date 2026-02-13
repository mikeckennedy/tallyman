"""Generate PNG summary card from tallyman results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tallyman import __version__
from tallyman.aggregator import TallyResult, language_percentages
from tallyman.display import _language_display_names

IMAGE_WIDTH = 1200
PADDING = 60
TITLE_FONT_SIZE = 36
BODY_FONT_SIZE = 24
LEGEND_FONT_SIZE = 16
LINE_HEIGHT = 36
LEGEND_LINE_HEIGHT = 24
BAR_HEIGHT = 28
BAR_GAP = 2  # px gap between bar segments (filled with background)
SMALL_LANGUAGE_THRESHOLD = 2.0
MAX_LEGEND_ITEMS = 5  # show at most this many languages; remainder grouped as "Other"


@dataclass(slots=True)
class ImageTheme:
    """Colors for image rendering (hex strings)."""

    background: str
    text: str
    text_dimmed: str
    bar_background: str
    attribution: str


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert '#rrggbb' to (r, g, b)."""
    hex_str = hex_str.lstrip('#')
    return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


DARK_THEME = ImageTheme(
    background='#1e1e2e',
    text='#cdd6f4',
    text_dimmed='#a6adc8',
    bar_background='#313244',
    attribution='#6c7086',
)

LIGHT_THEME = ImageTheme(
    background='#ffffff',
    text='#4c4f69',
    text_dimmed='#6c7086',
    bar_background='#e6e9ef',
    attribution='#9ca0b0',
)


def _rich_color_to_rgb(name: str) -> tuple[int, int, int]:
    """Convert Rich color name to (r, g, b) for Pillow."""
    from rich.color import Color

    color = Color.parse(name)
    triplet = color.get_truecolor(None, True)
    return (triplet.red, triplet.green, triplet.blue)


def _load_font(size: int, bold: bool = False):
    """Load monospace font: bundled JetBrains Mono, then system fallbacks."""
    from PIL import ImageFont

    from tallyman.fonts import JETBRAINS_MONO_BOLD, JETBRAINS_MONO_REGULAR

    path = JETBRAINS_MONO_BOLD if bold else JETBRAINS_MONO_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size)

    # System fallbacks
    system_fonts = [
        '/System/Library/Fonts/Monaco.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        'C:\\Windows\\Fonts\\consola.ttf',
    ]
    for font_path in system_fonts:
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size)

    return ImageFont.load_default()


def _cap_legend(
    main_langs: list[tuple],
    display_names: dict,
) -> list[str]:
    """Build legend parts, capping at MAX_LEGEND_ITEMS and grouping the rest as 'Other'."""
    legend_parts: list[str] = []
    overflow_pct = 0.0
    for i, (lang, pct) in enumerate(main_langs):
        if i >= MAX_LEGEND_ITEMS:
            overflow_pct += pct
            continue
        if lang is None:
            overflow_pct += pct
        else:
            name = display_names.get(lang, lang.name)
            legend_parts.append(f'{name} {pct:.0f}%')
    if overflow_pct > 0:
        legend_parts.append(f'Other {overflow_pct:.0f}%')
    return legend_parts


def generate_image(
    result: TallyResult,
    directory: str,
    output_path: Path,
    theme: ImageTheme,
) -> None:
    """Render tallyman summary to a PNG file. Pillow imported lazily on first use."""
    from PIL import Image, ImageDraw

    bg_rgb = _hex_to_rgb(theme.background)
    text_rgb = _hex_to_rgb(theme.text)
    dim_rgb = _hex_to_rgb(theme.text_dimmed)
    attr_rgb = _hex_to_rgb(theme.attribution)

    font_title = _load_font(TITLE_FONT_SIZE, bold=True)
    font_body = _load_font(BODY_FONT_SIZE, bold=False)
    font_legend = _load_font(LEGEND_FONT_SIZE, bold=False)
    font_attr = _load_font(14, bold=False)

    # Compute height: title + spacing + category lines + combined + bar + legend + attribution
    active_categories = sorted(
        (c for c in result.by_category if c.total_lines > 0),
        key=lambda c: c.effective_lines,
        reverse=True,
    )
    num_category_lines = len(active_categories) + 1 if active_categories else 0  # +1 for Combined
    has_bar = result.grand_total_lines > 0
    percentages = language_percentages(result) if has_bar else []
    main_langs = [(lang, pct) for lang, pct in percentages if pct >= SMALL_LANGUAGE_THRESHOLD]
    other_pct = sum(pct for _, pct in percentages if pct < SMALL_LANGUAGE_THRESHOLD)
    if other_pct > 0:
        main_langs.append((None, other_pct))

    # Pre-compute legend parts (capped at MAX_LEGEND_ITEMS + Other)
    display_names = _language_display_names(result) if result.by_language else {}
    legend_parts: list[str] = []
    if has_bar and main_langs:
        legend_parts = _cap_legend(main_langs, display_names)

    content_lines = 1 + num_category_lines + 1  # title, categories, attribution
    if not result.by_language:
        content_lines = 2  # title + "No recognized source files"

    title_gap = 40  # extra space below the title
    separator_gap = 14 if active_categories else 0  # space for the line above "Total:"
    bar_section = (BAR_HEIGHT + 16 + LEGEND_LINE_HEIGHT) if has_bar else 0
    height = PADDING * 2 + content_lines * LINE_HEIGHT + title_gap + separator_gap + bar_section + LINE_HEIGHT
    img = Image.new('RGB', (IMAGE_WIDTH, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    y = PADDING

    # Title
    title = f'Code stats for {directory}'
    draw.text((PADDING, y), title, font=font_title, fill=text_rgb)
    y += LINE_HEIGHT + title_gap

    if not result.by_language:
        draw.text((PADDING, y), 'No recognized source files found.', font=font_body, fill=dim_rgb)
        y += LINE_HEIGHT * 2
    else:
        # Category totals
        max_name_len = max((len(c.name) for c in active_categories), default=0)
        max_name_len = max(max_name_len, len('Combined'))

        for cat in active_categories:
            if len(cat.languages) <= 3:
                lang_list = ' + '.join(cat.languages)
            else:
                lang_list = ' + '.join(cat.languages[:3]) + ', etc'
            line = f'{cat.name}:'.ljust(max_name_len + 1) + f'{cat.effective_lines:>10,} lines ({lang_list})'
            draw.text((PADDING, y), line, font=font_body, fill=text_rgb)
            y += LINE_HEIGHT

        if active_categories:
            # Separator line above total
            y += 4
            draw.line((PADDING, y, IMAGE_WIDTH - PADDING, y), fill=dim_rgb, width=1)
            y += 10

            combined = sum(c.effective_lines for c in active_categories)
            total_line = 'Total:'.ljust(max_name_len + 1) + f'{combined:>10,} lines'
            draw.text((PADDING, y), total_line, font=font_body, fill=text_rgb)
            y += LINE_HEIGHT

        # Percentage bar -- square segments separated by background-color gaps
        if has_bar and main_langs:
            y += 8
            bar_left = PADDING
            bar_right = IMAGE_WIDTH - PADDING
            bar_top = y
            bar_bottom = y + BAR_HEIGHT
            total_width = bar_right - bar_left
            x = bar_left
            for i, (lang, pct) in enumerate(main_langs):
                if pct <= 0:
                    continue
                if i == len(main_langs) - 1:
                    seg_right = bar_right
                else:
                    segment_width = max(4, int(total_width * pct / 100))
                    segment_width = min(segment_width, bar_right - x)
                    seg_right = x + segment_width
                if seg_right <= x:
                    continue
                rgb = _rich_color_to_rgb(lang.color) if lang is not None else _rich_color_to_rgb('grey50')
                draw.rectangle((x, bar_top, seg_right - BAR_GAP, bar_bottom), fill=rgb)
                x = seg_right
            y = bar_bottom + 12

            # Legend -- single line, capped to MAX_LEGEND_ITEMS + Other
            legend = '  \u00b7  '.join(legend_parts)
            draw.text((PADDING, y), legend, font=font_legend, fill=dim_rgb)
            y += LEGEND_LINE_HEIGHT

    y += 8
    # Attribution
    attr_text = f'tallyman v{__version__}'
    bbox = font_attr.getbbox(attr_text)
    attr_x = IMAGE_WIDTH - PADDING - (bbox[2] - bbox[0])
    draw.text((attr_x, y), attr_text, font=font_attr, fill=attr_rgb)

    img.save(output_path, 'PNG')


def slugify_directory_name(name: str) -> str:
    """Convert directory name to URL-slug style for filename."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug or 'tallyman-report'


def resolve_image_path(directory_name: str, desktop_preferred: bool = True) -> Path:
    """Resolve output path: Desktop (or cwd) + slugified name + numeric suffix if exists."""
    if desktop_preferred:
        desktop = Path.home() / 'Desktop'
        if desktop.is_dir():
            base_dir = desktop
        else:
            base_dir = Path.cwd()
    else:
        base_dir = Path.cwd()

    slug = slugify_directory_name(directory_name)
    candidate = base_dir / f'{slug}.png'
    if not candidate.exists():
        return candidate
    n = 1
    while True:
        candidate = base_dir / f'{slug}-{n}.png'
        if not candidate.exists():
            return candidate
        n += 1
