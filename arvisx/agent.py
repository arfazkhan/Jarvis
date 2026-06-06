"""
ArvisX Phase-12 — agentic investigation + proactive monitor.

This is what makes ArvisX genuinely AGENTIC (on investigation, not action — it stays
read-only). When a risk fires, instead of one LLM call, an agent runs a multi-step
ReAct loop: it decides which TOOL to call (get history, get baseline, check
dependency impact, recall a known pattern…), reads the real result, decides the next
step, and only concludes once it has gathered enough evidence.

Grounded by construction: every tool returns REAL data from the deterministic floor /
DB, so the agent can't reason on hallucinated evidence; it cites what it gathered; and
it is never 'confirmed' without physical inspection. No LLM → it degrades to the
deterministic rules-floor advisory (still useful, just not multi-step).

The proactive MONITOR decides what to investigate and HOW DEEP by risk tier
(critical → deep, warning → shallow, maintenance → rules-only) and caps the fan-out so
cost is bounded — autonomous perception → prioritization → investigation.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from arvisx.models import Asset, Risk, Severity

logger = logging.getLogger("arvisx.agent")


# ── Tools (each returns REAL deterministic data) ─────────────────────────
def _t_get_asset_state(ctx, asset_id: str = "", **_):
    a = ctx["by_id"].get(asset_id)
    if not a:
        return {"error": f"unknown asset {asset_id}"}
    return {"asset_id": asset_id, "type": a.asset_type.value, "signals": dict(a.signals or {})}


def _t_get_fault_history(ctx, asset_id: str = "", **_):
    db = ctx.get("db")
    return {"asset_id": asset_id, "history": (db.history(asset_id, 5) if db else [])}


def _t_get_baseline(ctx, asset_id: str = "", signal: str = "", **_):
    bl = ctx.get("baselines")
    if not bl:
        return {"baseline": None, "note": "no learned baseline available"}
    base = bl.baseline(asset_id, signal)
    z = bl.drift_z(asset_id, signal)
    if base is None:
        return {"baseline": None, "note": "insufficient history"}
    med, mad, n = base
    return {"asset_id": asset_id, "signal": signal, "median": round(med, 2),
            "mad": round(mad, 3), "samples": n, "drift_sigma": (round(z, 2) if z is not None else None)}


def _t_check_dependency_impact(ctx, asset_id: str = "", **_):
    from arvisx.topology import impact_analysis
    a = ctx["by_id"].get(asset_id)
    rel = [r for r in ctx["risks"] if r.asset_id == asset_id]
    if not a or not rel:
        return {"impact": None}
    imp = impact_analysis(ctx["assets"], rel)
    return {"impacts": [{"service": c.service.value, "impact": c.impact, "redundancy": c.redundancy,
                         "readiness_delta": c.readiness_delta, "note": c.note} for c in imp]}


def _t_recall_known_pattern(ctx, asset_id: str = "", **_):
    sb = ctx.get("skillbook")
    a = ctx["by_id"].get(asset_id)
    rel = [r for r in ctx["risks"] if r.asset_id == asset_id]
    if not sb or not a or not rel:
        return {"known_pattern": None}
    return {"known_pattern": sb.recall(a, rel[0])}


def _t_get_active_risks(ctx, **_):
    return {"risks": [{"asset_id": r.asset_id, "service": r.service.value,
                       "severity": r.severity.value, "message": r.message} for r in ctx["risks"]]}


_TOOLS = {
    "get_asset_state": _t_get_asset_state,
    "get_fault_history": _t_get_fault_history,
    "get_baseline": _t_get_baseline,
    "check_dependency_impact": _t_check_dependency_impact,
    "recall_known_pattern": _t_recall_known_pattern,
    "get_active_risks": _t_get_active_risks,
}
_TOOL_DOC = (
    "get_asset_state(asset_id) · get_fault_history(asset_id) · get_baseline(asset_id,signal) · "
    "check_dependency_impact(asset_id) · recall_known_pattern(asset_id) · get_active_risks()"
)


@dataclass
class Investigation:
    asset_id: str
    trigger: str
    root_cause: str
    recommended_action: str
    confidence_band: str
    confirmed: bool
    steps: List[Dict[str, Any]] = field(default_factory=list)   # the agent's tool-use trace
    evidence: List[str] = field(default_factory=list)
    source: str = "agent"


def _llm_on(llm) -> bool:
    return llm is not None and os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True")


def _rules_fallback(asset: Asset, risk: Risk) -> Investigation:
    from arvisx.advisory import _rules_floor
    adv = _rules_floor(asset, [risk])
    return Investigation(asset.asset_id, risk.message, adv.root_cause, adv.recommended_action,
                         "Low", False, steps=[], evidence=[risk.detail or risk.message], source="rules")


async def investigate(asset: Asset, risk: Risk, assets: List[Asset], risks: List[Risk],
                      llm=None, db=None, baselines=None, skillbook=None, max_steps: int = 5) -> Investigation:
    """Agentic multi-step investigation of one fired risk."""
    if not _llm_on(llm):
        return _rules_fallback(asset, risk)
    ctx = {"by_id": {a.asset_id: a for a in assets}, "assets": assets, "risks": risks,
           "db": db, "baselines": baselines, "skillbook": skillbook}
    sys = (
        "You are an autonomous residential-infrastructure investigator. A risk has fired. "
        "GATHER EVIDENCE with tools before concluding — check history, baselines, dependency "
        "impact, and known patterns as relevant. Tools: " + _TOOL_DOC + ". "
        "Each turn output ONE json object, either:\n"
        '  {"thought": str, "tool": "<name>", "args": {...}}   to gather evidence, or\n'
        '  {"thought": str, "final": {"root_cause": str, "recommended_action": str,'
        '"discriminating_test": str, "confidence": 0..1, "evidence": [str]}}\n'
        "Cite only evidence you actually retrieved. Physical confirmation is required — never claim certainty."
    )
    convo = [{"role": "user", "content": f"RISK: {risk.message} — {risk.detail}\nAsset: {asset.asset_id} "
              f"({asset.asset_type.value}). Investigate."}]
    steps: List[Dict[str, Any]] = []
    from arvisx.llm_env import load_arvis_env
    load_arvis_env()
    for _ in range(max_steps):
        try:
            resp = await llm.ask_json(messages=convo, system_msgs=[{"role": "system", "content": sys}],
                                      channel="reasoning")
        except Exception as e:
            logger.warning(f"[Agent] step failed: {e}")
            break
        if not isinstance(resp, dict):
            break
        if "final" in resp and isinstance(resp["final"], dict):
            f = resp["final"]
            band = "Medium" if float(f.get("confidence", 0.4) or 0.4) >= 0.5 else "Low"
            return Investigation(
                asset.asset_id, risk.message, str(f.get("root_cause", ""))[:160],
                str(f.get("recommended_action", ""))[:200], band, False, steps=steps,
                evidence=[str(x)[:120] for x in (f.get("evidence") or [])], source="agent")
        tool = resp.get("tool")
        args = resp.get("args") or {}
        if tool not in _TOOLS:
            convo.append({"role": "user", "content": f"OBSERVATION: unknown tool '{tool}'. Pick a valid tool or finalize."})
            continue
        result = _TOOLS[tool](ctx, **args)
        steps.append({"thought": str(resp.get("thought", ""))[:160], "tool": tool, "args": args,
                      "result": result})
        convo.append({"role": "assistant", "content": json.dumps({"tool": tool, "args": args})})
        convo.append({"role": "user", "content": "OBSERVATION: " + json.dumps(result, default=str)[:700]})
    # Budget exhausted / error → ground out on the rules floor, keep the trace.
    fb = _rules_fallback(asset, risk)
    fb.steps = steps
    fb.source = "agent(incomplete)→rules" if steps else "rules"
    return fb


# ── Proactive monitor: decide what to investigate + how deep ─────────────
_TIER_DEPTH = {Severity.CRITICAL: 6, Severity.WARNING: 3, Severity.MAINTENANCE: 0, Severity.INFO: 0}


async def monitor(assets: List[Asset], risks: List[Risk], llm=None, db=None, baselines=None,
                  skillbook=None, max_investigations: int = 3) -> List[Investigation]:
    """Autonomously prioritize the active risks and investigate the top ones to a depth
    set by their tier. Fan-out capped so cost stays bounded."""
    by_id = {a.asset_id: a for a in assets}
    # Priority: severity first, then dependency criticality (single-point essentials).
    from arvisx.topology import impact_analysis
    impact = {c.asset_id: c.service_impact for c in impact_analysis(assets, risks)}
    _sev = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.MAINTENANCE: 2, Severity.INFO: 3}
    ranked = sorted(risks, key=lambda r: (_sev.get(r.severity, 9), -impact.get(r.asset_id, 0.0)))

    out: List[Investigation] = []
    for r in ranked:
        if len(out) >= max_investigations:
            break
        a = by_id.get(r.asset_id)
        if a is None:
            continue
        depth = _TIER_DEPTH.get(r.severity, 0)
        if depth == 0 or not _llm_on(llm):
            out.append(_rules_fallback(a, r))           # maintenance / no-LLM → rules advisory
        else:
            out.append(await investigate(a, r, assets, risks, llm=llm, db=db, baselines=baselines,
                                         skillbook=skillbook, max_steps=depth))
    return out
