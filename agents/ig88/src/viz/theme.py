"""
IG-88 Visualization Theme — Consistent fonts, colors, and styling.
Shared across all Manim scenes for visual consistency.
"""

# Font families (must be installed in ~/Library/Fonts/ and in fc-list)
FONT_SANS = "Geist"              # Primary UI font
FONT_MONO = "Geist Mono"         # Numbers, data, code
FONT_FALLBACK = "sans-serif"     # Fallback if Geist not found

# Manim Text() font parameter
# Usage: Text("Hello", font=FONT_SANS)

# Colors (matches HTML viewer)
COLOR_BG = "#09090b"             # Near-black
COLOR_TEXT = "#fafafa"            # Primary text
COLOR_TEXT_MUTED = "#a1a1aa"      # Secondary text
COLOR_TEXT_DIM = "#71717a"        # Tertiary text

COLOR_ACCENT = "#22c55e"         # Green (positive P&L)
COLOR_LOSS = "#ef4444"           # Red (negative P&L)
COLOR_WARNING = "#f59e0b"        # Yellow/amber
COLOR_INFO = "#3b82f6"           # Blue
COLOR_PURPLE = "#a855f7"         # Purple
COLOR_CYAN = "#06b6d4"           # Cyan

# Manim color objects (for use in scenes)
from manim import *

MANIM_GREEN = "#22c55e"
MANIM_RED = "#ef4444"
MANIM_BLUE = "#3b82f6"
MANIM_YELLOW = "#f59e0b"
MANIM_CYAN = "#06b6d4"
MANIM_PURPLE = "#a855f7"
MANIM_WHITE = "#fafafa"
MANIM_GREY = "#71717a"
MANIM_BG = "#09090b"

# Regime colors
REGIME_COLORS = {
    "RISK_ON": "#22c55e",
    "NEUTRAL": "#f59e0b",
    "RISK_OFF": "#ef4444",
}


def styled_text(text: str, size: int = 20, weight: str = "NORMAL", color: str = MANIM_WHITE, font: str = FONT_SANS):
    """
    Create a Manim Text object with consistent styling.
    
    Args:
        text: The text content
        size: Font size (default 20)
        weight: "NORMAL", "BOLD", or "NORMAL"
        color: Hex color string
        font: Font family name (default Geist)
    
    Returns:
        Manim Text object
    """
    return Text(text, font_size=size, color=color, weight=weight, font=font)


def mono_text(text: str, size: int = 18, color: str = MANIM_WHITE, weight: str = "NORMAL"):
    """Create monospaced text for data/numbers."""
    return styled_text(text, size=size, color=color, weight=weight, font=FONT_MONO)


def header_text(text: str, size: int = 28, color: str = MANIM_WHITE):
    """Create header text."""
    return styled_text(text, size=size, weight="BOLD", color=color)


def muted_text(text: str, size: int = 16):
    """Create muted secondary text."""
    return styled_text(text, size=size, color=MANIM_GREY)


def positive_text(text: str, size: int = 18):
    """Create green positive text."""
    return styled_text(text, size=size, color=MANIM_GREEN, weight="BOLD")


def negative_text(text: str, size: int = 18):
    """Create red negative text."""
    return styled_text(text, size=size, color=MANIM_RED, weight="BOLD")


def stat_value(text: str, is_positive: bool = None, size: int = 18):
    """Create stat value with automatic color based on sentiment."""
    if is_positive is True:
        color = MANIM_GREEN
    elif is_positive is False:
        color = MANIM_RED
    else:
        color = MANIM_WHITE
    return mono_text(text, size=size, color=color, weight="BOLD")
