"""
Rule model shared by every FDD rule family.

A rule is declarative: the point roles it needs, SI parameters, the gate that
decides when it is fair to judge, a confirmation delay, and a pure ``compute``
that returns a RAW boolean fault mask over a role-column DataFrame (columns
are ``PointRole.value`` strings, values already in canonical SI units).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from agent_commercial.fdd.gates import GateSpec
from agent_commercial.semantics import PointRole as R

# Imperial → SI helpers used when porting open-fdd thresholds.
F_DELTA = 5.0 / 9.0                      # °F difference → °C difference
def f_to_c(f: float) -> float: return (f - 32.0) * 5.0 / 9.0
INWC_PA = 249.0889                       # in. w.c. → Pa
PSI_PA = 6894.757                        # psi → Pa
CFM_M3S = 0.000471947                    # cfm → m³/s

# A required entry is one role, or a tuple of roles of which any one suffices.
Requirement = Union[R, Tuple[R, ...]]


@dataclass(frozen=True)
class Param:
    key: str
    default: Optional[float]     # None → site must configure it (rule SKIPs otherwise)
    unit: str
    label: str


@dataclass
class RuleContext:
    """Per-run extras a compute may read or write (sensor sweeps publish their
    per-role masks here; topology enrichment is exposed as ctx columns)."""
    poll_seconds: float
    per_role_masks: Dict[str, pd.Series] = field(default_factory=dict)
    notes: Dict[str, Any] = field(default_factory=dict)


Compute = Callable[[pd.DataFrame, Dict[str, float], RuleContext], pd.Series]


@dataclass
class RuleSpec:
    id: str
    title: str
    family: str                          # sensor | control | ahu | vav | plant | schedule
    equipment_kinds: Tuple[str, ...]
    required: Tuple[Requirement, ...]
    compute: Compute
    params: Tuple[Param, ...] = ()
    optional: Tuple[R, ...] = ()
    confirm_seconds: float = 300.0
    gate: GateSpec = field(default_factory=GateSpec)
    summary: str = ""
    origin: str = ""                     # e.g. "open-fdd FC14 (ASHRAE G36 L)" or "arvis"
    requires_design: Optional[str] = None   # design_attributes flag that must be True
    root_cause_candidates: Tuple[str, ...] = ()
    energy_impact: Optional[str] = None  # key understood by fdd.impact (Phase 4)
    sensor_sweep: bool = False
    context_columns: Tuple[str, ...] = ()   # ctx:* enrichment columns the rule needs
    min_window_hours: float = 0.0        # data span needed before the rule can be judged

    def defaults(self) -> Dict[str, Optional[float]]:
        return {p.key: p.default for p in self.params}

    def resolved_params(self, overrides: Optional[Dict[str, float]] = None) -> Dict[str, Optional[float]]:
        out = self.defaults()
        for k, v in (overrides or {}).items():
            if k in out or k in ("confirm_seconds", "startup_delay_s"):
                out[k] = v
        return out

    def missing_params(self, params: Dict[str, Optional[float]]) -> list:
        return [p.key for p in self.params if params.get(p.key) is None]

    def fingerprint(self, params: Dict[str, Any]) -> str:
        blob = json.dumps({"rule": self.id, "params": params}, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "family": self.family,
            "equipment_kinds": list(self.equipment_kinds),
            "required": [[r.value for r in q] if isinstance(q, tuple) else q.value
                         for q in self.required],
            "optional": [r.value for r in self.optional],
            "params": [{"key": p.key, "default": p.default, "unit": p.unit, "label": p.label}
                       for p in self.params],
            "confirm_seconds": self.confirm_seconds, "gate": self.gate.kind,
            "summary": self.summary, "origin": self.origin,
            "requires_design": self.requires_design,
            "root_cause_candidates": list(self.root_cause_candidates),
        }


# ──────────────────────────────────────────────────────────────────────────
# Column helpers
# ──────────────────────────────────────────────────────────────────────────
def has(d: pd.DataFrame, role: Union[R, str]) -> bool:
    c = role.value if isinstance(role, R) else role
    return c in d.columns and bool(d[c].notna().any())


def col(d: pd.DataFrame, role: Union[R, str]) -> pd.Series:
    """Numeric column for a role (all-NaN if absent — comparisons then yield False)."""
    c = role.value if isinstance(role, R) else role
    if c in d.columns:
        return pd.to_numeric(d[c], errors="coerce")
    return pd.Series(np.nan, index=d.index, dtype=float)


def frac(d: pd.DataFrame, role: R, fill: float = 0.0) -> pd.Series:
    """Fraction-type role (0–1) with NaN → ``fill`` (open-fdd norm_cmd(...).fillna(0))."""
    return col(d, role).fillna(fill)


def fan(d: pd.DataFrame) -> pd.Series:
    """Fan signal as used inside rule equations (open-fdd ``_fan``): proven
    status (0/1) first, then VFD speed fraction, then start/stop command.
    The gate has already established the unit was running; with no fan point
    at all this is 1.0 (only reachable when the site allows ungated rules)."""
    if has(d, R.SUPPLY_FAN_STATUS):
        return (col(d, R.SUPPLY_FAN_STATUS).fillna(0) > 0.5).astype(float)
    if has(d, R.SUPPLY_FAN_SPEED):
        return frac(d, R.SUPPLY_FAN_SPEED)
    if has(d, R.SUPPLY_FAN_CMD):
        return (col(d, R.SUPPLY_FAN_CMD).fillna(0) > 0.5).astype(float)
    return pd.Series(1.0, index=d.index)


def false(d: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=d.index)


def p(params: Dict[str, Any], key: str) -> float:
    return float(params[key])


FAN_ANY: Tuple[R, ...] = (R.SUPPLY_FAN_STATUS, R.SUPPLY_FAN_SPEED, R.SUPPLY_FAN_CMD)
CONFIRM_MIN = lambda minutes: minutes * 60.0  # noqa: E731


def rules_by_id(rules: Sequence[RuleSpec]) -> Dict[str, RuleSpec]:
    out: Dict[str, RuleSpec] = {}
    for r in rules:
        if r.id in out:
            raise ValueError(f"duplicate rule id {r.id}")
        out[r.id] = r
    return out
