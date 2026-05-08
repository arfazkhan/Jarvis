"""
Autonomous Goal Generator
=========================

Generates proactive goals for building operators by analyzing data from
Fleet Intelligence, Predictive Maintenance, and Energy Analysis engines.

Goals are prioritized opportunities or risks that the operator should address,
such as "Prevent Chiller Failure" or "Reduce Energy Waste by 15%".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, timedelta

# Import data models from other engines
try:
    from agent_commercial.fleet_intelligence import FleetIntelligence, BenchmarkResult
except Exception:
    FleetIntelligence = Any
    BenchmarkResult = Any

try:
    from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine, FailurePrediction
except Exception:
    PredictiveMaintenanceEngine = Any
    FailurePrediction = Any

try:
    from agent_commercial.energy_analyzer import EnergyAnalyzer, WastePattern
except Exception:
    EnergyAnalyzer = Any
    WastePattern = Any

if TYPE_CHECKING:
    from agent_advisory.memory_conflict_resolver import MemoryConflictResolver
    from agent_advisory.terminal_advisory import TerminalAdvisoryEngine
    from agent_advisory.trust_governor import TrustGovernor
    from agent_commercial.gsas_reporter import GSASReporter

logger = logging.getLogger("arvis.advisory.goals")


@dataclass
class ProactiveGoal:
    """
    A proactive goal for the operator.
    
    Represents a specific objective derived from data analysis,
    such as preventing a failure or capturing an efficiency opportunity.
    """
    goal_id: str
    title: str
    description: str
    goal_type: str  # "risk_mitigation", "efficiency", "compliance", "optimization"
    priority: str   # "critical", "high", "medium", "low"
    score: float    # 0.0 to 1.0 (calculated priority score)
    
    # Context
    source_engine: str  # "predictive", "energy", "fleet"
    building_id: str
    equipment_ids: List[str]
    
    # Impact
    potential_savings_qar: float
    risk_reduction: str
    
    # Actionability
    recommended_deadline: Optional[datetime] = None
    suggested_actions: List[str] = field(default_factory=list)
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Simulation Result (Phase 4: World Model)
    simulated_impact: Dict[str, Any] = field(default_factory=dict) # E.g., {"confidence": 0.85, "predicted_utility": 45.2}

    # GSAS Operationalization
    gsas_impact: Dict[str, Any] = field(default_factory=dict)
    
    # Memory Conflict Annotations (Phase 5: Conflict Resolution)
    memory_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "goal_type": self.goal_type,
            "priority": self.priority,
            "score": round(self.score, 2),
            "source_engine": self.source_engine,
            "building_id": self.building_id,
            "equipment_ids": self.equipment_ids,
            "potential_savings_qar": round(self.potential_savings_qar, 0),
            "risk_reduction": self.risk_reduction,
            "recommended_deadline": self.recommended_deadline.isoformat() if self.recommended_deadline else None,
            "suggested_actions": self.suggested_actions,
            "gsas_impact": self.gsas_impact,
            "timestamp": self.timestamp.isoformat()
        }


class GoalScorer:
    """Helper to calculate priority scores for goals"""
    
    @staticmethod
    def calculate_score(
        goal_type: str,
        potential_savings: float,
        risk_level: str,
        urgency_days: int
    ) -> float:
        """
        Calculate a 0-1 priority score.
        
        Args:
            goal_type: Type of goal
            potential_savings: Annual savings in QAR
            risk_level: "critical", "high", "medium", "low"
            urgency_days: Days until deadline
        """
        score = 0.0
        
        # Base score by type/risk
        if goal_type == "risk_mitigation":
            if risk_level == "critical": score += 0.9
            elif risk_level == "high": score += 0.7
            elif risk_level == "medium": score += 0.5
            else: score += 0.3
        elif goal_type == "efficiency":
            # Scale by savings (capped at QAR 50,000)
            savings_score = min(0.8, potential_savings / 50000)
            score += savings_score
        elif goal_type == "compliance":
            score += 0.6
        else:
            score += 0.4
            
        # Urgency boost
        if urgency_days <= 3:
            score += 0.2
        elif urgency_days <= 7:
            score += 0.1
            
        return min(1.0, score)


class GoalGenerator:
    """
    Generates and prioritizes proactive goals.
    """
    
    def __init__(
        self,
        fleet_intelligence: Optional[FleetIntelligence] = None,
        predictive_engine: Optional[PredictiveMaintenanceEngine] = None,
        energy_analyzer: Optional[EnergyAnalyzer] = None,
        world_model: Optional[Any] = None, # Avoiding circular import or using WorldModel type
        memory_resolver: Optional["MemoryConflictResolver"] = None,
        terminal_engine: Optional["TerminalAdvisoryEngine"] = None,
        trust_governor: Optional["TrustGovernor"] = None,
        gsas_reporter: Optional["GSASReporter"] = None,
    ):
        self.fleet = fleet_intelligence
        self.predictive = predictive_engine
        self.energy = energy_analyzer
        self.world_model = world_model
        self.memory_resolver = memory_resolver
        self.terminal_engine = terminal_engine
        self.trust_governor = trust_governor
        self.gsas_reporter = gsas_reporter
        self.scorer = GoalScorer()
        self._last_resolution = None  # Cache for briefing access
        self._last_terminal_advisory = None  # Cache for briefing access
        
    def get_active_goals(self, category: Optional[str] = None, building_id: str = "default") -> List[Dict[str, Any]]:
        """
        Retrieve active goals as a list of dictionaries for tool consumption.
        
        Args:
            category: Optional filter by goal type
            building_id: Target building (defaults to 'default')
            
        Returns:
            List of dictionaries representing active goals
        """
        goals = self.generate_goals(building_id)
        
        if category:
            goals = [g for g in goals if g.goal_type == category]
            
        return [g.to_dict() for g in goals]
        
    def generate_goals(self, building_id: str) -> List[ProactiveGoal]:
        """
        Generate all proactive goals for a building.
        
        Args:
            building_id: ID of the building to analyze
            
        Returns:
            List of prioritized ProactiveGoal objects
        """
        goals = []
        
        # 1. Harvest goals from Predictive Maintenance (Equipment Risk)
        if self.predictive:
            goals.extend(self._get_predictive_goals(building_id))
            
        # 2. Harvest goals from Energy Analyzer (Waste Reduction)
        if self.energy:
            goals.extend(self._get_energy_goals(building_id))
            
        # 3. Harvest goals from Fleet Intelligence (Optimization)
        if self.fleet:
            goals.extend(self._get_fleet_goals(building_id))

        # 4. Score normal recommendations against GSAS operational targets.
        # Safety-critical terminal advisories remain non-suppressible later.
        if self.gsas_reporter:
            self._apply_gsas_operationalization(goals)
            
        # 5. Filter and Validate with World Model (if available)
        if self.world_model:
            # We assume current building state can be retrieved
            current_state = {"total_power_kw": 0, "zone_temp_avg_c": 23.0, "outdoor_temp_c": 35.0} # fallback
            if hasattr(self.world_model, "get_current_state"):
                try:
                    current_state = self.world_model.get_current_state(building_id)
                except Exception:
                    pass
            
            for goal in goals:
                if goal.suggested_actions:
                    # Pick the primary action
                    action = goal.suggested_actions[0]
                    traj = self.world_model.simulate_action(current_state, action, horizon=4)
                    
                    goal.simulated_impact = {
                        "confidence": sum(traj.confidence_scores) / len(traj.confidence_scores),
                        "predicted_utility": traj.total_reward,
                        "trajectory_len": len(traj.predicted_states)
                    }
                    
                    # Update score based on simulation outcome
                    # If utility is negative (disaster predicted), lower the score
                    if traj.total_reward < -50: # Arbitrary threshold for 'bad'
                        goal.score *= 0.5
                        goal.priority = "medium" if goal.priority == "high" else "low"

        # 6. Memory Conflict Resolution (if resolver available)
        if self.memory_resolver:
            try:
                resolution = self.memory_resolver.resolve_conflicts(goals, building_id)
                self._last_resolution = resolution
                goals = resolution.resolved_goals
                
                # Annotate surviving goals with any related conflicts
                conflict_map = {}
                for conflict in resolution.conflicts:
                    conflict_map.setdefault(conflict.winner_id, []).append(conflict.to_dict())
                
                for goal in goals:
                    if goal.goal_id in conflict_map:
                        goal.memory_conflicts = conflict_map[goal.goal_id]
                
                logger.info(
                    f"[GOALS] Conflict resolution: {resolution.original_count} → {len(goals)} goals, "
                    f"entropy={resolution.entropy_level.value}"
                )
            except Exception as e:
                logger.error(f"[GOALS] Conflict resolution failed (proceeding without): {e}")
        
        # 7. Terminal Advisory Evaluation (non-suppressible)
        if self.terminal_engine:
            try:
                # Get current building state from world model or default
                building_state = {}
                if self.world_model:
                    building_state = getattr(self.world_model, '_current_state', {})

                advisory = self.terminal_engine.evaluate(building_state, building_id)
                self._last_terminal_advisory = advisory

                if advisory:
                    from agent_advisory.terminal_advisory import AdvisorySeverity
                    # Inject TERMINAL goal at top of list — cannot be suppressed
                    terminal_goal = ProactiveGoal(
                        goal_id=f"TERMINAL-{advisory.advisory_id[:8]}",
                        title=f"⛔ TERMINAL ADVISORY: {advisory.severity.value.upper()}",
                        description=advisory.summary,
                        goal_type="safety",
                        priority="critical",
                        score=1.0,       # Always top priority
                        source_engine="terminal_advisory_engine",
                        building_id=building_id,
                        equipment_ids=advisory.affected_equipment,
                        potential_savings_qar=0.0,
                        risk_reduction=f"Critical safety breach: {advisory.severity.value}",
                        suggested_actions=[f"Acknowledge terminal advisory {advisory.advisory_id}"],
                    )
                    goals.insert(0, terminal_goal)  # Always first
                    logger.warning(
                        f"[GOALS] ⛔ Terminal advisory injected: {advisory.severity.value.upper()} "
                        f"(active {advisory.active_duration_str})"
                    )
            except Exception as e:
                logger.error(f"[GOALS] Terminal advisory evaluation failed: {e}")

        # 8. Trust-Weighted Reasoning (confidence dampening + proactive throttle)
        if self.trust_governor:
            try:
                goals = self.trust_governor.apply_to_goals(goals, building_id)
            except Exception as e:
                logger.error(f"[GOALS] Trust governor failed (proceeding without): {e}")

        # Sort by score (descending) — TERMINAL goal stays at top (score=1.0)
        goals.sort(key=lambda g: g.score, reverse=True)
        
        return goals

    def _apply_gsas_operationalization(self, goals: List[ProactiveGoal]) -> None:
        """Annotate and boost recommendations based on GSAS target impact."""
        for goal in goals:
            try:
                impact = self.gsas_reporter.score_operational_recommendation(goal.to_dict())
                impact_dict = impact.to_dict()
                goal.gsas_impact = impact_dict

                # GSAS relevance should affect normal prioritization, but not dominate
                # safety/risk logic. Cap boost to keep operational risk first.
                boost = min(0.15, impact.impact_score * impact.confidence * 0.15)
                if goal.priority not in ("critical",):
                    goal.score = min(1.0, goal.score + boost)

                if impact.criteria:
                    action = (
                        f"Track GSAS impact: {impact.category} "
                        f"({', '.join(impact.criteria)}) target delta +{impact.target_delta:.3f}"
                    )
                    if action not in goal.suggested_actions:
                        goal.suggested_actions.append(action)

            except Exception as e:
                logger.error(f"[GOALS] GSAS operationalization failed for {goal.goal_id}: {e}")

    def _get_predictive_goals(self, building_id: str) -> List[ProactiveGoal]:
        """Generate goals based on predictive maintenance risks"""
        goals = []
        
        # Iterate over known equipment in history
        # (In production obtain full equipment list from BMS state)
        if not self.predictive:
            return goals
            
        equipment_list = list(self.predictive.equipment_history.keys())
        
        for eq_id in equipment_list:
            # Check if this equipment belongs to the target building
            # (Assuming eq_id format like "building/equipment" or filtering logic)
            if "/" in eq_id and not eq_id.startswith(building_id):
                continue
                
            # Get latest features
            history = self.predictive.equipment_history.get(eq_id)
            if not history or not len(history):
                continue
                
            try:
                # Handle both list and dict-like indexing
                latest_features = history[-1] if isinstance(history, list) else list(history.values())[-1]
            except (IndexError, KeyError, AttributeError):
                continue
            
            # Predict
            prediction = self.predictive.predict_failure(eq_id, latest_features)
            
            # Defensive check for prediction result format (handle both objects and dicts)
            risk_level = getattr(prediction, 'risk_level', None)
            if risk_level is None and isinstance(prediction, dict):
                risk_level = prediction.get('risk_level') or prediction.get('risk')
            
            if risk_level in ["critical", "high"]:
                goal_id = str(uuid.uuid4())
                
                # Get RUL from object or dict
                rul = getattr(prediction, 'predicted_rul_days', -1)
                if rul == -1 and isinstance(prediction, dict):
                    rul = prediction.get('predicted_rul_days') or prediction.get('window_days', -1)

                urgency = max(1, rul) if rul != -1 else (3 if risk_level == "critical" else 14)
                
                # Calculate potential impact (avoided cost of failure)
                avoided_cost = getattr(prediction, 'estimated_replacement_cost_qar', None)
                if not avoided_cost and isinstance(prediction, dict):
                    avoided_cost = prediction.get('estimated_replacement_cost_qar')
                if not avoided_cost:
                    # Fallback heuristic based on risk
                    avoided_cost = 25000.0 if risk_level == "critical" else 5000.0
                
                score = self.scorer.calculate_score(
                    goal_type="risk_mitigation",
                    potential_savings=avoided_cost,
                    risk_level=prediction.risk_level,
                    urgency_days=urgency
                )
                
                goals.append(ProactiveGoal(
                    goal_id=goal_id,
                    title=f"Prevent Failure: {eq_id}",
                    description=f"Risk Level: {prediction.risk_level.upper()}. {prediction.recommendation}",
                    goal_type="risk_mitigation",
                    priority=prediction.risk_level,
                    score=score,
                    source_engine="predictive",
                    building_id=building_id,
                    equipment_ids=[eq_id],
                    potential_savings_qar=avoided_cost,
                    risk_reduction=f"Prevents {prediction.risk_level} failure",
                    recommended_deadline=datetime.now() + timedelta(days=urgency),
                    suggested_actions=[prediction.recommendation]
                ))
                
        return goals

    def _get_energy_goals(self, building_id: str) -> List[ProactiveGoal]:
        """Generate goals based on detected energy waste"""
        goals = []
        patterns = self.energy.identify_waste_patterns()
        
        for pattern in patterns:
            # Filter for this building
            if pattern.building_id and pattern.building_id != building_id:
                continue
                
            est = self.energy.estimate_savings(pattern)
            
            # Map pattern to goal
            goal_id = str(uuid.uuid4())
            urgency = 7 if pattern.estimated_waste_qar_annual > 10000 else 30
            
            score = self.scorer.calculate_score(
                goal_type="efficiency",
                potential_savings=est.annual_savings_qar,
                risk_level="low",
                urgency_days=urgency
            )
            
            priority = "high" if score > 0.7 else "medium" if score > 0.4 else "low"
            
            goals.append(ProactiveGoal(
                goal_id=goal_id,
                title=f"Fix {pattern.pattern_type.replace('_', ' ').title()}",
                description=pattern.description,
                goal_type="efficiency",
                priority=priority,
                score=score,
                source_engine="energy",
                building_id=building_id,
                equipment_ids=pattern.equipment_ids,
                potential_savings_qar=est.annual_savings_qar,
                risk_reduction="Reduces operational cost",
                recommended_deadline=datetime.now() + timedelta(days=urgency),
                suggested_actions=[est.recommendation]
            ))
            
        return goals

    def _get_fleet_goals(self, building_id: str) -> List[ProactiveGoal]:
        """Generate goals based on fleet benchmarking gaps"""
        goals = []
        
        # Benchmark available metrics
        try:
            result = self.fleet.benchmark_building(building_id)
            for opp in result.improvement_opportunities:
                # Only create goals for significant gaps (>50th percentile)
                if opp['percentile'] < 40:
                    goal_id = str(uuid.uuid4())
                    
                    # Estimate savings (rough)
                    savings = 0.0
                    if opp['metric'] == 'eui':
                        # EUI gap * area (assume 10k sqm) * rate (0.05 QAR/kWh)
                        savings = abs(opp['gap']) * 10000 * 0.05
                        
                    score = self.scorer.calculate_score(
                        goal_type="optimization",
                        potential_savings=savings,
                        risk_level="low",
                        urgency_days=90 # Strategic goals are long term
                    )
                    
                    goals.append(ProactiveGoal(
                        goal_id=goal_id,
                        title=f"Improve {opp['metric'].upper()} to Fleet Average",
                        description=f"Building is in {opp['percentile']}th percentile. Target: {opp['target']}.",
                        goal_type="optimization",
                        priority="medium", # Strategic/long-term
                        score=score,
                        source_engine="fleet",
                        building_id=building_id,
                        equipment_ids=[],
                        potential_savings_qar=savings,
                        risk_reduction="Improves asset value",
                        recommended_deadline=datetime.now() + timedelta(days=90),
                        suggested_actions=[opp['action']]
                    ))
        except Exception as e:
            logger.error(f"Error generating fleet goals: {e}")
            

        return goals


class GoalDiscoveryEngine:
    """
    Autonomous goal discovery - runs proactively, not on-demand.
    
    Wraps the GoalGenerator to provide a specialized 'proactive' behavior layer.
    """
    
    def __init__(self, 
                 goal_generator: GoalGenerator, 
                 event_bus, 
                 check_interval_seconds: int = 900): # 15 minutes default
        self.generator = goal_generator
        self.event_bus = event_bus
        self.interval = check_interval_seconds
        self.last_run = 0.0
        
        # Track discovered goal IDs to avoid spamming the operator with duplicate alerts
        # In a full clustered production setup, this should be in Redis/DB.
        # For single-node production, memory is sufficient (resets on restart).
        self.known_goals: Dict[str, float] = {} # {id: timestamp}
        
    def run_discovery_cycle(self, building_id: str) -> List[ProactiveGoal]:
        """
        Autonomously discover new goals and publish notifications.
        Should be called periodically by the main loop.
        """
        now = datetime.now().timestamp()
        if now - self.last_run < self.interval:
            return []
            
        self.last_run = now
        logger.info(f"Running autonomous goal discovery for {building_id}...")
        
        try:
            # 1. Generate goals (computationally heavy, effectively backgrounded)
            goals = self.generator.generate_goals(building_id)
            
            new_goals = []
            for goal in goals:
                # Deduplication logic
                # We assume goal_id is deterministic or persisted if the underlying condition persists.
                # However, GoalGenerator creates new UUIDs each time.
                # We must dedupe by 'signature' (Title + Type + Equipment) or rely on generator to be stable.
                # The current generator uses UUIDs, so we must dedupe by content signature.
                signature = f"{goal.building_id}:{goal.goal_type}:{goal.title}:{','.join(sorted(goal.equipment_ids))}"
                
                # Check if we've seen this recently (last 24 hours)
                if signature in self.known_goals:
                    if now - self.known_goals[signature] < 86400:
                        continue
                        
                # It's new or re-surfaced
                self.known_goals[signature] = now
                new_goals.append(goal)
                
                # Publish Event
                self._notify_operator(goal)
            
            if new_goals:
                logger.info(f"Discovered {len(new_goals)} new proactive goals")
                
            return new_goals
            
        except Exception as e:
            logger.error(f"Error in goal discovery: {e}")
            return []
            
    def _notify_operator(self, goal: ProactiveGoal):
        """Proactively notify operator of discovered goal via EventBus."""
        # Determine notification level
        if goal.score > 0.8:
            urgency = "high"
        elif goal.score > 0.5:
            urgency = "medium"
        else:
            urgency = "low"
            
        # Only notify for medium/high to avoid noise
        if urgency == "low":
            return

        self.event_bus.publish({
            "type": "proactive_goal_discovered",
            "source": "GoalDiscoveryEngine",
            "payload": {
                "goal": goal.to_dict(),
                "message": f"💡 I found an opportunity: {goal.title} (Score: {goal.score:.2f})",
                "urgency": urgency,
                "requires_approval": True
            }
        })
