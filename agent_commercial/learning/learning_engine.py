"""
BMS Learning Engine - Titans Architecture for Ops Copilot
==========================================================

Periodic learning cycle that analyzes operator behavior and generates
optimization suggestions. Implements the Titans architecture for BMS:

1. PATTERN DETECTION: Analyze alarm responses, queries, energy patterns
2. LESSON EXTRACTION: Use LLM to identify actionable insights
3. AUTOMATION SUGGESTIONS: Propose schedule/rule changes
4. FEW-SHOT LEARNING: Store successful patterns for future use

The learning engine runs periodically (default: every 30 minutes) and:
- Analyzes recent operator interactions
- Detects repeating patterns (e.g., "always silences comfort alarms at 9am")
- Proposes automations or priority adjustments
- Stores lessons in database
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from agent_commercial.database import get_database
from agent_commercial.learning.operator_patterns import get_pattern_store

logger = logging.getLogger("arvis.bms.learning.engine")


# ═══════════════════════════════════════════════════════════════════════════
# LEARNING SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════

LEARNING_SYSTEM_PROMPT = """
You are ARVIS Ops Copilot's Learning Module.

Your job is to analyze operator behavior patterns in a commercial building
and suggest optimizations that reduce alarm fatigue and save energy.

## Input You Receive
- Recent alarm history with operator responses
- Operator query patterns
- Energy usage patterns
- Current automation rules

## Patterns to Detect

1. **ALARM FATIGUE PATTERNS**
   - Alarms always silenced without action → suggest priority reduction
   - Same alarm recurring daily → suggest root cause investigation
   - Alarms clustered at specific times → suggest schedule adjustment

2. **ENERGY WASTE PATTERNS**
   - After-hours HVAC running without acknowledgment → suggest schedule fix
   - Same zones flagged for ghost operations → suggest occupancy schedule update

3. **OPERATOR PREFERENCE PATTERNS**
   - Consistent setpoint adjustments → suggest baseline change
   - Frequently queried equipment → add to quick-access dashboard

## Output Format
Return JSON array of suggestions:
[
  {
    "type": "alarm_priority",
    "action": "reduce",
    "target": "AHU-01 filter alarms",
    "reason": "Silenced 15 times this week without action"
  },
  {
    "type": "schedule",
    "action": "extend",
    "target": "HVAC Zone 3",
    "reason": "Operator manually extends every day at 6pm"
  }
]

## Constraints
- Only suggest changes backed by 3+ occurrences
- Never suggest safety-critical priority reductions
- Be conservative - operators know their building
"""


class BMSLearningEngine:
    """
    Learning engine for ARVIS Ops Copilot.
    
    Implements the Titans architecture:
    - Periodic pattern detection
    - LLM-based lesson extraction
    - Few-shot pattern storage
    
    Example:
        >>> engine = BMSLearningEngine(interval_minutes=30)
        >>> await engine.start()
        >>> # Engine now runs learning cycles every 30 minutes
    """
    
    def __init__(
        self,
        interval_minutes: int = 30,
        history_limit: int = 200,
        llm_agent=None,
    ):
        """
        Initialize learning engine.
        
        Args:
            interval_minutes: How often to run learning cycles
            history_limit: How many recent events to analyze
            llm_agent: BMSLLMAgent instance for generation
        """
        self.interval_seconds = interval_minutes * 60
        self.history_limit = history_limit
        self.llm_agent = llm_agent
        
        self.db = get_database()
        self.pattern_store = get_pattern_store()
        
        self._running = False
        self._task = None
        self._last_run = 0.0
        
        # Store learned suggestions
        self._pending_suggestions: List[Dict] = []
        
        logger.info(f"[LearningEngine] Initialized with {interval_minutes}min cycle")
    
    def set_llm_agent(self, agent):
        """Set the LLM agent for generation."""
        self.llm_agent = agent
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def start(self):
        """Start the periodic learning loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._learning_loop())
        logger.info("[LearningEngine] Started periodic learning loop")
    
    async def stop(self):
        """Stop the learning loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[LearningEngine] Stopped")
    
    async def _learning_loop(self):
        """Background loop for periodic learning."""
        while self._running:
            try:
                now = time.time()
                
                if now - self._last_run >= self.interval_seconds:
                    self._last_run = now
                    await self.run_learning_cycle()
                
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[LearningEngine] Loop error: {e}")
                await asyncio.sleep(60)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN LEARNING CYCLE
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def run_learning_cycle(self) -> Dict[str, Any]:
        """
        Run a single learning cycle.
        
        Returns:
            Summary of patterns found and suggestions generated
        """
        logger.info("[LearningEngine] 🧠 Running learning cycle...")
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "patterns_found": 0,
            "suggestions": [],
            "lessons_stored": 0,
        }
        
        try:
            # 1. Gather recent data
            context = await self._gather_learning_context()
            
            if not context.get("has_data"):
                logger.info("[LearningEngine] No recent data to analyze")
                return results
            
            # 2. Analyze patterns locally (rule-based)
            local_patterns = self._analyze_patterns_local(context)
            results["patterns_found"] = len(local_patterns)
            
            # 3. If LLM available, get deeper insights
            if self.llm_agent and local_patterns:
                suggestions = await self._generate_suggestions(context, local_patterns)
                results["suggestions"] = suggestions
                self._pending_suggestions.extend(suggestions)
            
            # 4. Store lessons in database
            for pattern in local_patterns:
                await self._store_lesson(pattern)
                results["lessons_stored"] += 1
            
            logger.info(
                f"[LearningEngine] Cycle complete: "
                f"{results['patterns_found']} patterns, "
                f"{len(results['suggestions'])} suggestions"
            )
            
        except Exception as e:
            logger.error(f"[LearningEngine] Cycle failed: {e}")
            results["error"] = str(e)
        
        return results
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DATA GATHERING
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _gather_learning_context(self) -> Dict:
        """Gather recent data for analysis."""
        context = {
            "has_data": False,
            "alarms": [],
            "energy_readings": [],
            "query_patterns": [],
        }
        
        # Get recent alarms from database
        alarms = await self.db.get_active_alarms()
        context["alarms"] = alarms
        
        # Get alarm response patterns
        pattern_stats = self.pattern_store.get_stats()
        context["pattern_stats"] = pattern_stats
        
        # Get query patterns (top similar queries)
        if self.pattern_store.query_collection:
            try:
                all_queries = self.pattern_store.query_collection.get(
                    include=['documents', 'metadatas'],
                    limit=self.history_limit
                )
                if all_queries and all_queries.get('documents'):
                    context["query_patterns"] = [
                        {
                            "query": doc,
                            "tool": meta.get('tool', 'unknown'),
                            "quality": meta.get('response_quality', 'unknown'),
                        }
                        for doc, meta in zip(
                            all_queries['documents'],
                            all_queries.get('metadatas', [{}] * len(all_queries['documents']))
                        )
                    ]
            except Exception as e:
                logger.warning(f"[LearningEngine] Failed to get query patterns: {e}")
        
        context["has_data"] = bool(alarms or context["query_patterns"])
        
        return context
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PATTERN ANALYSIS (LOCAL/RULE-BASED)
    # ═══════════════════════════════════════════════════════════════════════════
    
    def _analyze_patterns_local(self, context: Dict) -> List[Dict]:
        """
        Analyze patterns using local rules (no LLM needed).
        
        Returns list of detected patterns.
        """
        patterns = []
        
        # Pattern 1: Frequently silenced alarms
        alarm_counts = {}
        for alarm in context.get("alarms", []):
            key = f"{alarm.get('equipment_id')}:{alarm.get('message')}"
            alarm_counts[key] = alarm_counts.get(key, 0) + 1
        
        for key, count in alarm_counts.items():
            if count >= 3:
                equipment_id, message = key.split(":", 1)
                patterns.append({
                    "type": "recurring_alarm",
                    "equipment_id": equipment_id,
                    "message": message,
                    "count": count,
                    "suggestion": f"Consider investigating root cause or adjusting priority",
                })
        
        # Pattern 2: Tool usage patterns
        tool_counts = {}
        for query in context.get("query_patterns", []):
            tool = query.get("tool", "unknown")
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
        
        most_used = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        if most_used:
            patterns.append({
                "type": "frequent_tools",
                "tools": [{"tool": t, "count": c} for t, c in most_used],
                "suggestion": "Consider adding quick-access shortcuts for these operations",
            })
        
        # Pattern 3: Equipment focus
        equipment_focus = {}
        for query in context.get("query_patterns", []):
            eq_id = query.get("equipment_id")
            if eq_id:
                equipment_focus[eq_id] = equipment_focus.get(eq_id, 0) + 1
        
        if equipment_focus:
            top_equipment = max(equipment_focus.items(), key=lambda x: x[1])
            if top_equipment[1] >= 5:
                patterns.append({
                    "type": "equipment_focus",
                    "equipment_id": top_equipment[0],
                    "query_count": top_equipment[1],
                    "suggestion": f"Operator frequently queries {top_equipment[0]} - consider adding to dashboard",
                })
        
        return patterns
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LLM-BASED SUGGESTION GENERATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _generate_suggestions(
        self, 
        context: Dict, 
        local_patterns: List[Dict]
    ) -> List[Dict]:
        """
        Use LLM to generate optimization suggestions.
        
        Args:
            context: Learning context data
            local_patterns: Patterns detected by local analysis
            
        Returns:
            List of suggestion dicts
        """
        if not self.llm_agent:
            return []
        
        try:
            # Build prompt with patterns
            pattern_summary = "\n".join([
                f"- {p['type']}: {p.get('suggestion', '')}"
                for p in local_patterns
            ])
            
            prompt = f"""
Based on these detected patterns in the building:
{pattern_summary}

And this context:
- Active alarms: {len(context.get('alarms', []))}
- Query patterns logged: {len(context.get('query_patterns', []))}

Generate 1-3 specific, actionable suggestions to improve operations.
Focus on reducing alarm fatigue and energy waste.
Return as JSON array.
"""
            
            # Use LLM agent's chat method
            response = await self.llm_agent.chat(prompt, context={"mode": "learning"})
            
            # Parse response for suggestions
            # The response should be in JSON format
            suggestions = []
            if response and hasattr(response, 'response'):
                # Try to extract JSON from response
                import json
                import re
                json_match = re.search(r'\[[\s\S]*\]', response.response)
                if json_match:
                    try:
                        suggestions = json.loads(json_match.group())
                        logger.debug(f"[LearningEngine] Parsed {len(suggestions)} suggestions from LLM")
                    except json.JSONDecodeError as e:
                        logger.warning(f"[LearningEngine] JSON decode error: {e}. Raw: {json_match.group()}")
                else:
                    logger.warning(f"[LearningEngine] No JSON array found in LLM response: {response.response[:200]}...")
            
            return suggestions
            
        except Exception as e:
            logger.error(f"[LearningEngine] LLM suggestion generation failed: {e}")
            return []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # LESSON STORAGE
    # ═══════════════════════════════════════════════════════════════════════════
    
    async def _store_lesson(self, pattern: Dict):
        """Store a learned pattern as a lesson in the suggested_actions table."""
        try:
            import json
            import uuid
            suggestion_id = f"learn_{uuid.uuid4().hex[:8]}"
            conn = await self.db._get_async_connection()
            await conn.execute(
                """INSERT OR IGNORE INTO suggested_actions
                   (suggestion_id, type, target, action, reason, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    suggestion_id,
                    pattern.get("type", "unknown"),
                    pattern.get("equipment_id", pattern.get("target", "")),
                    json.dumps(pattern.get("suggestion", "")),
                    json.dumps(pattern),
                    "pending",
                    datetime.now().isoformat(),
                ),
            )
            await conn.commit()
            logger.debug(f"[LearningEngine] Stored lesson: {pattern['type']} -> {suggestion_id}")
        except Exception as e:
            logger.error(f"[LearningEngine] Failed to store lesson: {e}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # PUBLIC INTERFACE
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_pending_suggestions(self) -> List[Dict]:
        """Get pending optimization suggestions."""
        return self._pending_suggestions.copy()

    def clear_suggestions(self):
        """Clear pending suggestions after they've been acted on."""
        self._pending_suggestions = []

    async def apply_suggestion(self, suggestion_id: str) -> Dict[str, Any]:
        """
        Execute a learning suggestion (with operator notification).

        Marks it as applied and records the application timestamp.
        """
        import json
        try:
            conn = await self.db._get_async_connection()
            async with conn.execute(
                "SELECT type, target, action, reason FROM suggested_actions WHERE suggestion_id = ?",
                (suggestion_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return {"status": "error", "reason": "suggestion not found"}

            stype, target, action_json, reason = row[0], row[1], row[2], row[3]

            await conn.execute(
                "UPDATE suggested_actions SET status = 'applied', applied_at = ? WHERE suggestion_id = ?",
                (datetime.now().isoformat(), suggestion_id),
            )
            await conn.commit()

            logger.info(f"[LearningEngine] Applied suggestion {suggestion_id}: {stype} on {target}")
            return {"status": "applied", "suggestion_id": suggestion_id, "type": stype, "target": target}
        except Exception as e:
            logger.error(f"[LearningEngine] apply_suggestion failed: {e}")
            return {"status": "error", "reason": str(e)}

    async def track_suggestion_outcome(self, suggestion_id: str, metrics_after: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Check if applied suggestion improved metrics (called 7-30 days later).

        Compares pre/post metrics for affected area and records outcome.
        """
        import json
        try:
            conn = await self.db._get_async_connection()
            async with conn.execute(
                "SELECT type, target, applied_at, reason FROM suggested_actions WHERE suggestion_id = ? AND status = 'applied'",
                (suggestion_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return {"status": "error", "reason": "suggestion not found or not applied"}

            stype, target, applied_at, reason_json = row[0], row[1], row[2], row[3]

            outcome = "neutral"
            outcome_metrics = {}

            if metrics_after:
                outcome_metrics = metrics_after
                improvement = metrics_after.get("improvement", 0)
                if improvement > 0.05:
                    outcome = "improved"
                elif improvement < -0.05:
                    outcome = "degraded"

            await conn.execute(
                "UPDATE suggested_actions SET status = 'validated', outcome = ?, outcome_metrics = ? WHERE suggestion_id = ?",
                (outcome, json.dumps(outcome_metrics), suggestion_id),
            )
            await conn.commit()

            logger.info(f"[LearningEngine] Outcome for {suggestion_id}: {outcome}")
            return {"status": "tracked", "suggestion_id": suggestion_id, "outcome": outcome}
        except Exception as e:
            logger.error(f"[LearningEngine] track_outcome failed: {e}")
            return {"status": "error", "reason": str(e)}

    async def calibrate_routing(self) -> Dict[str, Any]:
        """
        Update MetaCognition weights based on suggestion outcomes.

        Suggestions that helped -> boost related node weights.
        Suggestions that degraded -> penalize related node weights.
        """
        try:
            conn = await self.db._get_async_connection()
            async with conn.execute(
                "SELECT type, outcome FROM suggested_actions WHERE status = 'validated' AND outcome IS NOT NULL",
            ) as cursor:
                rows = await cursor.fetchall()
            if not rows:
                return {"status": "no_data"}

            from agent_cognitive.meta_cognition import MetaCognition
            meta = MetaCognition()

            improved = sum(1 for _, o in rows if o == "improved")
            degraded = sum(1 for _, o in rows if o == "degraded")

            for stype, outcome in rows:
                weight_delta = 0.1 if outcome == "improved" else (-0.15 if outcome == "degraded" else 0.0)
                if weight_delta != 0:
                    meta.update_ewc_weights(
                        rule_name=f"learning_{stype}",
                        new_weight=weight_delta,
                        importance=1.5,
                    )

            logger.info(f"[LearningEngine] Calibrated routing: {improved} improved, {degraded} degraded")
            return {"status": "calibrated", "improved": improved, "degraded": degraded, "total": len(rows)}
        except Exception as e:
            logger.error(f"[LearningEngine] calibrate_routing failed: {e}")
            return {"status": "error", "reason": str(e)}
    
    def log_query_success(self, query: str, tool_calls: List[Dict]):
        """Log a successful query for few-shot learning."""
        self.pattern_store.log_query_success(query, tool_calls)
    
    def log_alarm_response(
        self,
        alarm_id: str,
        alarm_type: str,
        equipment_id: str,
        action: str,
        response_time_seconds: float,
        resolved: bool = False
    ):
        """Log an alarm response for pattern learning."""
        self.pattern_store.log_alarm_response(
            alarm_id=alarm_id,
            alarm_type=alarm_type,
            equipment_id=equipment_id,
            action=action,
            response_time_seconds=response_time_seconds,
            resolved=resolved,
        )
    
    def get_fewshot_examples(self, query: str) -> str:
        """Get few-shot examples for a query."""
        patterns = self.pattern_store.get_similar_queries(query)
        return self.pattern_store.format_query_fewshot(patterns)
    
    def get_stats(self) -> Dict:
        """Get learning engine statistics."""
        return {
            "running": self._running,
            "last_run": datetime.fromtimestamp(self._last_run).isoformat() if self._last_run else None,
            "interval_seconds": self.interval_seconds,
            "pending_suggestions": len(self._pending_suggestions),
            "pattern_store": self.pattern_store.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

_learning_engine: Optional[BMSLearningEngine] = None


def get_learning_engine(
    interval_minutes: int = 30,
    llm_agent=None
) -> BMSLearningEngine:
    """Get or create the singleton learning engine instance."""
    global _learning_engine
    
    if _learning_engine is None:
        _learning_engine = BMSLearningEngine(
            interval_minutes=interval_minutes,
            llm_agent=llm_agent,
        )
    elif llm_agent and not _learning_engine.llm_agent:
        _learning_engine.set_llm_agent(llm_agent)
    
    return _learning_engine
