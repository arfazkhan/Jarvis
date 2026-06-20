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


def parse_shift_window(timing: str, shift_date: str):
    """Parse a template timing like '08:00 AM – 04:15 PM' into (start, end) datetimes on
    shift_date. Overnight shifts (end <= start, e.g. '08:00 PM – 08:15 AM') end the NEXT day.
    Returns None for non-clock timings (e.g. PPM 'Every 3 months')."""
    from datetime import datetime as _dt, timedelta as _td
    if not timing:
        return None
    sep = next((d for d in ("–", "—", " to ", " - ", "-") if d in timing), None)
    if not sep:
        return None
    try:
        a, b = [p.strip() for p in timing.split(sep, 1)]
        base = _dt.strptime(shift_date, "%Y-%m-%d")
        st = _dt.strptime(a, "%I:%M %p")
        en = _dt.strptime(b, "%I:%M %p")
        start = base.replace(hour=st.hour, minute=st.minute)
        end = base.replace(hour=en.hour, minute=en.minute)
        if end <= start:
            end += _td(days=1)                      # overnight shift
        return (start, end)
    except Exception:
        return None


def ensure_daily_runs(db, building: str, today: str, now=None, min_hour: int = 6) -> List[Dict[str, Any]]:
    """Auto-open today's recurring (cadence='daily') rounds so the day's checklists always
    appear — carrying forward each template's usual technician. Idempotent (skips templates
    that already have a run today). Gated to >= min_hour local time so it opens in the
    morning, not at midnight (min_hour=0 = open immediately, for the manual button)."""
    from datetime import datetime as _dt
    now = now or _dt.now()
    if now.hour < min_hour:
        return []
    have = {r["template_id"] for r in db.checklist_runs_for(building, today)}
    created: List[Dict[str, Any]] = []
    for tmpl in templates_for(building):
        if tmpl.cadence != "daily" or tmpl.template_id in have:
            continue
        # Open UNASSIGNED — the manager assigns each day (no auto carry-forward of the
        # previous person). The round still appears so the day's checklist is visible.
        rid = db.create_checklist_run(building, tmpl.template_id, today)
        created.append({"run_id": rid, "template_id": tmpl.template_id, "assignee": ""})
    return created


def lapse_stale_rounds(db, building: str, now=None) -> List[Dict[str, Any]]:
    """Give incomplete rounds a TERMINAL. A run lapses once its shift window has ENDED
    (shift-end-aware; overnight shifts end next morning). Templates without a clock window
    fall back to the prior-day rule. Manager gets a notice; a round never hangs open or
    silently disappears. Runs at 100% but unsubmitted still lapse, recorded with completion."""
    from datetime import datetime as _dt, timedelta as _td
    now = now or _dt.now()
    today = now.strftime("%Y-%m-%d")
    fired: List[Dict[str, Any]] = []
    # today + a few prior days covers same-day shift-end, overnight, and carryover.
    dates = sorted({today} | {(now - _td(days=i)).strftime("%Y-%m-%d") for i in range(1, 4)})
    seen = set()
    for d in dates:
        for run in db.checklist_runs_for(building, d):
            if run["id"] in seen:
                continue
            seen.add(run["id"])
            if run.get("status") != "open":
                continue
            tmpl = get_template(run["template_id"], building)
            win = parse_shift_window(tmpl.timing, run["shift_date"]) if tmpl else None
            ended = (now >= win[1]) if win else (run["shift_date"] < today)
            if not ended:
                continue
            pct = run_summary(tmpl, db.checklist_entries(run["id"]))["completion_pct"] if tmpl else 0.0
            db.set_run_status(run["id"], "lapsed")
            name = tmpl.name if tmpl else run["template_id"]
            who = run.get("assignee") or run.get("technician") or "unassigned"
            db.enqueue_notification(
                building, f"⚠️ {name} ({run['shift_date']}) closed INCOMPLETE at {pct:.0f}% "
                          f"— assigned: {who}. Carry over / follow up.", to_number="", kind="round_lapsed")
            fired.append({"run_id": run["id"], "shift_date": run["shift_date"], "completion_pct": pct})
    return fired


def building_evaluation(db, building: str, now=None, days: int = 7) -> Dict[str, Any]:
    """Grounded performance rollup for the admin panel — how AllGud is doing at a building
    over the last `days`. Real counts only (rounds, issues, PPM, per-technician)."""
    from datetime import datetime as _dt, timedelta as _td
    now = now or _dt.now()
    today = now.strftime("%Y-%m-%d")
    dates = [(now - _td(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    runs = [r for d in dates for r in db.checklist_runs_for(building, d)]

    total = len(runs)
    submitted = sum(1 for r in runs if r["status"] == "submitted")
    lapsed = sum(1 for r in runs if r["status"] == "lapsed")
    openn = sum(1 for r in runs if r["status"] == "open")
    comps = []
    for r in runs:
        t = get_template(r["template_id"], building)
        if t:
            comps.append(run_summary(t, db.checklist_entries(r["id"]))["completion_pct"])
    avg_completion = round(sum(comps) / len(comps), 1) if comps else 0.0

    issues = db.list_issues(building)
    recent = [i for i in issues if (i.get("created_at") or "")[:10] in dates]
    raised = len(recent)
    resolved = sum(1 for i in recent if i["status"] == "resolved")
    res_hrs = []
    for i in recent:
        if i["status"] == "resolved" and i.get("created_at") and i.get("updated_at"):
            try:
                res_hrs.append((_dt.fromisoformat(i["updated_at"][:19])
                                - _dt.fromisoformat(i["created_at"][:19])).total_seconds() / 3600.0)
            except Exception:
                pass

    from arvisx.sla import sla_status
    cfg = db.get_sla_config(building)
    open_iss = [i for i in issues if i["status"] != "resolved"]
    sla_breached = sla_at_risk = 0
    for i in open_iss:
        st = sla_status(i, cfg, now)
        if st["breached_resolution"]:
            sla_breached += 1
        elif st["escalation_level"] >= 1:
            sla_at_risk += 1

    scheds = db.list_ppm_schedules(building)
    pstates = [ppm_status(s, today, None) for s in scheds]

    techs = []
    for t in db.list_technicians(building):
        trs = [r for r in runs if t["name"] in (r.get("assignee"), r.get("technician"))]
        sub = sum(1 for r in trs if r["status"] == "submitted")
        techs.append({"name": t["name"], "assigned": len(trs), "submitted": sub,
                      "completion_pct": round(100 * sub / len(trs), 1) if trs else 0.0})

    return {
        "building": building, "window_days": days, "generated_at": now.isoformat(timespec="seconds"),
        "rounds": {"total": total, "submitted": submitted, "lapsed": lapsed, "open": openn,
                   "submit_rate_pct": round(100 * submitted / total, 1) if total else 0.0,
                   "avg_completion_pct": avg_completion},
        "issues": {"raised": raised, "resolved": resolved, "open": len(open_iss),
                   "sla_breached": sla_breached, "sla_at_risk": sla_at_risk,
                   "avg_resolution_hrs": round(sum(res_hrs) / len(res_hrs), 1) if res_hrs else None,
                   "action_rate_pct": round(100 * resolved / raised, 1) if raised else None},
        "ppm": {"scheduled": len(scheds),
                "overdue": sum(1 for p in pstates if p.get("status") == "overdue"),
                "due_soon": sum(1 for p in pstates if p.get("status") == "due_soon")},
        "technicians": sorted(techs, key=lambda x: -x["assigned"]),
        "bot": {"pending_notifications": len(db.pending_notifications())},
    }


def building_trend(db, building: str, days: int = 30, now=None) -> List[Dict[str, Any]]:
    """Per-day series (oldest→newest) for trend charts: completion %, rounds, issues opened.
    Lets the UI show that a low day sits inside an otherwise-healthy week/month."""
    from datetime import datetime as _dt, timedelta as _td
    now = now or _dt.now()
    issues = db.list_issues(building)
    out: List[Dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        d = (now - _td(days=i)).strftime("%Y-%m-%d")
        runs = db.checklist_runs_for(building, d)
        comps = []
        for r in runs:
            t = get_template(r["template_id"], building)
            if t:
                comps.append(run_summary(t, db.checklist_entries(r["id"]))["completion_pct"])
        out.append({"date": d,
                    "completion_pct": round(sum(comps) / len(comps), 1) if comps else 0.0,
                    "runs": len(runs),
                    "issues_opened": sum(1 for x in issues if (x.get("created_at") or "")[:10] == d)})
    return out


def aged_open_issues(db, building: str, now: Optional["datetime"] = None,
                     days: float = 2.0) -> List[Dict[str, Any]]:
    """Fix #2: issues open longer than `days` — so a long-unresolved issue can't fade even
    after it hits the top of the escalation ladder. Feeds the manager digest."""
    from datetime import datetime as _dt
    now = now or _dt.now()
    out = []
    for i in db.list_issues(building):
        if i["status"] == "resolved":
            continue
        try:
            age_d = (now - _dt.fromisoformat(str(i["created_at"])[:19])).total_seconds() / 86400.0
        except Exception:
            continue
        if age_d >= days:
            out.append({"id": i["id"], "title": i["title"], "status": i["status"],
                        "age_days": round(age_d, 1), "assignee": i.get("assignee") or "",
                        "vendor": i.get("vendor") or ""})
    out.sort(key=lambda x: x["age_days"], reverse=True)
    return out


def round_reminders(db, building: str, now: Optional["datetime"] = None,
                    remind_after_h: float = 6.0, escalate_after_h: float = 10.0,
                    nudge_frac: float = 0.6, escalate_before_min: int = 30) -> List[Dict[str, Any]]:
    """Chase ASSIGNED, unfinished rounds — SHIFT-END AWARE. When the template has a clock
    window (timing), nudge the technician partway through the shift (nudge_frac of the way)
    and escalate to the manager shortly before shift close (escalate_before_min). Templates
    without a clock window fall back to fixed hours-since-start (remind_after_h/escalate_after_h).
    Past shift end, the lapse sweep takes over. One notification per level (reminded_level
    guard). This is the 'if not done → WhatsApp' half for ROUNDS (the SLA sweep covers ISSUES)."""
    from datetime import datetime as _dt, timedelta as _td
    now = now or _dt.now()
    fired: List[Dict[str, Any]] = []
    # today + yesterday so overnight shifts (which end next morning) are still chased.
    dates = {now.strftime("%Y-%m-%d"), (now - _td(days=1)).strftime("%Y-%m-%d")}
    seen = set()
    for d in sorted(dates):
        for run in db.checklist_runs_for(building, d):
            if run["id"] in seen:
                continue
            seen.add(run["id"])
            if run.get("status") != "open":          # submitted/lapsed → skip
                continue
            tmpl = get_template(run["template_id"], building)
            if tmpl is None:
                continue
            summ = run_summary(tmpl, db.checklist_entries(run["id"]))
            if summ["completion_pct"] >= 100:
                continue
            prev = int(run.get("reminded_level") or 0)
            assignee = run.get("assignee") or ""
            pending = summ["total"] - summ["done"]
            pct = summ["completion_pct"]

            win = parse_shift_window(tmpl.timing, run["shift_date"])
            if win:
                start, end = win
                if now >= end:                       # shift over → lapse sweep handles it
                    continue
                nudge_at = start + (end - start) * nudge_frac
                esc_at = max(nudge_at, end - _td(minutes=escalate_before_min))
                do_nudge, do_escalate = now >= nudge_at, now >= esc_at
            else:                                    # no clock window → fixed hours since start
                try:
                    age_h = (now - _dt.fromisoformat(str(run["started_at"])[:19])).total_seconds() / 3600.0
                except Exception:
                    continue
                do_nudge, do_escalate = age_h >= remind_after_h, age_h >= escalate_after_h

            if do_escalate and prev < 2:
                who = assignee or "unassigned"
                db.enqueue_notification(
                    building, f"⚠️ {tmpl.name} ({run['shift_date']}) only {pct:.0f}% done by {who} — "
                              f"{pending} item(s) pending, shift closing.", to_number="", kind="round_escalation")
                db.set_run_reminded(run["id"], 2)
                fired.append({"run_id": run["id"], "level": 2, "assignee": assignee})
            elif do_nudge and prev < 1:
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
