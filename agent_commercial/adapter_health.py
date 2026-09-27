"""
Per-point freshness for protocol adapters (VOLTTRON-style stale timeout).

A point that stops answering must not keep looking live. After
``stale_factor`` × its poll interval without a successful read the adapter
emits it once with quality STALE (and its last value, so dashboards can show
what it last said); the next good read clears the flag.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional


class PointFreshness:
    def __init__(self, stale_factor: float = 3.0):
        self.stale_factor = stale_factor
        self._last_ok: Dict[str, float] = {}
        self._stale: set = set()

    def mark_ok(self, point_id: str, now: Optional[float] = None) -> None:
        self._last_ok[point_id] = time.monotonic() if now is None else now
        self._stale.discard(point_id)

    def register(self, point_id: str, now: Optional[float] = None) -> None:
        """Start the clock for a configured point that has never answered."""
        self._last_ok.setdefault(point_id, time.monotonic() if now is None else now)

    def newly_stale(self, intervals: Dict[str, float], now: Optional[float] = None) -> List[str]:
        """Points that just crossed their stale timeout (each reported once)."""
        now = time.monotonic() if now is None else now
        out = []
        for pid, interval in intervals.items():
            last = self._last_ok.get(pid)
            if last is None or pid in self._stale:
                continue
            if now - last > self.stale_factor * max(float(interval), 1.0):
                self._stale.add(pid)
                out.append(pid)
        return out

    @property
    def stale_points(self) -> List[str]:
        return sorted(self._stale)
