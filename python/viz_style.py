"""
viz_style.py
============
A small matplotlib theme + palette so every chart reads as one system.

Colors come from a validated data-viz palette (colorblind-checked in both light
and dark modes). Rules honored here:
  * categorical hues assigned in a FIXED order, never cycled;
  * sequential (magnitude) encodings use ONE blue hue, light -> dark;
  * text stays in ink tokens, never the series color;
  * recessive gridlines/axes, no chartjunk, no dual axes.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: render straight to PNG
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# --- ink / chrome ---------------------------------------------------------- #
SURFACE = "#fcfcfb"
INK = "#0b0b0b"       # primary text
INK2 = "#52514e"      # secondary text
MUTED = "#898781"     # axis labels / ticks
GRID = "#e1e0d9"      # hairline gridlines
BASELINE = "#c3c2b7"  # axis / baseline

# --- categorical series (fixed order) -------------------------------------- #
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
BLUE = SERIES[0]
ACCENT = SERIES[0]

# --- sequential blue ramp (magnitude) -------------------------------------- #
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
             "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#0d366b"]
SEQ_BLUE = LinearSegmentedColormap.from_list(
    "seq_blue", ["#eef5fd", "#cde2fb", "#9ec5f4", "#6da7ec",
                 "#3987e5", "#2a78d6", "#1c5cab", "#104281"]
)

# --- status --------------------------------------------------------------- #
GOOD = "#0ca30c"
CRIT = "#d03b3b"

# Fixed category -> hue mapping (identity is stable across every chart).
CATEGORY_COLORS = {
    "Furniture": SERIES[0],
    "Lighting": SERIES[1],
    "Textiles": SERIES[2],
    "Kitchen & Dining": SERIES[3],
    "Decor": SERIES[4],
    "Outdoor": SERIES[5],
}


def apply_theme() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "font.size": 10.5,
        # dollar signs are literal currency, never math delimiters
        "text.parse_math": False,
        "text.color": INK,
        "axes.labelcolor": INK2,
        "axes.titlecolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.edgecolor": BASELINE,
        "axes.linewidth": 1.0,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.bottom": False,
        "ytick.left": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 110,
        "legend.frameon": False,
        "legend.fontsize": 9.5,
    })


def new_fig(w: float = 10, h: float = 5):
    fig, ax = plt.subplots(figsize=(w, h))
    return fig, ax


def titles(ax, title: str, subtitle: str | None = None) -> None:
    """A bold primary-ink title with an optional secondary-ink subtitle above."""
    if subtitle:
        ax.set_title(subtitle, loc="left", fontsize=10.5, color=INK2, pad=6)
        ax.text(0, 1.06, title, transform=ax.transAxes, fontsize=15,
                fontweight="bold", color=INK, va="bottom")
    else:
        ax.set_title(title, loc="left", fontsize=15, fontweight="bold",
                     color=INK, pad=8)


def grid_y_only(ax) -> None:
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)


def grid_off(ax) -> None:
    ax.grid(False)


def save(fig, name: str) -> str:
    path = f"charts/{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def usd(x, _=None) -> str:
    """Axis formatter: compact dollars ($1.2k / $3.4M)."""
    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:.1f}M"
    if abs(x) >= 1_000:
        return f"${x/1_000:.0f}k"
    return f"${x:.0f}"
