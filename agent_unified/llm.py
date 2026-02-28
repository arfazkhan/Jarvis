from typing import List, Optional, Dict, Any, Union
import json
import os
import logging

logger = logging.getLogger("arvis.unified.llm")

from pydantic import BaseModel, Field, PrivateAttr

# Import legacy LLMAgent logic to reuse provider connections
from agent_home.llm_agent.llm_agent import LLMAgent
from agent_unified.schema import Message, ToolCall

# Global singletons for hybrid architecture
_REASONING_AGENT = None  # K2 Think
_TOOL_AGENT = None       # Groq

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
        global _REASONING_AGENT, _TOOL_AGENT
        
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
                automations=None, 
                subscribe_to_voice=False,
                override_provider=provider,
                override_model=model
            )
            
            # Configure Provider Specifics
            if provider == "k2think" and _REASONING_AGENT.client:
                _REASONING_AGENT.client.base_url = "https://api.k2think.ai/v2"
                k2_key = os.getenv("K2THINK_API_KEY")
                if k2_key:
                    _REASONING_AGENT.client.api_key = k2_key
            elif provider == "groq" and _REASONING_AGENT.client:
                 # Groq client usually configured by LLMAgent via GROQ_API_KEY env var
                 pass
            elif provider == "nvidia":
                 # Nvidia uses custom adapter _ask_nvidia using httpx
                 _REASONING_AGENT.provider = "nvidia"
                 pass
            
        # Initialize Tool Agent (Configurable, defaults to Groq)
        if _TOOL_AGENT is None:
            tool_provider = os.getenv("TOOL_PROVIDER", "groq")
            tool_model = os.getenv("TOOL_MODEL", "llama-3.3-70b-versatile")
            
            print(f"[UnifiedLLM] Initializing Tool Agent with Provider: {tool_provider}, Model: {tool_model}")
            
            _TOOL_AGENT = LLMAgent(
                event_bus=DummyBus(), 
                state_engine=None, 
                automations=None, 
                subscribe_to_voice=False,
                override_provider=tool_provider,
                override_model=tool_model
            )

    async def ask(
        self, 
        messages: List[Dict[str, str]], 
        system_msgs: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        override_model: Optional[str] = None,
        max_tokens: Optional[int] = None
    ) -> Message:
        """
        Send a request to the Reasoning Engine (K2 Think).
        """
        full_system_prompt = ""
        if system_msgs:
            full_system_prompt = "\n".join([m["content"] for m in system_msgs])
            
        # Route to REASONING AGENT
        # Note: K2 might struggle with tools, so we prefer not sending them unless necessary
        # But if user insists on tools here, we pass them.
        # Route to REASONING AGENT
        # Note: K2 might struggle with tools, so we prefer not sending them unless necessary
        # But if user insists on tools here, we pass them.
        
        # User requested: NO FALLBACK to Groq. If K2 fails,
        response = await self._ask_provider(_REASONING_AGENT, full_system_prompt, messages, tools, tool_choice, override_model, max_tokens=max_tokens)
        if response.content and "LLM Error" in response.content:
            raise RuntimeError(response.content)
        return response

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> Message:
        """Alias for ask() to maintain compatibility with other interfaces."""
        return await self.ask(messages, **kwargs)

    async def ask_tool(self, messages, system_msgs, tools, tool_choice) -> Message:
        """
        Send a request to the Execution Engine (Groq).
        Note: Groq/Llama-3 is optimized for function calling and JSON.
        """
        full_system_prompt = ""
        if system_msgs:
            full_system_prompt = "\n".join([m["content"] for m in system_msgs])
            
        # Route to TOOL AGENT
        return await self._ask_provider(_TOOL_AGENT, full_system_prompt, messages, tools, tool_choice)

    async def ask_streaming(self, messages: List[Dict], system_msgs: Optional[List[Dict]] = None):
        """Streaming generator (Phase 6 support)"""
        # Placeholder for streaming implementation
        # For now, just non-streaming fallback yielded
        response = await self.ask(messages, system_msgs)
        if response.content:
            yield response.content

    async def ask_json(
        self, 
        messages: List[Dict[str, str]], 
        retries: int = 2,
        system_msgs: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Ask LLM and enforce JSON output with Self-Repair Loop.
        """
        attempts = 0
        last_error = None
        current_messages = list(messages)
        
        while attempts <= retries:
            try:
                response = await self.ask(current_messages, system_msgs=system_msgs)
                content = response.content or "{}"
                
                # 1. Clean Markdown
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                # 2. Parse
                return json.loads(content)
                
            except json.JSONDecodeError as e:
                attempts += 1
                last_error = e
                print(f"[UnifiedLLM] ⚠️ JSON Parse Error (Attempt {attempts}/{retries+1}): {e}")
                
                if attempts <= retries:
                    # 3. SELF-REPAIR: Ask LLM to fix it
                    repair_prompt = f"""
                    Your previous response was not valid JSON. 
                    Error: {str(e)}
                    
                    Please fix the JSON and return ONLY the valid JSON object. Do not add any markdown formatting or explanation.
                    """
                    # Append the invalid response and the repair request to history
                    # We treat the invalid response as an assistant message for context
                    current_messages.append({"role": "assistant", "content": response.content})
                    current_messages.append({"role": "user", "content": repair_prompt})
                    
        raise ValueError(f"Failed to get valid JSON after {retries} retries. Last error: {last_error}")

    # ═══════════════════════════════════════════════════════════
    # ADAPTERS
    # ═══════════════════════════════════════════════════════════

    async def _ask_provider(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=None):
        # Dispatch to appropriate adapter based on agent configuration
        if agent.provider == "gemini":
            return await self._ask_gemini(agent, system_prompt, messages, tools)
        elif agent.provider == "nvidia":
            return await self._ask_nvidia(agent, system_prompt, messages, tools, tool_choice, override_model, max_tokens)
        elif agent.client:
            return await self._ask_openai_compat(agent, system_prompt, messages, tools, tool_choice, override_model, max_tokens=max_tokens)
        return Message.assistant_message(f"Error: Provider {agent.provider} not supported in hybrid adapter")

    async def _ask_openai_compat(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=None):
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
                if content:
                    msg["content"] = content
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
        # Call API (async wrapper for sync client)
        def _call():
            kwargs = {
                "model": model,
                "messages": api_messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
                
            return agent.client.chat.completions.create(**kwargs)
        
        try:
            response = await asyncio.to_thread(_call)
            choice = response.choices[0]
            message = choice.message
            
            tool_calls = []
            if message.tool_calls:
                from agent_unified.schema import ToolCall, Function
                for tc in message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id,
                        function=Function(name=tc.function.name, arguments=tc.function.arguments)
                    ))
            
            content = message.content
            
            # Universal Parsing: extract <think>...<answer> if present
            # valid for DeepSeek-R1, K2, or any model prompted to use these tags
            if content:
                import re
                # Pattern to extract think and answer blocks
                # The API returns <think>...</think>\n<answer>...</answer>
                # We want to log the thought but return the answer
                
                think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
                answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)
                
                if think_match:
                    thought_process = think_match.group(1).strip()
                    print(f"\n[Thinking] 🧠 Thought Process:\n{thought_process}\n")
                    # GLASS BOX: Stream Thought
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    import asyncio
                    try:
                        # Broadcast immediately - await to ensure it sends
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                             loop.create_task(SSEBroadcaster().broadcast("think", {"content": thought_process}))
                    except Exception as e:
                        logger.warning(f"Failed to broadcast thought: {e}")
                    
                if answer_match:
                    content = answer_match.group(1).strip()
                else:
                    # Fallback: if no answer tag, retry extracting valid text or return all
                    # Sometimes models output just text if they fail to follow format
                    # But if <think> exists, strip it from content
                    if think_match:
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            
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

    async def _ask_nvidia(self, agent, system_prompt, messages, tools, tool_choice, override_model=None, max_tokens=16384):
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
                 return await self._ask_provider(_TOOL_AGENT, system_prompt, messages, tools, tool_choice)
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

    async def _ask_gemini(self, agent, system_prompt, messages, tools):
        # Gemini adapter implementation ...
        # For brevity in this turn, assuming OpenAI compatible preference logic which handles Groq/OpenAI/Synthetic
        # If Gemini needed, we'd enable this.
        return Message.assistant_message("Gemini adapter not fully implemented in UnifiedLLM yet")
