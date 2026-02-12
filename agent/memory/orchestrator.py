"""
Memory Orchestrator - Unified memory interface
Single entry point for all memory operations.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from .preference_store import PreferenceStore
from .observation_store import ObservationStore
from .conversation_buffer import ConversationBuffer
from .context_builder import ContextBuilder
from .pattern_store import PatternStore

logger = logging.getLogger(__name__)


class MemoryOrchestrator:
    """
    Unified interface for ARVIS memory system.
    
    Manages:
    - Preferences (long-term, semantic)
    - Observations (medium-term, time-decay)
    - Conversations (short-term, sliding window)
    
    Example:
        memory = MemoryOrchestrator("./data/memories")
        
        # Store preference
        memory.remember("I like 40% brightness", key="brightness", context="evening")
        
        # Get context for LLM
        context = memory.get_context("make it cozy", device_states)
        
        # Recall specific memory
        results = memory.recall("brightness preferences")
    """
    
    def __init__(self, persist_dir: str = "./data/memories",
                 max_conversation_turns: int = 10,
                 observation_decay_days: int = 30):
        """
        Initialize memory system.
        
        Args:
            persist_dir: Directory for persistent storage
            max_conversation_turns: Max turns in conversation buffer
            observation_decay_days: Days before observations expire
        """
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize stores
        self.preferences = PreferenceStore(str(self.persist_dir))
        self.observations = ObservationStore(
            str(self.persist_dir), 
            decay_days=observation_decay_days
        )
        self.conversations = ConversationBuffer(
            str(self.persist_dir),
            max_turns=max_conversation_turns
        )
        
        # Pattern store for few-shot learning (Titans Update loop)
        self.patterns = PatternStore(str(self.persist_dir))
        
        # Context builder
        self.context_builder = ContextBuilder(
            self.preferences,
            self.observations,
            self.conversations
        )
        
        logger.info(f"[MemoryOrchestrator] Initialized at {self.persist_dir}")
    
    # ==================== Pattern Learning (Titans Update Loop) ====================
    
    def log_successful_pattern(self, command: str, tool_calls: list, 
                               resolved_device: str = None) -> bool:
        """
        Log a successful command pattern for few-shot learning.
        Called after local agent successfully handles a command.
        """
        return self.patterns.log_success(command, tool_calls, resolved_device)
    
    def get_similar_patterns(self, command: str, k: int = 3) -> list:
        """Get similar past successful patterns for few-shot injection."""
        return self.patterns.get_similar_patterns(command, k=k)
    
    def format_patterns_for_prompt(self, command: str, k: int = 3) -> str:
        """Get formatted few-shot examples from past patterns."""
        patterns = self.get_similar_patterns(command, k=k)
        return self.patterns.format_as_fewshot(patterns)
    
    # ==================== High-Level API ====================
    
    def remember(self, content: str, memory_type: str = "preference",
                 key: str = None, context: str = "general",
                 importance: float = 0.7, timestamp: Optional[datetime] = None, 
                 **kwargs) -> str:
        """
        Store a memory.
        
        Args:
            content: What to remember
            memory_type: "preference" or "observation"
            key: Key for preferences
            context: When this applies
            importance: How important (0-1)
            timestamp: Optional explicit timestamp
            
        Returns:
            Memory ID
        """
        if memory_type == "preference":
            key = key or f"auto_{(timestamp or datetime.now()).strftime('%Y%m%d%H%M%S')}"
            return self.preferences.add(
                content=content,
                key=key,
                context=context,
                confidence=importance,
                metadata=kwargs
            )
        elif memory_type == "observation":
            return self.observations.add(
                content=content,
                category=context or "routine",
                importance=importance,
                metadata=kwargs,
                timestamp=timestamp
            )
        elif memory_type == "behavior":
            return self.observations.add(
                content=content,
                category="behavior",
                importance=importance,
                metadata=kwargs,
                timestamp=timestamp
            )
        else:
            raise ValueError(f"Unknown memory type: {memory_type}")
    
    def recall(self, query: str, memory_type: str = "all",
               limit: int = 5) -> List[Dict]:
        """
        Search for memories.
        
        Args:
            query: Natural language query
            memory_type: "preferences", "observations", or "all"
            limit: Max results
            
        Returns:
            List of matching memories
        """
        results = []
        
        # DEBUG: Trace call
        print(f"[DEBUG] MemoryOrchestrator.recall called with query='{query}', memory_type='{memory_type}'")
        
        # Normalize memory_type to plural if singular
        if memory_type == "preference": memory_type = "preferences"
        if memory_type == "observation": memory_type = "observations"
        if memory_type == "behavior": memory_type = "behaviors"
        
        if memory_type in ("preferences", "all"):
            pref_matches = self.preferences.search(query, limit=limit)
            for match in pref_matches:
                match['memory_type'] = 'preference'
                results.append(match)
        
        if memory_type in ("observations", "behaviors", "all"):
            obs_matches = self.observations.search(query, limit=limit)
            for match in obs_matches:
                match['memory_type'] = 'observation'
                results.append(match)
        
        # Sort by score/importance
        results.sort(key=lambda x: x.get('score', x.get('importance', 0.5)), 
                    reverse=True)
        
        return results[:limit]
    
    def forget(self, memory_id: str = None, key: str = None,
               memory_type: str = None) -> bool:
        """
        Delete a memory.
        
        Args:
            memory_id: Specific memory ID
            key: Preference key (for preferences)
            memory_type: "preference" or "observation"
            
        Returns:
            Success
        """
        if memory_id:
            if memory_id.startswith("pref_"):
                return self.preferences.delete(memory_id)
            elif memory_id.startswith("obs_"):
                return self.observations.delete(memory_id)
        
        if key and memory_type == "preference":
            return self.preferences.delete_by_key(key)
        
        return False
    
    def add_conversation(self, role: str, content: str):
        """Add a message to conversation history."""
        self.conversations.add(role, content)
    
    def get_context(self, query: str = "",
                    device_states: Optional[Dict] = None,
                    home_state: Optional[Dict] = None) -> str:
        """
        Get full context for LLM call.
        
        Args:
            query: Current user query
            device_states: Current device states
            home_state: presence, sleep_state, etc.
            
        Returns:
            Formatted context string
        """
        return self.context_builder.build(
            query=query,
            device_states=device_states,
            home_state=home_state
        )
    
    def get_quick_context(self, device_states: Optional[Dict] = None,
                          home_state: Optional[Dict] = None) -> str:
        """Get minimal context for simple commands."""
        return self.context_builder.get_quick_context(
            device_states=device_states,
            home_state=home_state
        )
    
    def get_conversation_history(self) -> List[Dict]:
        """Get current conversation context."""
        return self.conversations.get_context()
    
    # ==================== GDPR Compliance ====================
    
    def export_all_data(self) -> Dict:
        """
        Export all user data (GDPR Article 20 - Right to data portability).
        
        Returns:
            Complete data export as dict
        """
        return {
            "preferences": self.preferences.export_all(),
            "observations": self.observations.export_all(),
            "conversations": self.conversations.export_all(),
            "exported_at": datetime.now().isoformat(),
            "version": "1.0"
        }
    
    def delete_all_data(self) -> bool:
        """
        Delete all user data (GDPR Article 17 - Right to erasure).
        
        Returns:
            Success
        """
        try:
            self.preferences.clear_all()
            self.observations.clear_all()
            self.conversations.clear_all()
            logger.info("[MemoryOrchestrator] All user data deleted (GDPR)")
            return True
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] Data deletion failed: {e}")
            return False
    
    # ==================== Maintenance ====================
    
    def cleanup(self):
        """Prune expired observations."""
        self.observations.cleanup()
        logger.info("[MemoryOrchestrator] Cleanup completed.")

    def summarize_history(self, query: str, limit: int = 10) -> str:
        """
        Retrieves recent observations and generates a trend summary.
        """
        try:
            from agent.memory.summarizer import MemorySummarizer
            
            # 1. Recall relevant observations
            obs = self.recall(query, memory_type="observations", limit=limit)
            
            # 1b. Explicitly ensure latest GROUND TRUTH is included
            gts = self.recall("GROUND TRUTH", memory_type="observations", limit=3)
            # Merge and deduplicate
            seen_ids = {o.get('id') for o in obs}
            for gt in gts:
                if gt.get('id') not in seen_ids:
                    obs.append(gt)
            
            # 2. Define patterns we care about for BMS
            patterns = {
                "vibration": r"Vibration: ([\d.]+)",
                "efficiency": r"Efficiency: ([\d.]+)",
                "zone temperature": r"Zone Temp ([\d.]+)",
                "power": r"Power: ([\d.]+)"
            }
            
            # 3. Generate Summary
            trend_text = MemorySummarizer.extract_numerical_trends(obs, patterns)
            conflict_text = MemorySummarizer.summarize_conflicts(obs)
            
            return f"{trend_text}\n{conflict_text}".strip()
            
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] Summary failed: {e}")
            return "Unable to generate history summary."

    def get_inaction_count(self, query: str = "vibration") -> int:
        """Returns the number of cycles a specific recommendation has been ignored."""
        try:
            from agent.memory.summarizer import MemorySummarizer
            obs = self.recall(query, memory_type="observations", limit=15)
            streak = MemorySummarizer.detect_inaction_streak(obs)
            return streak['count'] if streak else 0
        except:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics."""
        return {
            "preferences_count": len(self.preferences.list_all()),
            "observations_count": len(self.observations.get_recent(hours=24*30)),
            "conversation_session": self.conversations.get_session_info(),
            "persist_dir": str(self.persist_dir)
        }
    
    # ==================== Tool Handlers ====================
    
    def handle_log_memory(self, args: Dict) -> str:
        """Handle log_memory tool call from LLM."""
        key = args.get('key', 'auto')
        value = args.get('value', '')
        context = args.get('context', 'general')
        
        memory_id = self.remember(
            content=f"{key}: {value}",
            memory_type="preference",
            key=key,
            context=context
        )
        
        return f"Remembered: {key} = {value}"
    
    def handle_recall_memory(self, args: Dict) -> Dict:
        """Handle recall_memory tool call from LLM."""
        query = args.get('query', '')
        memory_type = args.get('memory_type', 'all')
        limit = args.get('limit', 5)
        
        results = self.recall(query, memory_type, limit)
        
        return {
            "query": query,
            "matches": len(results),
            "results": results
        }
    
    def handle_forget_memory(self, args: Dict) -> str:
        """Handle forget_memory tool call from LLM."""
        memory_id = args.get('memory_id')
        memory_type = args.get('memory_type')
        confirm = args.get('confirm', False)
        
        if not confirm:
            return "Deletion not confirmed. Set confirm=true to delete."
        
        success = self.forget(memory_id=memory_id, memory_type=memory_type)
        
        return "Memory deleted" if success else "Memory not found"
