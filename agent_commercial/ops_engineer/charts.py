"""
Trend charts as WhatsApp images — the escape hatch instead of a dashboard.

render_trend() draws up to three points over a window, marks the moment of an
action and a target band if given, breaks the line over gaps in the data (it never
draws through missing readings), and returns PNG bytes. It uses matplotlib's
Figure API (no pyplot global state), so charts for two people can render at once
in worker threads.

caption_for() writes the caption from the same samples, so every number a person
sees on or under the chart comes from the data.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

Series = List[Tuple[datetime, float]]

# Categorical slots 1-3 of the validated reference palette (light surface), in fixed order.
_SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
_SURFACE, _INK, _INK_2, _GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"


def _hhmm(dt: datetime, tz: Any) -> str:
    return dt.astimezone(tz).strftime("%H:%M") if tz else dt.strftime("%H:%M")


def caption_for(series: Dict[str, Series], tz: Any, hours: float) -> str:
    parts = []
    for pid, pts in series.items():
        if not pts:
            parts.append(f"{pid}: no readings in the last {hours:g} h")
            continue
        lo = min(pts, key=lambda p: p[1])
        hi = max(pts, key=lambda p: p[1])
        parts.append(f"{pid}: {pts[0][1]:g} → {pts[-1][1]:g} (min {lo[1]:g} at {_hhmm(lo[0], tz)}, "
                     f"max {hi[1]:g} at {_hhmm(hi[0], tz)})")
    return f"Last {hours:g} h — " + "; ".join(parts)


def _with_gaps(ts: List[datetime], vals: List[float]) -> Tuple[list, list]:
    """Insert a break where readings stop for more than 3× the usual spacing."""
    gaps = sorted((ts[i + 1] - ts[i]).total_seconds() for i in range(len(ts) - 1))
    usual = gaps[len(gaps) // 2] if gaps else 0
    xs, ys = [ts[0]], [vals[0]]
    for i in range(1, len(ts)):
        if usual and (ts[i] - ts[i - 1]).total_seconds() > 3 * usual:
            xs.append(ts[i - 1])
            ys.append(float("nan"))
        xs.append(ts[i])
        ys.append(vals[i])
    return xs, ys


def render_trend(series: Dict[str, Series], *, tz: Any = None, title: str = "",
                 mark_at: Optional[datetime] = None, target: Optional[float] = None,
                 band: Optional[float] = None) -> bytes:
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8, 4), dpi=120, facecolor=_SURFACE)
    ax = fig.subplots()
    ax.set_facecolor(_SURFACE)
    ends = []
    for slot, (pid, pts) in enumerate(list(series.items())[:len(_SERIES)]):
        if not pts:
            continue
        ts = [t.astimezone(tz) if tz else t for t, _ in pts]
        xs, ys = _with_gaps(ts, [v for _, v in pts])
        ax.plot(xs, ys, color=_SERIES[slot], linewidth=2, label=pid, solid_capstyle="round")
        ends.append((ts[-1], pts[-1][1]))
    drawn = len(ends)
    if target is not None:
        ax.axhline(target, linestyle="--", linewidth=1, color=_INK_2)
        ax.annotate(f"target {target:g}", (0, target), xycoords=("axes fraction", "data"), xytext=(2, 3),
                    textcoords="offset points", fontsize=8, color=_INK_2)
        if band:
            ax.axhspan(target - band, target + band, color=_INK_2, alpha=0.08, linewidth=0)
    if mark_at is not None:
        at = mark_at.astimezone(tz) if tz else mark_at
        ax.axvline(at, color=_INK_2, linewidth=1.2, linestyle=":")
        ax.annotate("action", (at, 1), xycoords=("data", "axes fraction"), xytext=(3, -10),
                    textcoords="offset points", fontsize=8, color=_INK_2)
    # Direct label on each latest reading only (never a number on every point), nudged apart
    # on screen so close values don't print over each other.
    ax.autoscale_view()
    placed = []
    for x, y in sorted(ends, key=lambda e: e[1]):
        py = ax.transData.transform((mdates.date2num(x), y))[1]
        shown = max(py, placed[-1] + 11) if placed else py
        placed.append(shown)
        ax.annotate(f"{y:g}", (x, y), xytext=(6, shown - py), textcoords="offset pixels",
                    va="center", fontsize=8, color=_INK)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_GRID)
    ax.tick_params(colors=_INK_2, labelsize=8)
    ax.set_title(title, fontsize=11, color=_INK, loc="left")
    if drawn >= 2:                                   # one series: the title names it, no legend box
        ax.legend(fontsize=8, loc="best", frameon=False, labelcolor=_INK)
    fig.autofmt_xdate()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_SURFACE)
    return buf.getvalue()
