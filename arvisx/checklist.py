"""
ArvisX Phase-17b — the self-writing daily checklist + pencil-whip detection.

The field reality: technicians are supposed to walk daily equipment rounds and log
readings; in practice nobody walks, and at week-end random numbers are backfilled and
submitted. ArvisX fixes this with its own core philosophy — every claim checked
against evidence:

  1. AUTO-FILL  — most checklist items ARE telemetry ArvisX already reads (tank %,
     runtimes, battery V, pressures). The daily log writes itself from the live
     stream: timestamped, complete, tamper-proof.
  2. VERIFY     — when a human submits a reading, compare it against the recorded
     telemetry at the claimed time → matched / MISMATCH (flagged) / no-data (honest
     abstain). Friday-backfilled fiction collapses because the sensors were watching.
  3. PHYSICAL   — the few checks only a human can do (visual leak, noise, smell) are
     prompted over WhatsApp ("pump room visual check? reply OK / photo") and land in
     the same timestamped log.

Deterministic throughout — no LLM in this path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Telemetry-backed items: (item_id, asset_id, signal, label, unit)
AUTO_ITEMS = [
    ("ugt_level",    "UG-TANK-01",    "tank_level_pct",      "Underground tank level", "%"),
    ("oht_level",    "OH-TANK-01",    "tank_level_pct",      "Overhead tank level", "%"),
    ("boost_power",  "BOOST-PUMP-01", "power_kw",            "Booster pump power draw", "kW"),
    ("gen_fuel",     "GEN-01",        "fuel_level_pct",      "Generator fuel level", "%"),
    ("gen_battery",  "GEN-BATT-01",   "battery_voltage",     "Generator battery voltage", "V"),
    ("stp_runtime",  "STP-BLOWER-01", "runtime_today_hours", "STP blower runtime today", "h"),
    ("pool_runtime", "POOL-FILT-01",  "runtime_today_hours", "Pool filtration runtime today", "h"),
    ("gas_level",    "GAS-PLANT-01",  "tank_level_pct",      "Gas bank level", "%"),
    ("gas_pressure", "GAS-PLANT-01",  "line_pressure_bar",   "Gas line pressure", "bar"),
]

# Human-only items: (item_id, label, prompt sent over WhatsApp)
PHYSICAL_ITEMS = [
    ("pump_room_visual", "Pump room visual check",
     "🔧 Daily check: pump room visual — leaks, unusual noise/vibration? Reply: ok pump_room_visual / issue pump_room_visual <note>"),
    ("gen_room_visual", "Generator room visual check",
     "🔧 Daily check: generator room — oil/coolant leaks, battery terminals? Reply: ok gen_room_visual / issue gen_room_visual <note>"),
    ("gas_plant_smell", "Gas plant area odour check",
     "🔧 Daily check: gas plant area — any gas odour? Reply: ok gas_plant_smell / issue gas_plant_smell <note>"),
    ("pool_area_visual", "Pool area visual check",
     "🔧 Daily check: pool water clarity + deck condition? Reply: ok pool_area_visual / issue pool_area_visual <note>"),
]

# Verification tolerance: |submitted − recorded| within max(rel% of recorded, abs floor).
_TOLERANCE_REL = 0.10
_TOL_ABS = {"%": 4.0, "V": 0.3, "kW": 0.5, "h": 1.0, "bar": 0.1}


@dataclass
class ReadingVerdict:
    verdict: str                # "matched" | "mismatch" | "no_data"
    submitted: float
    recorded: Optional[float] = None
    recorded_ts: Optional[str] = None
    note: str = ""


def verify_reading(db, asset_id: str, signal: str, submitted: float,
                   claimed_ts: Optional[datetime] = None, unit: str = "") -> ReadingVerdict:
    """Check a human-submitted reading against the recorded telemetry at the claimed
    time. The grounding rule applied to people: a claim with no matching evidence is
    flagged, a claim with no evidence at all is an honest abstain — never assumed."""
    claimed_ts = claimed_ts or datetime.now()
    rec = db.signal_near(asset_id, signal, claimed_ts)
    if rec is None:
        return ReadingVerdict("no_data", submitted,
                              note="no telemetry recorded near the claimed time — cannot verify")
    recorded = float(rec["value"])
    tol = max(_TOLERANCE_REL * abs(recorded), _TOL_ABS.get(unit, 0.5))
    if abs(submitted - recorded) <= tol:
        return ReadingVerdict("matched", submitted, recorded, rec["ts"],
                              note=f"within ±{tol:.2g}{unit} of the sensor")
    return ReadingVerdict(
        "mismatch", submitted, recorded, rec["ts"],
        note=f"submitted {submitted:g}{unit} but the sensor recorded {recorded:g}{unit} "
             f"at {rec['ts']} — reading does not match reality, flag for review")


def daily_log(assets: List[Any], db, date: Optional[str] = None) -> Dict[str, Any]:
    """The self-writing daily checklist: telemetry items auto-filled from live state,
    physical items merged from technician responses, submitted readings with verdicts."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    by_id = {a.asset_id: a for a in assets}
    auto = []
    for item_id, aid, signal, label, unit in AUTO_ITEMS:
        a = by_id.get(aid)
        v = (a.signals or {}).get(signal) if a is not None else None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            auto.append({"item_id": item_id, "label": label, "asset_id": aid,
                         "status": "no_data", "value": None, "unit": unit,
                         "source": "telemetry"})
        else:
            auto.append({"item_id": item_id, "label": label, "asset_id": aid,
                         "status": "recorded", "value": round(float(v), 2), "unit": unit,
                         "source": "telemetry", "ts": datetime.now().isoformat(timespec="seconds")})

    responses = db.checklist_responses_for(date)
    resp_by_item: Dict[str, Dict] = {}
    for r in responses:
        resp_by_item[r["item_id"]] = r          # latest wins (ordered by ts)

    physical = []
    for item_id, label, prompt in PHYSICAL_ITEMS:
        r = resp_by_item.get(item_id)
        physical.append({"item_id": item_id, "label": label,
                         "status": (r["status"] if r else "pending"),
                         "note": (r["note"] if r else ""), "by": (r["by_user"] if r else None),
                         "ts": (r["ts"] if r else None), "source": "technician"})

    submitted = [r for r in responses if r["item_id"].startswith("reading:")]
    flagged = [r for r in submitted if r.get("verdict", "").startswith("mismatch")]
    done_phys = sum(1 for p in physical if p["status"] != "pending")
    return {
        "date": date,
        "auto": auto,
        "physical": physical,
        "submitted_readings": submitted,
        "summary": {
            "auto_recorded": sum(1 for a in auto if a["status"] == "recorded"),
            "auto_total": len(auto),
            "physical_done": done_phys,
            "physical_total": len(physical),
            "flagged_readings": len(flagged),
        },
    }


def pending_prompts(db, date: Optional[str] = None) -> List[Dict[str, str]]:
    """Physical items not yet answered today — what the WhatsApp bot should send."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    answered = {r["item_id"] for r in db.checklist_responses_for(date)}
    return [{"item_id": i, "label": lbl, "prompt": prompt}
            for i, lbl, prompt in PHYSICAL_ITEMS if i not in answered]


def parse_checklist_reply(text: str) -> Optional[Dict[str, str]]:
    """Parse a technician's WhatsApp reply: 'ok <item_id>' or 'issue <item_id> <note>'."""
    parts = (text or "").strip().split(maxsplit=2)
    if len(parts) >= 2 and parts[0].lower() in ("ok", "issue"):
        item_ids = {i for i, _, _ in PHYSICAL_ITEMS}
        if parts[1] in item_ids:
            return {"item_id": parts[1],
                    "status": "ok" if parts[0].lower() == "ok" else "issue",
                    "note": parts[2] if len(parts) > 2 else ""}
    return None
