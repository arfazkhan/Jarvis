"""
ArvisX — escalation policy: deterministic floor first, agent only when needed.

The product idea: ArvisX is deterministic wherever rules suffice (the trustworthy,
auditable, offline floor). An AGENT is invoked ONLY when the situation is something
rules can't cleanly resolve — case-by-case problems where a fixed rule would be wrong:

  • a low-confidence warning (the rules floor itself is unsure),
  • several concurrent risks on one asset (possible common cause → needs reasoning),
  • a sensor-quality problem on the asset (the value rules would trust is suspect),
  • a learned-drift deviation with no matching known pattern (novel, needs investigation).

`should_escalate` is itself DETERMINISTIC — a cheap rule that decides whether to spend an
LLM call. `handle_incident` runs the rules advisory always, then escalates to the agent
only when the policy says so (and an LLM is available). Read-only throughout.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from arvisx.models import Asset, Risk, Severity

_ACTIONABLE = {Severity.CRITICAL, Severity.WARNING}


def should_escalate(risk: Risk, asset: Optional[Asset], all_risks: List[Risk],
                    store=None, skillbook=None) -> Tuple[bool, List[str]]:
    """Deterministic decision: does this incident need an agent investigation?"""
    reasons: List[str] = []

    if risk.severity in _ACTIONABLE and (risk.confidence or "Low") == "Low":
        reasons.append("low-confidence actionable risk — rules floor is unsure")

    same = [r for r in all_risks if r.asset_id == risk.asset_id]
    if len(same) >= 2:
        reasons.append(f"{len(same)} concurrent risks on this asset — possible common cause")

    if store is not None:
        q = [x for x in (getattr(store, "quarantined", []) or []) if x.get("asset_id") == risk.asset_id]
        if q:
            reasons.append("sensor-quality issue on this asset — value may be untrustworthy")

    msg = (risk.message + " " + (risk.detail or "")).lower()
    if ("drift" in msg or "creep" in msg or "above its own normal" in msg):
        known = None
        if skillbook is not None and asset is not None:
            try:
                known = skillbook.recall(asset, risk)
            except Exception:
                known = None
        if not known:
            reasons.append("learned-baseline deviation with no known pattern — novel case")

    return (len(reasons) > 0, reasons)


async def handle_incident(asset: Asset, risk: Risk, assets: List[Asset], risks: List[Risk],
                          llm=None, db=None, baselines=None, skillbook=None,
                          store=None, zones=None, wo_store=None,
                          max_steps: int = 5) -> Dict[str, Any]:
    """Deterministic advisory ALWAYS; escalate to the agent only when the policy fires
    and an LLM is available. Returns a verdict dict describing the route taken."""
    from arvisx.advisory import investigate_asset

    det = await investigate_asset(asset, [risk], llm=None)   # rules floor — no LLM
    escalate, reasons = should_escalate(risk, asset, risks, store=store, skillbook=skillbook)

    out: Dict[str, Any] = {
        "asset_id": asset.asset_id, "risk": risk.message,
        "route": "deterministic", "escalated": False, "escalation_reasons": reasons,
        "deterministic": {"root_cause": det.root_cause, "recommended_action": det.recommended_action},
        "investigation": None,
    }

    from arvisx.agent import _llm_on
    if escalate and _llm_on(llm):
        from arvisx.agent import investigate
        inv = await investigate(asset, risk, assets, risks, llm=llm, db=db, baselines=baselines,
                                skillbook=skillbook, max_steps=max_steps,
                                store=store, zones=zones, wo_store=wo_store)
        out["route"] = "agent"
        out["escalated"] = True
        out["investigation"] = {
            "root_cause": inv.root_cause, "recommended_action": inv.recommended_action,
            "confidence": inv.confidence_band, "source": inv.source,
            "steps": [s.get("tool") for s in inv.steps], "evidence": inv.evidence,
            "watch": inv.watch}
    return out
