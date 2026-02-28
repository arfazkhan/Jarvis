"""
K2 Think Provider
=================

K2 Think reasoning model provider implementation.
"""

import json
import logging
import re
from typing import Dict, List, Any, Optional, Generator

from agent_home.llm_agent.providers.openai import OpenAIProvider

logger = logging.getLogger("arvis.llm.providers.k2think")


class K2ThinkProvider(OpenAIProvider):
    """K2 Think reasoning model provider (OpenAI-compatible)."""
    
    name = "k2think"
    default_model = "MBZUAI-IFM/K2-Think"
    default_base_url = "https://api.k2think.ai/v2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ):
        # K2 Think uses OpenAI-compatible API
        kwargs["base_url"] = kwargs.get("base_url", self.default_base_url)
        super().__init__(api_key, model or self.default_model, **kwargs)
    
    def _parse_k2think_response(self, content: str) -> tuple:
        """
        Parse K2 Think response which uses thi... and <answer>...</answer> tags.
        Returns (answer, thinking) - answer is the user-facing response, thinking is for logs.
        """
        answer = content
        thinking = ""

        # Extract thinking trace (for debugging/logging)
        think_match = re.search(r'thi(.*?)', content, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()

        # Extract final answer (user-facing)
        answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL)
        if answer_match:
            answer = answer_match.group(1).strip()
        else:
            # If no <answer> tags, strip thi tags and use remainder
            answer = re.sub(r'thi.*?', '', content, flags=re.DOTALL).strip()

        return answer, thinking
    
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response from K2 Think with response parsing."""
        result = super().generate(messages, tools, tool_choice, **kwargs)
        
        # Parse K2 Think response format
        if result.get("content"):
            answer, thinking = self._parse_k2think_response(result["content"])
            if thinking:
                logger.info(f"[K2Think] Reasoning: {thinking[:200]}...")
            result["content"] = answer
            result["thinking"] = thinking
        
        return result
    
    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Generator[Dict[str, Any], None, None]:
        """Generate a streaming response from K2 Think."""
        # For streaming, we yield raw content and let the caller handle parsing
        yield from super().generate_stream(messages, tools, tool_choice, **kwargs)
