"""
ArvisX LLM client — a thin, self-owned adapter the reasoning/agent layers call.

Why not just use the commercial UnifiedLLM? In this codebase agent_home's LLMAgent
is a stub (only a Groq text client; `.client` is always None), so UnifiedLLM's
OpenAI-compatible adapter never fires — k2think/groq/openai all error with
"Provider X not supported in hybrid adapter", leaving only the Bedrock path. ArvisX
shouldn't depend on Bedrock for its long-tail reasoning. K2Think (and Groq/OpenAI)
are all OpenAI-compatible, so a ~50-line client gives ArvisX a sovereign,
provider-swappable LLM with the exact `ask_json` interface reasoning.py and agent.py
expect — and the deterministic floor still owns every fact (LLM only proposes).

Provider via ARVISX_LLM_PROVIDER (default k2think). Each is OpenAI-compatible:
  k2think : K2THINK_API_KEY   base https://api.k2think.ai/v1     MBZUAI-IFM/K2-Think-v2
  groq    : GROQ_API_KEY      base https://api.groq.com/openai/v1 llama-3.3-70b-versatile
  openai  : OPENAI_API_KEY    base https://api.openai.com/v1      gpt-4o-mini
Override per provider with <PROVIDER>_BASE_URL / <PROVIDER>_MODEL.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvisx.llm")


def _record_usage(resp: Any, channel: str, model: str) -> None:
    """Log token usage + cost for one LLM call (best-effort; never breaks the call)."""
    try:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        from arvisx import metrics
        metrics.record_llm(channel, model,
                           int(getattr(u, "prompt_tokens", 0) or 0),
                           int(getattr(u, "completion_tokens", 0) or 0))
    except Exception:
        pass


# provider → (key_env, default_base_url, default_model). All OpenAI-compatible chat endpoints.
_PROVIDERS = {
    "k2think":    ("K2THINK_API_KEY", "https://api.k2think.ai/v1", "MBZUAI-IFM/K2-Think-v2"),
    "groq":       ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openai":     ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
    "nvidia":     ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
    "gemini":     ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
}

# Suggested models per provider — for the admin-panel dropdown (free-text still allowed).
PROVIDER_CATALOG = {
    "groq":       ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"],
    "openai":     ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o4-mini"],
    "openrouter": ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash-001", "meta-llama/llama-3.3-70b-instruct"],
    "nvidia":     ["meta/llama-3.3-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
    "gemini":     ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro"],
    "k2think":    ["MBZUAI-IFM/K2-Think-v2"],
}

# The API sets this so make_llm can read the admin-panel-saved config (DB) before env.
_CONFIG_DB = None


def set_config_db(db) -> None:
    global _CONFIG_DB
    _CONFIG_DB = db


def db_llm_keys() -> List[str]:
    """The key POOL saved from the admin panel. '_llm/api_keys' is a JSON list; the legacy
    single '_llm/api_key' is kept as the first key so existing installs keep working."""
    if _CONFIG_DB is None:
        return []
    keys: List[str] = []
    try:
        raw = (_CONFIG_DB.get_setting("_llm", "api_keys", "") or "").strip()
        if raw:
            keys = [str(k).strip() for k in json.loads(raw) if str(k).strip()]
    except Exception:
        keys = []
    try:
        single = (_CONFIG_DB.get_setting("_llm", "api_key", "") or "").strip()
        if single and single not in keys:
            keys.insert(0, single)
    except Exception:
        pass
    return keys


def _db_llm_config():
    """The LLM config saved from the admin panel (building_settings under '_llm'), or None."""
    if _CONFIG_DB is None:
        return None
    try:
        prov = (_CONFIG_DB.get_setting("_llm", "provider", "") or "").strip().lower()
        if not prov:
            return None
        keys = db_llm_keys()
        return {"provider": prov,
                "model": _CONFIG_DB.get_setting("_llm", "model", "").strip(),
                "api_key": keys[0] if keys else "",
                "api_keys": keys,
                "base_url": _CONFIG_DB.get_setting("_llm", "base_url", "").strip()}
    except Exception:
        return None


# ── key pool: rotate off a rate-limited key instead of failing the conversation ──
# Cooldowns are MODULE-level, not per-instance: make_llm() builds a fresh ArvisxLLM on every
# request, so instance state would forget which keys are burned the moment the turn ends.
_COOLDOWN: Dict[str, float] = {}          # api_key → epoch when it may be used again

_RETRY_RE = re.compile(r"try again in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:([\d.]+)\s*s)?", re.I)


def _is_rate_limit(e: Exception) -> bool:
    if type(e).__name__ == "RateLimitError" or getattr(e, "status_code", None) == 429:
        return True
    s = str(e).lower()
    return "rate_limit" in s or "rate limit" in s or "429" in s


def _retry_after_seconds(e: Exception) -> float:
    """How long this key is actually burned. Prefer the Retry-After header, else parse the
    provider's own words ('Please try again in 1h11m35.808s'). Default to an hour: a
    tokens-per-DAY cap is the case that matters, and retrying it early just burns calls."""
    resp = getattr(e, "response", None)
    headers = getattr(resp, "headers", None)
    if headers is not None:
        try:
            v = headers.get("retry-after") or headers.get("Retry-After")
            if v:
                return max(1.0, float(v))
        except Exception:
            pass
    m = _RETRY_RE.search(str(e))
    if m and any(m.groups()):
        h, mi, s = m.groups()
        secs = int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
        if secs > 0:
            return secs
    return 3600.0


def _cool(key: str, seconds: float) -> None:
    import time
    _COOLDOWN[key] = time.time() + seconds


def key_cooldown_remaining(key: str) -> float:
    import time
    return max(0.0, _COOLDOWN.get(key, 0.0) - time.time())


def key_pool_status(keys: List[str]) -> List[Dict[str, Any]]:
    """Per-key health for the admin panel. Never returns a key — only its last 4."""
    out = []
    for k in keys:
        rem = key_cooldown_remaining(k)
        out.append({"last4": k[-4:] if k else "", "cooling": rem > 0,
                    "cooldown_s": int(rem)})
    return out


def _balanced_objects(s: str):
    """Yield every top-level {...} substring (brace-matched), in order."""
    depth, start = 0, None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield s[start:i + 1]


def _extract_json(text: str) -> Optional[dict]:
    """Pull the answer JSON out of an LLM reply. Reasoning models (e.g. K2-Think)
    emit long chain-of-thought — itself full of `{...}` example fragments — then a
    `</think>` delimiter, then the real JSON last. So: drop everything up to the
    final `</think>`, strip fences, then take the LAST balanced object that parses."""
    if not text:
        return None
    s = text
    if "</think>" in s:
        s = s.rsplit("</think>", 1)[1]
    s = s.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in s:
        for block in s.split("```"):
            if block.strip().startswith("{"):
                s = block.strip()
                break
    # direct parse first
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # else the last balanced {...} that parses (the model's final answer)
    for cand in reversed(list(_balanced_objects(s))):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def _parse_tool_args(raw: Any) -> dict:
    """Tool-call arguments come as a JSON string — and some providers (K2Think)
    double-encode them (a JSON string wrapping a JSON string). Decode until dict."""
    v = raw
    for _ in range(3):
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                return {}
        else:
            return {}
    return v if isinstance(v, dict) else {}


class ArvisxLLM:
    """OpenAI-compatible LLM with the `ask_json` + native `ask_tools` interfaces ArvisX
    reasoning/agent layers expect."""

    supports_tools = True

    def __init__(self, provider: str, api_key, base_url: str, model: str):
        # Fail fast when the SDK isn't installed: make_llm() promises None (→ deterministic floor)
        # rather than a client that only blows up at call time. Clients themselves are built
        # lazily per key below, but the import check has to happen here.
        from openai import OpenAI  # noqa: F401
        self.provider = provider
        self.model = model
        self.base_url = base_url
        # `api_key` may be a single key or a POOL. A pool lets a rate-limited key be parked and
        # the next one used, so one exhausted quota doesn't take the conversation down.
        keys = [api_key] if isinstance(api_key, str) else list(api_key or [])
        self.keys = [k for k in (str(k).strip() for k in keys) if k]
        if not self.keys:
            raise ValueError("no API key")
        # Explicit timeout + SDK retry so a slow/flaky turn fails fast and retries
        # instead of hanging (a hang → the caller's context-blind deterministic fallback).
        self._timeout = float(os.environ.get("ARVISX_LLM_TIMEOUT", "45"))
        self._clients: Dict[str, Any] = {}

    def _client_for(self, key: str):
        from openai import OpenAI
        if key not in self._clients:
            self._clients[key] = OpenAI(api_key=key, base_url=self.base_url,
                                        timeout=self._timeout, max_retries=2)
        return self._clients[key]

    @property
    def _client(self):
        """The first usable key's client — for callers that just want a client."""
        for k in self.keys:
            if key_cooldown_remaining(k) <= 0:
                return self._client_for(k)
        return self._client_for(self.keys[0])

    def _rotate(self, fn):
        """Run `fn(client)`, rotating off any key the provider rate-limits. A burned key is
        parked for as long as the provider says, so we don't keep hammering it. Only when EVERY
        key is exhausted does this raise — and the caller then degrades honestly (busy message).
        Non-rate-limit errors propagate immediately: they are not a quota problem."""
        usable = [k for k in self.keys if key_cooldown_remaining(k) <= 0]
        if not usable:
            soonest = min(key_cooldown_remaining(k) for k in self.keys)
            raise RuntimeError(
                f"all {len(self.keys)} {self.provider} API keys are rate-limited "
                f"(next frees up in {int(soonest)}s)")
        last: Optional[Exception] = None
        for key in usable:
            try:
                return fn(self._client_for(key))
            except Exception as e:
                if not _is_rate_limit(e):
                    raise
                wait = _retry_after_seconds(e)
                _cool(key, wait)
                last = e
                logger.warning("[ArvisxLLM:%s] key •••%s rate-limited — parked %.0fs, rotating "
                               "(%d of %d keys still usable)", self.provider, key[-4:], wait,
                               sum(1 for k in self.keys if key_cooldown_remaining(k) <= 0),
                               len(self.keys))
        logger.warning("[ArvisxLLM:%s] ALL %d keys rate-limited", self.provider, len(self.keys))
        raise last if last else RuntimeError("no usable API key")

    async def ask_tools(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
                        system_msgs: Optional[List[Dict[str, str]]] = None,
                        tool_choice: str = "auto", max_tokens: int = 2000,
                        temperature: float = 0.0,
                        **_: Any) -> Dict[str, Any]:
        """Native function-calling turn. Returns:
        {"tool_calls": [{"id","name","args"}], "content": str, "finish": str,
         "assistant_message": <openai msg dict for the follow-up>}.

        `temperature` defaults to 0 (extraction/classification want determinism). The CONVERSATIONAL
        agent passes a non-zero value: at 0 the model re-walks the identical token path whenever the
        tools and context repeat, so with its own last answer in history it parrots that answer back
        verbatim, turn after turn. Sampling breaks that lock-in; it can't weaken grounding, because
        every figure still has to come from a tool result and survive verify_grounded."""
        msgs: List[Dict[str, Any]] = []
        for s in (system_msgs or []):
            msgs.append({"role": s.get("role", "system"), "content": s.get("content", "")})
        msgs.extend(messages)

        def _call():
            return self._rotate(lambda c: c.chat.completions.create(
                model=self.model, messages=msgs, tools=tools, tool_choice=tool_choice,
                temperature=temperature, max_tokens=max_tokens))

        resp = await asyncio.to_thread(_call)
        _record_usage(resp, "tool", self.model)
        choice = resp.choices[0]
        m = choice.message
        calls = []
        assistant_tool_calls = []
        for tc in (m.tool_calls or []):
            args = _parse_tool_args(tc.function.arguments)
            calls.append({"id": tc.id, "name": tc.function.name, "args": args})
            assistant_tool_calls.append({"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": json.dumps(args)}})
        assistant_message: Dict[str, Any] = {"role": "assistant", "content": m.content or ""}
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls
        return {"tool_calls": calls, "content": m.content or "",
                "finish": choice.finish_reason, "assistant_message": assistant_message}

    async def ask_json(self, messages: List[Dict[str, str]],
                       system_msgs: Optional[List[Dict[str, str]]] = None,
                       channel: str = "chat", **_: Any) -> Dict[str, Any]:
        msgs: List[Dict[str, str]] = []
        for s in (system_msgs or []):
            msgs.append({"role": s.get("role", "system"), "content": s.get("content", "")})
        for m in messages:
            msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        def _attempt(c):
            # Ask for a native JSON object so parsing is reliable by construction, not by
            # scraping prose. Some OpenAI-compatible providers (K2Think / a few self-hosted
            # gateways) reject response_format — fall back to a plain call + _extract_json.
            # A rate limit is NOT a format problem: re-raise so the pool rotates keys.
            try:
                return c.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0,
                    response_format={"type": "json_object"})
            except Exception as e:
                if _is_rate_limit(e):
                    raise
                return c.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0)

        resp = await asyncio.to_thread(lambda: self._rotate(_attempt))
        _record_usage(resp, channel, self.model)
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        obj = _extract_json(content)
        if obj is None:
            logger.warning(f"[ArvisxLLM:{self.provider}] no JSON in reply (channel={channel})")
            return {}
        return obj


def make_llm(provider: Optional[str] = None) -> Optional[ArvisxLLM]:
    """Build the configured ArvisX LLM, or None if no usable key / SDK. Precedence: the admin
    panel's saved config (DB) → env (ARVISX_LLM_PROVIDER + provider key). 'bedrock'/'unified'
    → UnifiedLLM."""
    if provider is None:
        cfg = _db_llm_config()
        if cfg:
            prov = cfg["provider"]
            pdef = _PROVIDERS.get(prov)
            base = cfg["base_url"] or (pdef[1] if pdef else "")
            model = cfg["model"] or (pdef[2] if pdef else "")
            keys = cfg.get("api_keys") or []
            if not keys and pdef:
                env_key = os.environ.get(pdef[0], "").strip()
                if env_key:
                    keys = [env_key]
            if keys and base and model:
                try:
                    logger.info("[ArvisxLLM] provider=%s model=%s (admin config, %d key%s)",
                                prov, model, len(keys), "" if len(keys) == 1 else "s")
                    return ArvisxLLM(prov, keys, base, model)
                except Exception as e:
                    logger.warning(f"[ArvisxLLM] admin-config init failed: {e}")
    provider = (provider or os.environ.get("ARVISX_LLM_PROVIDER", "k2think")).strip().lower()

    if provider in ("bedrock", "unified"):
        try:
            from arvisx.llm_env import load_arvis_env
            load_arvis_env()
            from agent_unified.llm import UnifiedLLM
            return UnifiedLLM()
        except Exception as e:
            logger.warning(f"[ArvisxLLM] UnifiedLLM unavailable: {e}")
            return None

    cfg = _PROVIDERS.get(provider)
    if cfg is None:
        logger.warning(f"[ArvisxLLM] unknown provider '{provider}'")
        return None
    key_env, default_base, default_model = cfg
    key = os.environ.get(key_env, "").strip()
    if not key:
        logger.warning(f"[ArvisxLLM] {key_env} not set — LLM disabled (deterministic floor only)")
        return None
    base = os.environ.get(f"{provider.upper()}_BASE_URL", default_base)
    model = os.environ.get(f"{provider.upper()}_MODEL", default_model)
    try:
        llm = ArvisxLLM(provider, key, base, model)
        logger.info(f"[ArvisxLLM] provider={provider} model={model}")
        return llm
    except Exception as e:
        logger.warning(f"[ArvisxLLM] init failed: {e}")
        return None
