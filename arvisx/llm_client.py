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

# provider → (key_env, default_base_url, default_model)
_PROVIDERS = {
    "k2think": ("K2THINK_API_KEY", "https://api.k2think.ai/v1", "MBZUAI-IFM/K2-Think-v2"),
    "groq":    ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openai":  ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
}


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
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    async def ask_tools(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
                        system_msgs: Optional[List[Dict[str, str]]] = None,
                        tool_choice: str = "auto", max_tokens: int = 2000,
                        **_: Any) -> Dict[str, Any]:
        """Native function-calling turn. Returns:
        {"tool_calls": [{"id","name","args"}], "content": str, "finish": str,
         "assistant_message": <openai msg dict for the follow-up>}."""
        msgs: List[Dict[str, Any]] = []
        for s in (system_msgs or []):
            msgs.append({"role": s.get("role", "system"), "content": s.get("content", "")})
        msgs.extend(messages)

        def _call():
            return self._client.chat.completions.create(
                model=self.model, messages=msgs, tools=tools, tool_choice=tool_choice,
                temperature=0, max_tokens=max_tokens)

        resp = await asyncio.to_thread(_call)
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
            return self._client.chat.completions.create(
                model=self.model, messages=msgs, temperature=0)

        resp = await asyncio.to_thread(_call)
        content = (resp.choices[0].message.content or "") if resp.choices else ""
        obj = _extract_json(content)
        if obj is None:
            logger.warning(f"[ArvisxLLM:{self.provider}] no JSON in reply (channel={channel})")
            return {}
        return obj


def make_llm(provider: Optional[str] = None) -> Optional[ArvisxLLM]:
    """Build the configured ArvisX LLM, or None if no usable key / SDK.
    Honours ARVISX_LLM_PROVIDER (default k2think). 'bedrock'/'unified' → UnifiedLLM."""
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
