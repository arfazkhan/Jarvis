"""
Equipment frames: stored telemetry → one time-aligned, SI, role-named table
per equipment, ready for the rules.

Only points with a trusted role are used (explicit, or an unambiguous suffix
suggestion); values are converted with ``to_canonical`` and a point whose unit
cannot be converted is left out and reported — never guessed. Every sample is
bucketed onto a fixed grid so equipment frames align with each other (needed
for AHU → VAV and plant ← building context).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from agent_commercial.semantics import PointRole, PointRoleRegistry, to_canonical


@dataclass
class EquipmentFrame:
    equipment_id: str
    kind: str
    frame: pd.DataFrame
    points_used: Dict[str, str] = field(default_factory=dict)      # role → point_id
    role_sources: Dict[str, str] = field(default_factory=dict)     # role → explicit|suggested|context
    unconvertible: Dict[str, str] = field(default_factory=dict)    # point_id → unit
    conflicts: List[str] = field(default_factory=list)
    design_attributes: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None

    def add_context(self, name: str, series: pd.Series) -> None:
        """Attach a building/topology context column (e.g. parent AHU supply air)."""
        if self.frame.empty:
            return
        self.frame[name] = series.reindex(self.frame.index)
        self.role_sources[name] = "context"


def _grid_index(start: pd.Timestamp, end: pd.Timestamp, seconds: int) -> pd.DatetimeIndex:
    freq = f"{int(seconds)}s"
    return pd.date_range(start.floor(freq), end.floor(freq), freq=freq)


def build_frame(equipment_id: str, kind: str, rows: Iterable[Dict[str, Any]],
                registry: PointRoleRegistry, *, resample_seconds: int = 300,
                min_confidence: float = 0.9,
                design_attributes: Optional[Dict[str, Any]] = None,
                parent_id: Optional[str] = None) -> EquipmentFrame:
    """rows: dicts with point_id, value, unit, timestamp (from data_points)."""
    by_point: Dict[str, List] = defaultdict(list)
    units: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        pid = r.get("point_id")
        if not pid or r.get("value") is None:
            continue
        by_point[pid].append((r["timestamp"], r["value"]))
        units[pid][r.get("unit") or ""] += 1

    ef = EquipmentFrame(equipment_id, kind, pd.DataFrame(),
                        design_attributes=dict(design_attributes or {}), parent_id=parent_id)
    if not by_point:
        return ef

    chosen, ef.conflicts = registry.role_map(by_point.keys(), kind, min_confidence=min_confidence)
    columns: Dict[str, pd.Series] = {}
    for role, assignment in chosen.items():
        pid = assignment.point_id
        unit = assignment.unit_override or units[pid].most_common(1)[0][0]
        ts, vals = zip(*by_point[pid])
        conv = [to_canonical(v, unit, role) for v in vals]
        if all(c is None for c in conv):
            ef.unconvertible[pid] = unit
            continue
        s = pd.Series(conv, index=pd.to_datetime(list(ts), errors="coerce"), dtype="float64")
        s = s[s.index.notna()].dropna().sort_index()
        if s.empty:
            continue
        columns[role.value] = s.resample(f"{int(resample_seconds)}s").mean()
        ef.points_used[role.value] = pid
        ef.role_sources[role.value] = assignment.source

    if not columns:
        return ef
    start = min(s.index.min() for s in columns.values())
    end = max(s.index.max() for s in columns.values())
    idx = _grid_index(start, end, resample_seconds)
    ef.frame = pd.DataFrame({k: v.reindex(idx) for k, v in columns.items()}, index=idx)
    return ef
