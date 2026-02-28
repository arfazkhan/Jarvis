"""
Context Builder - Smart context assembly for LLM
Selects and formats relevant memories per query.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds optimized LLM context from multiple memory sources.
    
    Responsibilities:
    - Analyze incoming query
    - Select relevant memories from each store
    - Format for LLM consumption
    - Stay within token budget
    
    Example:
        builder = ContextBuilder(preference_store, observation_store, conversation_buffer)
        context = builder.build("make it cozy", device_states)
        # Returns formatted context string for LLM
    """
    
    def __init__(self, preferences, observations, conversations,
                 max_tokens: int = 2000):
        """
        Args:
            preferences: PreferenceStore instance
            observations: ObservationStore instance  
            conversations: ConversationBuffer instance
            max_tokens: Approximate max tokens for context
        """
        self.preferences = preferences
        self.observations = observations
        self.conversations = conversations
        self.max_tokens = max_tokens
        
        # Approximate chars per token (conservative)
        self.chars_per_token = 4
    
    def build(self, query: str, device_states: Optional[Dict] = None,
              current_time: Optional[datetime] = None,
              home_state: Optional[Dict] = None) -> str:
        """
        Build complete context for LLM.
        
        Args:
            query: User's current query/command
            device_states: Current device states
            current_time: Current time (for time-aware context)
            home_state: presence, sleep_state, etc.
            
        Returns:
            Formatted context string
        """
        current_time = current_time or datetime.now()
        sections = []
        
        # 1. Device States (always included, ~200 tokens)
        if device_states:
            device_section = self._format_device_states(device_states)
            sections.append(device_section)
        
        # 2. Home State (always included, ~50 tokens)
        if home_state:
            home_section = self._format_home_state(home_state, current_time)
            sections.append(home_section)
        
        # 3. Relevant Preferences (semantic search, ~300 tokens)
        pref_section = self._get_relevant_preferences(query)
        if pref_section:
            sections.append(pref_section)
        
        # 4. Recent Observations (time-weighted, ~200 tokens)
        obs_section = self._get_relevant_observations(query, current_time)
        if obs_section:
            sections.append(obs_section)
        
        # 5. Conversation History (always last, ~500 tokens)
        conv_section = self._format_conversation()
        if conv_section:
            sections.append(conv_section)
        
        context = "\n\n".join(sections)
        
        # Trim if too long
        max_chars = self.max_tokens * self.chars_per_token
        if len(context) > max_chars:
            context = self._trim_context(context, max_chars)
        
        logger.debug(f"[ContextBuilder] Built context: {len(context)} chars")
        return context
    
    def _format_device_states(self, states: Dict) -> str:
        """Format device states section."""
        lines = ["### Device States"]
        for device_id, state in states.items():
            if isinstance(state, dict):
                state_str = ", ".join(f"ep{k}:{v}" for k, v in state.items())
                lines.append(f"- {device_id}: {state_str}")
            else:
                lines.append(f"- {device_id}: {state}")
        return "\n".join(lines)
    
    def _format_home_state(self, state: Dict, current_time: datetime) -> str:
        """Format home state section."""
        lines = ["### Home State"]
        lines.append(f"- Time: {current_time.strftime('%H:%M')} on {current_time.strftime('%A')}")
        
        if 'presence' in state:
            lines.append(f"- Presence: {state['presence']}")
        if 'sleep_state' in state:
            lines.append(f"- Sleep state: {state['sleep_state']}")
        if 'activity_hint' in state:
            lines.append(f"- Activity: {state['activity_hint']}")
        if 'location' in state:
            lines.append(f"- User location: {state['location']}")
            
        return "\n".join(lines)
    
    def _get_relevant_preferences(self, query: str) -> Optional[str]:
        """Search for relevant preferences."""
        try:
            matches = self.preferences.search(query, limit=5)
            
            if not matches:
                return None
            
            lines = ["### User Preferences"]
            for match in matches:
                if match.get('score', 0) > 0.3:  # Only include relevant matches
                    lines.append(f"- {match['content']}")
                    if match.get('metadata', {}).get('context'):
                        lines[-1] += f" (context: {match['metadata']['context']})"
            
            return "\n".join(lines) if len(lines) > 1 else None
            
        except Exception as e:
            logger.error(f"[ContextBuilder] Preference search failed: {e}")
            return None
    
    def _get_relevant_observations(self, query: str, 
                                   current_time: datetime) -> Optional[str]:
        """Get time-weighted observations."""
        try:
            # Get recent observations (last 24 hours)
            recent = self.observations.get_recent(hours=24, limit=10)
            
            if not recent:
                return None
            
            # Also search for query-relevant observations
            keyword_matches = self.observations.search(query, limit=5)
            
            # Combine and deduplicate
            seen_ids = set()
            combined = []
            for obs in recent + keyword_matches:
                if obs['id'] not in seen_ids:
                    seen_ids.add(obs['id'])
                    combined.append(obs)
            
            # Sort by score
            combined.sort(key=lambda x: x.get('score', x.get('importance', 0.5)), 
                         reverse=True)
            
            if not combined:
                return None
            
            lines = ["### Recent Observations"]
            for obs in combined[:5]:  # Top 5
                lines.append(f"- {obs['content']}")
            
            return "\n".join(lines) if len(lines) > 1 else None
            
        except Exception as e:
            logger.error(f"[ContextBuilder] Observation retrieval failed: {e}")
            return None
    
    def _format_conversation(self) -> Optional[str]:
        """Format conversation history."""
        try:
            context = self.conversations.get_context()
            
            if not context:
                return None
            
            lines = ["### Conversation"]
            for msg in context:
                role = msg['role'].capitalize()
                content = msg['content'][:200]  # Truncate long messages
                if len(msg['content']) > 200:
                    content += "..."
                lines.append(f"- {role}: {content}")
            
            return "\n".join(lines) if len(lines) > 1 else None
            
        except Exception as e:
            logger.error(f"[ContextBuilder] Conversation formatting failed: {e}")
            return None
    
    def _trim_context(self, context: str, max_chars: int) -> str:
        """Trim context to fit token budget, preserving most important parts."""
        if len(context) <= max_chars:
            return context
        
        # Split into sections
        sections = context.split("\n\n")
        
        # Priority: Device States > Home State > Conversation > Preferences > Observations
        priority_order = [
            "### Device States",
            "### Home State", 
            "### Conversation",
            "### User Preferences",
            "### Recent Observations"
        ]
        
        # Sort sections by priority
        def get_priority(section: str) -> int:
            for i, prefix in enumerate(priority_order):
                if section.startswith(prefix):
                    return i
            return len(priority_order)
        
        sections.sort(key=get_priority)
        
        # Build context up to limit
        result = []
        current_len = 0
        for section in sections:
            if current_len + len(section) + 2 <= max_chars:
                result.append(section)
                current_len += len(section) + 2
            else:
                # Truncate last section
                remaining = max_chars - current_len - 5
                if remaining > 100:
                    result.append(section[:remaining] + "...")
                break
        
        return "\n\n".join(result)
    
    def get_quick_context(self, device_states: Optional[Dict] = None,
                          home_state: Optional[Dict] = None) -> str:
        """
        Get minimal context for simple commands (no query analysis).
        Faster than full build.
        """
        sections = []
        
        if device_states:
            sections.append(self._format_device_states(device_states))
        
        if home_state:
            sections.append(self._format_home_state(home_state, datetime.now()))
        
        # Just last 3 conversation turns
        recent = self.conversations.get_last_n(3)
        if recent:
            lines = ["### Recent"]
            for msg in recent:
                lines.append(f"- {msg['role']}: {msg['content'][:100]}")
            sections.append("\n".join(lines))
        
        return "\n\n".join(sections)
