
import logging
import json
import uuid
import time
from typing import Dict, Any, List, Set, Optional
from agent_advisory.database import AdvisoryDatabase

logger = logging.getLogger("arvis.advisory.economy")

STOP_WORDS = {"alert", "at", "due", "to", "a", "the", "on", "is", "of", "and", "in", "it", "with", "as", "for", "was", "were", "be", "has", "have", "had", "been", "by", "from", "up", "out", "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "should", "now"}

class ToolEconomyPolicy:
    """
    Data-driven policy for tool economy. 
    Prioritizes surgical precision (minimal tools).
    """
    
    def __init__(self, db_path: Optional[str] = None):
        self.db = AdvisoryDatabase(db_path)
        self.min_utility_threshold = 0.6 # High quality requirement
        
    async def record_utility(self, query: str, site_type: str, tool_calls: List[Dict], tool_results: List[Any]):
        """
        Record the utility of a tool chain, with a heavy penalty for length.
        """
        if not tool_calls:
            return

        count = len(tool_calls)
        data_points = 0
        for res in tool_results:
             if isinstance(res, list): data_points += len(res)
             elif isinstance(res, dict): 
                 data_points += sum(1 for v in res.values() if v is not None and v != "")
             elif res: data_points += 1
        
        # Base utility: did we get data?
        raw_utility = min(1.0, data_points / count) if count > 0 else 0
        
        # Economy multiplier: penalize > 3 tools
        # 3 tools = 1.0x, 6 tools = 0.5x, 9 tools = 0.3x
        economy_multiplier = 3.0 / max(3.0, count)
        
        utility = raw_utility * economy_multiplier
        
        try:
            await self.db.execute(
                "INSERT INTO economy_trajectories (id, timestamp, query, site_type, tool_chain, utility_score, data_density) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), time.time(), query, site_type, json.dumps([t['tool'] for t in tool_calls]), utility, data_points)
            )
            logger.info(f"[EconomyPolicy] Recorded trajectory for '{site_type}/{query[:30]}...' Score: {utility:.2f} (Tools: {count})")
        except Exception as e:
            logger.error(f"[EconomyPolicy] Failed to record utility: {e}")

    async def get_minimal_sufficient_set(self, query: str, context: Optional[Dict] = None, urgency: str = "normal") -> Set[str]:
        """
        Predicts minimal sufficient set using context-filtered k-NN.
        Adapts to urgency:
        - normal: Strict economy (min_utility 0.6)
        - high: Relaxed (min_utility 0.4, max 10 tools)
        - critical: Analysis paralysis prevention (return broader set)
        """
        query_lower = query.lower()
        site_type = context.get('site_type') if context else None
        
        # Adaptive Thresholds
        threshold = self.min_utility_threshold
        if urgency == "high":
            threshold = 0.4
        elif urgency == "critical":
            threshold = 0.2
            
        query_words = {w for w in query_lower.split() if w not in STOP_WORDS and len(w) > 2}
        
        try:
            if site_type:
                similar = await self.db.fetch_all("SELECT query, tool_chain, utility_score FROM economy_trajectories WHERE site_type = ?", (site_type,))
            else:
                similar = await self.db.fetch_all("SELECT query, tool_chain, utility_score FROM economy_trajectories")
        except Exception:
            similar = []
            
        best_tools = set()
        max_overlap = 0
        best_utility = 0
        
        for traj in similar:
            traj_words = {w for w in traj['query'].lower().split() if w not in STOP_WORDS and len(w) > 2}
            overlap = len(query_words.intersection(traj_words))
            
            # Match strictly on overlap and THEN utility
            if overlap >= 2:
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_utility = traj['utility_score']
                    best_tools = set(json.loads(traj['tool_chain']))
                elif overlap == max_overlap and traj['utility_score'] > best_utility:
                    # Same overlap, but this one is more surgical (higher utility score)
                    best_utility = traj['utility_score']
                    best_tools = set(json.loads(traj['tool_chain']))
        
        # Only use history if it's high quality and good overlap
        if not best_tools or best_utility < threshold:
            # Fallback
            candidates = set(self._get_category_candidates(query_lower))
            if urgency in ("high", "critical"):
                 # Expand candidates for high urgency
                 candidates.update(self._get_safety_candidates())
            

            return candidates
            
        logger.info(f"[EconomyPolicy] Inferred surgical set ({site_type}, urgency={urgency}) Utility: {best_utility:.2f}: {best_tools}")
        

        return best_tools

    def _get_category_candidates(self, query: str) -> List[str]:
        """Strictly 1-2 essential tools fallbacks + Mandatory Tags."""
        candidates = []
        
        # GSAS: Just status and priorities
        if "gsas" in query: 
            candidates.extend(["get_gsas_status", "get_gsas_improvement_priorities"])
        
        # Alarms: Just alarms and status
        if any(w in query for w in ["fault", "failure", "alarm", "trip", "safety", "risk"]): 
            candidates.extend(["get_active_alarms", "get_equipment_status"])
            
        # Energy: Just analysis
        if any(w in query for w in ["energy", "bill", "kwh", "cost"]): 
            candidates.extend(["analyze_energy", "forecast_energy", "check_cost_impact"])
            
        # Ghost Rooms
        if "ghost" in query or "occupancy" in query:
            candidates.extend(["find_ghost_spaces", "list_equipment", "get_equipment_status"])

        # SOVEREIGN COGNITION (Tier 3)
        if any(w in query for w in ["skill", "memory", "quirk", "learned", "past", "history", "skillbook"]):
            candidates.extend(["query_skillbook", "add_to_skillbook"])
        
        if any(w in query for w in ["fleet", "benchmark", "other tower", "similar building"]):
            candidates.extend(["compare_to_fleet"])
            
        if any(w in query for w in ["simulate", "impact", "what if", "scenario"]):
            candidates.extend(["simulate_change"])
            
        if any(w in query for w in ["life", "rul", "remaining", "wear"]):
            candidates.extend(["predict_remaining_life"])



        return list(set(candidates))

    def _get_safety_candidates(self) -> List[str]:
        """Return broad set of safety tools for critical urgency."""
        return ["get_active_alarms", "get_equipment_status", "get_zone_environment"]

    def _get_safety_candidates(self) -> List[str]:
        """Return broad set of safety tools for critical urgency."""
        return ["get_active_alarms", "get_equipment_status", "get_zone_environment"]
