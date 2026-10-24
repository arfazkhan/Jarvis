"""
Utility bills → monthly meter points.

What the utility charged is the ground truth a building's own meters are checked
against (and, in a building with no meters at all, the only consumption figure).
Each bill becomes points on the bill's last day, source "import":

    <METER>/BILL_KWH   electricity consumed in the period
    <METER>/BILL_M3    water consumed in the period
    <METER>/BILL_COST  amount charged (QAR)

From a bill document (document_ingestion, once it's confirmed — never from a guess)
or a CSV of bills: meter,period,kwh,m3,cost  (period = YYYY-MM).
"""

from __future__ import annotations

import csv
import io
import re
from calendar import monthrange
from datetime import datetime
from typing import Any, Dict, List, Optional


def period_end(period: str) -> datetime:
    m = re.fullmatch(r"(20\d\d)-(0[1-9]|1[0-2])", (period or "").strip())
    if not m:
        raise ValueError(f"period is YYYY-MM, not {period!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    return datetime(y, mo, monthrange(y, mo)[1], 23, 59, 59)


async def record_bill(database: Any, meter_id: str, period: str, *, kwh: Optional[float] = None,
                      m3: Optional[float] = None, cost: Optional[float] = None) -> List[Dict[str, Any]]:
    ts = period_end(period)
    rows = []
    for suffix, value, unit in (("BILL_KWH", kwh, "kWh"), ("BILL_M3", m3, "m3"), ("BILL_COST", cost, "QAR")):
        if value is None:
            continue
        rows.append({"point_id": f"{meter_id}/{suffix}", "equipment_id": meter_id, "value": float(value),
                     "unit": unit, "quality": "good", "timestamp": ts, "source": "import", "confidence": 1.0})
    if not rows:
        raise ValueError(f"bill for {meter_id} {period}: no kWh, m3 or cost")
    await database.save_data_points_batch(rows)
    return rows


async def import_bills_csv(database: Any, text: str) -> Dict[str, Any]:
    out = {"bills": 0, "errors": []}
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        try:
            num = lambda k: float(row[k].replace(",", "")) if row.get(k) else None   # noqa: E731
            await record_bill(database, row.get("meter") or "MAIN", row.get("period", ""), kwh=num("kwh"),
                              m3=num("m3"), cost=num("cost"))
            out["bills"] += 1
        except (ValueError, KeyError) as e:
            out["errors"].append({"line": i, "error": str(e)})
    return out
