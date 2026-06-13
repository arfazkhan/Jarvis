"""
ArvisX — SLA + escalation + vendor accountability (deterministic).

Issues stop disappearing into "the dots". Every issue carries a priority → an SLA clock →
a timed escalation ladder (reminder → supervisor → facility manager → committee). And when
a vendor owns the fix, their response/resolution times are measured so committees can see
which AMC is slowest / causes the most escalations.

Pure functions over issue dicts (with history) + a per-building SLA config. The escalation
SWEEP (api/bot) calls sla_status() and enqueues to the existing notification queue; one
notification per level (no spam). Nothing here auto-closes an issue — breach escalates only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

# Per-priority default SLA in HOURS: (response, resolution). Per-building configurable.
DEFAULT_SLA: Dict[str, tuple] = {
    "critical": (1, 4),
    "high": (4, 24),
    "medium": (24, 72),
    "low": (48, 168),
}
# Existing issue.severity (critical|issue) → priority when none set.
PRIORITY_FROM_SEVERITY = {"critical": "critical", "issue": "medium"}
PRIORITIES = ["critical", "high", "medium", "low"]

# Escalation ladder: level → who to notify.
LEVEL_TARGET = {1: "reminder", 2: "supervisor", 3: "facility_manager", 4: "committee"}


def priority_of(issue: Dict[str, Any]) -> str:
    p = (issue.get("priority") or "").lower()
    if p in DEFAULT_SLA:
        return p
    return PRIORITY_FROM_SEVERITY.get(issue.get("severity", ""), "medium")


def sla_for(priority: str, cfg: Optional[Dict[str, tuple]] = None) -> tuple:
    cfg = cfg or {}
    return cfg.get(priority) or DEFAULT_SLA.get(priority, DEFAULT_SLA["medium"])


def _age_hours(created_at: str, now: datetime) -> Optional[float]:
    try:
        return (now - datetime.fromisoformat(str(created_at)[:19])).total_seconds() / 3600.0
    except Exception:
        return None


def escalation_level(age_h: float, response_h: float, resolution_h: float) -> int:
    if age_h >= 3 * resolution_h:
        return 4      # committee
    if age_h >= 2 * resolution_h:
        return 3      # facility manager
    if age_h >= resolution_h:
        return 2      # supervisor
    if age_h >= response_h:
        return 1      # reminder (assignee/owner)
    return 0


def sla_status(issue: Dict[str, Any], cfg: Optional[Dict[str, tuple]] = None,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now()
    pr = priority_of(issue)
    resp, res = sla_for(pr, cfg)
    age = _age_hours(issue.get("created_at", ""), now)
    resolved = issue.get("status") == "resolved"
    lvl = 0 if (resolved or age is None) else escalation_level(age, resp, res)
    return {"priority": pr, "age_hours": (round(age, 1) if age is not None else None),
            "response_hours": resp, "resolution_hours": res,
            "breached_resolution": bool(age is not None and not resolved and age > res),
            "escalation_level": lvl, "target": LEVEL_TARGET.get(lvl)}


# ── vendor accountability ─────────────────────────────────────────────────
def _first_ts(history: List[Dict[str, Any]], needles: List[str]) -> Optional[str]:
    for h in history or []:
        a = (h.get("action") or "").lower()
        if any(n in a for n in needles):
            return h.get("ts")
    return None


def _hours_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    if not a or not b:
        return None
    try:
        return (datetime.fromisoformat(str(b)[:19]) - datetime.fromisoformat(str(a)[:19])).total_seconds() / 3600.0
    except Exception:
        return None


def vendor_performance(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-vendor: jobs, avg response (opened→visited/assigned), avg resolution
    (opened→resolved), escalations. Slowest resolution first — the committee's view."""
    by: Dict[str, Dict[str, Any]] = {}
    for i in (issues or []):
        v = i.get("vendor")
        if not v:
            continue
        rec = by.setdefault(v, {"vendor": v, "jobs": 0, "resolved": 0,
                                "_resp": [], "_resn": [], "escalations": 0})
        rec["jobs"] += 1
        created = i.get("created_at")
        hist = i.get("history", [])
        resp = _hours_between(created, _first_ts(hist, ["visited", "assigned"]))
        if resp is not None:
            rec["_resp"].append(resp)
        if i.get("status") == "resolved":
            rec["resolved"] += 1
            resn = _hours_between(created, _first_ts(hist, ["resolved"]) or i.get("updated_at"))
            if resn is not None:
                rec["_resn"].append(resn)
        if int(i.get("escalated_level") or 0) > 0:
            rec["escalations"] += 1
    out = []
    for rec in by.values():
        resp, resn = rec.pop("_resp"), rec.pop("_resn")
        rec["avg_response_hours"] = round(sum(resp) / len(resp), 1) if resp else None
        rec["avg_resolution_hours"] = round(sum(resn) / len(resn), 1) if resn else None
        out.append(rec)
    out.sort(key=lambda r: (r["avg_resolution_hours"] is None, r["avg_resolution_hours"] or 0), reverse=True)
    return out


# ── escalation sweep (DB-bound; enqueues to the notification queue) ───────
def _escalation_text(issue: Dict[str, Any], st: Dict[str, Any]) -> str:
    who = {"reminder": "Reminder", "supervisor": "Escalated to SUPERVISOR",
           "facility_manager": "Escalated to FACILITY MANAGER",
           "committee": "Escalated to COMMITTEE"}.get(st["target"], "Escalation")
    vend = f" · vendor: {issue['vendor']}" if issue.get("vendor") else ""
    age = st["age_hours"]
    return (f"⏰ {who}: {issue['title']} [{st['priority']}]\n"
            f"Open {age:.0f}h (resolution SLA {st['resolution_hours']}h){vend}. "
            "Open the app to act.")


def run_escalations(db, building: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Find issues whose SLA escalation level has risen and notify the right party ONCE per
    level. reminder → the assigned tech (DM if a roster phone exists), else ops; supervisor/
    FM/committee → ops broadcast. Records the new level so it never re-fires. Never closes."""
    cfg = db.get_sla_config(building)
    fired: List[Dict[str, Any]] = []
    for iss in db.list_issues(building):
        if iss.get("status") == "resolved":
            continue
        st = sla_status(iss, cfg, now)
        lvl, prev = st["escalation_level"], int(iss.get("escalated_level") or 0)
        if lvl <= prev:
            continue
        to_number = ""
        if st["target"] == "reminder" and iss.get("assignee"):
            tech = db.get_technician(building, iss["assignee"])
            to_number = (tech or {}).get("phone", "") or ""
        db.enqueue_notification(building, _escalation_text(iss, st),
                                to_number=to_number, kind="escalation")
        db.set_issue_fields(iss["id"], escalated_level=lvl)
        db.append_issue_history(iss["id"], f"escalated: {st['target']}", by="system")
        fired.append({"issue_id": iss["id"], "level": lvl, "target": st["target"]})
    return fired
