"""Client for a self-hosted Kev decision model (POST /v1/systemone).

Kev answers typed questions with calibrated probabilities. We use only the
`noul` (yes/no) type: the response carries the probability of "yes".

Request:  {"state": "...", "model": "kev-latest",
           "questions": {"<id>": {"type": "noul", "instructions": "..."}}}
Response: per-question results carrying `"noul": <p_yes>`, plus usage/latency_ms.

The exact nesting of per-question results is not pinned down by the public docs,
so parsing looks for the question id and then the `noul` value, tolerating the
shapes {"<id>": {"noul": p}}, {"answers"|"results"|"questions": {"<id>": ...}}
and {"<id>": p}. Anything else is a failure, never a guess.

Config (env):
  ARVIS_DECISION_URL      base URL, e.g. http://127.0.0.1:8090 (unset = disabled)
  ARVIS_DECISION_MODEL    model name (default kev-latest)
  ARVIS_DECISION_TIMEOUT  seconds (default 3)
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("arvis.decision.kev")


def configured() -> bool:
    return bool(os.getenv("ARVIS_DECISION_URL", "").strip())


def _find_p(payload: Any, qid: str) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    for container in (payload, *(payload.get(k) for k in ("answers", "results", "questions"))):
        if not isinstance(container, dict) or qid not in container:
            continue
        v = container[qid]
        if isinstance(v, dict):
            v = v.get("noul")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0:
            return float(v)
    return None


async def ask_noul(state: str, instructions: str, qid: str = "q") -> Optional[float]:
    """Probability of "yes", or None if Kev is unconfigured, unreachable, slow or
    returned something we cannot read. Callers must have a fallback."""
    base = os.getenv("ARVIS_DECISION_URL", "").strip().rstrip("/")
    if not base:
        return None
    body: Dict[str, Any] = {
        "state": state,
        "model": os.getenv("ARVIS_DECISION_MODEL", "kev-latest"),
        "questions": {qid: {"type": "noul", "instructions": instructions}},
    }
    try:
        import httpx
        timeout = float(os.getenv("ARVIS_DECISION_TIMEOUT", "3"))
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/v1/systemone", json=body)
            r.raise_for_status()
            p = _find_p(r.json(), qid)
        if p is None:
            logger.warning(f"[Kev] unreadable response shape: {str(r.text)[:200]}")
        return p
    except Exception as e:
        logger.warning(f"[Kev] decision call failed ({type(e).__name__}: {e}) — using rule fallback")
        return None
