"""Bundled fonts for image export."""

from __future__ import annotations

from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent
JETBRAINS_MONO_REGULAR = FONTS_DIR / 'JetBrainsMono-Regular.ttf'
JETBRAINS_MONO_BOLD = FONTS_DIR / 'JetBrainsMono-Bold.ttf'
