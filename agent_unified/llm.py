"""
ARVIS Unified LLM Client
========================

Wrapper around existing ARVIS LLM infrastructure (k2think).
Provides interface compatible with agent hierarchy.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr


logger = logging.getLogger("arvis.unified.llm")


class UnifiedLLM(BaseModel):
    """
    Unified LLM client for ARVIS agents.
    
    Uses existing k2think infrastructure for LLM calls.
    Falls back to OpenAI-compatible API if k2think not configured.
    """
    
    config_name: str = Field(default="default", description="LLM config name")
    _client: Any = PrivateAttr(default=None)
    _provider: str = PrivateAttr(default="openai")
    
    model_config = {"arbitrary_types_allowed": True}
    
    def model_post_init(self, __context) -> None:
        """Initialize the underlying LLM client."""
        self._init_client()
    
    def _init_client(self):
        """Initialize the underlying LLM client."""
        # Determine provider based on available keys
        if os.environ.get("K2THINK_API_KEY"):
            self._provider = "k2think"
            logger.info("Using K2 Think LLM provider")
        elif os.environ.get("GROQ_API_KEY"):
            self._provider = "groq"
            logger.info("Using Groq LLM provider")
        elif os.environ.get("OPENAI_API_KEY"):
            self._provider = "openai"
            logger.info("Using OpenAI LLM provider")
        else:
            logger.warning("No LLM API key found - calls will fail without configuration")
    
    def _get_api_config(self) -> Dict[str, str]:
        """Get API configuration based on provider."""
        if self._provider == "k2think":
            return {
                "api_key": os.environ.get("K2THINK_API_KEY"),
                "base_url": "https://api.k2think.ai/v2",
                "model": os.environ.get("K2THINK_MODEL", "MBZUAI-IFM/K2-Think")
            }
        elif self._provider == "groq":
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
        Send messages to LLM and get response.
        
        Args:
            messages: List of message dicts
            system_msgs: Optional system messages
            stream: Whether to stream response
            temperature: Optional temperature override
            
        Returns:
            LLM response
        """
        try:
            from openai import AsyncOpenAI
            
            config = self._get_api_config()
            
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
        
        Args:
            messages: List of message dicts
            system_msgs: Optional system messages
            tools: List of tool definitions
            tool_choice: Tool choice strategy
            temperature: Optional temperature
            
        Returns:
            LLM response with potential tool calls
        """
        try:
            from openai import AsyncOpenAI
            
            config = self._get_api_config()
            
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
        """Get current LLM provider."""
        return self._provider
