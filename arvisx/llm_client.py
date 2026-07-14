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


def _db_llm_config():
    """The LLM config saved from the admin panel (building_settings under '_llm'), or None."""
    if _CONFIG_DB is None:
        return None
    try:
        prov = (_CONFIG_DB.get_setting("_llm", "provider", "") or "").strip().lower()
        if not prov:
            return None
        return {"provider": prov,
                "model": _CONFIG_DB.get_setting("_llm", "model", "").strip(),
                "api_key": _CONFIG_DB.get_setting("_llm", "api_key", "").strip(),
                "base_url": _CONFIG_DB.get_setting("_llm", "base_url", "").strip()}
    except Exception:
        return None


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

    def __init__(self, provider: str, api_key: str, base_url: str, model: str):
        from openai import OpenAI
        self.provider = provider
        self.model = model
        # Explicit timeout + SDK retry so a slow/flaky K2Think turn fails fast and retries
        # instead of hanging (a hang → the caller's context-blind deterministic fallback).
        timeout = float(os.environ.get("ARVISX_LLM_TIMEOUT", "45"))
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)

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
            return self._client.chat.completions.create(
                model=self.model, messages=msgs, tools=tools, tool_choice=tool_choice,
                temperature=temperature, max_tokens=max_tokens)

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

        def _call():
            # Ask for a native JSON object so parsing is reliable by construction, not by
            # scraping prose. Some OpenAI-compatible providers (K2Think / a few self-hosted
            # gateways) reject response_format — fall back to a plain call + _extract_json.
            try:
                return self._client.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0,
                    response_format={"type": "json_object"})
            except Exception:
                return self._client.chat.completions.create(
                    model=self.model, messages=msgs, temperature=0)

        resp = await asyncio.to_thread(_call)
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
            key = cfg["api_key"] or (os.environ.get(pdef[0], "") if pdef else "")
            if key and base and model:
                try:
                    logger.info(f"[ArvisxLLM] provider={prov} model={model} (admin config)")
                    return ArvisxLLM(prov, key, base, model)
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
