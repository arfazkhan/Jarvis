"""
ArvisX LLM environment bootstrap.

Standalone `python -m arvisx.*` does NOT load the repo `.env`, so the shared
UnifiedLLM had no provider creds (K2THINK_API_KEY / BEDROCK_API_KEY) and every
free-form channel failed ('Provider k2think not supported in hybrid adapter').
The commercial backend loads `.env` at boot; ArvisX must do the same before it
constructs a UnifiedLLM. Idempotent, best-effort.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("arvisx.llm_env")
_LOADED = False


def load_arvis_env() -> bool:
    """Load the repo-root .env once so UnifiedLLM gets its provider keys.
    Returns True if a .env was found and loaded."""
    global _LOADED
    if _LOADED:
        return True
    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.warning("[ArvisX] python-dotenv not installed — LLM creds may be missing")
        return False
    # Repo root = two levels up from this file (arvisx/ -> repo).
    root = Path(__file__).resolve().parent.parent
    env = root / ".env"
    if env.exists():
        load_dotenv(env)
        _LOADED = True
        logger.info(f"[ArvisX] loaded LLM env from {env}")
        return True
    logger.info("[ArvisX] no .env found — LLM will use ambient env only")
    return False
