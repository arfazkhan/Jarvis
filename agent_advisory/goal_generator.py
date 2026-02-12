"""
Autonomous Goal Generator
=========================

Generates proactive goals for building operators by analyzing data from
Fleet Intelligence, Predictive Maintenance, and Energy Analysis engines.

Goals are prioritized opportunities or risks that the operator should address,
such as "Prevent Chiller Failure" or "Reduce Energy Waste by 15%".
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

# Import data models from other engines
from agent_bms.fleet_intelligence import FleetIntelligence, BenchmarkResult
from agent_bms.predictive_maintenance import PredictiveMaintenanceEngine, FailurePrediction
from agent_bms.energy_analyzer import EnergyAnalyzer, WastePattern

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
        world_model: Optional[Any] = None # Avoiding circular import or using WorldModel type
    ):
        self.fleet = fleet_intelligence
        self.predictive = predictive_engine
        self.energy = energy_analyzer
        self.world_model = world_model
        self.scorer = GoalScorer()
        
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
            
        # 4. Filter and Validate with World Model (if available)
        if self.world_model:
            # We assume current building state can be retrieved
            # For this prototype: Assume building_id has a current state we can mock
            # In production: self.world_model.transition_model.fe.get_current_state(building_id)
            current_state = {"total_power_kw": 450, "zone_temp_avg_c": 24.0, "outdoor_temp_c": 42.0}
            
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

        # Sort by score (descending)
        goals.sort(key=lambda g: g.score, reverse=True)
        
        return goals

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
            if not history:
                continue
                
            latest_features = history[-1]
            
            # Predict
            prediction = self.predictive.predict_failure(eq_id, latest_features)
            
            if prediction.risk_level in ["critical", "high"]:
                goal_id = str(uuid.uuid4())
                
                # Calculate urgency based on RUL
                rul = prediction.predicted_rul_days
                urgency = max(1, rul) if rul != -1 else (3 if prediction.risk_level == "critical" else 14)
                
                # Calculate potential impact (avoided cost of failure)
                # Placeholder: Critical failure costs QAR 20,000 to fix vs QAR 2,000 maintenance
                avoided_cost = 18000 
                
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
                        # EUI gap * size * rate (simplified)
                        savings = 50000 # Placeholder for calculated savings
                        
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

