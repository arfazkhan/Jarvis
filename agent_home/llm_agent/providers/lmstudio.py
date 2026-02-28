"""
LM Studio Provider
==================

Local LM Studio provider implementation (OpenAI-compatible).
"""

import logging
from typing import Dict, List, Any, Optional, Generator

from agent_home.llm_agent.providers.openai import OpenAIProvider

logger = logging.getLogger("arvis.llm.providers.lmstudio")


class LMStudioProvider(OpenAIProvider):
    """Local LM Studio provider (OpenAI-compatible API)."""
    
    name = "lmstudio"
    default_model = "local-model"
    default_base_url = "http://localhost:1234/v1"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        # LM Studio uses a dummy API key and local URL
        kwargs["base_url"] = base_url or self.default_base_url
        super().__init__(api_key or "lm-studio", model or self.default_model, **kwargs)
    
    def is_available(self) -> bool:
        """Check if LM Studio is available by pinging the local server."""
        if not self._client:
            return False
        
        try:
            import requests
            response = requests.get(f"{self.base_url}/models", timeout=2)
            return response.status_code == 200
        except Exception:
            return False
