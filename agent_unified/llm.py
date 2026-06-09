from typing import List, Optional, Dict, Any, Union
import asyncio
import json
import os
import logging

logger = logging.getLogger("arvis.unified.llm")

from pydantic import BaseModel, Field, PrivateAttr

# Import legacy LLMAgent logic to reuse provider connections
from agent_home.llm_agent.llm_agent import LLMAgent
from agent_unified.schema import Message, ToolCall

import re

_QUARANTINE_BLOCKLIST = {}
_RESPONSE_HISTORY = {}

def get_session_key(messages: List[Dict[str, str]]) -> Optional[str]:
    if not messages:
        return None
    content = messages[0].get("content") or ""
    return str(hash(content))

def quarantine_values(session_key: str, values: List[str]):
    if not session_key:
        return
    if session_key not in _QUARANTINE_BLOCKLIST:
        _QUARANTINE_BLOCKLIST[session_key] = set()
    for v in values:
        if v and len(str(v).strip()) > 0:
            _QUARANTINE_BLOCKLIST[session_key].add(str(v).strip())
    logger.info(f"[Quarantine] Quarantined values for session {session_key}: {_QUARANTINE_BLOCKLIST[session_key]}")

# Global singletons for hybrid architecture
_REASONING_AGENT = None  # K2 Think (Reasoning Layer)
_TOOL_AGENT = None       # Primary Execution Layer (Configurable)
_FALLBACK_TOOL_AGENT = None # Groq Fallback Layer

# ═══════════════════════════════════════════════════════════════════════════════
# BEDROCK CHANNEL → MODEL ROUTING TABLE
# Maps semantic channel names to specific Bedrock model IDs.
# Channels are set per-call-site (see arvis_core/swarm/node.py and swarm_nodes.py).
# ═══════════════════════════════════════════════════════════════════════════════
BEDROCK_MODEL_MAP: Dict[str, str] = {
    # Classification/planning — Nova Lite (reliable JSON; Nova Micro returns prose)
    "classify":         "us.amazon.nova-lite-v1:0",
    "intent_classify":  "us.amazon.nova-lite-v1:0",  # IntentClassifier 6-class router
    "depth_plan":       "us.amazon.nova-lite-v1:0",
    "feedback":         "us.amazon.nova-lite-v1:0",

    # Tool-call execution — Kimi K2.5
    "tool":        "moonshotai.kimi-k2.5",
    "tool_call":   "moonshotai.kimi-k2.5",

    # Root cause / deep reasoning — Kimi K2 Thinking
    "reasoning":   "moonshot.kimi-k2-thinking",
    "root_cause":  "moonshot.kimi-k2-thinking",

    # Narrative reports / briefings — Nova Lite
    "narrative":   "us.amazon.nova-lite-v1:0",
    "report":      "us.amazon.nova-lite-v1:0",

    # Structured JSON extraction — GLM 4.7 Flash
    "extract":     "zai.glm-4.7-flash",
    "structured":  "zai.glm-4.7-flash",

    # Meta-cognition / continual reflection — Nova Lite
    "reflect":     "us.amazon.nova-lite-v1:0",
    "meta":        "us.amazon.nova-lite-v1:0",

    # Multi-agent consensus — MiniMax M2.5 (agent-native, token-efficient)
    "consensus":   "minimax.minimax-m2.5",

    # Synthesis — MiniMax M2.5 (frontier-class, token-efficient, replaces GLM 5)
    "synthesis":   "minimax.minimax-m2.5",

    # General swarm node work — MiniMax M2.5 (agent-native, 6× cheaper than Sonnet)
    "swarm":       "minimax.minimax-m2.5",

    # Chat / default — MiniMax M2.5 (frontier-class, tool use, replaces GLM 5)
    "chat":        "minimax.minimax-m2.5",

    # Verification channels — Nova Lite for checks, MiniMax for corrections, MiniMax for faithfulness
    "faithfulness":             "minimax.minimax-m2.5",
    "faithfulness_correction":  "minimax.minimax-m2.5",
    "claim_verify":             "us.amazon.nova-lite-v1:0",
    "claim_correction":         "minimax.minimax-m2.5",
    "physics_regen":            "minimax.minimax-m2.5",
    "self_consistency":         "us.amazon.nova-lite-v1:0",
    "consolidator":             "minimax.minimax-m2.5",

    # Escalation / complex audit — Kimi K2 Thinking (replaces Opus)
    "escalation":  "moonshot.kimi-k2-thinking",
    "audit":       "moonshot.kimi-k2-thinking",
}

# Bedrock fallback model — used when primary model for a channel fails
BEDROCK_FALLBACK_MAP: Dict[str, str] = {
    "moonshotai.kimi-k2.5":      "zai.glm-5",
    "moonshot.kimi-k2-thinking": "zai.glm-5",
    "us.amazon.nova-lite-v1:0":  "minimax.minimax-m2.5",
    "zai.glm-5":                 "minimax.minimax-m2.5",
    "zai.glm-4.7-flash":         "us.amazon.nova-lite-v1:0",
    "minimax.minimax-m2.5":      "us.amazon.nova-lite-v1:0",
}

# Bedrock provider prefix detection
_BEDROCK_PREFIXES = ("amazon.", "anthropic.", "moonshot.", "moonshotai.", "minimax.",
                     "zai.", "z-ai.", "mistral.", "meta.", "cohere.", "deepseek.", "qwen.")


def _bedrock_enabled() -> bool:
    """Bedrock is the default backend when its creds exist — UNLESS ARVIS_LLM_BACKEND
    explicitly selects a legacy OpenAI-compatible provider (k2think / openai / groq).
    This is the single switch that lets commercial run on K2Think instead of Bedrock."""
    if os.getenv("ARVIS_LLM_BACKEND", "").strip().lower() in ("k2think", "legacy", "groq", "openai"):
        return False
    return bool(os.getenv("BEDROCK_API_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))


def _ensure_openai_client(agent, base_url: str, api_key):
    """Give a legacy LLMAgent a real OpenAI-compatible client (the vendored stub builds
    none), so _ask_openai_compat can serve k2think/openai/groq with NATIVE tool-calling."""
    if api_key and getattr(agent, "client", None) is None:
        try:
            from openai import OpenAI
            agent.client = OpenAI(base_url=base_url, api_key=api_key)
        except Exception as e:
            logger.warning(f"[UnifiedLLM] failed to build OpenAI client for {base_url}: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# BEDROCK COST METERING — per-model pricing ($/1M tokens: input, output)
# ═══════════════════════════════════════════════════════════════════════════════
_BEDROCK_PRICING: Dict[str, tuple] = {
    "amazon.nova-micro-v1:0":    (0.035, 0.14),
    "us.amazon.nova-lite-v1:0":  (0.06, 0.24),
    "moonshotai.kimi-k2.5":      (1.0, 4.0),
    "moonshot.kimi-k2-thinking": (1.0, 4.0),
    "zai.glm-4.7-flash":         (0.3, 0.6),
    "zai.glm-5":                 (1.0, 3.0),
    "minimax.minimax-m2.1":      (0.5, 1.5),
    "minimax.minimax-m2.5":      (0.5, 1.5),
}

_LLM_USAGE_LOG: List[Dict[str, Any]] = []


def _compute_bedrock_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost from token counts using pricing table."""
    pricing = _BEDROCK_PRICING.get(model_id)
    if not pricing:
        for key, val in _BEDROCK_PRICING.items():
            if model_id.startswith(key.split(".")[0]):
                pricing = val
                break
    if not pricing:
        pricing = (3.0, 15.0)
    return (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000


def drain_usage_log() -> List[Dict[str, Any]]:
    """Drain and return all accumulated LLM usage entries. Thread-safe for single event loop."""
    global _LLM_USAGE_LOG
    entries = _LLM_USAGE_LOG[:]
    _LLM_USAGE_LOG = []
    return entries

def _robust_extract(content: str) -> tuple[List[str], str]:
    """
    Extract reasoning tags and return (thoughts, clean_answer).

    Fast path: if content has no XML-like tags, return it directly.
    Otherwise: strip thinking/reasoning tags into thoughts list,
    extract answer tags or fall back to remaining content.
    """
    if not content:
        return [], ""

    # Fast path: no tags at all — return as-is
    if "<" not in content:
        return [], content.strip()

    thoughts = []
    working = content

    # Strip all thinking-family tags into thoughts
    think_pattern = re.compile(
        r"<(think|thinking|thought|reasoning|process|internal_monologue)>(.*?)</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in think_pattern.finditer(working):
        t = m.group(2).strip()
        if t:
            thoughts.append(t)
    working = think_pattern.sub("", working)

    # Extract answer-family tags
    answer_pattern = re.compile(
        r"<(answer|final_proposal|conclusion|response|output)>(.*?)</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    answer_match = answer_pattern.search(working)
    if answer_match:
        final_answer = answer_match.group(2).strip()
    else:
        # No answer tags — strip any remaining stray tags and return
        final_answer = re.sub(r"</?[a-zA-Z_]+>", "", working).strip()

    return thoughts, final_answer

def _extract_k2_answer(content: str) -> str:
    """Legacy wrapper for _robust_extract."""
    _, answer = _robust_extract(content)
    return answer


def _coerce_prose_to_json(channel: str, content: str) -> Optional[Dict[str, Any]]:
    """
    Last-resort coercion for models that return prose instead of JSON.
    Handles known simple channels: classify (tier 1/2/3) and depth_plan (turn count).
    Returns None if coercion not applicable.
    """
    if not content:
        return None
    c = content.lower()

    if channel == "classify":
        # Look for tier number in prose: "T3", "tier 3", "tier: 3", "3 (actionable)"
        m = re.search(r"t(?:ier)?\s*[:\-]?\s*([123])\b", c)
        if m:
            return {"tier": int(m.group(1))}
        # Keyword fallback — T3 first (most specific), then T2, then T1
        if any(w in c for w in ("action", "change", "optim", "fix", "simulat", "recommend",
                                 "write", "setpoint", "push", "command", "execute", "modify")):
            return {"tier": 3}
        if any(w in c for w in ("diagnos", "fault", "root cause", "why", "trend", "analyz",
                                 "investigate", "inspect", "assess", "evaluate")):
            return {"tier": 2}
        if any(w in c for w in ("lookup", "status", "list", "current", "what is", "show me",
                                 "tell me", "have you", "do you", "are you", "can you")):
            return {"tier": 1}
        return {"tier": 2}  # safe default

    if channel == "depth_plan":
        # Look for turn count: "3 turns", "plan 3", "depth: 3", etc.
        m = re.search(r"\b([1-9])\s*turns?\b", c)
        if m:
            return {"turns": int(m.group(1))}
        m = re.search(r"(?:depth|turns?|rounds?)\s*[:\-]?\s*([1-9])\b", c)
        if m:
            return {"turns": int(m.group(1))}
        return {"turns": 3}  # safe default

    if channel == "intent_classify":
        # IntentClassifier expects {"class": "<name>", "confidence": 0.x, "reason": "..."}.
        # When Nova returns prose, salvage what we can. Order matters — most
        # specific class checks first.
        intent_keywords = [
            ("safety_critical",     ["fire alarm", "evacuat", "smoke detect", "refrigerant leak",
                                     "gas leak", "sprinkler", "life-safety", "life safety", "emergency"]),
            ("write_attempt",       ["write_attempt", "write attempt", "imperative",
                                     "command", "set point", "setpoint command", "operator commanding"]),
            ("capability_question", ["capability_question", "capability question", "asking what arvis",
                                     "read-only", "read only", "access scope"]),
            ("actionable_advisory", ["actionable_advisory", "actionable advisory", "recommend",
                                     "what should we", "optimi"]),
            ("diagnostic",          ["diagnostic", "root cause", "why is", "trend", "anomaly"]),
            ("lookup",              ["lookup", "simple lookup", "status check", "current value"]),
        ]
        for cls, kws in intent_keywords:
            if any(kw in c for kw in kws):
                return {"class": cls, "confidence": 0.55, "reason": f"prose coercion → {cls}"}
        return {"class": "diagnostic", "confidence": 0.30, "reason": "prose coercion default"}

    return None

class DummyBus:
    def subscribe(self, *args, **kwargs): pass
    def publish(self, *args, **kwargs): pass

class UnifiedLLM(BaseModel):
    """
    Unified LLM Client that wraps the legacy LLMAgent logic 
    but exposes a clean, provider-agnostic interface for the new agent system.
    """
    
    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        global _REASONING_AGENT, _TOOL_AGENT, _FALLBACK_TOOL_AGENT

        _bedrock_active = _bedrock_enabled()
        if _bedrock_active:
            logger.info("[UnifiedLLM] Bedrock active — skipping legacy provider init (K2Think/Groq).")
            return

        # Initialize Reasoning Agent (K2 Think)
        # Initialize Reasoning Agent (Configurable)
        if _REASONING_AGENT is None:
            # Universal Provider Configuration
            provider = os.getenv("LLM_PROVIDER", "k2think")
            
            # Default models per provider if not specified
            default_models = {
                "k2think": "MBZUAI-IFM/K2-Think-v2",
                "groq": "llama-3.3-70b-versatile",
                "groq": "llama-3.3-70b-versatile",
                "openai": "gpt-4o",
                "anthropic": "claude-3-5-sonnet-20240620",
                "nvidia": "moonshotai/kimi-k2.5"
            }
            model = os.getenv("LLM_MODEL", default_models.get(provider, "gpt-3.5-turbo"))
            
            print(f"[UnifiedLLM] Initializing Reasoning Agent with Provider: {provider}, Model: {model}")
            
            _REASONING_AGENT = LLMAgent(
                event_bus=DummyBus(), 
                state_engine=None, 
                automation_engine=None, 
                subscribe_to_voice=False,
                override_provider=provider,
                override_model=model
            )
            
            # Configure Provider Specifics — build a real OpenAI-compatible client
            # (the vendored LLMAgent stub builds none) so native tool-calling works.
            if provider == "k2think":
                _ensure_openai_client(_REASONING_AGENT, "https://api.k2think.ai/v1",
                                      os.getenv("K2THINK_API_KEY"))
                if _REASONING_AGENT.client:
                    _REASONING_AGENT.client.base_url = "https://api.k2think.ai/v1"
            elif provider == "openai":
                _ensure_openai_client(_REASONING_AGENT, "https://api.openai.com/v1",
                                      os.getenv("OPENAI_API_KEY"))
            elif provider == "groq":
                _ensure_openai_client(_REASONING_AGENT, "https://api.groq.com/openai/v1",
                                      os.getenv("GROQ_API_KEY"))
            elif provider == "nvidia":
                 # Nvidia uses custom adapter _ask_nvidia using httpx
                 _REASONING_AGENT.provider = "nvidia"
                 pass
            
        # Initialize Tool Agent (Configurable, defaults to Groq)
        if _TOOL_AGENT is None:
            tool_provider = os.getenv("TOOL_PROVIDER", "groq")
            tool_model = os.getenv("TOOL_MODEL", "llama-3.3-70b-versatile")
            
            print(f"[UnifiedLLM] Initializing Primary Tool Agent with Provider: {tool_provider}, Model: {tool_model}")
            
            _TOOL_AGENT = LLMAgent(
                event_bus=DummyBus(), 
                state_engine=None, 
                automation_engine=None, 
                subscribe_to_voice=False,
                override_provider=tool_provider,
                override_model=tool_model
            )
            
            # K2Think tool agent — use api.k2think.ai/v1 (verified to serve the tools
            # API; build-api.k2think.ai/v1 returns 404). Build a real client if missing.
            if tool_provider == "k2think":
                _ensure_openai_client(_TOOL_AGENT, "https://api.k2think.ai/v1",
                                      os.getenv("K2THINK_API_KEY"))
                if _TOOL_AGENT.client:
                    _TOOL_AGENT.client.base_url = "https://api.k2think.ai/v1"
                    print(f"[UnifiedLLM] K2 tool endpoint: {_TOOL_AGENT.client.base_url}")
            elif tool_provider == "openai":
                _ensure_openai_client(_TOOL_AGENT, "https://api.openai.com/v1",
                                      os.getenv("OPENAI_API_KEY"))
            elif tool_provider == "groq":
                _ensure_openai_client(_TOOL_AGENT, "https://api.groq.com/openai/v1",
                                      os.getenv("GROQ_API_KEY"))
                
        # Initialize Groq Fallback Layer (Always warm if Groq is not the primary)
        if _FALLBACK_TOOL_AGENT is None:
            if os.getenv("TOOL_PROVIDER", "groq") != "groq":
                print(f"[UnifiedLLM] Initializing Groq Fallback Layer...")
                _FALLBACK_TOOL_AGENT = LLMAgent(
                    event_bus=DummyBus(),
                    state_engine=None,
                    automation_engine=None,
                    subscribe_to_voice=False,
                    override_provider="groq",
                    override_model="llama-3.3-70b-versatile"
                )
            else:
                _FALLBACK_TOOL_AGENT = _TOOL_AGENT

    def _prune_and_budget_context(
        self,
        messages: List[Dict[str, str]],
        system_msgs: Optional[List[Dict[str, str]]],
        channel: str
    ) -> tuple[List[Dict[str, str]], Optional[List[Dict[str, str]]]]:
        """Prune and budget evidence ledger based on channel limits and relevance sorting."""
        LIMITS = {
            "synthesis": 120000,
            "depth_plan": 20000,
            "faithfulness": 60000,
            "claim_verify": 40000,
            "chat": 80000
        }
        if channel not in LIMITS:
            return messages, system_msgs

        token_limit = LIMITS[channel]
        char_limit = int(token_limit * 3.5)

        # Extract queries from messages to build keyword overlap set
        user_queries = [m.get("content", "") for m in messages if m.get("role") == "user"]
        query_text = " ".join(user_queries)
        import re
        query_words = set(re.findall(r"\w+", query_text.lower()))
        eq_ids_in_query = set(re.findall(r"\b(?:CH|AHU|VAV|FCU|CT|CHWP|CDWP|ZONE|FLOOR|METER|PCHWP|SCHWP)-\d+[A-Z]?\b", query_text.upper()))
        ev_ids_in_query = set(re.findall(r"\b[a-fA-F0-9\-]{8,36}\b", query_text))

        def prune_text(text: str) -> str:
            if not text:
                return text
            start_marker = "--- EVIDENCE LEDGER (authoritative, from tool results) ---"
            end_marker = "--- END EVIDENCE LEDGER ---"

            if start_marker not in text or end_marker not in text:
                start_marker = "--- EVIDENCE LEDGER"
                end_marker = "--- END EVIDENCE"
                if start_marker not in text or end_marker not in text:
                    return text

            parts = text.split(start_marker, 1)
            before = parts[0]
            after_parts = parts[1].split(end_marker, 1)
            ledger_content = after_parts[0]
            after = after_parts[1] if len(after_parts) > 1 else ""

            # Parse entries starting with [uuid] or similar alphanumeric id in brackets
            entries = []
            current_entry = []
            for line in ledger_content.splitlines():
                if re.match(r"^\[[a-fA-F0-9\-]{8,36}\]", line.strip()):
                    if current_entry:
                        entries.append("\n".join(current_entry))
                    current_entry = [line]
                else:
                    if current_entry:
                        current_entry.append(line)
            if current_entry:
                entries.append("\n".join(current_entry))

            if not entries:
                return text

            scored_entries = []
            for idx, entry in enumerate(entries):
                entry_lower = entry.lower()
                entry_words = set(re.findall(r"\w+", entry_lower))
                overlap = len(query_words.intersection(entry_words))
                sub_matches = sum(1 for qw in query_words if qw in entry_lower)
                eq_matches = sum(100 for eq in eq_ids_in_query if eq in entry.upper())
                
                # Boost if this specific evidence UUID is explicitly cited in the query/chat
                id_match = re.match(r"^\[([a-fA-F0-9\-]{8,36})\]", entry.strip())
                citation_boost = 0
                if id_match:
                    eid = id_match.group(1)
                    if eid in ev_ids_in_query:
                        citation_boost = 50000
                
                # Recency boost (drop oldest first if score ties, newer = higher index)
                recency_boost = (idx / max(1, len(entries))) * 10.0
                
                score = float(overlap + 5 * sub_matches + eq_matches + citation_boost + recency_boost)
                scored_entries.append((score, entry))

            scored_entries.sort(key=lambda x: x[0], reverse=True)

            non_evidence_len = len(before) + len(after) + len(start_marker) + len(end_marker) + 100
            remaining_char_budget = char_limit - non_evidence_len

            packed_entries = []
            current_len = 0
            for score, entry in scored_entries:
                entry_len = len(entry) + 1
                if current_len + entry_len > remaining_char_budget:
                    break
                packed_entries.append(entry)
                current_len += entry_len

            new_ledger = "\n" + "\n".join(packed_entries) + "\n"
            return f"{before}{start_marker}{new_ledger}{end_marker}{after}"

        new_messages = []
        for m in messages:
            new_m = m.copy()
            if m.get("content"):
                new_m["content"] = prune_text(m["content"])
            new_messages.append(new_m)

        new_system_msgs = None
        if system_msgs:
            new_system_msgs = []
            for m in system_msgs:
                new_m = m.copy()
                if m.get("content"):
                    new_m["content"] = prune_text(m["content"])
                new_system_msgs.append(new_m)

        return new_messages, new_system_msgs

    @classmethod
    def quarantine_values(cls, session_key: str, values: List[str]):
        quarantine_values(session_key, values)

    async def ask(
        self,
        messages: List[Dict[str, str]],
        system_msgs: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        override_model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        stream_as: str = "message",
        channel: str = "chat"
    ) -> Message:
        # P1 Task 6: cross-turn hallucination quarantine
        session_key = get_session_key(messages)
        quarantined = _QUARANTINE_BLOCKLIST.get(session_key) if session_key else None
        if quarantined:
            q_list = ", ".join(f"'{q}'" for q in quarantined)
            q_instruction = f"\n\nCRITICAL SYSTEM BLOCKLIST: Do NOT mention any of the following values/IDs: {q_list}."
            if system_msgs:
                system_msgs = [m.copy() for m in system_msgs]
                system_msgs[-1]["content"] += q_instruction
            else:
                system_msgs = [{"role": "system", "content": q_instruction.strip()}]

        # Budget and prune context before send
        messages, system_msgs = self._prune_and_budget_context(messages, system_msgs, channel)
        """
        Send a request. If a Bedrock model is mapped for this channel, route to Bedrock.
        Otherwise fall through to the legacy REASONING_AGENT.
        """
        full_system_prompt = ""
        if system_msgs:
            full_system_prompt = "\n".join([m["content"] for m in system_msgs])

        bedrock_model = BEDROCK_MODEL_MAP.get(channel)
        if bedrock_model and _bedrock_enabled():
            # Fix 14a: honour explicit override_model when caller requests a specific model.
            _effective_model = override_model or bedrock_model
            response = await self._ask_bedrock(
                model_id=_effective_model,
                system_prompt=full_system_prompt,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                channel=channel,
            )
        else:
            if _REASONING_AGENT is None:
                raise RuntimeError(f"[UnifiedLLM] No Bedrock model for channel '{channel}' and no legacy Reasoning Agent initialised. Check BEDROCK_MODEL_MAP or set LLM_PROVIDER.")
            response = await self._ask_provider(_REASONING_AGENT, full_system_prompt, messages, tools, tool_choice, override_model, max_tokens=max_tokens, stream_as=stream_as, channel=channel)
            if response.content and "LLM Error" in response.content:
                raise RuntimeError(response.content)

        # Post-process response to replace quarantined values
        if response and response.content and quarantined:
            for q in quarantined:
                escaped_q = re.escape(q)
                pattern = rf"\b{escaped_q}\b"
                try:
                    response.content = re.sub(pattern, "[unverified]", response.content)
                except Exception:
                    response.content = response.content.replace(q, "[unverified]")

        # P3 Task 11: Looping response detector
        if response and response.content and session_key:
            last_resp = _RESPONSE_HISTORY.get(session_key)
            norm_content = " ".join(response.content.strip().lower().split())
            norm_last = " ".join(last_resp.strip().lower().split()) if last_resp else ""
            
            if norm_content and norm_content == norm_last:
                logger.warning(f"[LoopDetector] Detected duplicate response in session {session_key}: {response.content[:80]}...")
                loop_correction = {
                    "role": "user",
                    "content": "CORRECTION: Your previous response was a duplicate. Provide a different reasoning path and a highly specific analysis."
                }
                # Create a fresh copy to modify to avoid mutating original list
                reg_messages = list(messages) + [loop_correction]
                
                if bedrock_model and _bedrock_enabled():
                    _effective_model = override_model or bedrock_model
                    response = await self._ask_bedrock(
                        model_id=_effective_model,
                        system_prompt=full_system_prompt,
                        messages=reg_messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        max_tokens=max_tokens,
                        channel=channel,
                    )
                else:
                    response = await self._ask_provider(_REASONING_AGENT, full_system_prompt, reg_messages, tools, tool_choice, override_model, max_tokens=max_tokens, stream_as=stream_as, channel=channel)
                    if response.content and "LLM Error" in response.content:
                        raise RuntimeError(response.content)

                if response and response.content and quarantined:
                    for q in quarantined:
                        escaped_q = re.escape(q)
                        pattern = rf"\b{escaped_q}\b"
                        try:
                            response.content = re.sub(pattern, "[unverified]", response.content)
                        except Exception:
                            response.content = response.content.replace(q, "[unverified]")

            if response and response.content:
                _RESPONSE_HISTORY[session_key] = response.content
        return response

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> Message:
        """Alias for ask() to maintain compatibility with other interfaces."""
        return await self.ask(messages, **kwargs)

    async def ask_tool(self, messages, system_msgs, tools, tool_choice, stream_as="think", channel="chat") -> Message:
        """
        Send a tool-calling request. Routes to Bedrock if configured, else Groq fallback.
        """
        full_system_prompt = ""
        if system_msgs:
            full_system_prompt = "\n".join([m["content"] for m in system_msgs])

        # Bedrock-first: tool channels always prefer Bedrock if AWS creds present
        tool_channel = channel if channel in BEDROCK_MODEL_MAP else "tool"
        bedrock_model = BEDROCK_MODEL_MAP.get(tool_channel)
        if bedrock_model and _bedrock_enabled():
            try:
                return await self._ask_bedrock(
                    model_id=bedrock_model,
                    system_prompt=full_system_prompt,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    channel=channel,
                )
            except Exception as e:
                logger.warning(f"[UnifiedLLM] Bedrock tool call failed ({bedrock_model}): {e}. Falling back to legacy agent.")

        # Legacy fallback — only if agents were initialised (non-Bedrock mode)
        if _TOOL_AGENT is None:
            raise RuntimeError("[UnifiedLLM] No Bedrock model for this channel and no legacy Tool Agent initialised. Check BEDROCK_MODEL_MAP or set TOOL_PROVIDER.")
        try:
            return await self._ask_provider(_TOOL_AGENT, full_system_prompt, messages, tools, tool_choice, stream_as=stream_as, channel=channel)
        except Exception as e:
            if _FALLBACK_TOOL_AGENT and _FALLBACK_TOOL_AGENT != _TOOL_AGENT:
                logger.warning(f"[UnifiedLLM] Primary Tool Agent failed: {e}. Retrying with Groq Fallback...")
                try:
                    return await self._ask_provider(_FALLBACK_TOOL_AGENT, full_system_prompt, messages, tools, tool_choice, stream_as=stream_as)
                except Exception as fallback_err:
                    logger.error(f"[UnifiedLLM] Both Primary and Fallback Tool Agents failed: {fallback_err}")
                    raise fallback_err
            else:
                logger.error(f"[UnifiedLLM] Primary Tool Agent failed and no separate fallback available: {e}")
                raise e

    async def ask_streaming(self, messages: List[Dict], system_msgs: Optional[List[Dict]] = None):
        """Streaming generator (Phase 6 support)"""
        # Placeholder for streaming implementation
        # For now, just non-streaming fallback yielded
        response = await self.ask(messages, system_msgs, channel="chat")
        if response.content:
            yield response.content

    async def ask_json(
        self,
        messages: List[Dict[str, str]],
        retries: int = 2,
        system_msgs: Optional[List[Dict[str, str]]] = None,
        stream_as: str = "think",
        channel: str = "chat"
    ) -> Dict[str, Any]:
        """
        Ask LLM and enforce JSON output.

        Strategy:
        1. For providers supporting native JSON mode (Groq, OpenAI), use response_format
        2. Fast-path parse: try json.loads on stripped content
        3. Fallback: extract JSON from markdown/tags
        4. Self-repair loop on failure
        """
        attempts = 0
        current_messages = list(messages)
        # Fix 14b: track whether we've already switched to fallback model after
        # the first parse failure. Avoids three retries on the same model that
        # already produced unparseable output.
        _fallback_override: Optional[str] = None

        while attempts <= retries:
            try:
                response = await self.ask(
                    current_messages,
                    system_msgs=system_msgs,
                    stream_as=stream_as,
                    channel=channel,
                    override_model=_fallback_override,
                )
                content = response.content or "{}"

                # Throttle guard: Bedrock returns error string, not JSON
                if content.startswith("Bedrock Error") and ("ThrottlingException" in content or "Too Many Requests" in content):
                    wait_s = 30 * (attempts + 1)
                    logger.warning(f"[UnifiedLLM] Throttled on ask_json (attempt {attempts+1}) — sleeping {wait_s}s")
                    await asyncio.sleep(wait_s)
                    attempts += 1
                    continue

                # Fast path: direct parse
                stripped = content.strip()
                if stripped.startswith(("{", "[")):
                    try:
                        return json.loads(stripped)
                    except json.JSONDecodeError:
                        pass

                # Strip thinking tags
                content = re.sub(r"<(?:think|thinking)>.*?</(?:think|thinking)>", "", content, flags=re.DOTALL)
                content = re.sub(r"</?[a-zA-Z_]+>", "", content)

                # Extract from markdown code fences
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    for block in content.split("```"):
                        block = block.strip()
                        if block.startswith(("{", "[")):
                            content = block
                            break

                content = content.strip()
                if not content:
                    raise json.JSONDecodeError("Empty content", "", 0)

                # Try direct parse after cleanup
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    pass

                # Greedy extraction: find the largest JSON object/array
                obj_match = re.search(r"(\{.*\})", content, re.DOTALL)
                if obj_match:
                    try:
                        return json.loads(obj_match.group(1))
                    except json.JSONDecodeError:
                        pass

                arr_match = re.search(r"(\[.*\])", content, re.DOTALL)
                if arr_match:
                    try:
                        return json.loads(arr_match.group(1))
                    except json.JSONDecodeError:
                        pass

                # Channel-specific prose coercion — last resort before retry
                # Nova Lite/Micro may respond with prose instead of {"tier":2}
                _coerced = _coerce_prose_to_json(channel, response.content or "")
                if _coerced is not None:
                    logger.info(f"[UnifiedLLM] Prose coercion succeeded for channel='{channel}'")
                    return _coerced

                raise json.JSONDecodeError("No valid JSON found", content[:100], 0)

            except json.JSONDecodeError as e:
                attempts += 1
                raw_preview = (response.content or "")[:200] if 'response' in locals() else ""
                logger.warning(f"[UnifiedLLM] JSON parse failed (attempt {attempts}/{retries+1}): {e} | raw='{raw_preview}'")

                # Fix 14b: on first parse failure, switch to mapped fallback model
                # rather than re-prompting the primary model up to `retries` times.
                if _fallback_override is None:
                    _primary_model = BEDROCK_MODEL_MAP.get(channel)
                    if _primary_model:
                        _fb = BEDROCK_FALLBACK_MAP.get(_primary_model)
                        if _fb and _fb != _primary_model:
                            _fallback_override = _fb
                            logger.info(
                                f"[UnifiedLLM] ask_json: switching to fallback model "
                                f"'{_fb}' after first parse failure on channel='{channel}'"
                            )

                if attempts <= retries:
                    repair_prompt = "Your previous response was not valid JSON. Return ONLY the valid JSON object. No markdown, no explanation."
                    if len(current_messages) > 10:
                        current_messages = current_messages[:2] + current_messages[-4:]
                    current_messages.append({"role": "assistant", "content": response.content})
                    current_messages.append({"role": "user", "content": repair_prompt})

        raise ValueError(f"Failed to get valid JSON after {retries} retries. Last content: {content[:100]!r}")

    # ═══════════════════════════════════════════════════════════
    # ADAPTERS
    # ═══════════════════════════════════════════════════════════

    async def _ask_bedrock(
        self,
        model_id: str,
        system_prompt: str,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        channel: str = "chat",
    ) -> Message:
        """
        AWS Bedrock Converse API adapter.
        Auth priority: BEDROCK_API_KEY (httpx) → boto3 (AWS_ACCESS_KEY_ID / AWS_PROFILE).
        Supports all Bedrock models: Claude, Nova, Kimi, MiniMax, GLM, etc.
        """
        import asyncio

        region = os.getenv("AWS_BEDROCK_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        logger.info(f"[Bedrock] channel='{channel}' model='{model_id}' region='{region}'")

        # ── Build shared Converse payload ─────────────────────────────────────
        def _build_payload() -> Dict[str, Any]:
            converse_msgs = []
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    continue
                if role == "tool":
                    converse_msgs.append({
                        "role": "user",
                        "content": [{
                            "toolResult": {
                                "toolUseId": m.get("tool_call_id", "unknown"),
                                "content": [{"text": str(content)}],
                            }
                        }]
                    })
                elif role == "assistant":
                    tool_calls = m.get("tool_calls") or []
                    content_blocks = []
                    if content:
                        content_blocks.append({"text": content})
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            try:
                                inp = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else (tc["function"]["arguments"] or {})
                            except Exception:
                                inp = {}
                            content_blocks.append({
                                "toolUse": {
                                    "toolUseId": tc.get("id", "call_unknown"),
                                    "name": tc["function"]["name"],
                                    "input": inp,
                                }
                            })
                    if content_blocks:
                        converse_msgs.append({"role": "assistant", "content": content_blocks})
                else:
                    if content:
                        converse_msgs.append({"role": role, "content": [{"text": str(content)}]})

            if converse_msgs and converse_msgs[0]["role"] != "user":
                converse_msgs.insert(0, {"role": "user", "content": [{"text": "Begin."}]})

            # Bedrock requires strict user/assistant alternation — merge consecutive same-role turns
            merged: list = []
            for msg in converse_msgs:
                if merged and merged[-1]["role"] == msg["role"]:
                    merged[-1]["content"].extend(msg["content"])
                else:
                    merged.append({"role": msg["role"], "content": list(msg["content"])})
            converse_msgs = merged

            # Collect all toolResult IDs present in user turns
            result_ids: set = set()
            for msg in converse_msgs:
                if msg["role"] == "user":
                    for blk in msg.get("content", []):
                        tr = blk.get("toolResult")
                        if tr:
                            result_ids.add(tr.get("toolUseId", ""))

            # Strip orphaned toolUse blocks from assistant turns (no matching toolResult).
            # Bedrock rejects a conversation where toolUse has no paired toolResult.
            for msg in converse_msgs:
                if msg["role"] == "assistant":
                    cleaned = []
                    for blk in msg["content"]:
                        tu = blk.get("toolUse")
                        if tu and tu.get("toolUseId") not in result_ids:
                            continue  # orphaned — drop it
                        cleaned.append(blk)
                    msg["content"] = cleaned if cleaned else [{"text": "[tool call omitted]"}]

            # Drop any message that ended up with empty content (keeps alternation valid)
            converse_msgs = [m for m in converse_msgs if m.get("content")]

            payload: Dict[str, Any] = {"modelId": model_id, "messages": converse_msgs}
            if system_prompt:
                payload["system"] = [{"text": system_prompt}]
            if max_tokens:
                payload["inferenceConfig"] = {"maxTokens": max_tokens}
            if tools:
                tool_specs = []
                for t in tools:
                    fn = t.get("function", t)
                    params = fn.get("parameters", {"type": "object", "properties": {}})
                    tool_specs.append({
                        "toolSpec": {
                            "name": fn.get("name", "unknown"),
                            "description": fn.get("description", ""),
                            "inputSchema": {"json": params},
                        }
                    })
                payload["toolConfig"] = {
                    "tools": tool_specs,
                    "toolChoice": {"any": {}} if tool_choice == "required" else {"auto": {}},
                }
            return payload

        payload = _build_payload()

        # ── Auth path 1: BEDROCK_API_KEY via httpx ────────────────────────────
        # Only Anthropic models accept x-api-key auth on the Bedrock endpoint.
        # Cross-region inference IDs (us./eu./ap. prefix) also require boto3.
        # All other providers (Nova, Kimi, Minimax, GLM, etc.) must use boto3 IAM.
        api_key = os.getenv("BEDROCK_API_KEY")
        _is_cross_region = model_id.startswith(("us.", "eu.", "ap."))
        _is_anthropic = "anthropic" in model_id
        if api_key and not _is_cross_region and _is_anthropic:
            import httpx
            url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_id}/converse"
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code != 200:
                        logger.warning(f"[Bedrock] API key auth failed ({resp.status_code}): {resp.text[:200]}. Falling back to boto3.")
                    else:
                        response = resp.json()
                        return self._parse_bedrock_response(response, model_id, channel)
            except Exception as e:
                logger.warning(f"[Bedrock] httpx call failed: {e}. Falling back to boto3.")

        # ── Auth path 2: boto3 (IAM / profile) ───────────────────────────────
        try:
            import boto3
        except ImportError:
            return Message.assistant_message(
                "Error: Neither BEDROCK_API_KEY nor boto3 available. "
                "Set BEDROCK_API_KEY or run: pip install boto3"
            )

        def _call_boto3():
            from botocore.config import Config
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(
                    read_timeout=180,
                    connect_timeout=10,
                    retries={"max_attempts": 6, "mode": "adaptive"},
                ),
            )
            return client.converse(**payload)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_call_boto3),
                timeout=60.0
            )
        except Exception as e:
            error_str = str(e)
            # Adaptive mode handles most throttling; this catches residual bursts
            if "ThrottlingException" in error_str or "Too Many Requests" in error_str:
                for backoff_s in [10, 30, 60]:
                    logger.warning(f"[Bedrock] ThrottlingException — retrying in {backoff_s}s ({model_id})")
                    await asyncio.sleep(backoff_s)
                    try:
                        response = await asyncio.wait_for(
                            asyncio.to_thread(_call_boto3),
                            timeout=60.0
                        )
                        return self._parse_bedrock_response(response, model_id, channel)
                    except Exception as retry_e:
                        if "ThrottlingException" not in str(retry_e) and "Too Many Requests" not in str(retry_e):
                            break
                        error_str = str(retry_e)
                logger.error(f"[Bedrock] Still throttled after 3 backoff retries ({model_id})")

            # Fallback: try alternate model before giving up
            fallback_model = BEDROCK_FALLBACK_MAP.get(model_id)
            if fallback_model and fallback_model != model_id:
                logger.warning(f"[Bedrock] Primary {model_id} failed. Trying fallback: {fallback_model}")
                try:
                    payload["modelId"] = fallback_model
                    def _call_fallback():
                        from botocore.config import Config
                        client = boto3.client(
                            "bedrock-runtime",
                            region_name=region,
                            config=Config(read_timeout=180, connect_timeout=10, retries={"max_attempts": 2, "mode": "adaptive"}),
                        )
                        return client.converse(**payload)
                    response = await asyncio.wait_for(
                        asyncio.to_thread(_call_fallback),
                        timeout=45.0
                    )
                    return self._parse_bedrock_response(response, fallback_model, channel)
                except Exception as fb_e:
                    logger.error(f"[Bedrock] Fallback {fallback_model} also failed: {fb_e}")

            return Message.assistant_message(f"Bedrock Error ({model_id}): {error_str}")

        return self._parse_bedrock_response(response, model_id, channel)

    def _parse_bedrock_response(self, response: Dict[str, Any], model_id: str, channel: str) -> Message:
        """Parse Bedrock Converse API response into a Message."""
        output = response.get("output", {}).get("message", {})
        content_blocks = output.get("content", [])

        text_parts = []
        reasoning_parts = []
        tool_calls_out = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                from agent_unified.schema import ToolCall, Function
                tu = block["toolUse"]
                tool_calls_out.append(ToolCall(
                    id=tu.get("toolUseId", "call_unknown"),
                    function=Function(
                        name=tu["name"],
                        arguments=json.dumps(tu.get("input", {})),
                    )
                ))
            elif "reasoningContent" in block:
                # Kimi K2 Thinking / MiniMax extended thinking trace
                rt = block["reasoningContent"].get("reasoningText", {}).get("text", "")
                if rt:
                    reasoning_parts.append(rt)

        # Models like Kimi K2 Thinking may return ONLY reasoningContent with no text block
        if not text_parts and reasoning_parts:
            text_parts = reasoning_parts
            reasoning_parts = []

        text = "\n".join(text_parts) if text_parts else ""
        if text:
            _, text = _robust_extract(text)

        try:
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            import asyncio as _aio
            loop = _aio.get_event_loop()
            if loop.is_running() and text:
                broadcaster = SSEBroadcaster()
                loop.create_task(broadcaster.broadcast("message", {"content": text}, channel=channel))
        except Exception:
            pass

        # Extract token usage and compute cost
        from agent_unified.schema import UsageInfo
        from datetime import datetime as _dt
        usage_data = response.get("usage", {})
        input_tokens = usage_data.get("inputTokens", 0)
        output_tokens = usage_data.get("outputTokens", 0)
        cost_usd = _compute_bedrock_cost(model_id, input_tokens, output_tokens)

        usage_info = UsageInfo(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_id=model_id,
            cost_usd=cost_usd,
        )

        _LLM_USAGE_LOG.append({
            "model_id": model_id,
            "channel": channel,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "timestamp": _dt.utcnow().isoformat(),
        })

        return Message.assistant_message(
            content=text,
            tool_calls=tool_calls_out if tool_calls_out else None,
            usage=usage_info,
        )

    async def _ask_provider(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=None, stream_as="message", channel="chat"):
        # Dispatch to appropriate adapter based on agent configuration
        if agent.provider == "gemini":
            return await self._ask_gemini(agent, system_prompt, messages, tools, channel=channel)
        elif agent.provider == "nvidia":
            return await self._ask_nvidia(agent, system_prompt, messages, tools, tool_choice, override_model, max_tokens, stream_as=stream_as, channel=channel)
        elif agent.client:
            return await self._ask_openai_compat(agent, system_prompt, messages, tools, tool_choice, override_model, max_tokens=max_tokens, stream_as=stream_as, channel=channel)
        return Message.assistant_message(f"Error: Provider {agent.provider} not supported in hybrid adapter")

    async def _ask_openai_compat(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=None, stream_as="message", channel="chat"):
        import asyncio
        
        # Build full message list
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        
        for m in messages:
            # Ensure role is valid
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "tool":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id"),
                    "content": content
                })
            elif role == "assistant":
                msg = {"role": "assistant"}
                # API requires content field even if empty when there are tool calls
                msg["content"] = content or ""
                if m.get("tool_calls"):
                # Convert our internal tool calls back to API format
                # Handle both ToolCall objects and dicts (from model_dump)
                    api_tool_calls = []
                    for tc in m["tool_calls"]:
                        if isinstance(tc, dict):
                            api_tool_calls.append({
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                }
                            })
                        else:
                            api_tool_calls.append({
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments
                                }
                            })
                    msg["tool_calls"] = api_tool_calls
                api_messages.append(msg)
            else:
                api_messages.append({"role": role, "content": content})

        # Determine model
        model = "gpt-3.5-turbo"
        if agent.provider == "groq":
             model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        elif agent.provider == "openai":
             model = getattr(agent, "openai_model", "gpt-4o-mini")
        elif agent.provider == "synthetic":
             model = getattr(agent, "synthetic_model", "hf:meta-llama/Llama-3.3-70B-Instruct")
        elif agent.provider == "k2think":
             model = getattr(agent, "k2think_model", "MBZUAI-IFM/K2-Think-v2")
             # K2-Think specific headers/configs could be added here if needed
             # The client base_url is already set in __init__
        elif agent.provider == "openrouter":
             model = getattr(agent, "openrouter_model", "meta-llama/llama-3.3-70b-instruct")
        
        # Apply override if provided (e.g. Jais for Arabic)
        if override_model:
            model = override_model
             
        # Call API (async wrapper for sync client)
        def _call():
            kwargs = {
                "model": model,
                "messages": api_messages,
            }
            if tools:
                import copy
                clean_tools = []
                for t in tools:
                    t_clean = copy.deepcopy(t)
                    # Strict OpenAI schema formatting and parsing
                    if "name" in t_clean and "function" not in t_clean:
                        fn = {"name": t_clean.pop("name")}
                        if "description" in t_clean: fn["description"] = t_clean.pop("description")
                        if "parameters" in t_clean: fn["parameters"] = t_clean.pop("parameters")
                        clean_tools.append({"type": "function", "function": fn})
                    elif "function" in t_clean:
                        for bad_key in ["response_schema", "requires_confirmation"]:
                            if bad_key in t_clean.get("function", {}):
                                del t_clean["function"][bad_key]
                            if bad_key in t_clean:
                                del t_clean[bad_key]
                        clean_tools.append(t_clean)
                kwargs["tools"] = clean_tools
                kwargs["tool_choice"] = tool_choice
            
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
                
            return agent.client.chat.completions.create(**kwargs)
        
        # Exponential backoff for API limits (500 "Server is busy")
        import time 
        import asyncio
        max_limit_retries = 5
        base_delay = 5.0
        
        try:
            for attempt in range(max_limit_retries):
                try:
                    response = await asyncio.to_thread(_call)
                    break
                except Exception as e:
                    error_str = str(e)
                    if "500" in error_str or "Server is busy" in error_str or "rate_limit" in error_str.lower() or "429" in error_str:
                        if attempt < max_limit_retries - 1:
                            delay = base_delay * (2 ** attempt)
                            logger.warning(f"[LLM] API overloaded/rate-limited. Retrying in {delay}s... (Attempt {attempt+1}/{max_limit_retries})")
                            await asyncio.sleep(delay)
                            continue
                    raise e # Re-raise if retries exhausted or different error

            choice = response.choices[0]
            message = choice.message
            
            tool_calls = []
            if getattr(message, "tool_calls", None):
                from agent_unified.schema import ToolCall, Function
                for tc in message.tool_calls:
                    _args = tc.function.arguments
                    # K2Think double-encodes tool arguments (a JSON string wrapping the
                    # JSON object) — unwrap one layer so downstream json.loads works.
                    try:
                        _decoded = json.loads(_args)
                        if isinstance(_decoded, str):
                            _args = _decoded
                    except Exception:
                        pass
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        function=Function(name=tc.function.name, arguments=_args)
                    ))
            
            content = message.content
            
            # Universal Parsing: extract <think>...<answer> using centralized parser
            if content:
                import re
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    broadcaster = SSEBroadcaster()
                    import asyncio
                    loop = asyncio.get_event_loop()
                    is_running = loop.is_running()
                except ImportError:
                    is_running = False
                    
                # Advanced Multi-Tag Processing for Glass Box
                thoughts, clean_content = _robust_extract(content)
                
                def redact(text):
                    import re
                    patterns = [
                        r"(?i)(you are|act as) an? (expert|ai|assistant|agent|system).+?(?=\n\n|\Z)",
                        r"(?i)(here are your|available|these are the) tools:?[\s\S]*?(?=\n\n(?:I will|Let's|Thinking)|$)",
                        r"(?i)your (goal|task) is to.+?(?=\n\n|\Z)",
                        r"(?i)(guidelines|constraints|rules):[\s\S]*?(?=\n\n|$)",
                        r"(?i)use the following tools?:[\s\S]*?(?=\n\n|$)"
                    ]
                    redacted = text
                    for p in patterns:
                        redacted = re.sub(p, "\n[SYSTEM RULE REDACTED]\n", redacted)
                    return re.sub(r'\n{3,}', '\n\n', redacted).strip()

                if is_running:
                    # 1. Broadcast all extracted thoughts/reasoning tags
                    for t in thoughts:
                        try:
                            safe_thought = redact(t)
                            if safe_thought:
                                loop.create_task(broadcaster.broadcast("think", {"content": safe_thought}, channel=channel))
                        except Exception as e:
                            logger.debug(f"Failed to broadcast thought part: {e}")
                
                content = clean_content
                
                # Broadcast the actual response
                if content and is_running:
                    try:
                         # Apply IP redaction to internal thoughts too
                         if stream_as == "think":
                             content = redact(content)
                         loop.create_task(broadcaster.broadcast(stream_as, {"content": content}, channel=channel))
                    except Exception as e:
                        logger.debug(f"Failed to broadcast {stream_as}: {e}")
            
            return Message.assistant_message(content=content, tool_calls=tool_calls if tool_calls else None)
            
        except Exception as e:
            error_str = str(e)
            
            # ═══ GROQ tool_use_failed RECOVERY ═══
            # Groq sometimes generates tool calls in XML format:
            #   <function=search_knowledge_base {"query": "...", "top_k": 5}</function>
            # instead of proper JSON. The API rejects this but gives us
            # the failed_generation. We parse it and recover.
            if "tool_use_failed" in error_str and "failed_generation" in error_str:
                import re, json, uuid
                logger.debug(f"[LLM] Groq tool_use_failed raw: {error_str[:300]}")
                
                # Extract the failed_generation content
                # Pattern: <function=tool_name[=, >, ]({json_args})</function>
                pattern = r'<function=(\w+)[=,\s>}]*\(?((?:\{.*?\}|\[.*?\]|".*?"))\)?\s*</function>'
                matches = re.findall(pattern, error_str, re.DOTALL)
                
                if matches:
                    from agent_unified.schema import ToolCall, Function
                    recovered_calls = []
                    for func_name, args_str in matches:
                        try:
                            # If it's a quoted string, unquote it first
                            if args_str.startswith('"') and args_str.endswith('"'):
                                try:
                                    args_str = json.loads(args_str)
                                except:
                                    pass

                            if isinstance(args_str, str):
                                json.loads(args_str)  # Validate
                            else:
                                args_str = json.dumps(args_str)

                            call_id = f"call_{uuid.uuid4().hex[:8]}"
                            recovered_calls.append(ToolCall(
                                id=call_id,
                                function=Function(name=func_name, arguments=args_str)
                            ))
                        except json.JSONDecodeError:
                            logger.warning(f"[LLM] Could not parse args for {func_name}: {args_str}")
                    
                    if recovered_calls:
                        names = ", ".join(c.function.name for c in recovered_calls)
                        print(f"[LLM] ✅ Recovered {len(recovered_calls)} tool call(s): {names}")
                        return Message.assistant_message(
                            content="",
                            tool_calls=recovered_calls
                        )
                
                # ── Recovery failed → Retry WITHOUT tools (natural language fallback) ──
                print(f"[LLM] ⚠️ Tool call recovery failed, retrying without tools...")
                try:
                    def _retry_no_tools():
                        retry_kwargs = {
                            "model": model,
                            "messages": api_messages,
                        }
                        if max_tokens:
                            retry_kwargs["max_tokens"] = max_tokens
                        return agent.client.chat.completions.create(**retry_kwargs)
                    
                    retry_response = await asyncio.to_thread(_retry_no_tools)
                    retry_content = retry_response.choices[0].message.content or ""
                    print(f"[LLM] ✅ No-tools retry succeeded ({len(retry_content)} chars)")
                    return Message.assistant_message(content=retry_content)
                except Exception as retry_err:
                    logger.warning(f"[LLM] No-tools retry also failed: {retry_err}")
                
                # Final fallback: return a system note so the agent doesn't crash
                return Message.assistant_message(
                    content=(
                        "SYSTEM NOTE: The previous tool call failed and could not be parsed. "
                        "Do NOT try the same call again. "
                        "You must now Answer based ONLY on the snippets you already have. "
                        "If you have no info, ask the user for clarification. "
                        "DO NOT make up facts."
                    )
                )
            
            return Message.assistant_message(f"LLM Error: {error_str}")

    async def _ask_nvidia(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=16384, stream_as="message", channel="chat"):
        """
        Adapter for NVIDIA NIM/Moonshot API
        """
        import httpx
        
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
             return Message.assistant_message("Error: NVIDIA_API_KEY not found in environment")
             
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Build messages
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            api_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            
        payload = {
            "model": override_model or os.getenv("NVIDIA_MODEL", "moonshotai/kimi-k2.5"),
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "top_p": 1.0,
            "stream": False
        }
        
        # Thinking Mode (Model Specific)
        thinking_mode = os.getenv("NVIDIA_THINKING", "false").lower() == "true"
        model_name = payload["model"].lower()
        
        # -------------------------------------------------------------
        # HYBRID ADAPTER LOGIC (The "Bridge")
        # -------------------------------------------------------------
        # If tools are requested, and we know NVIDIA fails with them,
        # we automatically bridge this request to the TOOL_AGENT (Groq).
        # EXCEPTION: Nemotron supports native tools, so we bypass the bridge for it.
        if tools and "nemotron" not in model_name:
            print(f"[UnifiedLLM] ⚠️ NVIDIA Native Tool Call requested (Model: {model_name}). Bridging to Tool Agent (Groq) via Hybrid Adapter...")
            # We must ensure we don't infinitely recurse if tool agent is also nvidia (misconfiguration)
            if _TOOL_AGENT and _TOOL_AGENT.provider != "nvidia":
                 return await self._ask_provider(_TOOL_AGENT, system_prompt, messages, tools, tool_choice, channel=channel)
            else:
                 print(f"[UnifiedLLM] ❌ Cannot bridge: Tool Agent is missing or also NVIDIA. Attempting native (likely to fail).")

        if "moonshotai" in model_name:
             # Moonshot / Kimi style
             payload["chat_template_kwargs"] = {"thinking": thinking_mode}
        elif "z-ai" in model_name or "glm" in model_name:
             # GLM style
             payload["chat_template_kwargs"] = {
                 "enable_thinking": thinking_mode,
                 "clear_thinking": False
             }
        elif "nemotron" in model_name:
             # Nemotron style (no special kwargs needed usually, just system prompt /think)
             pass 
        elif thinking_mode:
             # Default fallback if user requested thinking but we don't know the keys
             # Some models might ignore this or error out.
             # payload["chat_template_kwargs"] = {"thinking": True} # Commented out to be safe
             pass
        
        # NVIDIA Native Tool Support (Only if we didn't bridge above)
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        async with httpx.AsyncClient() as client:
            try:
                # DEBUG: Print payload to verify tool schema
                import json
                print(f"DEBUG PAYLOAD: {json.dumps(payload, default=str)}") 
                
                response = await client.post(url, headers=headers, json=payload, timeout=120.0)
                if response.status_code != 200:
                    print(f"❌ NVIDIA API Error: Status {response.status_code}\nBody: {response.text}")
                response.raise_for_status()
                data = response.json()
                
                message_data = data["choices"][0]["message"]
                content = message_data.get("content")
                tool_calls_data = message_data.get("tool_calls")
                
                # Apply K2/reasoning model tag stripping
                if content:
                    content = _extract_k2_answer(content)
                
                msg = Message(role="assistant", content=content)
                if tool_calls_data:
                    from .schema import ToolCall, Function
                    msg.tool_calls = []
                    for tc in tool_calls_data:
                        msg.tool_calls.append(ToolCall(
                            id=tc.get("id", "call_unknown"),
                            type=tc.get("type", "function"),
                            function=Function(
                                name=tc["function"]["name"],
                                arguments=tc["function"]["arguments"]
                            )
                        ))
                return msg
            except Exception as e:
                import traceback
                traceback.print_exc()
                return Message.assistant_message(f"NVIDIA API Error: {str(e)}")

    async def _ask_gemini(self, agent, system_prompt, messages, tools, channel="chat"):
        # Gemini adapter implementation ...
        # For brevity in this turn, assuming OpenAI compatible preference logic which handles Groq/OpenAI/Synthetic
        # If Gemini needed, we'd enable this.
        return Message.assistant_message("Gemini adapter not fully implemented in UnifiedLLM yet")
