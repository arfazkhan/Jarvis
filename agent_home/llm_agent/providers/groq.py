"""
Groq Provider
=============

Groq Llama models provider implementation.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Generator

from agent_home.llm_agent.providers.base import BaseProvider

logger = logging.getLogger("arvis.llm.providers.groq")


class GroqProvider(BaseProvider):
    """Groq Llama models provider."""
    
    name = "groq"
    default_model = "llama-3.3-70b-versatile"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ):
        super().__init__(api_key, model or self.default_model, **kwargs)
        
        if api_key:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Groq client."""
        try:
            from groq import Groq
            self._client = Groq(api_key=self.api_key)
            logger.info(f"[Groq] Initialized with model {self.model}")
        except Exception as e:
            logger.error(f"[Groq] Failed to initialize: {e}")
            self._client = None
    
    def is_available(self) -> bool:
        """Check if Groq is available."""
        return self._client is not None
    
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response from Groq."""
        if not self.is_available():
            return {"content": None, "tool_calls": [], "error": "Groq not initialized"}
        
        self._log_request(messages, tools)
        
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice
            )
            
            if not response.choices:
                return {"content": None, "tool_calls": []}
            
            message = response.choices[0].message
            content = message.content
            tool_calls = []
            
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        tool_calls.append({
                            "tool": tc.function.name,
                            "args": json.loads(tc.function.arguments)
                        })
                    except json.JSONDecodeError:
                        pass
            
            result = {"content": content, "tool_calls": tool_calls}
            self._log_response(result)
            return result
            
        except Exception as e:
            self._log_error(e)
            return {"content": None, "tool_calls": [], "error": str(e)}
    
    def generate_stream(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Generator[Dict[str, Any], None, None]:
        """Generate a streaming response from Groq."""
        if not self.is_available():
            yield {"content": None, "error": "Groq not initialized"}
            return
        
        self._log_request(messages, tools)
        
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                stream=True
            )
            
            current_tool = None
            tool_args_buffer = ""
            
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                
                # Handle text content
                if delta.content:
                    yield {"content": delta.content}
                
                # Handle tool calls (streamed as deltas)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.function.name:
                            # New tool call starting
                            if current_tool:
                                # Emit previous tool
                                try:
                                    yield {
                                        "tool_call": {
                                            "tool": current_tool,
                                            "args": json.loads(tool_args_buffer)
                                        }
                                    }
                                except json.JSONDecodeError:
                                    pass
                            current_tool = tc.function.name
                            tool_args_buffer = tc.function.arguments or ""
                        elif tc.function.arguments:
                            # Accumulating arguments
                            tool_args_buffer += tc.function.arguments
            
            # Emit final tool if any
            if current_tool and tool_args_buffer:
                try:
                    yield {
                        "tool_call": {
                            "tool": current_tool,
                            "args": json.loads(tool_args_buffer)
                        }
                    }
                except json.JSONDecodeError:
                    logger.warning(f"[Groq] Failed to parse tool args: {tool_args_buffer}")
                    
        except Exception as e:
            self._log_error(e)
            yield {"content": None, "error": str(e)}
