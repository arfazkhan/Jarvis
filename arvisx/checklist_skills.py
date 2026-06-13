"""
ArvisX Agentic Phase-C — agent skills (skill-prompt + trigger on the shared core).

C-1 Shift Handover: at shift close, hand the next shift a grounded summary — open issues,
pending tasks, the day's anomalies, a priority. "Every shift starts informed."

Discipline: facts are GATHERED deterministically (the grounding source AND the always-works
fallback). The LLM only rewrites them into a tighter narrative, and only if the
fabricated-number guard passes against what it actually read. No LLM / guard fails / any
error → the deterministic render ships. The handover is never wrong, only sometimes prettier.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from collections import Counter

from arvisx import checklist_intel as intel
from arvisx.analyzers import reading_anomaly, trend_alert
from arvisx.checklist_agent import build_ctx, run_agent, verify_grounded
from arvisx.checklist_forms import get_template, run_summary, items_for_asset
from arvisx.models import confidence_band


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── gather (deterministic, grounded) ──────────────────────────────────────
def gather_handover(db, building: str, today: str) -> Dict[str, Any]:
    open_issues = [i for i in db.list_issues(building) if i["status"] != "resolved"]
    critical = [i for i in open_issues if i.get("severity") == "critical"]
    pending: List[Dict[str, Any]] = []
    for run in db.checklist_runs_for(building, today):
        tmpl = get_template(run["template_id"], building)
        if tmpl is None:
            continue
        summ = run_summary(tmpl, db.checklist_entries(run["id"]))
        by_id = {it.item_id: it for it in tmpl.all_items()}
        for m in summ["missing"]:
            if m in by_id:
                pending.append({"item": by_id[m].label, "shift": tmpl.name,
                                "assignee": run.get("assignee") or ""})
    anomalies, _by = intel.reading_findings(db, building)
    comp = intel.compliance(db, building, today)
    if critical or comp.get("compliance_risk") == "high":
        priority = "High"
    elif open_issues or anomalies or comp.get("compliance_risk") == "medium":
        priority = "Medium"
    else:
        priority = "Low"
    return {"open_issues": open_issues, "critical": critical, "pending": pending,
            "anomalies": anomalies, "compliance": comp, "priority": priority}


def render_handover(data: Dict[str, Any]) -> str:
    """Deterministic, grounded handover text — the source of truth + the fallback."""
    oi, pend, anom = data["open_issues"], data["pending"], data["anomalies"]
    comp = data["compliance"]
    overdue = comp.get("overdue_ppm") or []
    # All-clear is about OPEN WORK (issues / pending / anomalies / overdue PPM). Staleness
    # alone is a coverage signal (see compliance), not something to hand to the next shift.
    if not oi and not pend and not anom and not overdue:
        return "*Shift Handover*\n\n✅ All clear — no open issues, nothing pending, no PPM overdue."
    L = ["*Shift Handover*", ""]
    if oi:
        L.append("*Open Issues:*")
        for n, i in enumerate(oi[:8], 1):
            who = f" (→ {i['assignee']})" if i.get("assignee") else ""
            L.append(f"{n}. {i['title']} [{i.get('status', 'open')}]{who}")
        L.append("")
    if pend:
        L.append("*Pending Tasks:*")
        for p in pend[:8]:
            L.append(f"• {p['item']} — {p['shift']}")
        L.append("")
    if anom:
        L.append("*Watch (readings off-normal):*")
        for a in anom[:5]:
            L.append(f"• {a['label']}: {a['latest']}{a.get('unit', '')} ({a['direction']} normal)")
        L.append("")
    overdue = comp.get("overdue_ppm") or []
    if overdue:
        L.append("*PPM overdue:* " + ", ".join(o["asset"] for o in overdue))
        L.append("")
    L.append(f"*Priority:* {data['priority']}")
    return "\n".join(L)


_HANDOVER_SYSTEM = (
    "You are ArvisX's shift-handover assistant. Using ONLY the tools, write a SHORT handover "
    "for the incoming shift with three sections: *Open Issues* (numbered, with owner if known), "
    "*Pending Tasks*, and *Priority* (High/Medium/Low). Call open_issues, health_overview, "
    "reading_anomalies and compliance to get the facts. Operational tone, no preamble, no "
    "invented numbers."
)


async def run_handover(llm, db, building: str, today: str) -> Dict[str, Any]:
    """LLM narrative if available + grounded; otherwise (or on any failure) the
    deterministic render. Facts always come from gather_handover."""
    data = gather_handover(db, building, today)
    deterministic = render_handover(data)
    if llm is None:
        return {"text": deterministic, "source": "deterministic", "priority": data["priority"]}
    try:
        ctx = build_ctx(db, building, today)
        out = await run_agent(llm, _HANDOVER_SYSTEM,
                              "Write the shift handover for the incoming shift.", ctx)
        text = (out.get("text") or "").strip()
        if text and verify_grounded(text, out.get("evidence"))["grounded"]:
            return {"text": text, "source": "agent", "priority": data["priority"]}
    except Exception:
        pass
    return {"text": deterministic, "source": "deterministic-fallback", "priority": data["priority"]}


# ── C-2 Root-Cause Investigator ───────────────────────────────────────────
def _infer_cause(asset: str, reading_signals: List[Dict[str, Any]], ppm, recurring) -> tuple:
    """Skillbook-lite grounded inference. Returns (cause, action) or (None, None) — never
    invents; an unknown pattern abstains to 'inspect on site'."""
    a = asset.upper()
    batt_decline = any("battery" in s.get("item", "").lower() and s.get("trend") == "declining"
                       for s in reading_signals)
    below = any(s.get("anomaly") == "below" for s in reading_signals)
    overdue = bool(ppm and ppm.get("status") == "overdue")
    if a.startswith("DG") and batt_decline:
        return ("Battery deterioration — voltage trending down"
                + (", PPM overdue" if overdue else "") + " (ageing / low utilization likely).",
                "Battery load test; equalize charge; schedule periodic generator exercise runs.")
    if below and any(k in a for k in ("TANK", "WTP", "PUMP")):
        return ("A key reading is trending below normal — possible leak or supply shortfall.",
                "Inspect the supply line and check for leakage at the asset.")
    if recurring:
        return ("Recurring fault — repeated resets are masking a root cause.",
                "Escalate for component replacement / OEM inspection.")
    return (None, None)


def gather_rca(db, building: str, asset: str, today: str) -> Dict[str, Any]:
    hist = intel.asset_history(db, building, asset, today, limit=80)
    open_iss = [i for i in hist["issues"] if i["status"] != "resolved"]
    titles = Counter(i["title"].split(":")[0].strip() for i in hist["issues"])
    recurring = [t for t, c in titles.items() if c >= 2]
    reading_signals: List[Dict[str, Any]] = []
    for _t, it in items_for_asset(building, asset):
        if it.kind != "reading":
            continue
        vals = [_num(e["value"]) for e in db.asset_entries(building, [it.item_id], limit=60)]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 4:
            tr = trend_alert(list(reversed(vals)))
            if tr.get("flagged"):
                reading_signals.append({"item": it.label, "trend": tr["direction"],
                                        "from": tr["from"], "to": tr["to"]})
        if len(vals) >= 6:
            an = reading_anomaly(vals[1:], vals[0])
            if an.get("flagged"):
                reading_signals.append({"item": it.label, "anomaly": an["direction"],
                                        "latest": an["latest"]})
    observations: List[str] = []
    if open_iss:
        observations.append(f"{len(open_iss)} open issue(s): " + "; ".join(i["title"] for i in open_iss[:3]))
    for s in reading_signals:
        if s.get("trend"):
            observations.append(f"{s['item']} {s['trend']} ({s['from']}→{s['to']})")
        if s.get("anomaly"):
            observations.append(f"{s['item']} {s['anomaly']} normal (latest {s['latest']})")
    if hist["ppm"] and hist["ppm"].get("status") == "overdue":
        observations.append("PPM overdue")
    if recurring:
        observations.append("recurring: " + ", ".join(recurring))
    cause, action = _infer_cause(asset, reading_signals, hist["ppm"], recurring)
    return {"asset": asset, "observations": observations, "reading_signals": reading_signals,
            "recurring": recurring, "ppm": hist["ppm"], "probable_cause": cause,
            "recommended_action": action, "confidence": confidence_band(len(observations))}


def render_rca(data: Dict[str, Any]) -> str:
    L = [f"*Root Cause — {data['asset']}*", ""]
    if data["observations"]:
        L.append("Observations:")
        L += [f"• {o}" for o in data["observations"]]
        L.append("")
    if data["probable_cause"]:
        L.append(f"Probable cause: {data['probable_cause']}")
        L.append(f"Recommended: {data['recommended_action']}")
        L.append(f"Confidence: {data['confidence']}")
    else:
        L.append("No clear pattern in the data yet — inspect on site.")
        L.append("Confidence: Low")
    return "\n".join(L)


_RCA_SYSTEM = (
    "You are ArvisX's root-cause investigator. For the asset named by the user, call "
    "asset_history, open_issues and reading_anomalies, then give: Observations (the facts), "
    "Probable cause, Recommended action, and Confidence (Low/Medium/High by how many "
    "independent observations corroborate). Use ONLY tool data. If the evidence is thin, say "
    "'inspect on site' — never invent a cause or a confidence."
)


async def run_rca(llm, db, building: str, asset: str, today: str) -> Dict[str, Any]:
    data = gather_rca(db, building, asset, today)
    deterministic = render_rca(data)
    if llm is None:
        return {"asset": asset, "text": deterministic, "source": "deterministic",
                "confidence": data["confidence"], "probable_cause": data["probable_cause"]}
    try:
        ctx = build_ctx(db, building, today)
        out = await run_agent(llm, _RCA_SYSTEM, f"Investigate the root cause for {asset}.", ctx)
        text = (out.get("text") or "").strip()
        if text and verify_grounded(text, out.get("evidence"))["grounded"]:
            return {"asset": asset, "text": text, "source": "agent",
                    "confidence": data["confidence"], "probable_cause": data["probable_cause"]}
    except Exception:
        pass
    return {"asset": asset, "text": deterministic, "source": "deterministic-fallback",
            "confidence": data["confidence"], "probable_cause": data["probable_cause"]}
