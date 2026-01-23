"""
ARVIS Unified LLM Client
========================

Wrapper around existing ARVIS LLM infrastructure.
- k2think: For reasoning/planning (no function calling)
- Groq: For tool calling (supports OpenAI function format)
"""

import os
import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr


logger = logging.getLogger("arvis.unified.llm")


class UnifiedLLM(BaseModel):
    """
    Unified LLM client for ARVIS agents.
    
    Uses:
    - k2think for reasoning/planning (ask method)
    - Groq for tool calling (ask_tool method)
    """
    
    config_name: str = Field(default="default", description="LLM config name")
    _provider: str = PrivateAttr(default="groq")
    _reasoning_provider: str = PrivateAttr(default="k2think")
    
    model_config = {"arbitrary_types_allowed": True}
    
    def model_post_init(self, __context) -> None:
        """Initialize the underlying LLM client."""
        self._init_providers()
    
    def _init_providers(self):
        """Determine available providers based on API keys."""
        # Reasoning provider (k2think preferred)
        if os.environ.get("K2THINK_API_KEY"):
            self._reasoning_provider = "k2think"
        elif os.environ.get("GROQ_API_KEY"):
            self._reasoning_provider = "groq"
        elif os.environ.get("OPENAI_API_KEY"):
            self._reasoning_provider = "openai"
        else:
            self._reasoning_provider = None
            logger.warning("No reasoning LLM API key found")
        
        # Tool calling provider (Groq preferred, k2think doesn't support tools)
        if os.environ.get("GROQ_API_KEY"):
            self._provider = "groq"
        elif os.environ.get("OPENAI_API_KEY"):
            self._provider = "openai"
        else:
            self._provider = None
            logger.warning("No tool-calling LLM API key found")
        
        logger.info(f"Reasoning provider: {self._reasoning_provider}, Tool provider: {self._provider}")
    
    def _get_api_config(self, provider: str) -> Dict[str, str]:
        """Get API configuration based on provider."""
        if provider == "k2think":
            return {
                "api_key": os.environ.get("K2THINK_API_KEY"),
                "base_url": "https://api.k2think.ai/v2",
                "model": os.environ.get("K2THINK_MODEL", "MBZUAI-IFM/K2-Think")
            }
        elif provider == "groq":
            return {
                "api_key": os.environ.get("GROQ_API_KEY"),
                "base_url": "https://api.groq.com/openai/v1",
                "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            }
        else:
            return {
                "api_key": os.environ.get("OPENAI_API_KEY"),
                "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            }
    
    async def ask(
        self,
        messages: List[Dict],
        system_msgs: Optional[List[Dict]] = None,
        stream: bool = False,
        temperature: Optional[float] = None
    ) -> Any:
        """
        Send messages to LLM for reasoning/planning.
        Uses k2think if available (better reasoning).
        """
        try:
            from openai import AsyncOpenAI
            
            config = self._get_api_config(self._reasoning_provider or "groq")
            
            client = AsyncOpenAI(
                api_key=config["api_key"],
                base_url=config["base_url"]
            )
            
            # Build full message list
            full_messages = []
            if system_msgs:
                full_messages.extend(system_msgs)
            full_messages.extend(messages)
            
            response = await client.chat.completions.create(
                model=config["model"],
                messages=full_messages,
                temperature=temperature or 0.7,
                stream=stream
            )
            
            return response.choices[0].message
            
        except Exception as e:
            logger.error(f"LLM ask error: {e}")
            raise
    
    async def ask_tool(
        self,
        messages: List[Dict],
        system_msgs: Optional[List[Dict]] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        Send messages with tools to LLM.
        Uses Groq (k2think doesn't support function calling).
        """
        try:
            from openai import AsyncOpenAI
            
            # Use tool-calling provider (NOT k2think)
            config = self._get_api_config(self._provider or "groq")
            
            client = AsyncOpenAI(
                api_key=config["api_key"],
                base_url=config["base_url"]
            )
            
            # Build full message list
            full_messages = []
            if system_msgs:
                full_messages.extend(system_msgs)
            full_messages.extend(messages)
            
            # Build request kwargs
            request_kwargs = {
                "model": config["model"],
                "messages": full_messages,
                "temperature": temperature or 0.7,
            }
            
            if tools:
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = tool_choice
            
            response = await client.chat.completions.create(**request_kwargs)
            
            return response.choices[0].message
            
        except Exception as e:
            logger.error(f"LLM ask_tool error: {e}")
            raise
    
    @property
    def provider(self) -> str:
        """Get current tool-calling LLM provider."""
        return self._provider
    
    @property
    def reasoning_provider(self) -> str:
        """Get current reasoning LLM provider."""
        return self._reasoning_provider
