"""
Preference Learning Engine
===========================

Learns operator preferences from their decisions and overrides.

When operators override ARVIS's recommendations, this is valuable signal:
- What do they value? (comfort vs energy, risk vs reward)
- What patterns do they follow?
- How do their preferences differ from ARVIS's?

This module:
1. Records every decision (agreement or override)
2. Infers preference signals from overrides
3. Stores preferences in vector DB for similarity search
4. Ranks future options by predicted operator preference
"""

import uuid
import time
import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict

from agent_advisory.database import AdvisoryDatabase
from agent_advisory.schemas import OperatorPreference, OutcomeQuality

logger = logging.getLogger("arvis.advisory.preferences")


class PreferenceLearningEngine:
    """
    Learns operator preferences from decisions.
    
    Usage:
        learner = PreferenceLearningEngine()
        
        # When operator makes a decision
        learner.record_decision(
            context={"alarm_type": "high_head_pressure", ...},
            agent_recommendation={"action": "shutdown"},
            operator_choice={"action": "reduce_load"},
            operator_id="john_doe"
        )
        
        # When ranking options for future recommendations
        ranked = learner.rank_options_by_preference(
            context={"alarm_type": "high_head_pressure", ...},
            options=[
                {"action": "shutdown"},
                {"action": "reduce_load"},
                {"action": "investigate"}
            ],
            operator_id="john_doe"
        )
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize preference learner"""
        self.db = AdvisoryDatabase(db_path)
        
        # Try to use ChromaDB for vector storage, fallback to SQLite
        try:
            import chromadb
            self.chroma_client = chromadb.Client()
            self.chroma_collection = self.chroma_client.get_or_create_collection(
                name="operator_preferences"
            )
            self.use_chromadb = True
            logger.info("Preference learner using ChromaDB")
        except ImportError:
            self.use_chromadb = False
            logger.warning("ChromaDB not available - using SQLite fallback")
    
    async def record_decision(
        self,
        context: Dict[str, Any],
        agent_recommendation: Dict[str, Any],
        operator_choice: Dict[str, Any],
        operator_id: str = "unknown",
        building_id: str = "unknown",
        equipment_ids: Optional[List[str]] = None,
        outcome: Optional[OutcomeQuality] = None
    ):
        """
        Record an operator decision (agreement or override).
        
        This is the core learning signal.
        """
        
        # Extract features from context
        features = self._extract_features(context)
        
        # Check if it's an agreement or override
        is_agreement = self._actions_match(
            agent_recommendation,
            operator_choice
        )
        
        # Infer preference signal
        if is_agreement:
            preference_signal = "Operator agreed with recommendation"
            confidence = 0.6  # Moderate signal
        else:
            # Override - strong signal
            preference_signal = self._infer_preference_from_override(
                context,
                agent_recommendation,
                operator_choice
            )
            confidence = 0.8
        
        # Create preference record
        pref = OperatorPreference(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            operator_id=operator_id,
            context_type=features.get("context_type", "unknown"),
            context_features=features,
            agent_recommendation=agent_recommendation,
            operator_choice=operator_choice,
            is_agreement=is_agreement,
            preference_signal=preference_signal,
            confidence=confidence,
            outcome_quality=outcome,
            building_id=building_id,
            equipment_ids=equipment_ids or []
        )
        
        # Store in database
        data = pref.to_dict()
        await self.db.execute(
            """
            INSERT INTO operator_preferences VALUES (
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            tuple(data.values())
        )
        
        # Also store in ChromaDB if available
        if self.use_chromadb:
            # Enriched metadata for better search
            metadata = {
                "operator_id": operator_id,
                "context_type": features.get("context_type", "unknown"),
                "is_agreement": str(is_agreement), # ChromaDB prefers strings for some types
                "timestamp": str(pref.timestamp),
                "building_id": building_id
            }
            # Add features to metadata for filtering
            for k, v in features.items():
                if isinstance(v, (str, int, float, bool)):
                    metadata[f"feat_{k}"] = v
            
            # Chroma is sync in this version, but we should wrap if needed. 
            # Assuming standard chromadb client.
            self.chroma_collection.add(
                documents=[preference_signal],
                metadatas=[metadata],
                ids=[pref.id]
            )
        
        logger.info(
            f"Preference recorded: {operator_id} "
            f"{'agreed' if is_agreement else 'overrode'} - "
            f"{preference_signal}"
        )
    
    async def rank_options_by_preference(
        self,
        context: Dict[str, Any],
        options: List[Dict[str, Any]],
        operator_id: str = "unknown",
        top_k: int = 5
    ) -> List[tuple]:
        """
        Rank options by predicted operator preference.
        
        Returns:
            List of (option, score) tuples, sorted by score descending
        """
        
        if not options:
            return []
        
        # Extract context features
        features = self._extract_features(context)
        
        # Get similar past decisions
        similar_decisions = await self._get_similar_decisions(
            features,
            operator_id,
            k=top_k
        )
        
        if not similar_decisions:
            # No history - return options in original order with equal scores
            return [(opt, 0.5) for opt in options]
        
        # Score each option
        scores = {}
        for option in options:
            # How often did operator choose this type of action in similar contexts?
            matches = sum(
                1 for dec in similar_decisions
                if self._actions_match(dec.operator_choice, option)
            )
            score = matches / len(similar_decisions)
            scores[str(option)] = score
        
        # Sort by score
        ranked = sorted(
            [(opt, scores.get(str(opt), 0.0)) for opt in options],
            key=lambda x: x[1],
            reverse=True
        )
        
        logger.debug(
            f"Ranked {len(options)} options for {operator_id}. "
            f"Top choice: {ranked[0][0]} (score={ranked[0][1]:.2f})"
        )
        
        return ranked
    
    async def get_operator_preferences_summary(
        self,
        operator_id: str,
        window_days: int = 90
    ) -> Dict[str, Any]:
        """
        Get summary of operator's preferences.
        
        Returns insights like:
        - Comfort vs energy preference
        - Risk tolerance
        - Preferred action types
        - Override patterns
        """
        
        cutoff = time.time() - (window_days * 24 * 60 * 60)
        
        prefs = await self.db.fetch_all(
            """
            SELECT * FROM operator_preferences
            WHERE operator_id = ? AND timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (operator_id, cutoff)
        )
        
        if not prefs:
            return {
                "operator_id": operator_id,
                "total_decisions": 0,
                "override_rate": 0.0,
                "insights": []
            }
        
        # Calculate stats
        total = len(prefs)
        overrides = sum(1 for p in prefs if not p["is_agreement"])
        override_rate = overrides / total
        
        # Extract common preference signals
        import json
        from collections import Counter
        
        signals = Counter()
        for p in prefs:
            if not p["is_agreement"]:  # Focus on overrides
                signals[p["preference_signal"]] += 1
        
        top_preferences = [
            {"preference": sig, "count": count}
            for sig, count in signals.most_common(5)
        ]
        
        return {
            "operator_id": operator_id,
            "total_decisions": total,
            "agreement_count": total - overrides,
            "override_count": overrides,
            "override_rate": override_rate,
            "top_preferences": top_preferences,
            "insights": self._generate_insights(prefs)
        }
    
    def _extract_features(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant features from context"""
        
        features = {
            "context_type": "unknown",
            "time_of_day": context.get("time_of_day"),
            "day_of_week": context.get("day_of_week"),
        }
        
        # Determine context type
        if "alarm_type" in context:
            features["context_type"] = "alarm_response"
            features["alarm_type"] = context["alarm_type"]
            features["severity"] = context.get("severity")
        elif "optimization_type" in context:
            features["context_type"] = "energy_optimization"
            features["optimization_type"] = context["optimization_type"]
        elif "maintenance_type" in context:
            features["context_type"] = "maintenance"
            features["maintenance_type"] = context["maintenance_type"]
        
        return features
    
    def _infer_preference_from_override(
        self,
        context: Dict[str, Any],
        agent_rec: Dict[str, Any],
        operator_choice: Dict[str, Any]
    ) -> str:
        """Infer WHY operator chose differently"""
        
        agent_action = agent_rec.get("action", "")
        operator_action = operator_choice.get("action", "")
        
        # Pattern matching for common overrides
        
        # Graceful degradation preference
        if agent_action == "shutdown" and operator_action in ["reduce_load", "reduce_setpoint"]:
            return "Operator prefers graceful degradation over immediate shutdown"
        
        # Risk aversion
        if "investigate" in operator_action and "shutdown" in agent_action:
            return "Operator prefers investigating before taking action"
        
        # Time-based preferences
        hour = context.get("time_of_day", 12)
        if hour < 8 or hour > 18:
            if "defer" in operator_action:
                return "Operator avoids after-hours maintenance/changes"
        
        # Comfort vs energy
        if "comfort" in context.get("impact", ""):
            if "energy" in agent_action and "comfort" in operator_action:
                return "Operator prioritizes comfort over energy savings"
        
        # Generic override
        return f"Operator prefers {operator_action} over {agent_action}"
    
    async def _get_similar_decisions(
        self,
        features: Dict[str, Any],
        operator_id: str,
        k: int = 5
    ) -> List[OperatorPreference]:
        """Get similar past decisions using ChromaDB vector search (or SQL fallback)"""
        
        context_type = features.get("context_type", "unknown")
        
        # 1. Try Vector Search first
        if self.use_chromadb:
            try:
                results = self.chroma_collection.query(
                    query_texts=[features.get("alarm_type", context_type)],
                    n_results=k,
                    where={"operator_id": operator_id}
                )
                
                if results and results["ids"] and results["ids"][0]:
                    ids = results["ids"][0]
                    # Fetch full records from SQLite using the IDs from Chroma
                    placeholders = ", ".join(["?"] * len(ids))
                    prefs_data = await self.db.fetch_all(
                        f"SELECT * FROM operator_preferences WHERE id IN ({placeholders})",
                        tuple(ids)
                    )
                    return self._map_to_objects(prefs_data)
            except Exception as e:
                logger.warning(f"ChromaDB query failed: {e}")
 
        # 2. Fallback to SQL matching
        prefs_data = await self.db.fetch_all(
            """
            SELECT * FROM operator_preferences
            WHERE operator_id = ? AND context_type = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (operator_id, context_type, k)
        )
        return self._map_to_objects(prefs_data)

    def _map_to_objects(self, prefs_data: List[Dict]) -> List[OperatorPreference]:
        """Map raw DB rows to OperatorPreference objects"""
        import json
        prefs = []
        for data in prefs_data:
            prefs.append(OperatorPreference(
                id=data["id"],
                timestamp=data["timestamp"],
                operator_id=data["operator_id"],
                context_type=data["context_type"],
                context_features=json.loads(data["context_features"]),
                agent_recommendation=json.loads(data["agent_recommendation"]),
                operator_choice=json.loads(data["operator_choice"]),
                is_agreement=bool(data["is_agreement"]),
                preference_signal=data["preference_signal"],
                confidence=data["confidence"],
                outcome_quality=OutcomeQuality(data["outcome_quality"]) if data.get("outcome_quality") else None,
                building_id=data.get("building_id", "unknown"),
                equipment_ids=json.loads(data["equipment_ids"]) if data.get("equipment_ids") else []
            ))
        return prefs
    
    def _actions_match(self, action1: Dict, action2: Dict) -> bool:
        """Check if two actions are the same"""
        return action1.get("action") == action2.get("action")
    
    def _generate_insights(self, prefs: List[Dict]) -> List[str]:
        """Generate natural language insights from preferences"""
        
        insights = []
        
        import json
        
        # Override rate insight
        total = len(prefs)
        overrides = sum(1 for p in prefs if not p["is_agreement"])
        override_rate = overrides / total if total > 0 else 0
        
        if override_rate < 0.2:
            insights.append(f"High trust: Operator follows recommendations {(1-override_rate):.0%} of the time")
        elif override_rate > 0.5:
            insights.append(f"Frequent overrides: Operator modifies {override_rate:.0%} of recommendations")
        
        # Common patterns
        signals = {}
        for p in prefs:
            if not p["is_agreement"]:
                sig = p["preference_signal"]
                signals[sig] = signals.get(sig, 0) + 1
        
        if signals:
            most_common = max(signals.items(), key=lambda x: x[1])
            if most_common[1] >= 3:
                insights.append(f"Pattern detected: {most_common[0]}")
        
        return insights
