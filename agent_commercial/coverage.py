"""
How much of the building can ARVIS see — and what to connect next.

For every piece of equipment, each thing the equipment catalog says it needs
(config/equipment_catalog.yaml) is one of:

  connected   an instrument reads it (BMS, Modbus, OPC UA, MQTT, SNMP, ...)
  manual      a person reads it (a manual point — a reading round, a gauge photo)
  imported    only historical data was imported
  missing     nothing gives ARVIS this yet

From that, a building maturity level (the low-data ladder):

  Full      ≥ 90 % of what's needed is read by instruments
  Partial   ≥ 40 % by instruments
  Limited   some instruments, or ≥ 40 % covered at all (manual included)
  Manual    no instruments, but people read some of it
  Unknown   nothing declared yet

and "what to add next": missing needs, ranked by how many fault checks they would
switch on (for HVAC, the FDD rules that need that role and already have the rest),
each with the plain-words way to connect it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger("arvis.coverage")

CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "equipment_catalog.yaml"
_NOT_INSTRUMENT = ("manual", "import", "commission")
Need = Union[str, Tuple[str, ...]]


def load_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    import yaml
    data = yaml.safe_load((path or CATALOG_PATH).read_text(encoding="utf-8")) or {}
    for kind, spec in (data.get("kinds") or {}).items():
        spec["required"] = [tuple(r) if isinstance(r, list) else r for r in spec.get("required") or []]
        spec["optional"] = list(spec.get("optional") or [])
    return data


@dataclass
class EquipmentCoverage:
    equipment_id: str
    kind: str
    label: str
    roles: Dict[str, str] = field(default_factory=dict)       # role → connected | manual | imported | missing
    required: List[Need] = field(default_factory=list)

    def need_state(self, need: Need) -> str:
        alts = need if isinstance(need, tuple) else (need,)
        states = [self.roles.get(r, "missing") for r in alts]
        for s in ("connected", "manual", "imported"):
            if s in states:
                return s
        return "missing"

    @property
    def score(self) -> Dict[str, int]:
        out = {"connected": 0, "manual": 0, "imported": 0, "missing": 0}
        for n in self.required:
            out[self.need_state(n)] += 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {"equipment_id": self.equipment_id, "kind": self.kind, "label": self.label, "roles": self.roles,
                "required": [{"need": "|".join(n) if isinstance(n, tuple) else n, "state": self.need_state(n)}
                             for n in self.required], "score": self.score}


def _role_name(r: Any) -> Optional[str]:
    return getattr(r, "value", r) if r else None


def _equipment(state_engine: Any, manual_points: Sequence[Any], imported: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """equipment id → its Equipment record (or None when only its points are known)."""
    eq: Dict[str, Any] = dict(getattr(state_engine, "_equipment", {}) or {})
    for _pid, eq_id in imported:
        eq.setdefault(eq_id, None)
    for p in list((getattr(state_engine, "_points", {}) or {}).values()):
        if str(getattr(p, "source", "") or "").startswith("event:"):
            continue                              # zone occupancy points: a zone is not equipment
        if getattr(p, "equipment_id", None):
            eq.setdefault(p.equipment_id, None)
    for mp in manual_points:
        eq.setdefault(mp.equipment_id, None)
    return eq


def assess(state_engine: Any, manual_points: Sequence[Any] = (), catalog: Optional[Dict[str, Any]] = None,
           imported: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """The building's coverage: per equipment, the maturity level, and what to add next.
    `imported`: (point_id, equipment_id) of points that only have imported history."""
    from agent_commercial.semantics.point_roles import equipment_kind, get_role_registry
    catalog = catalog or load_catalog()
    kinds = catalog.get("kinds") or {}
    registry = get_role_registry(state_engine)
    points = list((getattr(state_engine, "_points", {}) or {}).values())
    by_eq: Dict[str, List[Any]] = {}
    for p in points:
        by_eq.setdefault(getattr(p, "equipment_id", "") or "", []).append(p)
    manual_by_eq: Dict[str, List[Any]] = {}
    for mp in manual_points:
        manual_by_eq.setdefault(mp.equipment_id, []).append(mp)
    imported_by_eq: Dict[str, List[str]] = {}
    for pid, eq_id in imported:
        imported_by_eq.setdefault(eq_id, []).append(pid)

    rank = {"connected": 3, "manual": 2, "imported": 1, "missing": 0}
    report: List[EquipmentCoverage] = []
    unrecognised: List[str] = []
    for eq_id, rec in sorted(_equipment(state_engine, manual_points, imported).items()):
        if not eq_id:
            continue
        kind = equipment_kind(getattr(rec, "equipment_type", None), eq_id)
        spec = kinds.get(kind)
        if spec is None:
            unrecognised.append(eq_id)
            continue
        cov = EquipmentCoverage(eq_id, kind, spec.get("label", kind), required=list(spec["required"]))
        for p in by_eq.get(eq_id, []):
            a = registry.resolve(p.point_id, kind)
            role = _role_name(a.role) if a.role is not None and a.confidence >= .9 else None
            if role is None:
                continue
            src = str(getattr(p, "source", "") or "").lower()
            state = "manual" if src == "manual" else "imported" if src == "import" else \
                "connected" if src not in _NOT_INSTRUMENT else None
            if state and rank[state] > rank[cov.roles.get(role, "missing")]:
                cov.roles[role] = state
        for pid in imported_by_eq.get(eq_id, []):   # history only (a trend export, a bill)
            a = registry.resolve(pid, kind)
            role = _role_name(a.role) if a.role is not None and a.confidence >= .9 else None
            if role and rank["imported"] > rank[cov.roles.get(role, "missing")]:
                cov.roles[role] = "imported"
        for mp in manual_by_eq.get(eq_id, []):      # declared for people to read, even before the first reading
            role = mp.role or _role_name(registry.resolve(mp.point_id, kind).role)
            if role and rank["manual"] > rank[cov.roles.get(role, "missing")]:
                cov.roles[role] = "manual"
        for need in cov.required + spec["optional"]:
            for r in (need if isinstance(need, tuple) else (need,)):
                cov.roles.setdefault(r, "missing")
        report.append(cov)

    totals = {"connected": 0, "manual": 0, "imported": 0, "missing": 0}
    for c in report:
        for k, v in c.score.items():
            totals[k] += v
    needed = sum(totals.values())
    live = totals["connected"] / needed if needed else 0.0
    covered = (needed - totals["missing"]) / needed if needed else 0.0
    if not needed:
        level = "Unknown"
    elif live >= .9:
        level = "Full"
    elif live >= .4:
        level = "Partial"
    elif live > 0 or covered >= .4:
        level = "Limited"
    elif covered > 0:
        level = "Manual"
    else:
        level = "Unknown"
    return {"level": level, "instrumented": round(live, 3), "covered": round(covered, 3), "totals": totals,
            "equipment": [c.to_dict() for c in report], "unrecognised_equipment": unrecognised,
            "next": what_next(report, catalog)}


def _fdd_unlocks(kind: str, role: str, have: set) -> int:
    """FDD rules for this kind that need `role` and would then have everything they need."""
    try:
        from agent_commercial.fdd import RULES
    except Exception:
        return 0
    n = 0
    for rule in RULES:
        if kind not in getattr(rule, "equipment_kinds", ()):
            continue
        needs = [tuple(_role_name(x) for x in r) if isinstance(r, tuple) else _role_name(r) for r in rule.required]
        flat = {x for n_ in needs for x in (n_ if isinstance(n_, tuple) else (n_,))}
        if role not in flat:
            continue
        ok = all((set(n_) & (have | {role})) if isinstance(n_, tuple) else (n_ in have | {role}) for n_ in needs)
        n += bool(ok)
    return n


def what_next(report: List[EquipmentCoverage], catalog: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    kinds, how_to = catalog.get("kinds") or {}, catalog.get("how_to") or {}
    out = []
    for c in report:
        spec = kinds.get(c.kind, {})
        how = spec.get("how") or {}
        have = {r for r, s in c.roles.items() if s != "missing"}
        for i, need in enumerate(c.required):
            if c.need_state(need) != "missing":
                continue
            role = need[0] if isinstance(need, tuple) else need
            way = how.get(role, how.get("default", "bms"))
            out.append({"equipment_id": c.equipment_id, "label": c.label, "role": role, "required": True,
                        "unlocks_fault_checks": _fdd_unlocks(c.kind, role, have), "how": way,
                        "advice": how_to.get(way, ""), "_order": (0, -_fdd_unlocks(c.kind, role, have))})
        for j, role in enumerate(spec.get("optional") or []):
            if c.roles.get(role, "missing") != "missing":
                continue
            unlocks = _fdd_unlocks(c.kind, role, have)
            if not unlocks:
                continue                                      # optional and switches nothing on: not "next"
            way = how.get(role, how.get("default", "bms"))
            out.append({"equipment_id": c.equipment_id, "label": c.label, "role": role, "required": False,
                        "unlocks_fault_checks": unlocks, "how": way, "advice": how_to.get(way, ""),
                        "_order": (1, -unlocks)})
    out.sort(key=lambda x: x["_order"])
    for x in out:
        x.pop("_order")
    return out[:limit]
