"""
ARVIS Unified LLM Client
========================

Wrapper around existing ARVIS LLM infrastructure.
Provides interface compatible with agent hierarchy.
"""

import os
import logging
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


logger = logging.getLogger("arvis.unified.llm")


class UnifiedLLM(BaseModel):
    """
    Unified LLM client for ARVIS agents.
    
    Wraps existing LLM infrastructure to provide a clean interface
    for the unified agent system.
    """
    
    config_name: str = Field(default="default", description="LLM config name")
    _client: Any = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self._init_client()
    
    def _init_client(self):
        """Initialize the underlying LLM client"""
        try:
            # Try to use existing ARVIS LLM
            from agent.llm_agent.llm_agent import LLMAgent
            # We'll use the LLM from existing infrastructure
            self._client = None  # Will be set when needed
        except ImportError:
            logger.warning("Could not import ARVIS LLMAgent, using OpenAI directly")
            self._client = None
    
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
            
            client = AsyncOpenAI(
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL") or "https://api.groq.com/openai/v1"
            )
            
            # Build full message list
            full_messages = []
            if system_msgs:
                full_messages.extend(system_msgs)
            full_messages.extend(messages)
            
            response = await client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile"),
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
            
            client = AsyncOpenAI(
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL") or "https://api.groq.com/openai/v1"
            )
            
            # Build full message list
            full_messages = []
            if system_msgs:
                full_messages.extend(system_msgs)
            full_messages.extend(messages)
            
            # Build request kwargs
            request_kwargs = {
                "model": os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile"),
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
