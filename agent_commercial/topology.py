"""
Equipment dependency graph + cascade impact (the "tree").

Ported from the residential ArvisX topology to commercial HVAC. The alarm engine
already tracks parent/child edges for *correlation*; this adds the missing piece —
SYSTEMS-LEVEL impact: each equipment sits in a ROLE with a REDUNDANCY, so a fault
propagates a QUANTIFIED impact down the chain plus a building-comfort delta:

    Chiller fault  →  generation, N+1 plant (parallel)  →  cooling MAJOR
                   →  downstream: 14 AHUs it feeds  →  building impact −X%

Redundancy absorbs impact (a standby CHW pump failing ≪ the only chiller failing).
The downstream walk uses the REAL Equipment.child_equipment_ids edges when present,
so it reflects the commissioned topology, not a guess. Read-only — informs reasoning.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent_commercial.bms_data_model import Equipment, EquipmentType


# EquipmentType → (role, default redundancy). Redundancy overridable via
# Equipment.design_attributes["redundancy"] when commissioned (single|standby|parallel).
EQUIPMENT_ROLE: Dict[EquipmentType, Tuple[str, str]] = {
    EquipmentType.CHILLER:       ("generation", "parallel"),   # N+1 plant
    EquipmentType.COOLING_TOWER: ("heat_rejection", "parallel"),
    EquipmentType.BOILER:        ("heating", "standby"),
    EquipmentType.PUMP:          ("transfer", "standby"),       # CHW/CW pumps usually have a standby
    EquipmentType.AHU:           ("air_handling", "single"),    # per-zone, typically single
    EquipmentType.FCU:           ("terminal", "single"),
    EquipmentType.VAV:           ("terminal", "single"),
    EquipmentType.FAN:           ("air_movement", "single"),
}

# How essential the role is to delivering comfort.
_ROLE_CRIT = {
    "generation": 1.0, "heat_rejection": 0.9, "heating": 0.9, "transfer": 0.7,
    "air_handling": 0.7, "air_movement": 0.5, "terminal": 0.4,
}
# Redundancy absorbs impact.
_REDUNDANCY_FACTOR = {"single": 1.0, "standby": 0.5, "parallel": 0.4}

_SEV_W = {"critical": 1.0, "severe": 1.0, "high": 0.6, "medium": 0.3, "low": 0.15}


@dataclass
class CascadeImpact:
    equipment_id: str
    name: str
    equipment_type: str
    role: str
    redundancy: str
    impact: str                # "partial" | "major" | "critical"
    system_impact: float       # 0..1 share of the system degraded
    building_impact_pct: float # approx % of building comfort affected
    downstream_affected: List[str] = field(default_factory=list)
    note: str = ""


def _role_redundancy(eq: Equipment) -> Tuple[str, str]:
    role, red = EQUIPMENT_ROLE.get(eq.equipment_type, ("equipment", "single"))
    red = (eq.design_attributes or {}).get("redundancy", red)
    return role, red


def _sev_weight(severity) -> float:
    return _SEV_W.get(str(getattr(severity, "value", severity)).lower(), 0.4)


def _downstream(eq_id: str, by_id: Dict[str, Equipment], limit: int = 200) -> List[str]:
    """BFS over the real child_equipment_ids edges → all equipment fed by eq_id."""
    out, seen = [], {eq_id}
    q = deque([eq_id])
    while q and len(out) < limit:
        cur = by_id.get(q.popleft())
        if not cur:
            continue
        for c in (cur.child_equipment_ids or []):
            if c not in seen:
                seen.add(c)
                out.append(c)
                q.append(c)
    return out


def system_graph(equipment_list: List[Equipment]) -> List[Dict[str, Any]]:
    """The dependency tree as nodes (role/redundancy/children) — exposes /topology."""
    nodes = []
    for eq in equipment_list:
        role, red = _role_redundancy(eq)
        nodes.append({"equipment_id": eq.equipment_id, "name": getattr(eq, "name", eq.equipment_id),
                      "type": eq.equipment_type.value, "role": role, "redundancy": red,
                      "parent": eq.parent_equipment_id, "children": list(eq.child_equipment_ids or [])})
    return nodes


def impact_analysis(equipment_list: List[Equipment], flagged: List) -> List[CascadeImpact]:
    """For each flagged equipment (alarm/anomaly with .equipment_id + .severity), propagate
    a quantified system + downstream + building-comfort impact. `flagged` items may be Alarm
    objects, AnomalyEvents, or (equipment_id, severity) tuples."""
    by_id = {e.equipment_id: e for e in equipment_list}
    total_terminals = max(1, sum(1 for e in equipment_list
                                 if _role_redundancy(e)[0] in ("terminal", "air_handling")))
    out: List[CascadeImpact] = []
    seen = set()
    for f in flagged:
        if isinstance(f, tuple):
            eq_id, severity = f[0], (f[1] if len(f) > 1 else "high")
        else:
            eq_id, severity = getattr(f, "equipment_id", None), getattr(f, "severity", "high")
        eq = by_id.get(eq_id)
        if eq is None or eq_id in seen:
            continue
        seen.add(eq_id)
        role, red = _role_redundancy(eq)
        crit = _ROLE_CRIT.get(role, 0.5)
        sev_w = _sev_weight(severity)
        system_impact = round(crit * sev_w * _REDUNDANCY_FACTOR.get(red, 1.0), 2)
        level = "critical" if system_impact >= 0.7 else "major" if system_impact >= 0.4 else "partial"
        downstream = _downstream(eq_id, by_id)
        # Building comfort impact: upstream equipment (chiller/pump) weighted by how many
        # terminals it feeds; a terminal unit affects only itself.
        terminals_hit = max(len(downstream), 1) if role not in ("terminal",) else 1
        building_impact_pct = round(min(100.0, 100.0 * system_impact * terminals_hit / total_terminals), 1)
        red_note = {"single": "no standby", "standby": "standby available",
                    "parallel": "parallel unit available"}.get(red, "")
        out.append(CascadeImpact(
            equipment_id=eq_id, name=getattr(eq, "name", eq_id), equipment_type=eq.equipment_type.value,
            role=role, redundancy=red, impact=level, system_impact=system_impact,
            building_impact_pct=building_impact_pct, downstream_affected=downstream,
            note=f"{getattr(eq, 'name', eq_id)} ({role}, {red_note}) → {level} system impact; "
                 f"{len(downstream)} downstream unit(s) → building comfort ~−{building_impact_pct:.0f}%"))
    out.sort(key=lambda c: c.system_impact, reverse=True)
    return out
