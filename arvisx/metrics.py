"""Usage + cost metrics (WhatsApp + LLM). A thin process-global recorder: the API sets the
db once at startup; the LLM client + WhatsApp endpoints log events; the admin panel
aggregates. Costs are configurable per-deployment (env) — Baileys WhatsApp is free today, so
ARVISX_WA_MSG_COST defaults to 0; LLM rates are per-1M-tokens. No db set → no-op (safe)."""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("arvisx.metrics")

_db = None


def set_db(db) -> None:
    global _db
    _db = db


def _f(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, default))
    except Exception:
        return float(default)


def llm_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """USD from configurable per-1M-token rates (ARVISX_LLM_PRICE_IN / _OUT)."""
    return round((prompt_tokens or 0) / 1_000_000 * _f("ARVISX_LLM_PRICE_IN", 0.0)
                 + (completion_tokens or 0) / 1_000_000 * _f("ARVISX_LLM_PRICE_OUT", 0.0), 6)


def wa_cost(n: int = 1) -> float:
    """Per-message cost (0 for Baileys; set ARVISX_WA_MSG_COST for the Business API)."""
    return round((n or 0) * _f("ARVISX_WA_MSG_COST", 0.0), 6)


def record_llm(channel: str, model: str, prompt_tokens: int, completion_tokens: int,
               building: str = "") -> None:
    if _db is None:
        return
    try:
        _db.log_usage(building, "llm", channel=channel, model=model,
                      prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                      n=1, cost=llm_cost(prompt_tokens, completion_tokens))
    except Exception as e:
        logger.warning(f"record_llm failed: {e}")


def record_whatsapp(direction: str, kind: str = "", building: str = "", count: int = 1) -> None:
    """direction = 'in' (received) | 'out' (sent)."""
    if _db is None or count <= 0:
        return
    try:
        _db.log_usage(building, f"whatsapp_{direction}", channel=kind, n=count, cost=wa_cost(count))
    except Exception as e:
        logger.warning(f"record_whatsapp failed: {e}")
