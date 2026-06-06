"""
ArvisX reasoning layer — where ArvisX stops just DETECTING and starts THINKING.

The deterministic layers (health/drift/virtual/fusion/ghost) are the trust floor —
fast, auditable, no hallucination. This layer sits ON TOP and does what fixed rules
can't:

  • CORRELATE — when several systems flag at once, find a COMMON root cause
    ("generator tripped + water pressure dropped + pump room hot → one power event")
    instead of N separate alerts.
  • ASK — answer an operator's natural-language question over the live community state.

Same grounding discipline as commercial ARVIS: the LLM PROPOSES, the floor keeps it
honest — every linked asset must be a REAL asset id (hallucinated links dropped),
confidence is reported, nothing is 'confirmed', and it ABSTAINS gracefully when no LLM
is available (no creds / offline) rather than inventing a story.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

from arvisx.models import Asset, Risk

logger = logging.getLogger("arvisx.reasoning")


@dataclass
class Correlation:
    common_cause: Optional[str]
    linked_assets: List[str]
    independent: bool
    confidence: str               # Low | Medium | High
    rationale: str
    source: str                   # "llm" | "deterministic" (no-LLM fallback)


@dataclass
class Answer:
    answer: str
    cited: List[str] = field(default_factory=list)
    confidence: str = "Low"
    source: str = "llm"


def _llm_enabled(llm) -> bool:
    return llm is not None and os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True")


def _state_ledger(assets: List[Asset], risks: List[Risk]) -> tuple[str, set]:
    """Compact, grounded community snapshot for the LLM + the set of valid ids."""
    valid = {a.asset_id for a in assets} | {r.asset_id for r in risks}
    lines = ["ACTIVE RISKS:"]
    for r in risks:
        lines.append(f"  - {r.asset_id} ({r.service.value}/{r.severity.value}): {r.message}")
    lines.append("ASSET STATE:")
    for a in assets:
        sig = ", ".join(f"{k}={v}" for k, v in list((a.signals or {}).items())[:8])
        lines.append(f"  - {a.asset_id} ({a.asset_type.value}): {sig}")
    return "\n".join(lines), valid


# ── Cross-asset correlation (the headline 'thinking') ────────────────────
async def correlate(assets: List[Asset], risks: List[Risk], llm: Any = None) -> Correlation:
    if len(risks) < 2:
        return Correlation(None, [], True, "High",
                           "Fewer than two active risks — nothing to correlate.", "deterministic")
    if not _llm_enabled(llm):
        return Correlation(None, [r.asset_id for r in risks], True, "Low",
                           f"{len(risks)} risks active; cross-cause reasoning unavailable (no LLM) — "
                           "treat as independent until reviewed.", "deterministic")
    ledger, valid = _state_ledger(assets, risks)
    sys = (
        "You are a residential-infrastructure diagnostician. Several systems are flagged. "
        "Decide whether a SINGLE common underlying cause links some of them (e.g. an upstream "
        "power event, a water-supply interruption, a hot plant room) or whether they are "
        "independent problems. Rules: only LINK assets you can justify from the evidence; cite "
        "asset ids EXACTLY as given; do not invent ids; if there is no real common cause, say "
        "independent=true. Physical confirmation is required — do not claim certainty. "
        'Output JSON: {"common_cause":str|null,"linked_assets":[str],"independent":bool,'
        '"confidence":0..1,"rationale":str}'
    )
    try:
        from arvisx.llm_env import load_arvis_env
        load_arvis_env()
        resp = await llm.ask_json(messages=[{"role": "user", "content": ledger}],
                                  system_msgs=[{"role": "system", "content": sys}], channel="reasoning")
    except Exception as e:
        logger.warning(f"[ArvisX] correlate LLM failed: {e}")
        return Correlation(None, [r.asset_id for r in risks], True, "Low",
                           "Reasoning unavailable (LLM error) — treat as independent.", "deterministic")
    if not isinstance(resp, dict):
        resp = {}
    linked = [a for a in (resp.get("linked_assets") or []) if a in valid]   # evidence-bind
    cause = resp.get("common_cause")
    independent = bool(resp.get("independent", not linked))
    try:
        cf = float(resp.get("confidence", 0.4))
    except (TypeError, ValueError):
        cf = 0.4
    band = "High" if (cf >= 0.7 and len(linked) >= 2) else "Medium" if cf >= 0.5 else "Low"
    # A common cause with no valid linked assets is ungrounded → demote to independent.
    if cause and not linked:
        cause, independent, band = None, True, "Low"
    return Correlation(common_cause=(None if independent else cause), linked_assets=linked,
                       independent=independent, confidence=band,
                       rationale=str(resp.get("rationale", ""))[:300], source="llm")


# ── Natural-language Q&A over community state ────────────────────────────
async def ask(question: str, assets: List[Asset], risks: List[Risk], llm: Any = None) -> Answer:
    if not _llm_enabled(llm):
        return Answer("Natural-language reasoning is unavailable (no LLM configured). "
                      "The dashboard risks and advisories above are derived deterministically.",
                      [], "Low", "deterministic")
    ledger, valid = _state_ledger(assets, risks)
    sys = (
        "You answer an operator's question using ONLY the community state below. Ground every "
        "claim in the asset ids/signals given; cite the asset ids you used. If the data needed "
        "to answer isn't present, say so plainly — do not guess. Be concise. "
        'Output JSON: {"answer":str,"cited":[str],"confidence":0..1}'
    )
    usr = f"{ledger}\n\nQUESTION: {question}"
    try:
        from arvisx.llm_env import load_arvis_env
        load_arvis_env()
        resp = await llm.ask_json(messages=[{"role": "user", "content": usr}],
                                  system_msgs=[{"role": "system", "content": sys}], channel="reasoning")
    except Exception as e:
        logger.warning(f"[ArvisX] ask LLM failed: {e}")
        return Answer("Reasoning unavailable (LLM error).", [], "Low", "deterministic")
    if not isinstance(resp, dict):
        resp = {}
    cited = [a for a in (resp.get("cited") or []) if a in valid]            # evidence-bind
    try:
        cf = float(resp.get("confidence", 0.4))
    except (TypeError, ValueError):
        cf = 0.4
    band = "High" if cf >= 0.7 else "Medium" if cf >= 0.5 else "Low"
    return Answer(str(resp.get("answer", "")).strip() or "No answer.", cited, band, "llm")
