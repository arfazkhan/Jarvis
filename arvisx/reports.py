"""
Weekly / monthly operations report — grounded data rollup + PDF render.

Data comes from checklist_intel.building_evaluation (rounds/issues/PPM/per-tech) plus a
per-actor accountability pass over the period's entries (WHO recorded what). The PDF is a
plain, dependable summary a manager can file or forward. Pure-Python (fpdf2) — no system deps.
Nothing is fabricated: every figure is a real count over the window.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from arvisx import checklist_intel as intel


def _days(period: str) -> int:
    return 30 if str(period or "").lower().startswith(("month", "mo")) else 7


def _resolver(db, issue_id: int) -> str:
    """Who resolved an issue (last resolving actor in its history) — for accountability."""
    iss = db.get_issue(issue_id) or {}
    hist = iss.get("history") or []
    if isinstance(hist, str):
        try:
            hist = json.loads(hist)
        except Exception:
            hist = []
    for h in reversed(hist if isinstance(hist, list) else []):
        act = str(h.get("action", "")).lower()
        if "resolv" in act or str(h.get("status", "")).lower() == "resolved":
            return h.get("by", "") or ""
    return ""


def report_data(db, building: str, period: str = "weekly", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Grounded weekly/monthly rollup: rounds, per-technician accountability (rounds + items
    recorded), issues raised/resolved (with who), still-open items, and PPM compliance."""
    now = now or datetime.now()
    days = _days(period)
    ev = intel.building_evaluation(db, building, now=now, days=days)
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    runs = [r for d in dates for r in db.checklist_runs_for(building, d)]

    # Accountability: count entries recorded per actor across the window.
    by_actor: Dict[str, int] = {}
    for r in runs:
        for _item_id, e in db.checklist_entries(r["id"]).items():
            a = (e.get("actor") or "").strip()
            if a:
                by_actor[a] = by_actor.get(a, 0) + 1

    tech_names = {t["name"] for t in ev["technicians"]}
    techs = [{**t, "items_recorded": by_actor.get(t["name"], 0)} for t in ev["technicians"]]
    # actors who recorded entries but aren't on the technician roster (e.g. a manager who filled in)
    techs += [{"name": a, "assigned": 0, "submitted": 0, "completion_pct": 0.0, "items_recorded": n}
              for a, n in sorted(by_actor.items(), key=lambda x: -x[1]) if a not in tech_names]

    issues = db.list_issues(building)
    period_issues = [i for i in issues if (i.get("created_at") or "")[:10] in dates]
    resolved = [{"id": i["id"], "title": i.get("title", ""), "asset": i.get("asset", ""),
                 "by": _resolver(db, i["id"]), "at": (i.get("updated_at") or "")[:16]}
                for i in period_issues if i["status"] == "resolved"]
    open_now = [{"id": i["id"], "title": i.get("title", ""), "asset": i.get("asset", ""),
                 "status": i["status"], "raised_by": i.get("raised_by", "")}
                for i in issues if i["status"] != "resolved"]

    # Who SKIPPED — assigned rounds that weren't completed (missed = assigned - submitted).
    skips = [{"name": t["name"], "missed": t["assigned"] - t["submitted"]}
             for t in ev["technicians"] if t["assigned"] - t["submitted"] > 0]
    skips.sort(key=lambda x: -x["missed"])

    # Checklist completion trend (per day) + first-half vs second-half direction.
    trend = intel.building_trend(db, building, days=days, now=now)
    half = max(1, len(trend) // 2)
    a1 = [x["completion_pct"] for x in trend[:half]]
    a2 = [x["completion_pct"] for x in trend[half:]]
    m1 = round(sum(a1) / len(a1), 1) if a1 else 0.0
    m2 = round(sum(a2) / len(a2), 1) if a2 else 0.0
    trend_dir = "improving" if m2 > m1 + 2 else ("declining" if m2 < m1 - 2 else "steady")

    # Equipment hotspots — assets with the most issues this period + recurring memory.
    from collections import Counter
    hot = Counter((i.get("asset") or "").strip() for i in period_issues)
    asset_hotspots = [{"asset": a, "count": n} for a, n in hot.most_common(5) if a]
    try:
        recurring = (intel.recurring_issues(db, building) or [])[:3]
    except Exception:
        recurring = []

    return {
        "label": "Monthly" if days == 30 else "Weekly", "days": days,
        "start": dates[-1], "end": dates[0],
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "ev": ev, "technicians": techs, "skips": skips,
        "resolved_issues": resolved, "open_issues": open_now,
        "trend": trend, "trend_first_half": m1, "trend_second_half": m2, "trend_dir": trend_dir,
        "asset_hotspots": asset_hotspots, "recurring": recurring,
    }


# ── LLM executive summary (grounded) ──────────────────────────────────────
_REPORT_SYS = (
    "You are a building-operations analyst writing the EXECUTIVE SUMMARY of a periodic report for "
    "the building manager. Use ONLY the figures provided below — never invent a number, name, "
    "asset, or trend. In 3 to 5 plain sentences cover: overall checklist completion and its "
    "direction (improving / declining / steady); WHO did the work and WHO missed or skipped "
    "assigned rounds (name them, with counts); issues raised vs resolved (and who resolved key "
    "ones); and any equipment or PPM concern (name the asset). Be specific and factual, not "
    'flowery. Output JSON only: {"summary": "..."}.'
)


def _facts_block(data: Dict[str, Any], building_name: str) -> str:
    ev = data["ev"]; r = ev["rounds"]; iss = ev["issues"]; ppm = ev["ppm"]
    L = [f"Building: {building_name}", f"Period: {data['label']} ({data['start']} to {data['end']})",
         f"Rounds: total {r['total']}, submitted {r['submitted']} ({r['submit_rate_pct']}%), "
         f"lapsed {r['lapsed']}, open {r['open']}, avg completion {r['avg_completion_pct']}%",
         f"Completion trend: first half {data['trend_first_half']}% -> second half "
         f"{data['trend_second_half']}% ({data['trend_dir']})",
         f"Issues: raised {iss['raised']}, resolved {iss['resolved']}, open {iss['open']}",
         f"PPM: overdue {ppm['overdue']}, due soon {ppm['due_soon']}"]
    acts = [t for t in data["technicians"] if t["assigned"] or t["items_recorded"]]
    if acts:
        L.append("Technician activity: " + "; ".join(
            f"{t['name']} assigned {t['assigned']} completed {t['submitted']} "
            f"({t['completion_pct']}%), {t['items_recorded']} items" for t in acts))
    if data["skips"]:
        L.append("Missed/skipped assigned rounds: " + ", ".join(
            f"{s['name']} {s['missed']}" for s in data["skips"]))
    if data["resolved_issues"]:
        L.append("Resolved: " + "; ".join(
            f"#{i['id']} {i['title']}" + (f" by {i['by']}" if i["by"] else "") for i in data["resolved_issues"][:8]))
    if data["asset_hotspots"]:
        L.append("Equipment with most issues: " + ", ".join(
            f"{h['asset']} ({h['count']})" for h in data["asset_hotspots"]))
    return "\n".join(L)


def _deterministic_narrative(data: Dict[str, Any], building_name: str) -> str:
    ev = data["ev"]; r = ev["rounds"]; iss = ev["issues"]
    parts = [f"Over this {data['label'].lower()} period, {r['submitted']} of {r['total']} rounds "
             f"were completed ({r['submit_rate_pct']}%), averaging {r['avg_completion_pct']}% — "
             f"completion is {data['trend_dir']}."]
    if data["skips"]:
        parts.append("Missed assigned rounds: " + ", ".join(f"{s['name']} ({s['missed']})" for s in data["skips"]) + ".")
    parts.append(f"{iss['raised']} issue(s) raised, {iss['resolved']} resolved, {iss['open']} still open.")
    if data["asset_hotspots"]:
        parts.append("Most issues on: " + ", ".join(f"{h['asset']}" for h in data["asset_hotspots"][:3]) + ".")
    if ev["ppm"]["overdue"]:
        parts.append(f"{ev['ppm']['overdue']} PPM task(s) overdue.")
    return " ".join(parts)


async def narrative(llm, data: Dict[str, Any], building_name: str) -> str:
    """LLM exec summary, grounded + number-guarded. Falls back to a deterministic summary on
    no-llm / fabricated number / error — the report always has a summary, never a wrong one."""
    facts = _facts_block(data, building_name)
    if not llm:
        return _deterministic_narrative(data, building_name)
    try:
        from arvisx.checklist_skills import _crisp, _looks_like_reasoning, _numbers_grounded
        out = await llm.ask_json(messages=[{"role": "user", "content": facts}],
                                 system_msgs=[{"role": "system", "content": _REPORT_SYS}], channel="chat")
        s = _crisp(str(out.get("summary", ""))).strip() if isinstance(out, dict) else ""
        if s and not _looks_like_reasoning(s) and len(s) <= 1200 and _numbers_grounded(s, facts):
            return s
    except Exception:
        pass
    return _deterministic_narrative(data, building_name)


# ── PDF render (fpdf2) ────────────────────────────────────────────────────
def _safe(s: Any) -> str:
    """Latin-1 only (core fpdf font) — drop anything that can't encode (emoji/dashes)."""
    return str(s).replace("–", "-").replace("—", "-").replace("’", "'").encode("latin-1", "ignore").decode("latin-1")


def render_pdf(data: Dict[str, Any], building_name: str, summary: str = "") -> bytes:
    from fpdf import FPDF
    ev = data["ev"]
    r, iss, ppm = ev["rounds"], ev["issues"], ev["ppm"]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def h1(t):
        pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 9, _safe(t), ln=1)
    def h2(t):
        pdf.ln(2); pdf.set_font("Helvetica", "B", 12); pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 7, _safe(t), ln=1); pdf.set_text_color(0, 0, 0)
    def kv(label, val):
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(70, 6, _safe(label)); pdf.cell(0, 6, _safe(val), ln=1)

    h1(f"AllGud - {data['label']} Operations Report")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, _safe(f"{building_name}   |   {data['start']} to {data['end']}   |   generated {data['generated_at']}"), ln=1)
    pdf.set_text_color(0, 0, 0)

    if summary:
        h2("Executive summary")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, _safe(summary))

    h2("Checklist rounds")
    kv("Total rounds", r["total"])
    kv("Submitted (completed)", f"{r['submitted']}  ({r['submit_rate_pct']}%)")
    kv("Lapsed (missed)", r["lapsed"])
    kv("Still open", r["open"])
    kv("Average completion", f"{r['avg_completion_pct']}%")
    kv("Completion trend", f"{data['trend_first_half']}% -> {data['trend_second_half']}%  ({data['trend_dir']})")

    h2("Accountability - who did what")
    pdf.set_font("Helvetica", "B", 9); pdf.set_fill_color(235, 235, 235)
    pdf.cell(70, 6, "Technician", border=1, fill=True)
    pdf.cell(30, 6, "Assigned", border=1, fill=True, align="C")
    pdf.cell(30, 6, "Completed", border=1, fill=True, align="C")
    pdf.cell(30, 6, "Rate", border=1, fill=True, align="C")
    pdf.cell(30, 6, "Items done", border=1, fill=True, align="C", ln=1)
    pdf.set_font("Helvetica", "", 9)
    rows = [t for t in data["technicians"] if t["assigned"] or t["items_recorded"]]
    if not rows:
        pdf.cell(0, 6, _safe("No recorded activity in this period."), ln=1)
    for t in rows:
        pdf.cell(70, 6, _safe(t["name"]), border=1)
        pdf.cell(30, 6, str(t["assigned"]), border=1, align="C")
        pdf.cell(30, 6, str(t["submitted"]), border=1, align="C")
        pdf.cell(30, 6, f"{t['completion_pct']}%", border=1, align="C")
        pdf.cell(30, 6, str(t["items_recorded"]), border=1, align="C", ln=1)

    h2("Issues")
    kv("Raised this period", iss["raised"])
    kv("Resolved", iss["resolved"] if iss.get("action_rate_pct") is None else f"{iss['resolved']}  ({iss['action_rate_pct']}%)")
    kv("Still open", iss["open"])
    if iss.get("avg_resolution_hrs") is not None:
        kv("Avg resolution time", f"{iss['avg_resolution_hrs']} hrs")
    if iss.get("sla_breached") or iss.get("sla_at_risk"):
        kv("SLA breached / at risk", f"{iss['sla_breached']} / {iss['sla_at_risk']}")

    if data["resolved_issues"]:
        h2("Resolved this period")
        pdf.set_font("Helvetica", "", 9)
        for i in data["resolved_issues"][:25]:
            tag = f" [{i['asset']}]" if i["asset"] else ""
            who = f" - by {i['by']}" if i["by"] else ""
            pdf.multi_cell(0, 5, _safe(f"#{i['id']} {i['title']}{tag}{who}"))
    if data["open_issues"]:
        h2("Still open")
        pdf.set_font("Helvetica", "", 9)
        for i in data["open_issues"][:25]:
            tag = f" [{i['asset']}]" if i["asset"] else ""
            pdf.multi_cell(0, 5, _safe(f"#{i['id']} {i['title']}{tag} ({i['status']})"))

    if data.get("asset_hotspots") or data.get("recurring"):
        h2("Equipment focus")
        pdf.set_font("Helvetica", "", 9)
        if data.get("asset_hotspots"):
            pdf.multi_cell(0, 5, _safe("Most issues this period: " + ", ".join(
                f"{h['asset']} ({h['count']})" for h in data["asset_hotspots"])))
        for rec in (data.get("recurring") or []):
            a = rec.get("asset") or rec.get("title") or "issue"
            n = rec.get("count") or rec.get("times") or ""
            pdf.multi_cell(0, 5, _safe(f"Recurring: {a}" + (f" ({n}x)" if n else "")))

    h2("Preventive maintenance")
    kv("Scheduled assets", ppm["scheduled"])
    kv("Overdue", ppm["overdue"])
    kv("Due soon", ppm["due_soon"])

    pdf.ln(6); pdf.set_font("Helvetica", "I", 8); pdf.set_text_color(130, 130, 130)
    pdf.multi_cell(0, 4, _safe("Generated by AllGud. All figures are real counts over the period - "
                               "no estimates or projections."))
    out = pdf.output(dest="S")
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")
