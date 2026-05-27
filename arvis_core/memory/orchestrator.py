"""
Memory Orchestrator - Unified memory interface
Single entry point for all memory operations.

BMS 7-tier façade methods are at the bottom of this file (query, write,
archive_investigation, recall_for_investigation, get_conversation).
Existing home-automation API (remember/recall/forget/etc.) is preserved.
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
from .types import (
    MemoryTier, MemoryHit, MemoryRecord, RecallBundle,
    ConversationContext, StoreHealth,
)

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
        # Honor ARVIS_MEMORY_DIR env var so test harnesses can redirect
        # T2/T3 episodic+observation+conversation DBs to a per-run isolated
        # directory. Falls back to the constructor argument otherwise.
        import os as _os
        _env_mem = _os.getenv("ARVIS_MEMORY_DIR", "").strip()
        if _env_mem:
            persist_dir = _env_mem
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
            from arvis_core.memory.summarizer import MemorySummarizer
            
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
            from arvis_core.memory.summarizer import MemorySummarizer
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

    # ── BMS 7-Tier Façade ────────────────────────────────────────────────────
    # These methods are the unified interface for the ARVIS production pipeline.
    # Adapters (arvis_core/memory/adapters/) implement the actual tier I/O.

    def _get_adapter(self, tier: MemoryTier):
        """Return adapter for tier, or None if not yet wired."""
        return getattr(self, "_adapters", {}).get(tier)

    def register_adapter(self, tier: MemoryTier, adapter) -> None:
        """Register a tier adapter. Called during app startup."""
        if not hasattr(self, "_adapters"):
            self._adapters: Dict[MemoryTier, Any] = {}
        self._adapters[tier] = adapter
        logger.info(f"[MemoryOrchestrator] Adapter registered for {tier.value}")

    async def query(
        self,
        query: str,
        building_id: str = "",
        tiers: Optional[List[MemoryTier]] = None,
        equipment_filter: Optional[List[str]] = None,
        top_k: int = 5,
        min_relevance: float = 0.4,
    ) -> List[MemoryHit]:
        """
        Federated query across selected tiers, ranked by confidence.
        tiers=None queries all registered adapters.
        Returns empty list (never raises) if adapters not wired yet.
        """
        active_tiers = tiers or list(getattr(self, "_adapters", {}).keys())
        hits: List[MemoryHit] = []
        for tier in active_tiers:
            adapter = self._get_adapter(tier)
            if adapter is None:
                continue
            try:
                tier_hits = await adapter.query(
                    query=query,
                    building_id=building_id,
                    equipment_filter=equipment_filter,
                    top_k=top_k,
                )
                hits.extend(tier_hits)
            except Exception as e:
                logger.debug(f"[MemoryOrchestrator] Tier {tier.value} query failed (non-fatal): {e}")

        hits.sort(key=lambda h: h.confidence, reverse=True)
        return [h for h in hits[:top_k] if h.confidence >= min_relevance]

    async def write(
        self,
        tier: MemoryTier,
        record: MemoryRecord,
        evidence_ids: Optional[List[str]] = None,
    ) -> str:
        """
        Write to a tier. All writes pass through conflict resolver for T3+T5.
        Returns the new record ID, or "" if adapter not wired.
        """
        if evidence_ids:
            record.evidence_ids = evidence_ids

        # Conflict resolution gate for procedural + institutional tiers
        if record.conflict_check and tier in (MemoryTier.T3_PROCEDURAL, MemoryTier.T5_INSTITUTIONAL):
            try:
                from agent_advisory.memory_conflict_resolver import MemoryConflictResolver
                from agent_advisory.goal_generator import ProactiveGoal as _PG
                from datetime import datetime as _dt
                _resolver = MemoryConflictResolver()
                _goal = _PG(
                    goal_id=f"mem_write_{id(record)}",
                    title=record.content[:120],
                    description=record.content,
                    goal_type="optimization" if tier == MemoryTier.T3_PROCEDURAL else "efficiency",
                    priority="medium",
                    score=record.confidence,
                    source_engine="memory_orchestrator",
                    building_id=record.building_id or "",
                    equipment_ids=[],
                    potential_savings_qar=0.0,
                    risk_reduction="",
                    timestamp=_dt.now(),
                )
                _resolution = _resolver.resolve_conflicts([_goal], building_id=record.building_id or "")
                _suppressed = bool(getattr(_resolution, "suppressed_goals", []))
                if _suppressed:
                    logger.info(
                        f"[MemoryOrchestrator] Write suppressed by conflict resolver "
                        f"(tier={tier.value}): {record.content[:80]}"
                    )
                    # Log suppression decision to T2 audit_spans
                    try:
                        _t2 = self._get_adapter(MemoryTier.T2_EPISODIC)
                        if _t2 and hasattr(_t2, "_db") and _t2._db:
                            await _t2._db.save_conversation_turn(
                                operator_id="system",
                                building_id=record.building_id or "",
                                role="system",
                                content=(
                                    f"[CONFLICT_GATE] Write suppressed: tier={tier.value}, "
                                    f"content={record.content[:200]}, "
                                    f"conflicts={len(getattr(_resolution, 'conflicts', []))}"
                                ),
                            )
                    except Exception:
                        pass
                    return ""
                # Log allowed write with conflict annotations if any
                if getattr(_resolution, "conflicts", []):
                    logger.info(
                        f"[MemoryOrchestrator] {len(_resolution.conflicts)} conflict(s) noted "
                        f"but write allowed for: {record.content[:60]}"
                    )
            except Exception as e:
                logger.debug(f"[MemoryOrchestrator] Conflict check skipped (non-fatal): {e}")

        adapter = self._get_adapter(tier)
        if adapter is None:
            logger.debug(f"[MemoryOrchestrator] No adapter for {tier.value} — write skipped")
            return ""
        try:
            return await adapter.write(record)
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] Write to {tier.value} failed: {e}")
            return ""

    async def archive_investigation(self, plan) -> str:
        """
        Persist completed InvestigationPlan to T2 Episodic store.
        Called by queen.execute_swarm() at completion.
        Returns plan.id on success, "" if adapter not wired.
        """
        adapter = self._get_adapter(MemoryTier.T2_EPISODIC)
        if adapter is None:
            logger.debug("[MemoryOrchestrator] T2 adapter not wired — archive skipped")
            return ""
        try:
            return await adapter.archive_plan(plan)
        except Exception as e:
            logger.error(f"[MemoryOrchestrator] archive_investigation failed: {e}")
            return ""

    async def recall_for_investigation(self, plan) -> RecallBundle:
        """
        Auto-recall before any node runs. Queries T2+T3+T5+T6 in parallel.
        Returns RecallBundle (always safe — empty if adapters not wired).
        """
        import asyncio

        query = getattr(plan, "query", "")
        building_id = getattr(plan, "building_id", "")

        async def _safe_query(tier, top_k=3):
            try:
                return await self.query(query, building_id=building_id, tiers=[tier], top_k=top_k)
            except Exception:
                return []

        results = await asyncio.gather(
            _safe_query(MemoryTier.T2_EPISODIC, top_k=3),
            _safe_query(MemoryTier.T5_INSTITUTIONAL, top_k=5),
            _safe_query(MemoryTier.T3_PROCEDURAL, top_k=5),
            _safe_query(MemoryTier.T6_IDENTITY, top_k=3),
            _safe_query(MemoryTier.T7_RESOLUTION, top_k=10),
            return_exceptions=True,
        )

        def _safe(r):
            return r if isinstance(r, list) else []

        alias_map: Dict[str, str] = {}
        for h in _safe(results[4]):
            if h.metadata.get("alias") and h.metadata.get("canonical_id"):
                alias_map[h.metadata["alias"]] = h.metadata["canonical_id"]

        return RecallBundle(
            similar_investigations=_safe(results[0]),
            applicable_skills=_safe(results[1]),
            matching_patterns=_safe(results[2]),
            operator_prefs=_safe(results[3]),
            alias_map=alias_map,
        )

    async def get_conversation(
        self,
        operator_id: str,
        building_id: str,
    ) -> ConversationContext:
        """
        Load T1 working memory for chat(). Returns ConversationContext with
        persisted turns + rolling summary. Empty context if adapter not wired.
        """
        adapter = self._get_adapter(MemoryTier.T1_WORKING)
        if adapter is None:
            return ConversationContext(operator_id=operator_id, building_id=building_id)
        try:
            return await adapter.load_conversation(operator_id, building_id)
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] get_conversation failed (non-fatal): {e}")
            return ConversationContext(operator_id=operator_id, building_id=building_id)

    async def save_conversation_turn(
        self,
        operator_id: str,
        building_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append one turn to T1 working memory."""
        adapter = self._get_adapter(MemoryTier.T1_WORKING)
        if adapter is None:
            return
        try:
            await adapter.append_turn(operator_id, building_id, role, content)
        except Exception as e:
            logger.debug(f"[MemoryOrchestrator] save_conversation_turn failed (non-fatal): {e}")
