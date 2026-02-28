"""
Base LLM Provider
=================

Abstract base class for LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Generator
import logging

logger = logging.getLogger("arvis.llm.providers")


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""
    
    name: str = "base"
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.model = model
        self.config = kwargs
        self._client = None
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is properly configured and available."""
        pass
    
    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a response from the LLM.
        
        Returns:
            Dict with 'content' (str) and 'tool_calls' (list) keys
        """
        pass
    
    @abstractmethod
    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Generate a streaming response from the LLM.
        
        Yields:
            Dict with 'content' (str) or 'tool_call' (dict) keys
        """
        pass
    
    def _log_request(self, messages: List[Dict], tools: Optional[List] = None):
        """Log the request for debugging."""
        msg_count = len(messages)
        tool_count = len(tools) if tools else 0
        logger.info(f"[{self.name}] Request: {msg_count} messages, {tool_count} tools")
    
    def _log_response(self, response: Dict):
        """Log the response for debugging."""
        has_content = bool(response.get("content"))
        tool_count = len(response.get("tool_calls", []))
        logger.info(f"[{self.name}] Response: content={has_content}, tool_calls={tool_count}")
    
    def _log_error(self, error: Exception):
        """Log an error."""
        logger.error(f"[{self.name}] Error: {error}")
    
    def get_model_name(self) -> str:
        """Get the model name being used."""
        return self.model or "unknown"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.get_model_name()}>"
