"""
ARVIS LLM Agent - Prompt Builder
Composes layered prompts at runtime with context injection.
"""

import json
from typing import Dict, List, Any, Optional

from agent_home.llm_agent.prompt_identity import IDENTITY_LAYER
from agent_home.llm_agent.prompt_rules import DECISION_RULES_LAYER


class PromptBuilder:
    """
    Compose layered prompts at runtime.
    
    Layers:
    1. Identity + Style (stable, rarely changes)
    2. Decision Rules (core behavior, safety)
    3. Tool Schema (separate, passed to LLM API)
    
    Runtime context is injected as user messages, not baked into system prompt.
    """
    
    def __init__(self):
        self.identity = IDENTITY_LAYER
        self.rules = DECISION_RULES_LAYER
        self._full_prompt_cache: Optional[str] = None
        self._rules_only_cache: Optional[str] = None
    
    def build_system_prompt(self, provider: str = "auto") -> str:
        """
        Build the system prompt for the given provider.
        
        Args:
            provider: LLM provider ("gemini", "groq", "lmstudio", "openai", etc.)
        
        Returns:
            Complete system prompt string
        """
        # LM Studio with Granite template has identity in Jinja, skip duplicate
        if provider.lower() == "lmstudio":
            if self._rules_only_cache is None:
                self._rules_only_cache = self.rules.strip()
            return self._rules_only_cache
        
        # All other providers get the full layered prompt
        if self._full_prompt_cache is None:
            self._full_prompt_cache = f"{self.identity}\n\n{self.rules}".strip()
        return self._full_prompt_cache
    
    def build_context_message(
        self,
        event: Dict[str, Any],
        home_state: Dict[str, Any],
        device_states: str,
        routines: List[str],
        preferences: Dict[str, Any],
        memory_context: str = ""
    ) -> str:
        """
        Build runtime context as a structured message.
        
        This is injected as a user message, NOT baked into system prompt.
        This allows the LLM to adapt to current context dynamically.
        
        Args:
            event: The triggering event (voice_command, time_tick, etc.)
            home_state: Current home state (presence, sleep, activity, time)
            device_states: Summary of current device states
            routines: List of available routine names
            preferences: User preferences from memory
            memory_context: Relevant memories for this query
        
        Returns:
            JSON string of runtime context
        """
        context = {
            "event": event,
            "home_state": home_state,
            "device_states": device_states,
            "available_routines": routines,
            "user_preferences": preferences,
        }
        
        # Only include memory context if present
        if memory_context:
            context["memory_context"] = memory_context
        
        return json.dumps(context, indent=2)
    
    def get_prompt_stats(self) -> Dict[str, int]:
        """Get statistics about prompt sizes for monitoring."""
        return {
            "identity_chars": len(self.identity),
            "rules_chars": len(self.rules),
            "full_prompt_chars": len(self.build_system_prompt("auto")),
            "lmstudio_prompt_chars": len(self.build_system_prompt("lmstudio")),
        }


# Singleton instance for easy access
_builder_instance: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    """Get the singleton PromptBuilder instance."""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = PromptBuilder()
    return _builder_instance
