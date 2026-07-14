"""LLM API-key pool: rotate off a rate-limited key instead of dropping the conversation.

Contract:
- A 429 parks THAT key for as long as the provider says, and the next key serves the request.
- Cooldowns are module-level, because make_llm() builds a fresh client on every request —
  per-instance state would forget which keys are burned the moment the turn ended.
- Only when EVERY key is exhausted do we raise (caller then degrades to the busy message).
- A non-rate-limit error is NOT a quota problem: it propagates immediately, no rotation.
"""
from __future__ import annotations

import pytest

import arvisx.llm_client as lc


class _RateLimited(Exception):
    """Shaped like the provider's 429 (openai.RateLimitError is matched by class name)."""
    status_code = 429

    def __init__(self, msg="Rate limit reached ... Please try again in 1h11m35.808s"):
        super().__init__(msg)


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    lc._COOLDOWN.clear()
    yield
    lc._COOLDOWN.clear()


def _llm(keys):
    return lc.ArvisxLLM.__new__(lc.ArvisxLLM)   # skip __init__ (no openai SDK needed)


def _mk(keys):
    o = _llm(keys)
    o.provider, o.model, o.base_url = "groq", "m", "http://x"
    o.keys = list(keys)
    o._timeout, o._clients = 5.0, {}
    o._client_for = lambda k: k                 # the "client" is just the key, for the test
    return o


# ── rate-limit detection + how long a key is burned ─────────────────────────
def test_detects_rate_limit():
    assert lc._is_rate_limit(_RateLimited())
    assert lc._is_rate_limit(Exception("Error code: 429 - rate_limit_exceeded"))
    assert not lc._is_rate_limit(Exception("connection reset"))


def test_parses_provider_retry_window():
    # Groq's own wording from the live 429 we hit
    assert lc._retry_after_seconds(Exception("Please try again in 1h11m35.808s")) == pytest.approx(4295.8, abs=1)
    assert lc._retry_after_seconds(Exception("Please try again in 45m29s")) == pytest.approx(2729, abs=1)
    assert lc._retry_after_seconds(Exception("Please try again in 7.5s")) == pytest.approx(7.5, abs=0.1)
    # unknown wording → assume a daily cap rather than hammering the key
    assert lc._retry_after_seconds(Exception("rate limited")) == 3600.0


# ── rotation ────────────────────────────────────────────────────────────────
def test_rotates_to_next_key_on_rate_limit():
    llm = _mk(["key-aaaa", "key-bbbb"])
    seen = []

    def fn(client):
        seen.append(client)
        if client == "key-aaaa":
            raise _RateLimited()
        return "answered"

    assert llm._rotate(fn) == "answered"
    assert seen == ["key-aaaa", "key-bbbb"]          # tried the first, rotated to the second
    assert lc.key_cooldown_remaining("key-aaaa") > 3600   # parked ~1h11m per the message
    assert lc.key_cooldown_remaining("key-bbbb") == 0


def test_burned_key_is_skipped_on_the_next_call():
    llm = _mk(["key-aaaa", "key-bbbb"])
    llm._rotate(lambda c: (_ for _ in ()).throw(_RateLimited()) if c == "key-aaaa" else "ok")
    seen = []

    def fn(client):
        seen.append(client)
        return "ok"

    assert llm._rotate(fn) == "ok"
    assert seen == ["key-bbbb"], "a parked key must not be retried while cooling"


def test_raises_only_when_every_key_is_exhausted():
    llm = _mk(["key-aaaa", "key-bbbb"])
    with pytest.raises(Exception):
        llm._rotate(lambda c: (_ for _ in ()).throw(_RateLimited()))
    assert lc.key_cooldown_remaining("key-aaaa") > 0
    assert lc.key_cooldown_remaining("key-bbbb") > 0
    # every key cooling → fail fast (the caller shows the honest busy message)
    with pytest.raises(RuntimeError, match="all 2 groq API keys are rate-limited"):
        llm._rotate(lambda c: "never reached")


def test_non_rate_limit_error_does_not_rotate():
    llm = _mk(["key-aaaa", "key-bbbb"])
    seen = []

    def fn(client):
        seen.append(client)
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        llm._rotate(fn)
    assert seen == ["key-aaaa"], "a non-quota error must not burn through the pool"
    assert lc.key_cooldown_remaining("key-aaaa") == 0, "and must not park the key"


# ── pool status for the admin panel: health, never the secret ───────────────
def test_key_pool_status_never_leaks_the_key():
    lc._cool("secret-key-wxyz", 120)
    st = lc.key_pool_status(["secret-key-wxyz", "fresh-key-1234"])
    assert st[0]["last4"] == "wxyz" and st[0]["cooling"] and 0 < st[0]["cooldown_s"] <= 120
    assert st[1]["last4"] == "1234" and not st[1]["cooling"]
    blob = str(st)
    assert "secret-key" not in blob and "fresh-key" not in blob


# ── config: the pool reads from the admin panel, legacy single key still works ──
def test_db_keys_merge_legacy_single_key(tmp_path):
    import json
    from arvisx.persistence import ArvisxDb
    db = ArvisxDb(str(tmp_path / "k.db"))
    db.set_setting("_llm", "api_key", "legacy-key-0001")
    db.set_setting("_llm", "api_keys", json.dumps(["pool-key-0002", "pool-key-0003"]))
    lc.set_config_db(db)
    try:
        keys = lc.db_llm_keys()
        assert keys[0] == "legacy-key-0001"           # legacy key stays first / still used
        assert "pool-key-0002" in keys and "pool-key-0003" in keys
        assert len(keys) == 3
    finally:
        lc.set_config_db(None)
