"""
ArvisX — checklist intelligence (DB + analyzers → grounded signals).

The single source the deterministic analyzers' API endpoints AND the agent tools both
call, so there's one implementation of "health of asset X", "reading anomalies", etc.
Everything here returns REAL computed data from the checklist DB — the grounding floor
the LLM agents reason over (they never invent these numbers).
"""
from __future__ import annotations

from collections import Counter
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


def round_reminders(db, building: str, now: Optional["datetime"] = None,
                    remind_after_h: float = 6.0, escalate_after_h: float = 10.0) -> List[Dict[str, Any]]:
    """Chase ASSIGNED rounds that aren't finished. After remind_after_h → DM the assigned
    technician (their pending items); after escalate_after_h still incomplete → escalate to
    the manager (ops). One notification per level (reminded_level guard). Submitted/complete
    rounds are skipped. This is the 'if not done → WhatsApp alert' half for ROUNDS (the SLA
    sweep covers ISSUES)."""
    from datetime import datetime as _dt
    now = now or _dt.now()
    today = now.strftime("%Y-%m-%d")
    fired: List[Dict[str, Any]] = []
    for run in db.checklist_runs_for(building, today):
        if run.get("status") == "submitted":
            continue
        tmpl = get_template(run["template_id"], building)
        if tmpl is None:
            continue
        summ = run_summary(tmpl, db.checklist_entries(run["id"]))
        if summ["completion_pct"] >= 100:
            continue
        try:
            age_h = (now - _dt.fromisoformat(str(run["started_at"])[:19])).total_seconds() / 3600.0
        except Exception:
            continue
        prev = int(run.get("reminded_level") or 0)
        assignee = run.get("assignee") or ""
        pending = summ["total"] - summ["done"]
        pct = summ["completion_pct"]
        if age_h >= escalate_after_h and prev < 2:
            who = assignee or "unassigned"
            db.enqueue_notification(
                building, f"⚠️ {tmpl.name} ({today}) only {pct:.0f}% done by {who} — "
                          f"{pending} item(s) pending, shift closing.", to_number="", kind="round_escalation")
            db.set_run_reminded(run["id"], 2)
            fired.append({"run_id": run["id"], "level": 2, "assignee": assignee})
        elif age_h >= remind_after_h and prev < 1:
            to_number = ""
            if assignee:
                tech = db.get_technician(building, assignee)
                to_number = (tech or {}).get("phone", "") or ""
            db.enqueue_notification(
                building, f"📋 {tmpl.name} is {pct:.0f}% done — {pending} item(s) still pending. "
                          "Please complete before shift close.", to_number=to_number, kind="round_reminder")
            db.set_run_reminded(run["id"], 1)
            fired.append({"run_id": run["id"], "level": 1, "assignee": assignee})
    return fired


def failure_watchlist(db, building: str, today: str) -> List[Dict[str, Any]]:
    """L6, the HONEST version: a grounded rising-concern list — evidence + a concern LEVEL
    (elevated / high), NEVER a fabricated failure probability or window. A real % needs the
    dense sensor telemetry of Phase 1; on sparse checklist data we name the signals only."""
    out: List[Dict[str, Any]] = []
    for asset in assets_in(building):
        signals: List[str] = []
        for _t, it in items_for_asset(building, asset):
            if it.kind != "reading":
                continue
            vals = [_num(e["value"]) for e in db.asset_entries(building, [it.item_id], limit=60)]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 4:
                tr = analyzers.trend_alert(list(reversed(vals)))
                if tr.get("flagged") and tr["direction"] == "declining":
                    signals.append(f"{it.label} declining ({tr['from']}→{tr['to']})")
            if len(vals) >= 6:
                an = analyzers.reading_anomaly(vals[1:], vals[0])
                if an.get("flagged") and an["direction"] == "below":
                    signals.append(f"{it.label} below normal (latest {an['latest']})")
        issues = db.list_issues(building, asset=asset)
        open_crit = [i for i in issues if i["status"] != "resolved" and i.get("severity") == "critical"]
        if open_crit:
            signals.append(f"{len(open_crit)} open critical issue(s)")
        titles = Counter(i["title"].split(":")[0].strip() for i in issues)
        recurring = [t for t, c in titles.items() if c >= 2]
        if recurring:
            signals.append("recurring: " + ", ".join(recurring))
        sched = db.get_ppm_schedule(building, asset)
        ppm = ppm_status(sched, today, latest_run_hours(db, building, asset)) if sched else None
        if ppm and ppm.get("status") == "overdue":
            signals.append("PPM overdue")
        if not signals:
            continue
        concern = "high" if (open_crit or len(signals) >= 2) else "elevated"
        out.append({"asset": asset, "concern": concern, "signals": signals,
                    "note": "Concern level from corroborating signals — no failure "
                            "probability/window (that needs continuous sensor data, Phase 1)."})
    out.sort(key=lambda w: {"high": 0, "elevated": 1}.get(w["concern"], 9))
    return out


def building_readiness(db, building: str, today: str) -> Dict[str, Any]:
    """One building score from the checklist data — MAINTENANCE readiness (is the building
    being properly inspected + maintained), NOT live equipment condition (that needs
    sensors). Transparent: returns its components so it's explainable. Honest: a day with
    no completed rounds is capped — you can't claim readiness you didn't verify.

    readiness = 0.7·(weighted asset health) + 0.3·(today's round completion) − PPM penalty.
    Risk-band assets weigh heavier so one bad asset realistically drags the score down."""
    assets = asset_health_all(db, building, today)          # riskiest first
    w = {"risk": 2.0, "watch": 1.5, "good": 1.0}
    if assets:
        num = sum(a["score"] * w.get(a["band"], 1.0) for a in assets)
        den = sum(w.get(a["band"], 1.0) for a in assets)
        health = num / den
    else:
        health = 100.0
    comps = []
    for r in db.checklist_runs_for(building, today):
        t = get_template(r["template_id"], building)
        if t:
            comps.append(run_summary(t, db.checklist_entries(r["id"]))["completion_pct"])
    completion = (sum(comps) / len(comps)) if comps else 0.0
    no_rounds = not comps
    comp = compliance(db, building, today)
    overdue_n = len(comp.get("overdue_ppm") or [])
    penalty = min(20, 5 * overdue_n)
    readiness = 0.7 * health + 0.3 * completion - penalty
    if no_rounds:
        readiness = min(readiness, 60.0)                   # unverified today → can't be "healthy"
    readiness = max(0.0, min(100.0, round(readiness)))
    band = "Healthy" if readiness >= 80 else ("Attention Required" if readiness >= 50 else "Critical")
    contributors = []
    for a in assets[:3]:
        if a["band"] != "good":
            why = f" ({', '.join(a['reasons'])})" if a["reasons"] else ""
            contributors.append(f"{a['asset']}: {a['score']}/100{why}")
    if overdue_n:
        contributors.append(f"{overdue_n} PPM overdue")
    if no_rounds:
        contributors.append("no rounds completed today")
    elif completion < 100:
        contributors.append(f"rounds {completion:.0f}% complete today")
    return {"label": "Maintenance Readiness", "readiness": readiness, "band": band,
            "components": {"asset_health_avg": round(health),
                           "rounds_completion_avg": round(completion),
                           "overdue_ppm": overdue_n, "compliance_penalty": penalty},
            "contributors": contributors, "assets_assessed": len(assets),
            "note": "Maintenance/inspection readiness from checklist data — not live equipment "
                    "condition (sensors, Phase 1, upgrade this same score to real-time)."}


def asset_history(db, building: str, asset: str, today: str, limit: int = 100) -> Dict[str, Any]:
    ids = [it.item_id for _t, it in items_for_asset(building, asset)]
    entries = db.asset_entries(building, ids, limit=limit)
    issues = db.list_issues(building, asset=asset)
    sched = db.get_ppm_schedule(building, asset)
    ppm = ppm_status(sched, today, latest_run_hours(db, building, asset)) if sched else None
    return {"asset": asset, "entries": entries, "issues": issues, "ppm": ppm}
