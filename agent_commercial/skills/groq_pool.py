"""
Groq Key Pool
=============

Shared rotation pool for Groq API keys. When a key hits a rate limit (429), it
is parked for as long as the provider says (parsed from the retry-after header or
the error message), and the next available key is used. Cooldowns are module-level
so they survive the per-request client rebuilds in skill_analyzer / vision_backend
and are shared across BOTH consumers — a key parked by the analyzer is also parked
for vision OCR.

Key sources (first non-empty wins, all merged + de-duped, order preserved):
  GROQ_API_KEYS   comma-separated list (preferred)
  GROQ_API_KEY    single key
  GROQ_API_KEY_1, GROQ_API_KEY_2, ...  numbered

Usage:
    pool = GroqKeyPool()
    resp = pool.chat_completion(model=..., messages=..., temperature=0.0)
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger("arvis.skills.groq_pool")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Module-level cooldown state: key -> unix ts until which the key is parked.
# Shared across all GroqKeyPool instances and both consumers.
_COOLDOWNS: dict[str, float] = {}
# Cache clients per key so we don't rebuild an OpenAI client every call.
_CLIENTS: dict[str, object] = {}

# Fallback park when the provider gives a 429 with no parseable duration.
_DEFAULT_COOLDOWN = 30.0
# Cap a single parse so a bogus huge value can't park a key for days by mistake,
# EXCEPT explicit daily (TPD) limits which legitimately park for hours.
_MAX_SHORT_COOLDOWN = 120.0
_TPD_COOLDOWN = 3600.0  # daily-limit park (re-checked hourly)


def _load_keys() -> list[str]:
    keys: list[str] = []
    csv = os.getenv("GROQ_API_KEYS", "").strip()
    if csv:
        keys.extend(k.strip() for k in csv.split(",") if k.strip())
    single = os.getenv("GROQ_API_KEY", "").strip()
    if single:
        keys.append(single)
    i = 1
    while True:
        v = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if not v:
            break
        keys.append(v)
        i += 1
    # de-dup, preserve order
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


class GroqAllKeysCoolingDown(Exception):
    """Raised when every key in the pool is currently rate-limited."""

    def __init__(self, wait_seconds: float):
        self.wait_seconds = wait_seconds
        super().__init__(f"all Groq keys cooling down; soonest in {wait_seconds:.1f}s")


class GroqKeyPool:
    def __init__(self, keys: Optional[list[str]] = None) -> None:
        self._keys = keys if keys is not None else _load_keys()

    @property
    def available(self) -> bool:
        return bool(self._keys)

    @property
    def size(self) -> int:
        return len(self._keys)

    def status(self) -> dict:
        now = time.time()
        return {
            "total": len(self._keys),
            "ready": sum(1 for k in self._keys if _COOLDOWNS.get(k, 0) <= now),
            "cooling": sum(1 for k in self._keys if _COOLDOWNS.get(k, 0) > now),
        }

    # ---- client management ------------------------------------------------

    @staticmethod
    def _client_for(key: str):
        c = _CLIENTS.get(key)
        if c is None:
            from openai import OpenAI
            c = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
            _CLIENTS[key] = c
        return c

    def _ready_keys(self) -> list[str]:
        now = time.time()
        return [k for k in self._keys if _COOLDOWNS.get(k, 0) <= now]

    def _soonest_wait(self) -> float:
        now = time.time()
        future = [_COOLDOWNS[k] - now for k in self._keys if _COOLDOWNS.get(k, 0) > now]
        return max(min(future), 0.0) if future else 0.0

    # ---- rate-limit parsing ----------------------------------------------

    @staticmethod
    def _park_seconds(exc) -> float:
        """Derive a cooldown from a 429 exception. Prefers retry-after header,
        falls back to parsing the message, then a default."""
        # retry-after header
        try:
            resp = getattr(exc, "response", None)
            if resp is not None:
                ra = resp.headers.get("retry-after")
                if ra:
                    return min(float(ra), _MAX_SHORT_COOLDOWN)
        except Exception:
            pass
        msg = str(getattr(exc, "message", "") or exc)
        low = msg.lower()
        # daily token limit → long park
        if "per day" in low or "tpd" in low or "tokens per day" in low:
            return _TPD_COOLDOWN
        # "try again in 7.5s" / "in 2m30s" / "in 1.2 seconds"
        m = re.search(r"in\s+([\d.]+)\s*(ms|s|sec|seconds|m|min|minutes)?", low)
        if m:
            val = float(m.group(1))
            unit = (m.group(2) or "s")
            if unit == "ms":
                val /= 1000.0
            elif unit.startswith("m") and unit != "ms":
                val *= 60.0
            return min(max(val, 1.0), _MAX_SHORT_COOLDOWN)
        return _DEFAULT_COOLDOWN

    def _park(self, key: str, exc) -> float:
        secs = self._park_seconds(exc)
        _COOLDOWNS[key] = time.time() + secs
        logger.warning("Groq key parked %.1fs (…%s): %s", secs, key[-4:], str(exc)[:120])
        return secs

    # ---- the call ---------------------------------------------------------

    def chat_completion(self, **kwargs):
        """Run a Groq chat completion, rotating keys on 429. Raises the last
        non-rate-limit error, or GroqAllKeysCoolingDown if every key is parked."""
        if not self._keys:
            raise RuntimeError("Groq key pool is empty (set GROQ_API_KEYS / GROQ_API_KEY)")

        try:
            from openai import RateLimitError
        except Exception:  # pragma: no cover
            RateLimitError = tuple()  # type: ignore

        last_err = None
        # Try each ready key once; parking on 429 as we go.
        tried = 0
        while True:
            ready = self._ready_keys()
            if not ready:
                raise GroqAllKeysCoolingDown(self._soonest_wait())
            key = ready[0]
            tried += 1
            try:
                return self._client_for(key).chat.completions.create(**kwargs)
            except Exception as e:
                is_429 = isinstance(e, RateLimitError) or getattr(
                    getattr(e, "response", None), "status_code", None) == 429 or "429" in str(e)
                if is_429:
                    self._park(key, e)
                    last_err = e
                    continue  # rotate to next ready key
                raise
        # unreachable
