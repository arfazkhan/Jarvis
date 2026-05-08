"""
Minimal LLMAgent Stub
=====================

Stub for legacy home automation LLM agent.
Provides minimal interface needed by UnifiedLLM.
"""

import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("arvis.home.llm_agent")


class LLMAgent:
    """
    Minimal stub for LLMAgent.
    
    UnifiedLLM uses this to:
    1. Get provider clients (Groq, OpenAI, etc.)
    2. Make LLM calls
    """
    
    def __init__(
        self,
        event_bus=None,
        state_engine=None,
        automation_engine=None,
        learning_engine=None,
        subscribe_to_voice=False,
    ):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automation_engine = automation_engine
        self.learning_engine = learning_engine
        
        # Provider clients
        self._groq_client = None
        self._openai_client = None
        
        # Initialize Groq client if API key exists
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=groq_key)
                logger.info("Groq client initialized")
            except ImportError:
                logger.warning("groq package not installed")
    
    async def ask(self, prompt: str, **kwargs) -> str:
        """Make LLM call."""
        if self._groq_client:
            try:
                model = kwargs.get("model", "llama-3.3-70b-versatile")
                response = self._groq_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"Groq API error: {e}")
                return f'{"error": "LLM call failed"}'
        
        # Fallback: return mock response
        return '{"status": "ok", "confidence": 0.85}'
    
    async def ask_tool(
        self,
        prompt: str,
        tools: List[Dict],
        **kwargs
    ) -> Dict[str, Any]:
        """Make tool-calling LLM request."""
        response_text = await self.ask(prompt, **kwargs)
        
        import json
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {
                "tool": tools[0]["name"] if tools else "unknown",
                "arguments": {},
            }
    
    def get_groq_client(self):
        """Return Groq client if available."""
        return self._groq_client
    
    def set_llm_client(self, client):
        """Set external LLM client."""
        pass
