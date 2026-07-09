"""
ArvisX Agentic Phase-B — the agent core (one agent, many skills).

A shared, READ-ONLY tool set over the checklist intelligence + a ReAct loop + a
fabricated-number GROUNDING GUARD. Every Phase-C agent (handover, RCA, work-order, Q&A)
is this loop with a different skill-prompt and trigger — not a separate agent.

Grounding is law: tools return only real computed data (checklist_intel), and the guard
rejects any answer containing a number that didn't come from a tool output — the
canned-text twin of the commercial GroundingGuard. On rejection the caller falls back to
deterministic text rather than ship an invented figure.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from arvisx import checklist_intel as intel
from arvisx.tools import ToolRegistry

CHECKLIST_REGISTRY = ToolRegistry()
_tool = CHECKLIST_REGISTRY.register

_AID = {"type": "object", "properties": {"asset": {"type": "string"}}, "required": ["asset"]}
_AID_OPT = {"type": "object", "properties": {"asset": {"type": "string"}}}
_NONE = {"type": "object", "properties": {}}


def _db(ctx):
    return ctx["db"], ctx.get("building", "one-anthem"), ctx.get("today", "")


@_tool("list_assets", "List the building's assets (the asset registry).", _NONE)
def _list_assets(ctx, **a):
    from arvisx.checklist_forms import assets_in
    _d, b, _t = _db(ctx)
    return {"assets": assets_in(b)}


@_tool("asset_health", "Health score (0-100) + reasons for ONE asset.", _AID)
def _asset_health(ctx, **a):
    d, b, t = _db(ctx)
    return intel.asset_health_one(d, b, a["asset"], t)


@_tool("health_overview", "Health score for every asset, riskiest first.", _NONE)
def _health_overview(ctx, **a):
    d, b, t = _db(ctx)
    return {"assets": intel.asset_health_all(d, b, t)}


@_tool("asset_history", "Recent checklist entries + issues + PPM status for ONE asset.", _AID)
def _asset_history(ctx, **a):
    d, b, t = _db(ctx)
    h = intel.asset_history(d, b, a["asset"], t, limit=40)
    return h


@_tool("open_issues", "Open (unresolved) issues, optionally filtered to one asset.", _AID_OPT)
def _open_issues(ctx, **a):
    d, b, _t = _db(ctx)
    iss = [i for i in d.list_issues(b, asset=a.get("asset", "")) if i["status"] != "resolved"]
    return {"open_issues": iss}


@_tool("reading_anomalies", "Readings that deviate from their own learned band (L1).", _NONE)
def _reading_anoms(ctx, **a):
    d, b, _t = _db(ctx)
    findings, _by = intel.reading_findings(d, b)
    return {"anomalies": findings}


@_tool("compliance", "Overdue PPM + stale (un-checked) assets (L8).", _NONE)
def _compliance(ctx, **a):
    d, b, t = _db(ctx)
    return intel.compliance(d, b, t)


@_tool("recurring_issues", "Building memory: problems that have RECURRED over the last ~90 days "
                           "— which assets/issues keep coming back, how many times, how many still "
                           "open. Use for 'has this happened before', 'recurring', 'chronic', 'history'.", _NONE)
def _recurring_issues(ctx, **a):
    d, b, _t = _db(ctx)
    # Manager-APPROVED learned lessons are trusted memory; surface them alongside the
    # raw recurring counts so the bot recalls confirmed knowledge first.
    lessons = [{"lesson": L["title"], "detail": L.get("detail", "")}
               for L in d.list_memory_candidates(b, "approved")]
    return {"recurring": intel.recurring_issues(d, b), "confirmed_lessons": lessons}


@_tool("asset_manual", "Manual-derived knowledge for ONE asset: specs, PPM intervals, and "
                       "troubleshooting steps distilled from its uploaded manual (C1). Use this "
                       "for 'what does the manual say', specs, service intervals, or how-to-fix.", _AID)
def _asset_manual(ctx, **a):
    d, b, _t = _db(ctx)
    k = d.get_asset_knowledge_by_name(b, a["asset"])
    if not k:
        return {"asset": a["asset"], "manual": "no manual knowledge on file for this asset"}
    return {"asset": a["asset"], "manual_name": k.get("manual_name", ""),
            "specs": k.get("specs", []), "ppm": k.get("ppm", []),
            "troubleshooting": k.get("troubleshooting", [])}


_DATE_OPT = {"type": "object", "properties": {
    "date": {"type": "string", "description": "YYYY-MM-DD; omit for today"}}}


@_tool("shift_rounds", "Who worked which shift and how it went, for a date (default TODAY). "
                       "Per shift: name, timing, who it's assigned to, who actually did it, status "
                       "(open/submitted/lapsed), completion %, and open-issue count. Use this for "
                       "'did anyone work the morning shift', 'what's pending', 'who's on shift II', "
                       "'is the round done', 'what happened today/yesterday'.", _DATE_OPT)
def _shift_rounds(ctx, **a):
    d, b, t = _db(ctx)
    date = (a.get("date") or "").strip() or t
    return {"date": date, "shifts": intel.shift_activity(d, b, date)}


@_tool("team_roster", "Active technicians on this building's team (the people who can be "
                      "assigned shifts/issues). Use for 'who's on the team', 'who can do this', "
                      "'list technicians'.", _NONE)
def _team_roster(ctx, **a):
    d, b, _t = _db(ctx)
    techs = [{"name": x.get("name", ""), "phone": x.get("phone", "")}
             for x in d.list_technicians(b, active_only=True)]
    return {"technicians": techs, "count": len(techs)}


_PENDING_ARGS = {"type": "object", "properties": {
    "date": {"type": "string", "description": "YYYY-MM-DD; omit for today"},
    "technician": {"type": "string", "description": "scope to one technician's assigned rounds"}}}


@_tool("pending_tasks", "What's still NOT DONE on the rounds (today by default). Each shift with "
                        "its assignee, completion %, and the list of undone item names. For a "
                        "MANAGER: omit technician to see everyone — who's behind and by how much. "
                        "For a TECHNICIAN asking about their OWN work, it is auto-scoped to them. "
                        "Use for 'what's pending', 'what's left', 'my pending items', 'who hasn't "
                        "finished', 'how much has X done'.", _PENDING_ARGS)
def _pending_tasks(ctx, **a):
    d, b, t = _db(ctx)
    date = (a.get("date") or "").strip() or t
    asker = ctx.get("asker") or {}
    # A technician may only see THEIR OWN pending work — force the scope to them, ignore any
    # technician they name. A manager/owner sees whoever they ask about (or everyone).
    if asker.get("kind") == "technician":
        who = asker.get("name", "")
    else:
        who = (a.get("technician") or "").strip()
    return {"date": date, "asked_as": asker.get("kind", "viewer"),
            "pending": intel.pending_tasks(d, b, date, technician=who)}


def build_ctx(db, building: str = "one-anthem", today: str = "",
              asker: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from datetime import datetime
    return {"db": db, "building": building, "today": today or datetime.now().strftime("%Y-%m-%d"),
            "asker": asker or {}}


_GROUNDING_RULES = (
    "\n\nRULES:\n"
    "- For any FACT (a number, asset name, status, who did what), use ONLY the tools — never "
    "state one you didn't get from a tool result. If the tools don't have it, say so plainly; "
    "never estimate or invent.\n"
    "- But TALK like a warm, real colleague, not a form. Natural and brief, first-person, a "
    "little personable. Greetings, thanks, and small talk get a friendly human reply with no "
    "tools. Use the person's name when it feels natural. Don't dump bullet lists unless asked.\n"
    "- You remember the recent conversation (shown as earlier messages) — use it for follow-ups; "
    "resolve 'it', 'that', 'him', 'the second one' from context."
)


async def run_agent(llm, system: str, user: str, ctx: Dict[str, Any],
                    max_steps: int = 6, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """ReAct loop: the model calls read-only tools until it answers. Returns
    {text, evidence, steps, truncated}. `evidence` = every tool output (for the guard).
    `history` = prior {role, content} turns so the model has conversational continuity
    (follow-ups, 'it'/'that'/'him' resolve from context)."""
    messages: List[Dict[str, Any]] = []
    for h in (history or []):
        r = h.get("role", "user")
        messages.append({"role": r if r in ("user", "assistant") else "user",
                         "content": str(h.get("content", ""))[:500]})
    messages.append({"role": "user", "content": user})
    system_msgs = [{"role": "system", "content": system + _GROUNDING_RULES}]
    schemas = CHECKLIST_REGISTRY.schemas()
    evidence: List[Any] = []
    last_content = ""
    for step in range(max_steps):
        resp = await llm.ask_tools(messages, schemas, system_msgs=system_msgs)
        messages.append(resp["assistant_message"])
        last_content = resp.get("content", "") or last_content
        calls = resp.get("tool_calls") or []
        if not calls:
            return {"text": resp.get("content", ""), "evidence": evidence,
                    "steps": step + 1, "truncated": False}
        for call in calls:
            result = CHECKLIST_REGISTRY.call(call["name"], ctx, call.get("args") or {})
            evidence.append(result)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, default=str)})
    return {"text": last_content, "evidence": evidence, "steps": max_steps, "truncated": True}


# ── fabricated-number guard ───────────────────────────────────────────────
_NUMRE = re.compile(r"\d[\d,]*\.?\d*")


def verify_grounded(text: str, evidence: Any, extra: str = "") -> Dict[str, Any]:
    """Every multi-digit number in `text` must appear in the tool outputs (or `extra` — e.g. the
    recent conversation, where figures were already grounded when first stated, so a follow-up may
    reuse them). Single digits (ordinals/counts) are ignored. Returns {grounded, ungrounded:[...]}.
    A failure means the answer contains an invented figure → caller uses the deterministic fallback."""
    ev = json.dumps(evidence, default=str) + " " + str(extra or "")
    ungrounded = []
    for tok in _NUMRE.findall(text or ""):
        clean = tok.replace(",", "")
        digits = clean.replace(".", "")
        if len(digits) < 2:                     # skip lone digits (ordinals, small counts)
            continue
        cands = {clean, clean.rstrip("0").rstrip("."), digits}
        try:
            f = float(clean)
            cands.add(str(int(f)) if f == int(f) else str(f))
        except ValueError:
            pass
        if not any(c and c in ev for c in cands):
            ungrounded.append(tok)
    return {"grounded": not ungrounded, "ungrounded": ungrounded}
