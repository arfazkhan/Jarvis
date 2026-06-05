"""
ArvisX Phase-1a grounded advisory engine.

Turns a flagged asset's signals + risks into a ranked root-cause advisory with the
SAME discipline as commercial ARVIS:
  - evidence-bound: hypotheses cite only the asset's REAL signals/risks,
  - never asserts from absence,
  - never 'confirmed' without physical inspection (read-only advisory),
  - honest when the signals are thin (low band, 'confirm on inspection').

Two tiers (mirrors the discovery design):
  1. RULES FLOOR (deterministic, offline) — known residential failure patterns →
     a probable cause + recommended action. Always available, air-gapped.
  2. LLM differential (optional, ARVIS_X_LLM=1) — UnifiedLLM ranks competing
     hypotheses with cited evidence; a deterministic gate drops any hypothesis that
     cites evidence the asset doesn't actually have (anti-hallucination).

Single-asset RCA → calls the LLM directly, NOT the 13-agent swarm (overkill here).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from arvisx.models import Advisory, Asset, AssetType, Hypothesis, Risk

logger = logging.getLogger("arvisx.advisory")


# ── Evidence ledger from the asset's real footprint ──────────────────────
def _evidence_ledger(asset: Asset, risks: List[Risk]) -> Dict[str, str]:
    led: Dict[str, str] = {}
    for k, v in (asset.signals or {}).items():
        led[f"sig:{k}"] = f"{k} = {v}"
    led["meta:runtime_hours"] = f"runtime_hours = {asset.runtime_hours}"
    if asset.runtime_threshold_hours:
        led["meta:runtime_threshold"] = f"runtime_threshold_hours = {asset.runtime_threshold_hours}"
    if asset.next_maintenance_due:
        led["meta:next_maintenance_due"] = f"next_maintenance_due = {asset.next_maintenance_due:%Y-%m-%d}"
    for i, r in enumerate(risks):
        led[f"risk:{i}"] = f"{r.message} — {r.detail}"
    return led


# ── Tier 1: deterministic rules floor (residential failure patterns) ─────
# asset_type → (cause, action). Keyed by the dominant risk signature.
def _rules_floor(asset: Asset, risks: List[Risk]) -> Advisory:
    at = asset.asset_type
    s = asset.signals or {}
    cause = "Operational deviation detected — cause not yet isolated"
    action = "Inspect the asset and review recent operating logs."
    headline = f"{asset.name}: attention required"

    rmsgs = " ".join(r.message.lower() for r in risks)

    if at == AssetType.BOOSTER_PUMP and "runtime above threshold" in rmsgs:
        cause = ("Cumulative mechanical wear at high duty — likely worn impeller/seals, "
                 "fouled suction strainer, or rising downstream demand forcing longer runtimes")
        action = "Inspect impeller + suction strainer, log motor current vs nameplate, check downstream demand/leaks."
        headline = f"{asset.name}: runtime above threshold — wear/load investigation"
    elif at == AssetType.POOL_FILTRATION_PUMP and "below normal" in rmsgs:
        cause = ("Filtration under-running — pump tripping, a timer/schedule fault, or a clogged "
                 "filter/closed valve cutting flow")
        action = "Check pump trip status + filter differential pressure + timer schedule and valve positions."
        headline = f"{asset.name}: filtration below normal — flow/availability"
    elif at == AssetType.STP_BLOWER and ("inactivity" in rmsgs or "below" in rmsgs):
        cause = "Blower not aerating — motor trip, contactor failure, or VFD/drive fault stopping the blower"
        action = "Inspect blower starter/contactor + VFD fault log; verify dissolved-oxygen recovery after restart."
        headline = f"{asset.name}: blower inactivity — STP process at risk"
    elif at == AssetType.DIESEL_GENERATOR and "fuel low" in rmsgs:
        cause = "Fuel reserve depleted — backup readiness compromised"
        action = "Refuel immediately; confirm no leak; verify fuel-level sender accuracy."
        headline = f"{asset.name}: fuel low — backup at risk"
    elif at == AssetType.DIESEL_GENERATOR and "service due" in rmsgs:
        cause = "Scheduled preventive-maintenance interval reached (time/runtime based)"
        action = "Schedule service: oil + filters, coolant, and an on-load test run."
        headline = f"{asset.name}: service due — preventive maintenance"
    elif at == AssetType.GENERATOR_BATTERY and "battery weak" in rmsgs:
        cause = "Starter battery aging or undercharged — risk of start failure on demand"
        action = "Load-test the battery; check alternator/float charger output; replace if capacity is low."
        headline = f"{asset.name}: weak battery — start reliability"
    elif at in (AssetType.UNDERGROUND_TANK, AssetType.OVERHEAD_TANK) and "low" in rmsgs:
        cause = "Level low — inflow below outflow: transfer pump underperforming or upstream supply interruption"
        action = "Check transfer pump operation + inlet supply/valve; confirm no overdraw or leak."
        headline = f"{asset.name}: level low — supply continuity"
    elif at == AssetType.FIRE_PUMP and "test overdue" in rmsgs:
        cause = "Mandatory test lapsed — pump readiness is UNVERIFIED (not necessarily failed)"
        action = "Run the scheduled churn/flow test per code and confirm with the certified fire vendor."
        headline = f"{asset.name}: test overdue — readiness unverified"
    elif at == AssetType.FIRE_PANEL and s.get("active_faults"):
        cause = "Fire panel reporting active fault(s) — device or loop issue (supplementary view)"
        action = "Verify on the certified fire panel; dispatch the fire-systems vendor for the active fault(s)."
        headline = f"{asset.name}: panel faults — verify on certified panel"

    return Advisory(
        asset_id=asset.asset_id, asset_name=asset.name, headline=headline,
        root_cause=cause, confidence_band="Low", confirmed=False,
        recommended_action=action,
        plain_summary=f"Most probable cause: {cause}. {action} (Unconfirmed — verify on site.)",
        source="rules",
    )


# ── Tier 2: optional LLM ranked differential (evidence-bound) ────────────
async def _llm_differential(asset: Asset, risks: List[Risk], ledger: Dict[str, str], llm: Any) -> List[Hypothesis]:
    valid = set(ledger)
    _sys = (
        "You are a residential-infrastructure maintenance diagnostician. Given ONE asset, "
        "its signal/risk EVIDENCE LEDGER, enumerate 2-4 COMPETING root-cause hypotheses a "
        "senior facilities engineer would hold. Rules: (1) each hypothesis cites "
        "supporting_evidence_ids using EXACT ids from the ledger — never invent ids. "
        "(2) NEVER assert a cause from the ABSENCE of a signal. (3) give a discriminating_test "
        "(the single field check that confirms/refutes it) and a recommended_action. (4) order "
        "most-probable first; probability in 0..1 summing ~1. (5) physical inspection is required — "
        "do not claim certainty. "
        'Output JSON: {"hypotheses":[{"label":str,"probability":float,"rationale":str,'
        '"supporting_evidence_ids":[str],"discriminating_test":str,"recommended_action":str}]}'
    )
    _led = "\n".join(f"- {k}: {v}" for k, v in ledger.items())
    _usr = (f"Asset: {asset.name} (type={asset.asset_type.value})\n"
            f"EVIDENCE LEDGER:\n{_led}\n\nList the competing root-cause hypotheses.")
    try:
        resp = await llm.ask_json(
            messages=[{"role": "user", "content": _usr}],
            system_msgs=[{"role": "system", "content": _sys}],
            channel="reasoning",
        )
    except Exception as e:
        logger.warning(f"[ArvisX] LLM differential failed for {asset.asset_id}: {e}")
        return []

    raw = (resp.get("hypotheses") if isinstance(resp, dict) else None) or []
    out: List[Hypothesis] = []
    for h in raw:
        if not isinstance(h, dict) or not h.get("label"):
            continue
        ev = [e for e in (h.get("supporting_evidence_ids") or []) if e in valid]  # evidence-bind
        # Anti-hallucination: a hypothesis with no valid cited evidence is dropped.
        if not ev:
            logger.debug(f"[ArvisX] dropped ungrounded hypothesis '{h.get('label')}' for {asset.asset_id}")
            continue
        try:
            p = float(h.get("probability", 0.0))
        except (TypeError, ValueError):
            p = 0.0
        out.append(Hypothesis(
            label=str(h.get("label"))[:120], probability=max(0.0, min(p, 1.0)),
            rationale=str(h.get("rationale", ""))[:240],
            evidence=[ledger[e][:80] for e in ev[:4]],
            discriminating_test=str(h.get("discriminating_test", ""))[:200],
            recommended_action=str(h.get("recommended_action", ""))[:200],
        ))
    out.sort(key=lambda x: x.probability, reverse=True)
    return out


# ── Public entry ─────────────────────────────────────────────────────────
async def investigate_asset(asset: Asset, risks: List[Risk], llm: Any = None) -> Advisory:
    """Grounded advisory for a flagged asset. Rules floor always; LLM differential
    layered in when llm is provided AND ARVIS_X_LLM=1."""
    adv = _rules_floor(asset, risks)
    ledger = _evidence_ledger(asset, risks)

    if llm is not None and os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True"):
        hyps = await _llm_differential(asset, risks, ledger, llm)
        if hyps:
            lead = hyps[0]
            adv.hypotheses = hyps
            adv.root_cause = lead.label
            adv.recommended_action = lead.recommended_action or adv.recommended_action
            # Band from the leading probability + dominance, but capped: a read-only
            # advisory on a single asset can't be 'High' without physical inspection.
            dom = lead.probability - (hyps[1].probability if len(hyps) > 1 else 0.0)
            adv.confidence_band = "Medium" if (lead.probability >= 0.5 and dom >= 0.15) else "Low"
            adv.confirmed = False
            adv.source = "llm+rules"
            adv.headline = f"{asset.name}: {lead.label}"
            adv.plain_summary = (
                f"Most probable cause: {lead.label} ({adv.confidence_band.lower()} confidence). "
                f"Do this: {adv.recommended_action} "
                f"Check to confirm: {lead.discriminating_test or 'physical inspection'}. "
                f"(Unconfirmed — verify on site.)"
            )
    return adv
