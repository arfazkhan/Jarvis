"""Context-aware reflector: after a memory search comes back empty, retry or accept?

An empty memory search means one of two things:
  - there is nothing to find (new building, or only other equipment's history) —
    retrying wastes a turn and invites the model to stretch an unrelated pattern;
  - relevant experience exists but this search missed it (a filter, wording, a
    near-miss score) — accepting loses institutional knowledge.

The tool tells us which, as `retrieval` diagnostics (BuildingSkillbook.explain_empty).
Most cases are settled by facts alone (`gate`). Only the genuinely ambiguous case —
memories exist, the nearest ones scored under threshold — needs judgement:
a calibrated decision model (Kev, opt-in) or the score-margin rule.

At most one reflection per tool per agent, and only while budget remains.

Config (env):
  ARVIS_REFLECTOR_JUDGE           rule (default) | kev
  ARVIS_REFLECTOR_MARGIN          rule: retry if best_score >= threshold - margin (default 0.1)
  ARVIS_REFLECTOR_KEV_THRESHOLD   kev: retry if p(yes) >= this (default 0.5)
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.decision.reflector")

KEV_INSTRUCTIONS = (
    "An agent diagnosing a building fault searched the building's memory of past "
    "incidents and found no match. The closest stored patterns and their similarity "
    "scores are given. Answer yes only if at least one of them plausibly describes the "
    "same kind of equipment AND the same kind of problem as the query, so that a reworded "
    "search would find relevant past experience. Answer no if they are about a different "
    "problem or different kind of equipment."
)


@dataclass
class ReflectionDecision:
    retry: bool
    reason: str                      # empty_reason, or the gate that decided
    source: str                      # "gate" | "rule" | "kev"
    note: str                        # text appended to the tool result for the agent
    p_retry: Optional[float] = None  # Kev probability, when Kev decided

    def to_dict(self) -> Dict[str, Any]:
        return {"retry": self.retry, "reason": self.reason, "source": self.source, "p_retry": self.p_retry}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _titles(diag: Dict[str, Any], n: int = 3) -> List[str]:
    return [f"'{m.get('title')}' ({m.get('equipment_id') or 'any equipment'}, score {m.get('score')})"
            for m in (diag.get("near_misses") or [])[:n] if m.get("title")]


def _accept(reason: str, source: str, why: str, p: Optional[float] = None) -> ReflectionDecision:
    return ReflectionDecision(
        retry=False, reason=reason, source=source, p_retry=p,
        note=(f"\n\nREFLECTION: No relevant past experience — {why} "
              "Do not search memory again for this; proceed from live data and other evidence."),
    )


def _retry(reason: str, source: str, how: str, p: Optional[float] = None) -> ReflectionDecision:
    return ReflectionDecision(
        retry=True, reason=reason, source=source, p_retry=p,
        note=f"\n\nREFLECTION: Relevant past experience may exist — {how} You may search memory ONCE more.",
    )


def is_ambiguous(diag: Dict[str, Any]) -> bool:
    return diag.get("empty_reason") in ("below_threshold", "no_candidates") \
        and diag.get("semantic_available", True) is not False


def gate(diag: Dict[str, Any]) -> Optional[ReflectionDecision]:
    """Decide from facts alone. None means ambiguous: a judge is needed."""
    reason = diag.get("empty_reason")
    if reason == "store_empty":
        return _accept(reason, "gate", "this building has no learned patterns yet.")
    if reason == "off_scope":
        others = sorted({m.get("equipment_id") for m in diag.get("near_misses") or [] if m.get("equipment_id")})
        where = f" ({', '.join(others)})" if others else ""
        return _accept(reason, "gate", f"past patterns exist only for other equipment{where} and do not apply here.")
    if reason == "low_confidence":
        titles = [f"'{m.get('title')}'" for m in diag.get("low_confidence_matches") or [] if m.get("title")]
        return _accept(reason, "gate", f"matching past patterns exist ({', '.join(titles) or 'unnamed'}) but none "
                       "is confident enough to cite; rewording would find the same ones. Do not cite them as fact.")
    if diag.get("semantic_available") is False:
        return _accept(reason or "unknown", "gate", "memory search is unavailable (no embedding model), so it cannot be refined.")
    if reason == "filtered_out":
        stype = (diag.get("filters") or {}).get("skill_type")
        return _retry(reason, "gate", f"a related pattern was excluded by the skill_type={stype!r} filter: "
                      f"{'; '.join(_titles(diag))}. Search again WITHOUT the skill_type filter.")
    if reason == "missed":
        return _retry(reason, "gate", f"patterns matching above threshold exist but were not returned: "
                      f"{'; '.join(_titles(diag))}. Search again using wording from these titles.")
    if is_ambiguous(diag):
        return None
    return _accept(reason or "unknown", "gate", "the memory store could not explain the empty result.")


def rule_judge(diag: Dict[str, Any]) -> bool:
    """Ambiguous case, no model: retry only if the nearest pattern was a near miss."""
    best = diag.get("best_score")
    if best is None:
        return False
    return float(best) >= float(diag.get("threshold", 0.3)) - _env_float("ARVIS_REFLECTOR_MARGIN", 0.1)


def kev_state(diag: Dict[str, Any], query: str) -> str:
    return json.dumps({
        "query": query,
        "patterns_in_memory": diag.get("store_size"),
        "match_threshold": diag.get("threshold"),
        "closest_patterns": [{k: m.get(k) for k in ("title", "equipment_id", "skill_type", "score")}
                             for m in diag.get("near_misses") or []],
    }, default=str)


async def kev_judge(diag: Dict[str, Any], query: str) -> Optional[float]:
    from arvis_core.decision import kev
    return await kev.ask_noul(kev_state(diag, query), KEV_INSTRUCTIONS, qid="reflect")


async def decide_reflection(diag: Optional[Dict[str, Any]], *, query: str = "",
                            already_reflected: bool = False, budget_ok: bool = True,
                            judge: Optional[str] = None) -> Optional[ReflectionDecision]:
    """Retry-or-accept for one empty memory search. None when the tool gave no diagnostics."""
    if not isinstance(diag, dict) or not diag.get("empty_reason"):
        return None
    if already_reflected:
        return _accept("already_reflected", "gate", "memory was already searched again once for this.")
    if not budget_ok:
        return _accept("budget", "gate", "the investigation budget is nearly spent.")

    decided = gate(diag)
    if decided is not None:
        return decided

    reason = diag["empty_reason"]
    best, thr = diag.get("best_score"), diag.get("threshold")
    near = "; ".join(_titles(diag))
    judge = (judge or os.getenv("ARVIS_REFLECTOR_JUDGE", "rule")).strip().lower()

    if judge == "kev":
        p = await kev_judge(diag, query)
        if p is not None:
            if p >= _env_float("ARVIS_REFLECTOR_KEV_THRESHOLD", 0.5):
                return _retry(reason, "kev", f"the closest patterns may describe this situation: {near}. "
                              "Search again using their wording.", p)
            return _accept(reason, "kev", f"the closest patterns ({near or 'none'}) describe a different situation.", p)
        # Kev unavailable → rule

    if rule_judge(diag):
        return _retry(reason, "rule", f"the closest patterns scored just under the match threshold "
                      f"(best {best} vs {thr}): {near}. If one describes this situation, search again using its wording.")
    return _accept(reason, "rule", f"the closest pattern scored {best if best is not None else 'nothing'} "
                   f"against a threshold of {thr}.")
