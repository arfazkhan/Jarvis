"""
Time-aware fault confirmation helpers (ported from open-fdd, MIT — see NOTICE).

A raw fault mask is only *confirmed* once it has stayed true for
``confirm_seconds`` of real elapsed time (actual timestamp gaps, not sample
counts), so a single noisy sample never becomes a fault.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sample_durations(index: pd.Index, poll_seconds: float) -> pd.Series | None:
    """Seconds each sample "covers" (gap to the next sample); the last sample
    gets the median gap. None when the index is not a DatetimeIndex."""
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return None
    if len(index) == 1:
        return pd.Series([float(poll_seconds)], index=index)
    ts = pd.DatetimeIndex(index).to_series()
    secs = ts.shift(-1).sub(ts).dt.total_seconds().clip(lower=0.0)
    med = float(secs.iloc[:-1].median()) if secs.iloc[:-1].notna().any() else float(poll_seconds)
    if not np.isfinite(med) or med < 0:
        med = float(max(poll_seconds, 0.0))
    secs = secs.copy()
    secs.iloc[-1] = med
    return secs.astype(float)


def confirm_fault(raw: pd.Series, *, poll_seconds: float, confirm_seconds: float) -> pd.Series:
    """True only after the raw fault has persisted for ``confirm_seconds``."""
    raw = raw.fillna(False).astype(bool)
    if confirm_seconds <= 0:
        return raw
    deltas = sample_durations(raw.index, poll_seconds)
    groups = (raw != raw.shift()).cumsum()
    if deltas is not None:
        cum = deltas.where(raw, 0.0).groupby(groups).cumsum()
        return raw & (cum >= float(confirm_seconds))
    rows = max(1, int(np.ceil(confirm_seconds / max(poll_seconds, 1))))
    streak = raw.groupby(groups).cumcount() + 1
    return raw & (streak >= rows)


def hours_true(mask: pd.Series, poll_seconds: float) -> float:
    """Hours covered by a boolean mask, using real timestamp gaps."""
    m = mask.fillna(False).astype(bool)
    deltas = sample_durations(m.index, poll_seconds)
    if deltas is not None:
        return float((m.astype(float) * (deltas / 3600.0)).sum())
    return float(m.sum()) * poll_seconds / 3600.0


def apply_startup_delay(active: pd.Series, poll_seconds: float, delay_seconds: float) -> pd.Series:
    """A sample counts as 'running' only after ``delay_seconds`` of continuous run."""
    on = active.fillna(False).astype(bool)
    if delay_seconds <= 0:
        return on
    rows = max(1, int(np.ceil(delay_seconds / max(poll_seconds, 1.0))))
    groups = (on != on.shift()).cumsum()
    streak = on.groupby(groups).cumcount() + 1
    return on & (streak >= rows)


def flatline_mask(series: pd.Series, tol: float, window: int) -> pd.Series:
    """True where the rolling (max − min) over ``window`` samples is ≤ ``tol``."""
    window = max(2, int(window))
    rmin = series.rolling(window, min_periods=window).min()
    rmax = series.rolling(window, min_periods=window).max()
    return series.notna() & ((rmax - rmin) <= tol)


def false_series(index) -> pd.Series:
    return pd.Series(False, index=index)
