"""Generate PNG summary card from tallyman results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Union

from tallyman import __version__
from tallyman.aggregator import TallyResult, active_categories, bar_segments, percent_label, segment_widths

if TYPE_CHECKING:  # Pillow is imported lazily at runtime
    from PIL.ImageFont import FreeTypeFont, ImageFont

IMAGE_WIDTH = 1200
PADDING = 60
TITLE_FONT_SIZE = 36
BODY_FONT_SIZE = 24
LEGEND_FONT_SIZE = 16
LINE_HEIGHT = 36
LEGEND_LINE_HEIGHT = 24
BAR_HEIGHT = 28
BAR_GAP = 2  # px gap between bar segments (filled with background)
MIN_SEGMENT_PX = 4  # the narrowest a bar segment gets; must stay above BAR_GAP or a segment would have no width
MAX_LEGEND_ITEMS = 5  # name at most this many languages, in the bar and the legend; the rest are grouped as "Other"
LEGEND_SEPARATOR = '  \u00b7  '


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
    """Convert Rich color name to (r, g, b) for Pillow.

    Falls back to medium grey if the color name is not recognised by Rich,
    so an invalid colour in the language registry never crashes the whole run.
    """
    from rich.color import Color, ColorParseError

    try:
        color = Color.parse(name)
    except ColorParseError:
        return (128, 128, 128)
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


def _fit_text(text: str, font: Union[FreeTypeFont, ImageFont], max_width: int) -> str:
    """Shorten *text* with an ellipsis until it fits in *max_width* pixels."""
    if font.getlength(text) <= max_width:
        return text
    while len(text) > 1 and font.getlength(text + '…') > max_width:
        text = text[:-1]
    return text.rstrip() + '…'


def generate_image(
    result: TallyResult,
    directory: str,
    output_path: Path,
    theme: ImageTheme,
    *,
    with_spaces: bool = False,
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
    categories = active_categories(result, with_spaces=with_spaces)
    num_category_lines = len(categories) + 1 if categories else 0  # +1 for Combined
    segments = bar_segments(result, with_spaces=with_spaces, max_languages=MAX_LEGEND_ITEMS)
    has_bar = bool(segments)  # no effective lines: no bar, and no room left for one

    content_lines = 1 + num_category_lines + 1  # title, categories, attribution
    if not result.by_language:
        content_lines = 2  # title + "No recognized source files"

    title_gap = 40  # extra space below the title
    separator_gap = 14 if categories else 0  # space for the line above "Total:"
    bar_section = (BAR_HEIGHT + 16 + LEGEND_LINE_HEIGHT) if has_bar else 0
    height = PADDING * 2 + content_lines * LINE_HEIGHT + title_gap + separator_gap + bar_section + LINE_HEIGHT
    img = Image.new('RGB', (IMAGE_WIDTH, height), bg_rgb)
    draw = ImageDraw.Draw(img)

    y = PADDING

    # Title
    title = _fit_text(f'Code stats for {directory}', font_title, IMAGE_WIDTH - 2 * PADDING)
    draw.text((PADDING, y), title, font=font_title, fill=text_rgb)
    y += LINE_HEIGHT + title_gap

    if not result.by_language:
        draw.text((PADDING, y), 'No recognized source files found.', font=font_body, fill=dim_rgb)
        y += LINE_HEIGHT * 2
    else:
        # Category totals
        max_name_len = max((len(c.name) for c in categories), default=0)
        max_name_len = max(max_name_len, len('Combined'))

        for cat in categories:
            if len(cat.languages) <= 3:
                lang_list = ' + '.join(cat.languages)
            else:
                lang_list = ' + '.join(cat.languages[:3]) + ', etc'
            lines = cat.shown_lines(with_spaces=with_spaces)
            line = f'{cat.name}:'.ljust(max_name_len + 1) + f'{lines:>10,} lines ({lang_list})'
            draw.text((PADDING, y), line, font=font_body, fill=text_rgb)
            y += LINE_HEIGHT

        if categories:
            # Separator line above total
            y += 4
            draw.line((PADDING, y, IMAGE_WIDTH - PADDING, y), fill=dim_rgb, width=1)
            y += 10

            combined = sum(c.shown_lines(with_spaces=with_spaces) for c in categories)
            total_line = 'Total:'.ljust(max_name_len + 1) + f'{combined:>10,} lines'
            draw.text((PADDING, y), total_line, font=font_body, fill=text_rgb)
            y += LINE_HEIGHT

        # Percentage bar -- square segments separated by background-color gaps
        if has_bar:
            y += 8
            bar_top = y
            bar_bottom = y + BAR_HEIGHT
            widths = segment_widths([s.percent for s in segments], IMAGE_WIDTH - 2 * PADDING, MIN_SEGMENT_PX)
            x = PADDING
            for segment, width in zip(segments, widths):
                draw.rectangle((x, bar_top, x + width - BAR_GAP, bar_bottom), fill=_rich_color_to_rgb(segment.color))
                x += width
            y = bar_bottom + 12

            # Legend -- single line, one entry per segment (at most MAX_LEGEND_ITEMS languages + Other)
            legend = LEGEND_SEPARATOR.join(f'{s.label} {percent_label(s.percent)}' for s in segments)
            draw.text((PADDING, y), legend, font=font_legend, fill=dim_rgb)
            y += LEGEND_LINE_HEIGHT

    y += 28
    # Attribution -- each line right-aligned to the bar's right edge
    right_edge = IMAGE_WIDTH - PADDING
    attr_line1 = f'tallyman v{__version__}'
    attr_line2 = 'mkennedy.codes/tools/tallyman'

    bbox1 = font_attr.getbbox(attr_line1)
    draw.text((right_edge - (bbox1[2] - bbox1[0]), y), attr_line1, font=font_attr, fill=attr_rgb)
    y += 18
    bbox2 = font_attr.getbbox(attr_line2)
    draw.text((right_edge - (bbox2[2] - bbox2[0]), y), attr_line2, font=font_attr, fill=attr_rgb)

    img.save(output_path, 'PNG')


MAX_SLUG_LENGTH = 100  # well under the 255-byte filename limit, leaving room for '-N.png'


def slugify_directory_name(name: str) -> str:
    """Convert directory name to URL-slug style for filename (ASCII only, at most MAX_SLUG_LENGTH chars)."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug[:MAX_SLUG_LENGTH].rstrip('-') or 'tallyman-report'


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
