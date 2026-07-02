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


def _template_due_today(tmpl, now, min_hour: int) -> bool:
    """Is this template's cadence schedule due to OPEN now? daily → every day; weekly → its
    day-of-week; monthly → its day-of-month; quarterly → its anchor day, every 3rd month from
    the anchor; custom → its one specific date. All gated to >= sched_time (else >= min_hour).
    Non-daily templates with NO schedule set never auto-open (stay manual) — backward-safe."""
    from datetime import datetime as _dt
    cad = (getattr(tmpl, "cadence", "daily") or "daily").lower()
    st = (getattr(tmpl, "sched_time", "") or "").strip()
    if st:
        try:
            hh, mm = [int(x) for x in st.split(":")[:2]]
        except Exception:
            hh, mm = min_hour, 0
        if (now.hour, now.minute) < (hh, mm):
            return False
    elif now.hour < min_hour:
        return False
    if cad == "daily":
        return True
    if cad == "weekly":
        dow = getattr(tmpl, "sched_dow", None)
        return dow is not None and now.weekday() == int(dow)
    if cad == "monthly":
        dom = getattr(tmpl, "sched_dom", None)
        if dom is None:
            return False
        import calendar
        last = calendar.monthrange(now.year, now.month)[1]   # clamp 29-31 to short months
        return now.day == min(int(dom), last)
    if cad == "quarterly":
        anchor = (getattr(tmpl, "sched_date", "") or "").strip()
        if not anchor:
            return False
        try:
            a = _dt.strptime(anchor, "%Y-%m-%d")
        except Exception:
            return False
        return now.date() >= a.date() and now.day == a.day and (now.month - a.month) % 3 == 0
    if cad == "custom":
        return (getattr(tmpl, "sched_date", "") or "").strip() == now.strftime("%Y-%m-%d")
    return False


def ensure_daily_runs(db, building: str, today: str, now=None, min_hour: int = 6) -> List[Dict[str, Any]]:
    """Auto-open today's DUE rounds so the day's checklists always appear. Daily templates open
    every morning; weekly/monthly/quarterly/custom open when their builder-set schedule lands
    today (see _template_due_today). Idempotent (skips templates that already have a run today).
    Gated to >= min_hour local time (min_hour=0 = open immediately, for the manual button)."""
    from datetime import datetime as _dt
    now = now or _dt.now()
    have = {r["template_id"] for r in db.checklist_runs_for(building, today)}
    created: List[Dict[str, Any]] = []
    for tmpl in templates_for(building):
        if tmpl.template_id in have or not _template_due_today(tmpl, now, min_hour):
            continue
        # Open UNASSIGNED — the manager assigns each day (no auto carry-forward of the
        # previous person). The round still appears so the day's checklist is visible.
        rid = db.create_checklist_run(building, tmpl.template_id, today)
        created.append({"run_id": rid, "template_id": tmpl.template_id, "assignee": ""})
    return created


def _schedule_due(sch: Dict[str, Any], now) -> bool:
    """Has this schedule's date+time arrived for now's date? (the once-per-day dedup via
    last_fired is checked by the caller). once → exact date; daily → every day; weekly →
    matching weekday; monthly → matching day-of-month — each at/after run_time."""
    today = now.strftime("%Y-%m-%d")
    try:
        hh, mm = [int(x) for x in (sch.get("run_time") or "00:00").split(":")[:2]]
    except Exception:
        hh, mm = 0, 0
    if (now.hour, now.minute) < (hh, mm):           # time not reached yet today
        return False
    mode = (sch.get("mode") or "once").lower()
    if mode == "once":
        return sch.get("run_date") == today
    recur = (sch.get("recur") or "daily").lower()
    if recur == "daily":
        return True
    if recur == "weekly":
        return sch.get("dow") is not None and now.weekday() == int(sch["dow"])
    if recur == "monthly":
        return sch.get("dom") is not None and now.day == int(sch["dom"])
    return False


def due_scheduled_checklists(db, building: str, now=None) -> List[Dict[str, Any]]:
    """B2 trigger engine: open a run for every scheduled checklist whose date+time has
    arrived (deduped once/day via last_fired). Pre-assigns when the schedule names a
    technician; one-off schedules deactivate after firing. The caller DMs the assignee."""
    from datetime import datetime as _dt
    now = now or _dt.now()
    today = now.strftime("%Y-%m-%d")
    fired: List[Dict[str, Any]] = []
    for sch in db.list_schedules(building, active_only=True):
        if sch.get("last_fired") == today or not _schedule_due(sch, now):
            continue
        assignee = sch.get("assignee") or ""
        rid = db.create_checklist_run(building, sch["template_id"], today, assignee=assignee)
        db.set_schedule_fired(sch["id"], today)
        if (sch.get("mode") or "once").lower() == "once":
            db.set_schedule_active(sch["id"], False)
        fired.append({"run_id": rid, "schedule_id": sch["id"],
                      "template_id": sch["template_id"], "assignee": assignee})
    return fired


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def lapse_streak(db, building: str, template_id: str, upto_date: str, max_back: int = 30):
    """How many consecutive days (ending on upto_date) this template lapsed — i.e. closed
    incomplete. Streak breaks the first day it didn't run or didn't lapse. Also reports
    whether the whole streak was unassigned (the 'nobody's using this shift' signal).
    Pure history read — grounds the escalation, fabricates nothing."""
    from datetime import datetime as _dt, timedelta as _td
    d0 = _dt.strptime(upto_date, "%Y-%m-%d")
    streak, all_unassigned = 0, True
    for i in range(max_back):
        d = (d0 - _td(days=i)).strftime("%Y-%m-%d")
        runs = [r for r in db.checklist_runs_for(building, d) if r["template_id"] == template_id]
        if not runs or not all(r["status"] == "lapsed" for r in runs):
            break
        if any((r.get("assignee") or r.get("technician")) for r in runs):
            all_unassigned = False
        streak += 1
    return streak, all_unassigned


def _lapse_message(name: str, shift_date: str, pct: float, who: str,
                   streak: int, all_unassigned: bool) -> str:
    """Streak-aware escalation ladder. Day 1 = neutral; days 2-3 = firmer, names the streak;
    day 4+ = chronic-gap escalation with a concrete next action. Adapts to whether the gap is
    'unassigned' (nobody picked it up) vs 'assigned-but-not-done' (the tech isn't doing it)."""
    head = f"{name} ({shift_date}) closed INCOMPLETE at {pct:.0f}% (assigned: {who})."
    if streak <= 1:
        return (f"⚠️ {head} Logged as a gap — today's round repeats these checks; "
                f"any open issues stay tracked.")
    if streak <= 3:
        nudge = ("Still nobody assigned — assign a technician so it actually gets done."
                 if all_unassigned else
                 "Assigned but still not completed — check in with the technician.")
        return f"⚠️ {name} — {_ordinal(streak)} day running at {pct:.0f}% (assigned: {who}). {nudge}"
    # streak >= 4 → chronic. Escalate tone + give the manager a decision to make.
    if all_unassigned:
        action = (f"*{streak} days straight* with nobody assigned and nothing done. "
                  f"Assign a regular technician to this shift — or pause it if it isn't a real "
                  f"shift (Setup → Checklists).")
    else:
        action = (f"*{streak} days straight* lapsed despite being assigned to {who}. "
                  f"The shift isn't getting done — reassign or follow up directly.")
    return f"🔴 {name} — chronic gap. {action}"


def shift_activity(db, building: str, date: str) -> List[Dict[str, Any]]:
    """Who worked which shift on `date`, and how it went — the personnel/round view the
    conversational bot needs to answer 'did anyone work the morning shift', 'what's pending',
    'who's assigned', 'is shift II done'. Real run rows only; nothing inferred."""
    from arvisx.checklist_forms import get_template, run_summary
    out: List[Dict[str, Any]] = []
    for run in db.checklist_runs_for(building, date):
        tmpl = get_template(run["template_id"], building)
        summ = run_summary(tmpl, db.checklist_entries(run["id"])) if tmpl else {}
        out.append({
            "shift": tmpl.name if tmpl else run["template_id"],
            "timing": (getattr(tmpl, "timing", "") or "") if tmpl else "",
            "date": run["shift_date"],
            "assignee": run.get("assignee") or "",          # who it's assigned to
            "worked_by": run.get("technician") or "",        # who actually did it (if anyone)
            "status": run["status"],                         # open / submitted / lapsed
            "completion_pct": summ.get("completion_pct", 0.0),
            "items_done": summ.get("done", 0),
            "items_total": summ.get("total", 0),
            "open_issues": len(summ.get("issues", []) or []),
        })
    return out


def pending_tasks(db, building: str, date: str, technician: str = "") -> List[Dict[str, Any]]:
    """What's still NOT DONE on `date`'s rounds, per shift — the undone item labels, the
    assignee, and completion %. Pass `technician` to scope to ONE person's assigned rounds
    (a tech asking 'my pending'); omit for the whole building (a manager's overview)."""
    from arvisx.checklist_forms import get_template, run_summary
    out: List[Dict[str, Any]] = []
    want = technician.strip().lower()
    for run in db.checklist_runs_for(building, date):
        assignee = run.get("assignee") or ""
        if want and assignee.lower() != want:
            continue
        tmpl = get_template(run["template_id"], building)
        if not tmpl:
            continue
        summ = run_summary(tmpl, db.checklist_entries(run["id"]))
        by_id = {it.item_id: it for it in tmpl.all_items()}
        missing = [by_id[m].label for m in summ.get("missing", []) if m in by_id]
        out.append({
            "shift": tmpl.name,
            "assignee": assignee or "unassigned",
            "status": run["status"],
            "completion_pct": summ["completion_pct"],
            "done": summ["done"], "total": summ["total"],
            "pending_count": len(missing),
            "pending_items": missing,
        })
    return out


def completion_streak(db, building: str, template_id: str, upto_date: str, max_back: int = 90) -> int:
    """Consecutive days (ending upto_date) this template was actually DONE (submitted).
    Breaks the first day it wasn't submitted. The positive mirror of lapse_streak."""
    from datetime import datetime as _dt, timedelta as _td
    d0 = _dt.strptime(upto_date, "%Y-%m-%d")
    streak = 0
    for i in range(max_back):
        d = (d0 - _td(days=i)).strftime("%Y-%m-%d")
        runs = [r for r in db.checklist_runs_for(building, d) if r["template_id"] == template_id]
        if not runs or not any(r["status"] == "submitted" for r in runs):
            break
        streak += 1
    return streak


def recognition_message(db, building: str, run: Dict[str, Any], name: str, who: str):
    """A round was actually DONE — decide whether it's worth a positive note, and what to say.
    Routine good days stay SILENT (no spam). Speaks up only for the two moments that mean
    something: RECOVERY (broke a run of missed days) and MILESTONE good streaks (3/7/14/30).
    Returns (message, facts) or (None, ''). Grounded in real run history — no fabrication."""
    from datetime import datetime as _dt, timedelta as _td
    date, tid = run["shift_date"], run["template_id"]
    good = completion_streak(db, building, tid, date)
    person = who if who and who != "unassigned" else ""
    # lapse run immediately BEFORE today → was this a recovery?
    prev = (_dt.strptime(date, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")
    missed, _ = lapse_streak(db, building, tid, prev)
    if missed >= 2:
        thanks = f" Thanks {person}." if person else " Nice recovery."
        msg = (f"✅ {name} back on track — done today after {missed} missed "
               f"day{'s' if missed != 1 else ''} in a row.{thanks}")
        facts = f"shift={name}; date={date}; done_by={person or '—'}; recovered_after_missed_days={missed}"
        return msg, facts
    if good in (3, 7, 14, 30):
        msg = f"✅ {name} — {_ordinal(good)} day running, fully done. Consistent, reliable shift."
        facts = f"shift={name}; date={date}; done_by={person or '—'}; consecutive_done_days={good}"
        return msg, facts
    return None, ""


def lapse_stale_rounds(db, building: str, now=None, enqueue: bool = True) -> List[Dict[str, Any]]:
    """Give incomplete rounds a TERMINAL. A run lapses once its shift window has ENDED
    (shift-end-aware; overnight shifts end next morning). Templates without a clock window
    fall back to the prior-day rule. Manager gets a notice; a round never hangs open or
    silently disappears. Runs at 100% but unsubmitted still lapse, recorded with completion.

    enqueue=True (default) sends the deterministic notice inline — the always-works path. Pass
    enqueue=False to get each fired entry's `msg`+`facts` back WITHOUT sending, so an async
    caller can run them through the LLM phraser first, then enqueue."""
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
            streak, all_unassigned = lapse_streak(db, building, run["template_id"], run["shift_date"])
            msg = _lapse_message(name, run["shift_date"], pct, who, streak, all_unassigned)
            facts = (f"shift={name}; date={run['shift_date']}; completion={pct:.0f}%; "
                     f"assigned={who}; consecutive_missed_days={streak}; "
                     f"nobody_assigned={all_unassigned}")
            if enqueue:
                db.enqueue_notification(building, msg, to_number="", kind="round_lapsed")
            fired.append({"run_id": run["id"], "shift_date": run["shift_date"],
                          "completion_pct": pct, "streak": streak, "msg": msg, "facts": facts})
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


def period_summary_text(db, building: str, period: str = "week") -> str:
    """WhatsApp-ready weekly/monthly summary (rounds, issues, PPM, top techs)."""
    days = 30 if period == "month" else 7
    ev = building_evaluation(db, building, days=days)
    r, iss, p = ev["rounds"], ev["issues"], ev["ppm"]
    label = "Monthly" if period == "month" else "Weekly"
    text = (f"📊 *{label} summary* — last {days} days\n"
            f"Rounds: {r['submitted']}/{r['total']} submitted ({r['submit_rate_pct']}%), "
            f"{r['lapsed']} lapsed · avg {r['avg_completion_pct']}% complete\n"
            f"Issues: {iss['raised']} raised, {iss['resolved']} resolved, {iss['open']} open"
            + (f", {iss['sla_breached']} SLA-breached" if iss.get("sla_breached") else "") + "\n"
            f"PPM: {p['overdue']} overdue, {p['due_soon']} due soon")
    techs = ev.get("technicians") or []
    if techs:
        text += "\nTechs: " + ", ".join(f"{t['name']} {t['completion_pct']}%" for t in techs[:3])
    return text


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


def _reminder_deeplink(rid: int, building: str, assignee: str) -> str:
    """Tappable deep-link straight into the field round runner, carrying a pre-minted
    technician token (?t=) so the tap auto-authenticates — same primitive as the
    assignment DM. Empty when no public URL is configured (dev)."""
    import os
    pub = os.environ.get("ARVISX_PUBLIC_URL", "").rstrip("/")
    if not pub:
        return ""
    tok = ""
    try:
        from arvisx import auth as _auth
        if assignee:
            tok = _auth.make_token(assignee, "technician")
    except Exception:
        tok = ""
    url = f"{pub}/field/run/{rid}?building={building}"
    if tok:
        url += f"&t={tok}"
    return f"\nOpen: {url}"


def recurring_issues(db, building: str, days: int = 90, min_count: int = 2,
                     now: Optional["datetime"] = None) -> List[Dict[str, Any]]:
    """C2 building memory: which problems KEEP COMING BACK over the window. Groups issues by
    asset (or a number-normalized title when no asset), counts recurrences, tracks how many
    are still open + when last seen. Grounded — only what's in the issue log; the agent uses
    this to answer 'has this happened before / is this chronic'."""
    from datetime import datetime as _dt, timedelta as _td
    import re as _re
    now = now or _dt.now()
    cutoff = now - _td(days=days)
    groups: Dict[str, Dict[str, Any]] = {}
    for i in db.list_issues(building):
        ts = i.get("created_at") or ""
        try:
            if _dt.fromisoformat(ts[:19]) < cutoff:
                continue
        except Exception:
            continue
        title = i.get("title", "")
        base = _re.sub(r"\s+", " ", _re.sub(r"\d+(\.\d+)?", "#", title)).strip().lower()
        key = (i.get("asset") or "").strip() or base
        g = groups.setdefault(key, {"key": key, "asset": i.get("asset") or "", "count": 0,
                                    "open": 0, "last_seen": "", "titles": set()})
        g["count"] += 1
        if i.get("status") != "resolved":
            g["open"] += 1
        if ts > g["last_seen"]:
            g["last_seen"] = ts
        g["titles"].add(title)
    out = [{"key": g["key"], "asset": g["asset"], "count": g["count"], "open": g["open"],
            "last_seen": g["last_seen"][:10],
            "example": sorted(g["titles"])[0] if g["titles"] else g["key"]}
           for g in groups.values() if g["count"] >= min_count]
    out.sort(key=lambda x: (x["count"], x["open"]), reverse=True)
    return out


def propose_memory_candidates(db, building: str, now: Optional["datetime"] = None) -> List[Dict[str, Any]]:
    """Turn detected recurring patterns into LEARNED-LESSON candidates for manager approval
    (don't auto-trust). Dedup per pattern key so each is proposed once. Returns the NEWLY
    proposed candidates (for the WhatsApp notification)."""
    new: List[Dict[str, Any]] = []
    for r in recurring_issues(db, building, now=now):
        key = "recurring:" + (r.get("asset") or r.get("key") or r.get("example") or "")
        title = f"Recurring problem on {r.get('asset') or r.get('example')}"
        detail = (f"\"{r.get('example')}\" has recurred {r['count']}× in 90 days "
                  f"({r['open']} still open, last {r.get('last_seen')}). "
                  f"Approve to remember this as a chronic pattern.")
        cid = db.add_memory_candidate(building, "recurring_pattern", title, detail,
                                      source="auto", dedup_key=key)
        if cid:
            new.append({"id": cid, "title": title, "detail": detail})
    return new


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
            assignee = run.get("assignee") or ""
            if not assignee:
                continue                         # nobody to chase — don't nag an unassigned round
            prev = int(run.get("reminded_level") or 0)
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

            tech = db.get_technician(building, assignee) or {}
            phone = tech.get("phone", "") or ""
            link = _reminder_deeplink(run["id"], building, assignee)

            if do_escalate and prev < 2:
                # 1) last-call to the TECHNICIAN (with their deep-link) — if reachable.
                if phone:
                    db.enqueue_notification(
                        building, f"⏰ {tmpl.name} is closing soon — still {pct:.0f}% "
                                  f"({pending} item(s) left). Please finish now.{link}",
                        to_number=phone, kind="round_reminder")
                # 2) escalate to the MANAGER (ops broadcast).
                db.enqueue_notification(
                    building, f"⚠️ {tmpl.name} ({run['shift_date']}) only {pct:.0f}% done by {assignee} — "
                              f"{pending} item(s) pending, shift closing.", to_number="", kind="round_escalation")
                db.set_run_reminded(run["id"], 2)
                fired.append({"run_id": run["id"], "level": 2, "assignee": assignee, "phone": bool(phone)})
            elif do_nudge and prev < 1:
                # Nudge the technician directly, WITH the deep-link. No roster phone → can't
                # reach them; skip rather than misroute the tech's link to the manager.
                if phone:
                    db.enqueue_notification(
                        building, f"📋 {tmpl.name} is {pct:.0f}% done — {pending} item(s) still pending. "
                                  f"Please complete before shift close.{link}",
                        to_number=phone, kind="round_reminder")
                    db.set_run_reminded(run["id"], 1)
                    fired.append({"run_id": run["id"], "level": 1, "assignee": assignee, "phone": True})
                else:
                    fired.append({"run_id": run["id"], "level": 1, "assignee": assignee, "phone": False, "skipped": "no_phone"})
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
