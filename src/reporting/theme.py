#!/usr/bin/env python3
"""Chart rendering for the verification report.

Every figure is rendered TWICE -- once for the light surface and once for the
dark -- and both SVGs are embedded, with CSS showing whichever matches the
reader's theme. Re-rendering rather than colour-flipping is deliberate: dark
steps are chosen for the dark surface, not derived from the light ones.

Charts are inline SVG (not PNG) so they stay crisp when a researcher prints the
report or zooms in to check a bar against the data table beneath it.

Palette: the validated default categorical order. Hues are assigned in fixed
slot order and never cycled; past the point where the order stops validating,
series fold into "Other" rather than inventing a ninth hue.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Emit <text> elements rather than glyph outlines: roughly 5x smaller SVGs, and
# the labels stay selectable and searchable -- which matters when a researcher
# is checking a bar against the data table beneath it.
matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["font.family"] = ["DejaVu Sans"]  # metrics; the stack is swapped in at emit


FONT_STACK = "Public Sans, ui-sans-serif, -apple-system, Segoe UI, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Mode:
    name: str
    surface: str
    ink: str
    ink_soft: str
    grid: str
    series: tuple[str, ...]
    seq: tuple[str, ...]


LIGHT = Mode(
    name="light", surface="#fcfcfb", ink="#0b0b0b", ink_soft="#52514e", grid="#e4e3df",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    seq=("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#256abf", "#184f95", "#0d366b"),
)
DARK = Mode(
    name="dark", surface="#1a1a19", ink="#ffffff", ink_soft="#c3c2b7", grid="#3a3a37",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    seq=("#0d366b", "#184f95", "#256abf", "#2a78d6", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"),
)
MODES = (LIGHT, DARK)

# Ordinal ramps stop short of the surface-adjacent steps so the lightest mark
# still clears 2:1 contrast (light: no lighter than step 250; dark: no darker
# than step 600).
def ordinal_ramp(mode: Mode, n: int) -> list[str]:
    steps = mode.seq[1:] if mode.name == "light" else mode.seq[:-1]
    if n <= 1:
        return [steps[len(steps) // 2]]
    idx = np.linspace(0, len(steps) - 1, n)
    return [steps[int(round(i))] for i in idx]


def _fig(mode: Mode, w: float, h: float):
    fig, ax = plt.subplots(figsize=(w, h), dpi=100)
    fig.patch.set_facecolor(mode.surface)
    ax.set_facecolor(mode.surface)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(mode.grid)
        ax.spines[spine].set_linewidth(1.0)
    ax.tick_params(colors=mode.ink_soft, labelsize=9, length=0)
    for lbl in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        lbl.set_color(mode.ink_soft)
    return fig, ax


def _emit(fig, mode: Mode) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    svg = buf.getvalue()
    svg = svg[svg.index("<svg"):]
    # matplotlib emits a fixed pt size; let CSS drive the width instead.
    svg = re.sub(r'(<svg[^>]*?)width="[^"]*" height="[^"]*"', r"\1", svg, count=1)
    # matplotlib measured with DejaVu; hand the browser a real stack to render.
    svg = svg.replace("DejaVu Sans", FONT_STACK)
    return f'<div class="fig fig-{mode.name}">{svg}</div>'


def dual(render) -> str:
    """Render a chart function under both modes and return both SVGs."""
    return "".join(_emit(*render(mode)) for mode in MODES)


def _wrap(labels, width=28):
    out = []
    for lab in labels:
        lab = str(lab)
        if len(lab) <= width:
            out.append(lab)
            continue
        words, line, lines = lab.split(), "", []
        for word in words:
            if len(line) + len(word) + 1 > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        out.append("\n".join(lines))
    return out


# --------------------------------------------------------------------------
# Chart forms
# --------------------------------------------------------------------------

def hbar(labels, values, *, xlabel="", color_slot=0, ramp=False, height=None, value_fmt="{:,.0f}"):
    """Ranked magnitude. Horizontal because category names are long."""
    def render(mode: Mode):
        h = height or max(2.0, 0.32 * len(labels) + 0.8)
        fig, ax = _fig(mode, 7.4, h)
        colors = ordinal_ramp(mode, len(labels))[::-1] if ramp else [mode.series[color_slot]] * len(labels)
        y = np.arange(len(labels))[::-1]
        ax.barh(y, values, color=colors, height=0.66, zorder=3)
        ax.set_yticks(y, _wrap(labels))
        ax.set_xlabel(xlabel, color=mode.ink_soft, fontsize=9)
        ax.grid(axis="x", color=mode.grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        span = max(values) if len(values) else 1
        for yy, v in zip(y, values):
            ax.text(v + span * 0.012, yy, value_fmt.format(v), va="center",
                    fontsize=8.5, color=mode.ink_soft)
        ax.set_xlim(0, span * 1.14)
        return fig, mode
    return dual(render)


def stacked_pct(row_labels, col_labels, matrix, *, legend_title=""):
    """100% composition across an ordered category set."""
    matrix = np.asarray(matrix, dtype=float)
    totals = matrix.sum(axis=1, keepdims=True)
    pct = np.divide(matrix, np.where(totals == 0, 1, totals)) * 100

    def render(mode: Mode):
        fig, ax = _fig(mode, 7.4, max(2.2, 0.46 * len(row_labels) + 1.2))
        y = np.arange(len(row_labels))[::-1]
        left = np.zeros(len(row_labels))
        colors = ordinal_ramp(mode, len(col_labels))
        for j, col in enumerate(col_labels):
            widths = pct[:, j]
            # 2px surface gap between adjacent segments
            ax.barh(y, widths, left=left, height=0.62, color=colors[j],
                    edgecolor=mode.surface, linewidth=1.6, zorder=3, label=col)
            for yy, w, l in zip(y, widths, left):
                if w >= 7:
                    ax.text(l + w / 2, yy, f"{w:.0f}%", ha="center", va="center",
                            fontsize=8, color=mode.surface, zorder=4)
            left += widths
        ax.set_yticks(y, _wrap(row_labels, 24))
        ax.set_xlim(0, 100)
        ax.set_xlabel("share of videos (%)", color=mode.ink_soft, fontsize=9)
        leg = ax.legend(title=legend_title, loc="upper center", bbox_to_anchor=(0.5, -0.16),
                        ncol=min(4, len(col_labels)), frameon=False, fontsize=8.5)
        leg.get_title().set_color(mode.ink_soft)
        leg.get_title().set_fontsize(8.5)
        for text in leg.get_texts():
            text.set_color(mode.ink_soft)
        return fig, mode
    return dual(render)


def heatmap(row_labels, col_labels, matrix, *, cbar_label="% of row", annot=True):
    """Magnitude across two categorical axes -- one hue, light to dark."""
    matrix = np.asarray(matrix, dtype=float)

    def render(mode: Mode):
        fig, ax = _fig(mode, 7.6, max(2.4, 0.42 * len(row_labels) + 1.6))
        steps = mode.seq if mode.name == "light" else mode.seq
        cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", steps, N=256)
        vmax = matrix.max() if matrix.size and matrix.max() > 0 else 1
        im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(col_labels)), _wrap(col_labels, 14), rotation=35, ha="right")
        ax.set_yticks(range(len(row_labels)), _wrap(row_labels, 26))
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        if annot:
            for i in range(matrix.shape[0]):
                for j in range(matrix.shape[1]):
                    val = matrix[i, j]
                    # ink flips on the dark half of the ramp so text stays legible
                    dark_cell = val > vmax * 0.55
                    ink = "#ffffff" if (dark_cell and mode.name == "light") else (
                        "#0b0b0b" if dark_cell else mode.ink_soft)
                    ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=8, color=ink)
        cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
        cbar.set_label(cbar_label, color=mode.ink_soft, fontsize=8.5)
        cbar.ax.tick_params(colors=mode.ink_soft, labelsize=8, length=0)
        cbar.outline.set_visible(False)
        return fig, mode
    return dual(render)


def lines(x, series: dict, *, ylabel="", xlabel="", direct_label=True):
    """Change over time. Max 8 series; the caller folds the tail into Other."""
    def render(mode: Mode):
        fig, ax = _fig(mode, 7.4, 3.4)
        for i, (name, ys) in enumerate(series.items()):
            color = mode.series[i % len(mode.series)]
            ax.plot(x, ys, color=color, linewidth=2.0, marker="o", markersize=4,
                    markeredgecolor=mode.surface, markeredgewidth=1.2, zorder=3, label=name)
            if direct_label and len(x):
                ax.annotate(name, (x[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                            fontsize=8.5, color=color, va="center")
        ax.grid(axis="y", color=mode.grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.set_ylabel(ylabel, color=mode.ink_soft, fontsize=9)
        ax.set_xlabel(xlabel, color=mode.ink_soft, fontsize=9)
        if len(series) > 1:
            leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18),
                            ncol=min(4, len(series)), frameon=False, fontsize=8.5)
            for text in leg.get_texts():
                text.set_color(mode.ink_soft)
        ax.margins(x=0.12)
        return fig, mode
    return dual(render)


def histogram(values, *, bins=40, xlabel="", ylabel="videos", logx=False):
    def render(mode: Mode):
        fig, ax = _fig(mode, 7.4, 2.8)
        data = np.asarray([v for v in values if np.isfinite(v)])
        edges = (np.logspace(np.log10(max(data.min(), 1)), np.log10(data.max()), bins)
                 if logx and len(data) else bins)
        ax.hist(data, bins=edges, color=mode.series[0], zorder=3)
        if logx:
            ax.set_xscale("log")
        ax.grid(axis="y", color=mode.grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.set_xlabel(xlabel, color=mode.ink_soft, fontsize=9)
        ax.set_ylabel(ylabel, color=mode.ink_soft, fontsize=9)
        return fig, mode
    return dual(render)


def dot_range(labels, values, *, xlabel="", color_slot=0, value_fmt="{:,.0f}"):
    """A dot plot -- for medians across categories, where bars would imply a sum."""
    def render(mode: Mode):
        fig, ax = _fig(mode, 7.4, max(2.0, 0.4 * len(labels) + 0.9))
        y = np.arange(len(labels))[::-1]
        ax.hlines(y, 0, values, color=mode.grid, linewidth=2.0, zorder=2)
        ax.scatter(values, y, s=64, color=mode.series[color_slot], zorder=3,
                   edgecolor=mode.surface, linewidth=1.4)
        ax.set_yticks(y, _wrap(labels, 26))
        ax.grid(axis="x", color=mode.grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.set_xlabel(xlabel, color=mode.ink_soft, fontsize=9)
        span = max(values) if len(values) else 1
        for yy, v in zip(y, values):
            ax.text(v + span * 0.02, yy, value_fmt.format(v), va="center",
                    fontsize=8.5, color=mode.ink_soft)
        ax.set_xlim(0, span * 1.18)
        return fig, mode
    return dual(render)
