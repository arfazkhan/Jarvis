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

from arvisx import checklist_intel as intel
from arvisx.checklist_agent import build_ctx, run_agent, verify_grounded
from arvisx.checklist_forms import get_template, run_summary


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
