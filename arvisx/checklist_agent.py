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
    return {"recurring": intel.recurring_issues(d, b)}


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


def build_ctx(db, building: str = "one-anthem", today: str = "") -> Dict[str, Any]:
    from datetime import datetime
    return {"db": db, "building": building, "today": today or datetime.now().strftime("%Y-%m-%d")}


_GROUNDING_RULES = (
    "\n\nRULES:\n"
    "- Use ONLY the tools to get facts. Never state a number, asset name, or status you "
    "did not get from a tool result.\n"
    "- If the tools don't have enough data, say so plainly — do not estimate or invent.\n"
    "- Be concise and operational. No preamble."
)


async def run_agent(llm, system: str, user: str, ctx: Dict[str, Any],
                    max_steps: int = 6) -> Dict[str, Any]:
    """ReAct loop: the model calls read-only tools until it answers. Returns
    {text, evidence, steps, truncated}. `evidence` = every tool output (for the guard)."""
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
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


def verify_grounded(text: str, evidence: Any) -> Dict[str, Any]:
    """Every multi-digit number in `text` must appear in the tool outputs. Single digits
    (ordinals/counts) are ignored. Returns {grounded, ungrounded:[...]}. A failure means
    the answer contains an invented figure → caller should use the deterministic fallback."""
    ev = json.dumps(evidence, default=str)
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
