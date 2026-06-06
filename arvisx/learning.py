"""
ArvisX Phase-4 pattern learning + drift detection.

Moves beyond fixed thresholds: learn each (asset, signal)'s OWN normal from its
history and flag when a signal DRIFTS from that baseline — "this pump draws 3σ above
its own 30-day normal" — catching early degradation a static limit misses.

Design (ports AnomalyWatchdog's robust-z idea, not its BMS plumbing):
- robust stats: median + MAD (resistant to outliers),
- SUSTAINED gate: drift is judged on a RECENT WINDOW vs the long baseline, so a single
  spike doesn't fire,
- COLD-START honesty: under MIN_SAMPLES history → abstain (fixed thresholds remain the
  floor), never a confident drift call on thin data.
Cumulative/monotonic signals (runtime_hours) and config/date signals are excluded.
Equipment-agnostic — works for any numeric signal on any asset.
"""
from __future__ import annotations

import re
import statistics
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

from arvisx.models import Asset, Risk, Severity

MIN_SAMPLES = 20          # need this much history before trusting a baseline
RECENT_WINDOW = 5         # judge drift on the last N obs (sustained, not a spike)
MIN_RECENT = 3
DRIFT_Z = 3.0             # robust-z to flag drift
_MAD_K = 1.4826           # MAD → std-equivalent

# Signals we do NOT drift-check: cumulative (monotonic), config, schedules/dates.
_SKIP = re.compile(r"runtime_hours$|_threshold$|^expected_|_due$|_date$|setpoint", re.I)


def _is_numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class BaselineStore:
    """Bounded rolling history per (asset_id, signal) → learned median/MAD."""
    def __init__(self, maxlen: int = 500):
        self._hist: Dict[Tuple[str, str], Deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        self._lock = threading.Lock()

    def observe(self, asset_id: str, signal: str, value) -> None:
        if not _is_numeric(value) or _SKIP.search(signal):
            return
        with self._lock:
            self._hist[(asset_id, signal)].append(float(value))

    def learn_from_assets(self, assets: List[Asset]) -> int:
        """Snapshot every asset's current numeric signals into the baselines.
        Returns how many observations were recorded."""
        n = 0
        for a in assets:
            for k, v in (a.signals or {}).items():
                if _is_numeric(v) and not _SKIP.search(k):
                    self.observe(a.asset_id, k, v)
                    n += 1
        return n

    def baseline(self, asset_id: str, signal: str) -> Optional[Tuple[float, float, int]]:
        with self._lock:
            h = self._hist.get((asset_id, signal))
            if not h or len(h) < MIN_SAMPLES:
                return None
            data = list(h)
        med = statistics.median(data)
        mad = statistics.median([abs(x - med) for x in data]) or 1e-9
        return med, mad, len(data)

    def drift_z(self, asset_id: str, signal: str) -> Optional[float]:
        """Robust z of the RECENT window's median vs the learned baseline.
        None = insufficient history (abstain)."""
        base = self.baseline(asset_id, signal)
        if base is None:
            return None
        med, mad, _ = base
        with self._lock:
            data = list(self._hist[(asset_id, signal)])
        recent = data[-RECENT_WINDOW:]
        if len(recent) < MIN_RECENT:
            return None
        rmed = statistics.median(recent)
        return (rmed - med) / (_MAD_K * mad)

    def save_to(self, db) -> int:
        """Persist each (asset, signal) history so drift learning survives a restart."""
        with self._lock:
            items = [(k, list(v)) for k, v in self._hist.items()]
        for (asset_id, signal), hist in items:
            db.save_baseline(asset_id, signal, hist)
        return len(items)

    def load_from(self, db) -> int:
        n = 0
        for asset_id, signal, values in db.load_baselines():
            with self._lock:
                dq = self._hist[(asset_id, signal)]
                dq.clear()
                dq.extend(float(v) for v in values)
            n += 1
        return n


def drift_risks(asset: Asset, baselines: BaselineStore, now: Optional[datetime] = None,
                exclude=()) -> List[Risk]:
    """Drift risks for one asset's numeric signals (abstains where history is thin).
    `exclude` = signal keys already owned by a named virtual sensor (e.g. power_kw →
    PowerCreep) so the same physical cause doesn't raise two risks / two tickets."""
    out: List[Risk] = []
    _ex = set(exclude)
    for k, v in (asset.signals or {}).items():
        if not _is_numeric(v) or _SKIP.search(k) or k in _ex or k.startswith("v_"):
            continue
        z = baselines.drift_z(asset.asset_id, k)
        if z is None or abs(z) < DRIFT_Z:
            continue
        direction = "above" if z > 0 else "below"
        out.append(Risk(
            asset.asset_id, asset.name, asset.service, Severity.WARNING,
            f"{asset.name} {k} drifting from its learned normal",
            f"{k}={v} is {abs(z):.1f}σ {direction} this asset's own baseline — early deviation, "
            f"not yet a threshold breach. Trend it and inspect before it escalates.",
            confidence="Medium",   # learned-baseline statistical signal (stronger than a raw threshold)
            evidence=[f"{k}={v}", f"{abs(z):.1f}σ vs learned baseline"],
        ))
    return out
