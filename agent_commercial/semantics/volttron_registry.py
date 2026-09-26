"""
VOLTTRON BACnet registry CSV → ARVIS point config
=================================================

Many sites (and every VOLTTRON deployment) already describe their BACnet
points as a VOLTTRON registry CSV:

    Point Name, Volttron Point Name, Units, Unit Details, BACnet Object Type,
    Property, Writable, Index, Write Priority, Notes

Importing that format means a building mapped for VOLTTRON needs no re-mapping
for ARVIS, and a later switch to a VOLTTRON edge collector keeps the same
point names. ARVIS only ever READS — ``Writable`` is recorded, never used.

An optional ``ARVIS Role`` (or ``Role``) column carries an explicit point
role (see semantics.point_roles); rows without one get suffix suggestions at
runtime like any other point.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_commercial.semantics.point_roles import parse_role

logger = logging.getLogger("arvis.semantics.volttron")

_REQUIRED = ("Volttron Point Name", "BACnet Object Type", "Index")


def load_volttron_registry(csv_path: str | Path, device_id: int, equipment_id: str,
                           point_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse a VOLTTRON registry CSV into ARVIS ``bacnet.points`` entries.

    point_id = ``<point_prefix or equipment_id>/<Volttron Point Name>``.
    Rows missing an object type or instance are skipped with a warning.
    """
    path = Path(csv_path)
    prefix = point_prefix or equipment_id
    points: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        missing = [h for h in _REQUIRED if h not in headers]
        if missing:
            raise ValueError(f"{path}: not a VOLTTRON registry (missing columns {missing})")
        for n, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            name = row.get("Volttron Point Name")
            obj_type = row.get("BACnet Object Type")
            idx = row.get("Index")
            if not name or not obj_type or not idx:
                logger.warning(f"{path}:{n}: skipped (name/object type/index missing)")
                continue
            try:
                instance = int(float(idx))
            except ValueError:
                logger.warning(f"{path}:{n}: skipped (bad Index {idx!r})")
                continue
            entry: Dict[str, Any] = {
                "point_id": f"{prefix}/{name}",
                "name": row.get("Point Name") or name,
                "device_id": int(device_id),
                "object_type": obj_type,
                "object_instance": instance,
                "property": row.get("Property") or "presentValue",
                "unit": row.get("Units", ""),
                "equipment_id": equipment_id,
                "writable_in_bms": row.get("Writable", "").upper() == "TRUE",
            }
            role_txt = row.get("ARVIS Role") or row.get("Role")
            if role_txt:
                role = parse_role(role_txt)
                if role is None:
                    logger.warning(f"{path}:{n}: unknown role {role_txt!r} — ignored")
                else:
                    entry["role"] = role.value
            points.append(entry)
    logger.info(f"Loaded {len(points)} points from VOLTTRON registry {path}")
    return points
