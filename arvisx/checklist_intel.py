"""
ArvisX — checklist intelligence (DB + analyzers → grounded signals).

The single source the deterministic analyzers' API endpoints AND the agent tools both
call, so there's one implementation of "health of asset X", "reading anomalies", etc.
Everything here returns REAL computed data from the checklist DB — the grounding floor
the LLM agents reason over (they never invent these numbers).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from arvisx import analyzers
from arvisx.checklist_forms import (assets_in, items_for_asset, templates_for,
                                    get_template, run_summary, ppm_status)


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def latest_run_hours(db, building: str, asset: str) -> Optional[float]:
    ids = [it.item_id for _t, it in items_for_asset(building, asset)
           if it.kind == "reading" and it.unit == "hrs"]
    for e in db.asset_entries(building, ids, limit=50):
        v = _num(e["value"])
        if v is not None:
            return v
    return None


def days_since_check(db, building: str, asset: str, today: str) -> Optional[int]:
    ids = [it.item_id for _t, it in items_for_asset(building, asset)]
    ents = db.asset_entries(building, ids, limit=1)
    if not ents:
        return None
    try:
        return (date.fromisoformat(today) - date.fromisoformat(ents[0]["ts"][:10])).days
    except Exception:
        return None


def reading_findings(db, building: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """L1 across every reading item with enough history. (flagged, anomaly_count_by_asset)."""
    findings, by_asset, seen = [], {}, set()
    for t in templates_for(building):
        for it in t.all_items():
            if it.kind != "reading" or it.item_id in seen:
                continue
            seen.add(it.item_id)
            vals = [_num(e["value"]) for e in db.asset_entries(building, [it.item_id], limit=60)]
            vals = [v for v in vals if v is not None]
            if len(vals) < 6:
                continue
            r = analyzers.reading_anomaly(vals[1:], vals[0])
            if r.get("flagged"):
                findings.append({"item_id": it.item_id, "label": it.label, "asset": it.asset,
                                 "unit": it.unit, **r})
                by_asset[it.asset] = by_asset.get(it.asset, 0) + 1
    return findings, by_asset


def asset_health_one(db, building: str, asset: str, today: str,
                     anomalies: int = 0) -> Dict[str, Any]:
    issues = [i for i in db.list_issues(building, asset=asset) if i["status"] != "resolved"]
    crit = sum(1 for i in issues if i.get("severity") == "critical")
    sched = db.get_ppm_schedule(building, asset)
    ppm = ppm_status(sched, today, latest_run_hours(db, building, asset)) if sched else None
    h = analyzers.asset_health(open_issues=len(issues), critical_issues=crit, anomalies=anomalies,
                               overdue_ppm=bool(ppm and ppm["status"] == "overdue"),
                               days_since_check=days_since_check(db, building, asset, today))
    return {"asset": asset, **h, "open_issues": len(issues),
            "overdue_ppm": bool(ppm and ppm["status"] == "overdue")}


def asset_health_all(db, building: str, today: str) -> List[Dict[str, Any]]:
    _f, by_asset = reading_findings(db, building)
    out = [asset_health_one(db, building, a, today, anomalies=by_asset.get(a, 0))
           for a in assets_in(building)]
    out.sort(key=lambda a: a["score"])      # riskiest first
    return out


def compliance(db, building: str, today: str) -> Dict[str, Any]:
    scheds = [ppm_status(s, today, latest_run_hours(db, building, s["asset"]))
              for s in db.list_ppm_schedules(building)]
    stale = []
    for asset in assets_in(building):
        d = days_since_check(db, building, asset, today)
        if d is None or d > 7:
            stale.append({"asset": asset, "days_since_check": d})
    return analyzers.compliance_report(scheds, stale)


def asset_history(db, building: str, asset: str, today: str, limit: int = 100) -> Dict[str, Any]:
    ids = [it.item_id for _t, it in items_for_asset(building, asset)]
    entries = db.asset_entries(building, ids, limit=limit)
    issues = db.list_issues(building, asset=asset)
    sched = db.get_ppm_schedule(building, asset)
    ppm = ppm_status(sched, today, latest_run_hours(db, building, asset)) if sched else None
    return {"asset": asset, "entries": entries, "issues": issues, "ppm": ppm}
