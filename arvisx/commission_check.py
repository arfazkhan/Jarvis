"""
ArvisX — commissioning self-awareness: detect what doesn't fit, let the agent explain why.

Commissioning is where a building's config meets reality. Things that don't line up — a
device publishing telemetry that was never commissioned, an asset with no signals mapped,
an asset whose type was never set, a sensor sending garbage — can't always be resolved by
a fixed rule, because the RIGHT action is case-by-case (add it? ignore it? fix the
mapping? replace the sensor?). So: a DETERMINISTIC detector finds the anomalies, and the
AGENT narrates each one — why it matters and what to do — grounded on the detected facts.
Read-only: it explains and recommends; the technician decides.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from arvisx.ingest.topics import parse


@dataclass
class CommissioningAnomaly:
    kind: str          # unmapped_topic | untyped_asset | unsignaled_asset | service_without_assets | bad_signal
    subject: str       # the topic / asset_id / service it concerns
    detail: str
    severity: str      # info | warning


def detect_commissioning_anomalies(config, observed_topics: Optional[List[str]] = None,
                                   store=None) -> List[CommissioningAnomaly]:
    """Deterministically find config/reality mismatches for a building."""
    out: List[CommissioningAnomaly] = []
    assets = getattr(config, "assets", []) or []
    asset_ids = {a.get("id") for a in assets}
    mapped = {m.get("asset_id") for m in (getattr(config, "signal_maps", []) or [])}

    for a in assets:
        if not a.get("type"):
            out.append(CommissioningAnomaly("untyped_asset", a.get("id", "?"),
                "asset has no equipment type — type-specific rules can't apply", "warning"))
        if a.get("id") not in mapped:
            out.append(CommissioningAnomaly("unsignaled_asset", a.get("id", "?"),
                "no signals mapped — this asset is invisible to monitoring", "warning"))

    svc_with_assets = {a.get("service") for a in assets if a.get("service")}
    for s in (getattr(config, "services", []) or []):
        if svc_with_assets and s not in svc_with_assets:
            out.append(CommissioningAnomaly("service_without_assets", s,
                f"service '{s}' is declared but has no assets assigned", "warning"))

    if observed_topics:
        for t in observed_topics:
            r = parse(t, "0")
            if r:
                aid = r[0][0]
                if aid not in asset_ids:
                    out.append(CommissioningAnomaly("unmapped_topic", t,
                        f"device '{aid}' is publishing telemetry but isn't commissioned", "info"))

    for q in (getattr(store, "quarantined", []) or []):
        out.append(CommissioningAnomaly("bad_signal", f"{q.get('asset_id')}.{q.get('signal')}",
            f"sensor reading rejected: {q.get('reason', 'out of range')}", "warning"))

    return out


_FALLBACK = {
    "unmapped_topic": "A device is sending data but isn't in the asset list. Add it as an asset "
                      "(and map its signals) or its telemetry will be ignored.",
    "untyped_asset": "Set the equipment type so type-specific rules and templates apply.",
    "unsignaled_asset": "Map at least one signal (e.g. power, runtime, level) so this asset is monitored.",
    "service_without_assets": "Assign assets to this service, or remove it from the building's services.",
    "bad_signal": "Inspect the sensor/wiring — the value is implausible and is being quarantined.",
}


async def narrate_anomalies(anomalies: List[CommissioningAnomaly], config, llm=None) -> List[Dict[str, Any]]:
    """Explain each anomaly (why it matters + what to do). Agent narration when an LLM is
    available; otherwise a deterministic explanation. Grounded on the detected facts."""
    from arvisx.agent import _llm_on
    use_llm = _llm_on(llm) and hasattr(llm, "ask_json")
    out: List[Dict[str, Any]] = []
    for an in anomalies:
        explanation = _FALLBACK.get(an.kind, an.detail)
        action = ""
        if use_llm:
            sys = ("You help a non-engineer commission a residential building's monitoring. "
                   "Given ONE detected commissioning anomaly, explain in 1-2 plain sentences why it "
                   "matters and the single best next action. Ground it in the facts given; do not "
                   'invent assets. Output JSON: {"explanation": str, "recommended_action": str}')
            usr = (f"Building '{getattr(config, 'name', '')}'. Anomaly: kind={an.kind}, "
                   f"subject={an.subject}, detail={an.detail}, severity={an.severity}.")
            try:
                resp = await llm.ask_json(messages=[{"role": "user", "content": usr}],
                                          system_msgs=[{"role": "system", "content": sys}], channel="reasoning")
                if isinstance(resp, dict):
                    explanation = str(resp.get("explanation", "") or explanation)[:300]
                    action = str(resp.get("recommended_action", ""))[:200]
            except Exception:
                pass
        out.append({**asdict(an), "explanation": explanation,
                    "recommended_action": action or _FALLBACK.get(an.kind, "")})
    return out
