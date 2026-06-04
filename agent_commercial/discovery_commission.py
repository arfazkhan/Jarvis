"""
discovery_commission.py
=======================
Discovery → DRAFT-commissioning bridge. Turns a discovered point/equipment
inventory into a *draft* commissioning spec a human reviews before go-live.

Pipeline (steps 1-4 of the live-readiness plan):
  1. SWEEP    — read the unified inventory from BMSStateEngine (protocol-agnostic:
                BACnet/Modbus discovery + the simulator all populate bms_state).
  2. INFER    — propose design_attributes with {value, confidence, evidence}.
  3. DRAFT    — emit config/commissioning/<building>.draft.yaml.
  4. REVIEW   — a human confirms (sets confirmed: true), then `promote` produces
                the clean <building>.yaml that commission_building consumes.

HARD RULE (the RCA-gap lesson): NEVER auto-assert a design prior from the ABSENCE
of telemetry. Absence of a motorized-damper command point != a fixed damper (could
be unmapped). Discovery proposes only POSITIVE inferences it has evidence for;
every physics-gating fact (damper_type, has_vfd, economizer, compressor_staging)
is marked needs_confirmation=True and is dropped to UNKNOWN unless a human confirms
it. ARVIS then flags unknown design as "confirm on inspection" rather than guessing.

CLI:
  python -m agent_commercial.discovery_commission sweep   --building default --out config/commissioning/default.draft.yaml
  python -m agent_commercial.discovery_commission promote config/commissioning/default.draft.yaml config/commissioning/default.yaml
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.discovery_commission")

# Physics-gating design facts — ALWAYS require human confirmation (they gate
# root-cause hypotheses; a wrong one reintroduces the design-context RCA bug).
_PHYSICS_GATING = {"damper_type", "has_vfd", "economizer", "compressor_staging"}


def _toks(*parts: str) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def _is_output(point_type: str) -> bool:
    """A controllable output (command/setpoint) implies an actuated device."""
    return str(point_type or "").lower() in ("command", "setpoint")


# ──────────────────────────────────────────────────────────────────────────
# Step 2 — design inferencer (POSITIVE evidence only)
# ──────────────────────────────────────────────────────────────────────────
def infer_design_attributes(equipment_id: str, points: List[Any]) -> Dict[str, Dict[str, Any]]:
    """
    Propose design_attributes for one equipment from its points. Each entry:
      {value, confidence, evidence, needs_confirmation}
    Only positive inferences are emitted; facts we cannot see are OMITTED (→ the
    human declares them) rather than asserted false.
    """
    out: Dict[str, Dict[str, Any]] = {}

    def _norm(s: str) -> str:
        # Separators (_ - /) are word-chars to regex \b, so "OA_DMPR_CMD" would
        # never match \bcmd\b. Normalize them to spaces for keyword matching.
        return re.sub(r"[_\-/]+", " ", str(s or "")).lower()

    def _pmeta(p):
        return (
            str(getattr(p, "point_id", "") or ""),
            _norm(_toks(getattr(p, "point_id", ""), getattr(p, "name", ""))),
            str(getattr(getattr(p, "point_type", ""), "value", getattr(p, "point_type", "")) or ""),
            str(getattr(p, "unit", "") or "").lower(),
        )
    meta = [_pmeta(p) for p in points]

    # ── VFD present? — a speed/Hz/drive point is positive evidence ─────────
    _vfd = [pid for pid, t, _pt, _u in meta
            if re.search(r"\b(vfd|speed|spd|\bhz\b|freq|drive|inverter)\b", t)]
    if _vfd:
        out["has_vfd"] = {"value": True, "confidence": 0.85,
                          "evidence": f"speed/drive point(s): {', '.join(_vfd[:3])}"}

    # ── Damper type — a COMMAND/SETPOINT damper point ⇒ motorized ──────────
    _dmp_all = [(pid, pt) for pid, t, pt, _u in meta if re.search(r"\b(dmpr|damper|louver)\b", t)]
    _dmp_cmd = [pid for pid, pt in _dmp_all if _is_output(pt) or re.search(r"\b(cmd|command|sp)\b", _norm(pid))]
    if _dmp_cmd:
        out["damper_type"] = {"value": "motorized", "confidence": 0.8,
                              "evidence": f"damper command point(s): {', '.join(_dmp_cmd[:3])}"}
    elif _dmp_all:
        # Only a position READING exists — cannot tell fixed vs motorized-unmapped.
        out["damper_type"] = {"value": None, "confidence": 0.0,
                              "evidence": f"only damper position reading(s) found ({_dmp_all[0][0]}), no command point — "
                                          f"CANNOT determine fixed vs motorized; confirm physically"}

    # ── Valve type — analog/% output ⇒ modulating; binary ⇒ 2-position ─────
    _vlv = [(pid, pt, u) for pid, t, pt, u in meta if re.search(r"\bvalve\b|\bvlv\b", t)]
    if _vlv:
        _mod = [pid for pid, pt, u in _vlv if (_is_output(pt) and (u in ("%", "fraction", "percent") or "pos" in pid.lower()))]
        if _mod:
            out["valve_type"] = {"value": "modulating", "confidence": 0.75,
                                 "evidence": f"analog valve output: {', '.join(_mod[:3])}"}
        else:
            out["valve_type"] = {"value": "2-position", "confidence": 0.55,
                                 "evidence": f"valve point(s) without analog command: {_vlv[0][0]}"}

    # ── Economizer — damper command + a mixed-air/MAT point ────────────────
    _has_mat = any(re.search(r"\b(mat|mixed.?air)\b", t) for _pid, t, _pt, _u in meta)
    if _dmp_cmd and _has_mat:
        out["economizer"] = {"value": True, "confidence": 0.6,
                             "evidence": "modulating OA damper + mixed-air temperature point present"}

    # ── Compressor staging — ≥2 compressor/stage points ⇒ staged ──────────
    _comp = [pid for pid, t, _pt, _u in meta if re.search(r"\b(comp|compressor|stage)\b", t)]
    if len(_comp) >= 2:
        out["compressor_staging"] = {"value": "staged", "confidence": 0.6,
                                     "evidence": f"{len(_comp)} compressor/stage points: {', '.join(_comp[:3])}"}

    # Tag confirmation requirement: physics-gating facts ALWAYS need a human.
    for k, v in out.items():
        v["needs_confirmation"] = True if (k in _PHYSICS_GATING or v.get("confidence", 0) < 0.8) else False
        v.setdefault("confirmed", False)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Step 1+3 — sweep the inventory and build the draft spec
# ──────────────────────────────────────────────────────────────────────────
async def sweep_and_draft(
    bms_state: Any,
    database: Any = None,
    building_id: str = "default",
) -> Dict[str, Any]:
    """Read the live inventory from bms_state, infer design, build a draft spec dict."""
    equipment = await bms_state.get_all_equipment()
    draft_equipment: List[Dict[str, Any]] = []

    for eq in equipment:
        eid = eq.equipment_id
        try:
            points = await bms_state.get_points_by_equipment(eid)
        except Exception:
            points = []
        eqtype = getattr(getattr(eq, "equipment_type", ""), "value", str(getattr(eq, "equipment_type", "")))
        design = infer_design_attributes(eid, points)
        draft_equipment.append({
            "id": eid,
            "type": eqtype,
            "name": getattr(eq, "name", eid),
            "location": getattr(eq, "location", ""),
            "points": [
                {"point_id": getattr(p, "point_id", ""),
                 "name": getattr(p, "name", ""),
                 "unit": getattr(p, "unit", ""),
                 "point_type": str(getattr(getattr(p, "point_type", ""), "value", getattr(p, "point_type", "")) or "sensor")}
                for p in points
            ],
            "design_attributes": design,
        })

    # Zones — reuse already-known zones if the DB has them; otherwise propose
    # candidates from equipment that carry CO2 + VAV points.
    zones: List[Dict[str, Any]] = []
    try:
        if database is not None and hasattr(database, "get_all_zones"):
            for z in (await database.get_all_zones()) or []:
                zones.append({k: z.get(k) for k in
                              ("zone_id", "name", "floor", "co2_point_id", "vav_point_id", "lighting_point_id", "load_kw")})
    except Exception as _ze:
        logger.debug(f"zone read skipped: {_ze}")

    n_design = sum(1 for e in draft_equipment for _ in e["design_attributes"])
    n_needs = sum(1 for e in draft_equipment for v in e["design_attributes"].values() if v.get("needs_confirmation"))
    return {
        "building_id": building_id,
        "_generated": datetime.now().isoformat(timespec="seconds"),
        "_instructions": (
            "DRAFT commissioning spec from auto-discovery. Review every design_attribute. "
            "Set confirmed: true to keep it; physics-gating facts (damper_type, has_vfd, "
            "economizer, compressor_staging) MUST be confirmed by an engineer (nameplate/site). "
            "value: null means discovery could NOT determine it — fill it in or leave to drop to UNKNOWN. "
            "Then run: python -m agent_commercial.discovery_commission promote <this> <building>.yaml"
        ),
        "_summary": {"equipment": len(draft_equipment), "design_proposed": n_design,
                     "needs_confirmation": n_needs, "zones": len(zones)},
        "equipment": draft_equipment,
        "zones": zones,
    }


def write_draft(draft: Dict[str, Any], out_path: str | Path) -> Path:
    import yaml
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(draft, sort_keys=False, default_flow_style=False), encoding="utf-8")
    logger.info(f"[Discovery] draft commissioning spec → {p} ({draft['_summary']})")
    return p


# ──────────────────────────────────────────────────────────────────────────
# Step 4 — promote a human-reviewed draft to a clean commissioning spec
# ──────────────────────────────────────────────────────────────────────────
def promote_draft(draft_path: str | Path, out_path: str | Path) -> Dict[str, Any]:
    """
    Convert a reviewed draft into the clean commissioning spec commission_building
    consumes. A design_attribute is KEPT (as a plain value) only if:
      - confirmed: true, OR
      - needs_confirmation: false (high-confidence, non-physics-gating)
    AND its value is not null. Everything else is dropped → UNKNOWN at runtime.
    """
    import yaml
    draft = yaml.safe_load(Path(draft_path).read_text(encoding="utf-8")) or {}
    out = {"building_id": draft.get("building_id", "default"), "equipment": [], "zones": draft.get("zones", []) or []}
    kept = dropped = 0
    for e in draft.get("equipment", []) or []:
        design_clean: Dict[str, Any] = {}
        for attr, meta in (e.get("design_attributes", {}) or {}).items():
            if not isinstance(meta, dict):
                continue
            val = meta.get("value")
            keep = (meta.get("confirmed") is True) or (meta.get("needs_confirmation") is False)
            if keep and val is not None:
                design_clean[attr] = val
                kept += 1
            else:
                dropped += 1
        eq_out = {"id": e.get("id"), "type": e.get("type"), "name": e.get("name"),
                  "location": e.get("location", "")}
        if design_clean:
            eq_out["design_attributes"] = design_clean
        if e.get("points"):
            eq_out["points"] = e["points"]
        out["equipment"].append(eq_out)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(yaml.safe_dump(out, sort_keys=False), encoding="utf-8")
    summary = {"equipment": len(out["equipment"]), "design_kept": kept,
               "design_dropped_to_unknown": dropped, "zones": len(out["zones"])}
    logger.info(f"[Discovery] promoted {draft_path} → {out_path}: {summary}")
    return summary


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    import asyncio
    import json

    ap = argparse.ArgumentParser(description="Discovery → draft-commissioning bridge.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("sweep", help="Discover inventory → write a draft spec.")
    s1.add_argument("--building", default="default")
    s1.add_argument("--out", default="")
    s2 = sub.add_parser("promote", help="Reviewed draft → clean commissioning spec.")
    s2.add_argument("draft")
    s2.add_argument("out")
    args = ap.parse_args()

    if args.cmd == "promote":
        print(json.dumps(promote_draft(args.draft, args.out), indent=2))
        return 0

    # sweep — boot a minimal state engine + simulator so there's an inventory.
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import get_database
    bms_state = BMSStateEngine()
    database = get_database(None)
    out = args.out or f"config/commissioning/{args.building}.draft.yaml"

    async def _run():
        draft = await sweep_and_draft(bms_state, database, args.building)
        write_draft(draft, out)
        return draft["_summary"]

    print(json.dumps(asyncio.run(_run()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
