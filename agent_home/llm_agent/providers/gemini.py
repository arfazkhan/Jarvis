"""
Gemini Provider
===============

Google Gemini 2.0 Flash provider implementation.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Generator

from agent_home.llm_agent.providers.base import BaseProvider

logger = logging.getLogger("arvis.llm.providers.gemini")


def convert_tools_for_gemini(openai_tools):
    """
    Convert OpenAI/Groq tool schema to Gemini protos format.
    Gemini SDK requires FunctionDeclaration objects, not raw dicts.
    """
    from google.generativeai import protos

    function_declarations = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool["function"]
            params = func.get("parameters", {"type": "object", "properties": {}})

            # Convert parameters to Gemini Schema format
            properties = {}
            for name, prop in params.get("properties", {}).items():
                properties[name] = _convert_property_to_schema(prop)

            schema = protos.Schema(
                type=protos.Type.OBJECT,
                properties=properties,
                required=params.get("required", [])
            )

            fd = protos.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
                parameters=schema
            )
            function_declarations.append(fd)

    # Return as a Tool containing all function declarations
    return [protos.Tool(function_declarations=function_declarations)]


def _convert_property_to_schema(prop: dict):
    """Convert a single property to Gemini Schema, handling arrays recursively."""
    from google.generativeai import protos

    prop_type = prop.get("type", "string")

    if prop_type == "array":
        items = prop.get("items", {"type": "string"})
        items_schema = _convert_property_to_schema(items)
        return protos.Schema(
            type=protos.Type.ARRAY,
            items=items_schema,
            description=prop.get("description", "")
        )
    elif prop_type == "object":
        nested_props = {}
        for name, nested_prop in prop.get("properties", {}).items():
            nested_props[name] = _convert_property_to_schema(nested_prop)
        return protos.Schema(
            type=protos.Type.OBJECT,
            properties=nested_props,
            required=prop.get("required", []),
            description=prop.get("description", "")
        )
    else:
        return protos.Schema(
            type=_get_gemini_type(prop_type),
            description=prop.get("description", "")
        )


def _get_gemini_type(openai_type: str):
    """Map OpenAI types to Gemini protos.Type"""
    from google.generativeai import protos
    type_map = {
        "string": protos.Type.STRING,
        "integer": protos.Type.INTEGER,
        "number": protos.Type.NUMBER,
        "boolean": protos.Type.BOOLEAN,
        "array": protos.Type.ARRAY,
        "object": protos.Type.OBJECT,
    }
    return type_map.get(openai_type, protos.Type.STRING)


class GeminiProvider(BaseProvider):
    """Google Gemini 2.0 Flash provider."""
    
    name = "gemini"
    default_model = "gemini-2.0-flash"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: str = "",
        tools: Optional[List[Dict]] = None,
        **kwargs
    ):
        super().__init__(api_key, model or self.default_model, **kwargs)
        self.system_prompt = system_prompt
        self.tools = tools or []
        self._model_instance = None
        
        if api_key:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize the Gemini client."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            
            # Convert tools for Gemini
            gemini_tools = convert_tools_for_gemini(self.tools) if self.tools else None
            
            self._model_instance = genai.GenerativeModel(
                model_name=self.model,
                system_instruction=self.system_prompt,
                tools=gemini_tools
            )
            self._client = genai
            logger.info(f"[Gemini] Initialized with model {self.model}")
        except Exception as e:
            logger.error(f"[Gemini] Failed to initialize: {e}")
            self._client = None
            self._model_instance = None
    
    def is_available(self) -> bool:
        """Check if Gemini is available."""
        return self._model_instance is not None
    
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a response from Gemini."""
        if not self.is_available():
            return {"content": None, "tool_calls": [], "error": "Gemini not initialized"}
        
        self._log_request(messages, tools)
        
        try:
            # Build chat history
            history = [{"role": "user", "parts": [messages[0].get("content", "")]}] if messages else []
            
            chat = self._model_instance.start_chat(history=history)
            
            # Get user message
            user_message = messages[-1].get("content", "") if len(messages) > 1 else ""
            
            response = chat.send_message(user_message)
            
            # Parse response
            content = ""
            tool_calls = []
            
            for part in response.parts:
                if hasattr(part, 'text') and part.text:
                    content += part.text
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tool_calls.append({
                        "tool": fc.name,
                        "args": dict(fc.args)
                    })
            
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
        """Generate a streaming response from Gemini."""
        if not self.is_available():
            yield {"content": None, "error": "Gemini not initialized"}
            return
        
        self._log_request(messages, tools)
        
        try:
            user_message = messages[-1].get("content", "") if messages else ""
            
            response = self._model_instance.generate_content(
                user_message,
                stream=True
            )
            
            for chunk in response:
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    for candidate in chunk.candidates:
                        if hasattr(candidate, 'content') and candidate.content:
                            for part in candidate.content.parts:
                                if hasattr(part, 'function_call') and part.function_call:
                                    fc = part.function_call
                                    yield {
                                        "tool_call": {
                                            "tool": fc.name,
                                            "args": dict(fc.args)
                                        }
                                    }
                                elif hasattr(part, 'text') and part.text:
                                    yield {"content": part.text}
                                    
        except Exception as e:
            self._log_error(e)
            yield {"content": None, "error": str(e)}
