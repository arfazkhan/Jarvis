"""
commissioning.py
================
Single onboarding path that populates ARVIS with a building's design facts —
the data several features need but cannot infer from telemetry:

  - equipment.design_attributes  → precondition gate (design-context RCA)
  - zones (CO2/VAV/light points)  → ghost-space detection
  - equipment specs/runtime_hours → predictive maintenance
  - point → equipment maps        → grounding

A real deployment commissions the building ONCE from a per-building spec file
(YAML or JSON). The simulator/demo fixtures emit the same schema, so onboarding
and the demo share one code path (no test-only divergence).

Schema (YAML):

    building_id: marina_heights
    equipment:
      - id: AHU-07
        type: air_handling_unit          # EquipmentType value
        name: AHU Floor 28 (Executive)
        location: "Floor 28, Zone A"
        design_attributes:               # declared, never guessed
          damper_type: fixed             # fixed | motorized | 2-position
          has_vfd: true
          economizer: false
        specs:
          manufacturer: Trane
          model: M-Series
          install_date: 2019-03-01
          runtime_hours: 31200
        points:
          - point_id: AHU-07/SAT
            name: Supply Air Temp
            unit: C
            point_type: sensor           # PointType value
            value: 16.5
    zones:
      - zone_id: ZONE-28A
        name: Executive Office 28A
        floor: "28"
        co2_point_id: ZONE-28A/CO2
        vav_point_id: ZONE-28A/VAV_DMPR
        lighting_point_id: ZONE-28A/LIGHT
        load_kw: 2.5

Idempotent: re-running upserts (register_equipment / save_zone / update_point all
overwrite). Safe to re-commission after a spec edit.

CLI:   python -m agent_commercial.commissioning config/commissioning/<building>.yaml
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.commissioning")


# ──────────────────────────────────────────────────────────────────────────
# Spec loading
# ──────────────────────────────────────────────────────────────────────────
def load_spec(path: str | Path) -> Dict[str, Any]:
    """Parse a commissioning spec from .yaml/.yml or .json."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Commissioning spec not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"PyYAML required to read {p.suffix} specs (pip install pyyaml), "
                f"or provide a .json spec instead."
            ) from e
        return yaml.safe_load(text) or {}
    return json.loads(text)


def _parse_date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%Y-%m"):
        try:
            return datetime.strptime(str(v), fmt)
        except ValueError:
            continue
    logger.warning(f"[Commission] unparseable install_date '{v}' — ignoring")
    return None


# ──────────────────────────────────────────────────────────────────────────
# Core commissioning — idempotent upserts into existing state APIs
# ──────────────────────────────────────────────────────────────────────────
async def commission_building(
    spec: Dict[str, Any],
    bms_state: Any,
    database: Any = None,
) -> Dict[str, Any]:
    """
    Apply a commissioning spec to live state. Returns a summary count dict.

    bms_state: BMSStateEngine (register_equipment, update_point)
    database:  BMSDatabase    (save_zone) — optional; zones skipped if absent.
    """
    from agent_commercial.bms_data_model import (
        Equipment, EquipmentType, EquipmentStatus, BMSDataPoint, PointType,
    )

    def _eq_type(s: str) -> EquipmentType:
        s = (s or "other").strip().lower()
        for t in EquipmentType:
            if t.value == s or t.name.lower() == s:
                return t
        logger.warning(f"[Commission] unknown equipment type '{s}' → OTHER")
        return EquipmentType.OTHER

    def _pt_type(s: str) -> PointType:
        s = (s or "sensor").strip().lower()
        for t in PointType:
            if t.value == s or t.name.lower() == s:
                return t
        return PointType.SENSOR

    building_id = spec.get("building_id", "default")
    counts = {"equipment": 0, "points": 0, "zones": 0, "design_attributed": 0}

    # ── Equipment + their points ──────────────────────────────────────────
    for eq in spec.get("equipment", []) or []:
        if not isinstance(eq, dict) or not eq.get("id"):
            logger.warning(f"[Commission] skipping equipment with no id: {eq}")
            continue
        specs = eq.get("specs", {}) or {}
        design = eq.get("design_attributes", {}) or {}
        # MERGE onto an existing equipment record if present (simulator-generated
        # or previously onboarded) so we add design facts/specs without clobbering
        # live status, data_points, or runtime metrics. Only create fresh when the
        # equipment doesn't exist yet (true cold onboarding).
        existing = None
        try:
            existing = await bms_state.get_equipment(eq["id"])
        except Exception:
            existing = None
        if existing is not None:
            existing.design_attributes = {**(getattr(existing, "design_attributes", {}) or {}), **design}
            if specs.get("manufacturer"): existing.manufacturer = specs["manufacturer"]
            if specs.get("model"): existing.model = specs["model"]
            if specs.get("install_date"): existing.install_date = _parse_date(specs["install_date"])
            if specs.get("runtime_hours") is not None:
                existing.runtime_hours = float(specs.get("runtime_hours") or 0.0)
            if eq.get("location"): existing.location = eq["location"]
            await bms_state.register_equipment(existing)
        else:
            await bms_state.register_equipment(Equipment(
                equipment_id=eq["id"],
                name=eq.get("name", eq["id"]),
                equipment_type=_eq_type(eq.get("type", "other")),
                location=eq.get("location", ""),
                status=EquipmentStatus.UNKNOWN,
                manufacturer=specs.get("manufacturer", ""),
                model=specs.get("model", ""),
                install_date=_parse_date(specs.get("install_date")),
                runtime_hours=float(specs.get("runtime_hours", 0.0) or 0.0),
                design_attributes=dict(design),
            ))
        counts["equipment"] += 1
        if design:
            counts["design_attributed"] += 1

        for pt in eq.get("points", []) or []:
            if not isinstance(pt, dict) or not pt.get("point_id"):
                continue
            _val = pt.get("value")
            await bms_state.update_point(BMSDataPoint(
                point_id=pt["point_id"],
                name=pt.get("name", pt["point_id"]),
                value=float(_val) if isinstance(_val, (int, float)) else None,
                unit=pt.get("unit", ""),
                source="commission",
                equipment_id=eq["id"],
                point_type=_pt_type(pt.get("point_type", "sensor")),
            ))
            counts["points"] += 1

    # ── Zones (ghost-space detection inputs) ──────────────────────────────
    zones = spec.get("zones", []) or []
    if zones and database is not None and hasattr(database, "save_zone"):
        for z in zones:
            if not isinstance(z, dict) or not z.get("zone_id"):
                continue
            await database.save_zone({
                "zone_id": z["zone_id"],
                "name": z.get("name", z["zone_id"]),
                "floor": str(z.get("floor", "")),
                "building": z.get("building", building_id),
                "co2_point_id": z.get("co2_point_id"),
                "vav_point_id": z.get("vav_point_id"),
                "lighting_point_id": z.get("lighting_point_id"),
                "return_air_point_id": z.get("return_air_point_id"),
                "schedule_id": z.get("schedule_id"),
                "load_kw": float(z.get("load_kw", 2.0) or 2.0),
                "metadata": z.get("metadata", {}),
            })
            counts["zones"] += 1
    elif zones:
        logger.warning("[Commission] zones present but no database with save_zone — zones skipped")

    logger.info(
        f"[Commission] building '{building_id}': "
        f"{counts['equipment']} equipment ({counts['design_attributed']} with design), "
        f"{counts['points']} points, {counts['zones']} zones"
    )
    return {"building_id": building_id, **counts}


def default_spec_path(building_id: str = "default") -> Path:
    """Convention: config/commissioning/<building_id>.yaml (or .json)."""
    base = Path(__file__).parent.parent / "config" / "commissioning"
    for ext in (".yaml", ".yml", ".json"):
        p = base / f"{building_id}{ext}"
        if p.exists():
            return p
    return base / f"{building_id}.yaml"


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="Commission a building into ARVIS.")
    ap.add_argument("spec", help="Path to commissioning spec (.yaml/.json)")
    ap.add_argument("--db", default=os.getenv("ARVIS_DB_PATH", ""), help="DB path (zones)")
    args = ap.parse_args()

    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import get_database

    spec = load_spec(args.spec)
    bms_state = BMSStateEngine()
    database = get_database(args.db or None)

    async def _run():
        if hasattr(database, "initialize"):
            try:
                await database.initialize()
            except Exception:
                pass
        return await commission_building(spec, bms_state, database)

    result = asyncio.run(_run())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
