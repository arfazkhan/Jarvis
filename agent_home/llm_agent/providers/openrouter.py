"""
OpenRouter Provider
===================

OpenRouter multi-model gateway provider implementation.
"""

import logging
from typing import Dict, List, Any, Optional, Generator

from agent_home.llm_agent.providers.openai import OpenAIProvider

logger = logging.getLogger("arvis.llm.providers.openrouter")


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter multi-model gateway provider."""
    
    name = "openrouter"
    default_model = "meta-llama/llama-3.3-70b-instruct"
    default_base_url = "https://openrouter.ai/api/v1"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ):
        kwargs["base_url"] = kwargs.get("base_url", self.default_base_url)
        super().__init__(api_key, model or self.default_model, **kwargs)
