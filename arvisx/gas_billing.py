"""
ArvisX Phase-17 — gas metering: kill the month-end manual meter round.

The pain: a basement gas plant pipes cooking gas to every apartment; someone walks the
building at month-end reading each meter by hand to bill the flats. ArvisX records the
per-apartment cumulative meter index continuously (signal `meter_total_m3` → the
timestamped signal_log), so the month-end statement computes itself:

    consumption = last index in month − first index in month, per apartment

Read-only and billing-adjacent, not billing: ArvisX MEASURES and emits the statement
(JSON/CSV); the society applies its tariff and bills. Honesty rules hold: a meter with
no readings in the period → "no_data", never an invented number; a meter whose index
DECREASED → flagged (meter rollover/replacement/tamper — human review).
"""
from __future__ import annotations

import calendar
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

GAS_RATE = float(os.environ.get("ARVISX_GAS_RATE", "0"))      # currency per m³ (0 = omit)
CURRENCY = os.environ.get("ARVISX_CURRENCY", "QAR")
METER_SIGNAL = "meter_total_m3"


def month_bounds(month: str) -> tuple:
    """'YYYY-MM' → (first instant, last instant) of that month."""
    y, m = int(month[:4]), int(month[5:7])
    last_day = calendar.monthrange(y, m)[1]
    return datetime(y, m, 1, 0, 0, 0), datetime(y, m, last_day, 23, 59, 59)


def monthly_statement(db, month: Optional[str] = None) -> Dict[str, Any]:
    """Per-apartment gas consumption for the month, from recorded meter history."""
    month = month or datetime.now().strftime("%Y-%m")
    start, end = month_bounds(month)
    rows: List[Dict[str, Any]] = []
    total = 0.0
    for meter_id in sorted(db.meters_with_history(METER_SIGNAL)):
        rng = db.signal_range(meter_id, METER_SIGNAL, start, end)
        if rng is None:
            rows.append({"meter_id": meter_id, "status": "no_data",
                         "note": "no readings recorded this month — cannot bill from data"})
            continue
        first, last = rng
        used = round(float(last["value"]) - float(first["value"]), 3)
        if used < 0:
            rows.append({"meter_id": meter_id, "status": "flagged",
                         "first_reading": first, "last_reading": last,
                         "note": "index decreased — meter rollover/replacement/tamper; review manually"})
            continue
        row = {"meter_id": meter_id, "status": "ok",
               "first_reading": first, "last_reading": last, "consumption_m3": used}
        if GAS_RATE > 0:
            row["amount"] = round(used * GAS_RATE, 2)
            row["currency"] = CURRENCY
        total += used
        rows.append(row)
    out: Dict[str, Any] = {
        "month": month, "meters": rows,
        "total_consumption_m3": round(total, 3),
        "billable_meters": sum(1 for r in rows if r["status"] == "ok"),
        "flagged": sum(1 for r in rows if r["status"] == "flagged"),
        "no_data": sum(1 for r in rows if r["status"] == "no_data"),
        "note": "Measured by ArvisX from continuous meter telemetry — replaces the manual "
                "month-end meter round. Society applies tariff and bills.",
    }
    if GAS_RATE > 0:
        out["total_amount"] = round(total * GAS_RATE, 2)
        out["currency"] = CURRENCY
        out["rate_per_m3"] = GAS_RATE
    return out


def statement_csv(stmt: Dict[str, Any]) -> str:
    """The statement as CSV — what the society's billing person actually wants."""
    lines = ["meter_id,status,first_index_m3,last_index_m3,consumption_m3"
             + (",amount" if GAS_RATE > 0 else "")]
    for r in stmt["meters"]:
        f = r.get("first_reading", {}).get("value", "")
        l = r.get("last_reading", {}).get("value", "")
        u = r.get("consumption_m3", "")
        amt = r.get("amount", "")
        lines.append(f"{r['meter_id']},{r['status']},{f},{l},{u}"
                     + (f",{amt}" if GAS_RATE > 0 else ""))
    return "\n".join(lines)
