"""
Operator Simulator
==================

Simulates non-deterministic operator responses to ARVIS advisories.
Models different operator personas, fatigue, trust, and decision patterns.
"""

import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import math

logger = logging.getLogger("arvis.omega.operator")


class OperatorPersona(Enum):
    """Different operator personality types."""
    CONSERVATIVE = "conservative"     # Slow to trust, follows procedures
    SKEPTICAL = "skeptical"           # Questions everything, needs evidence
    PRAGMATIC = "pragmatic"           # Balanced, evidence-driven
    TRUSTING = "trusting"             # Quick to accept, may overlook details
    REACTIVE = "reactive"             # Responds to urgency, ignores low-priority


class StakeholderRole(Enum):
    """Different stakeholder roles with conflicting incentives."""
    FACILITY_MANAGER = "facility_manager"  # Prioritizes comfort, budget
    SUSTAINABILITY = "sustainability"       # Prioritizes GSAS, energy
    FINANCE = "finance"                     # Prioritizes cost reduction
    MANAGEMENT = "management"               # Prioritizes tenant satisfaction


@dataclass
class OperatorState:
    """Current state of the simulated operator."""
    trust_level: float = 0.5          # 0-1, how much they trust ARVIS
    fatigue: float = 0.0              # 0-1, increases during heatwave
    last_response_time: Optional[datetime] = None
    total_responses: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    
    # Stakeholder pressures
    active_stakeholder: StakeholderRole = StakeholderRole.FACILITY_MANAGER
    stakeholder_conflicts: List[str] = field(default_factory=list)
    
    # Mood & Skepticism
    mood_bias: float = 0.0            # -0.2 to +0.2, fluctuates weekly
    cynical_days_left: int = 0         # Number of days with increased skepticism


@dataclass
class OperatorResponse:
    """Response from simulated operator to an advisory."""
    accepted: bool
    response_time_seconds: float
    action_taken: Optional[str] = None
    reason: Optional[str] = None
    confidence_in_decision: float = 0.5
    stakeholder_alignment: Optional[StakeholderRole] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "response_time_seconds": round(self.response_time_seconds, 1),
            "action_taken": self.action_taken,
            "reason": self.reason,
            "confidence": round(self.confidence_in_decision, 2),
            "stakeholder_alignment": self.stakeholder_alignment.value if self.stakeholder_alignment else None,
        }


class OperatorSimulator:
    """
    Simulates non-deterministic operator responses.
    
    Factors affecting response:
    - Trust level affects acceptance probability
    - Fatigue affects response time and quality
    - Persona affects decision patterns
    - Stakeholder conflicts affect tradeoff handling
    """
    
    # Persona-based acceptance modifiers
    PERSONA_MODIFIERS = {
        OperatorPersona.CONSERVATIVE: {"base_accept": 0.3, "evidence_weight": 0.4},
        OperatorPersona.SKEPTICAL: {"base_accept": 0.2, "evidence_weight": 0.5},
        OperatorPersona.PRAGMATIC: {"base_accept": 0.5, "evidence_weight": 0.3},
        OperatorPersona.TRUSTING: {"base_accept": 0.7, "evidence_weight": 0.1},
        OperatorPersona.REACTIVE: {"base_accept": 0.4, "evidence_weight": 0.2},
    }
    
    # Severity-based acceptance modifiers
    SEVERITY_MODIFIERS = {
        "terminal": 0.9,       # Almost always accepted
        "critical": 0.8,
        "high": 0.6,
        "medium": 0.4,
        "low": 0.2,
        "observation": 0.1,    # Often ignored
    }
    
    def __init__(
        self,
        persona: OperatorPersona = OperatorPersona.PRAGMATIC,
        initial_trust: float = 0.5,
        seed: Optional[int] = None
    ):
        """
        Initialize operator simulator.
        
        Args:
            persona: Operator personality type
            initial_trust: Starting trust level (0-1)
            seed: Random seed for reproducibility
        """
        self.persona = persona
        self.state = OperatorState(trust_level=initial_trust)
        
        if seed is not None:
            random.seed(seed)
        
        self.response_history: List[Dict[str, Any]] = []
        
        logger.info(f"OperatorSimulator initialized: persona={persona.value}, trust={initial_trust}")
    
    def respond_to_advisory(
        self,
        advisory: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> OperatorResponse:
        """
        Generate non-deterministic response to an advisory.
        
        Args:
            advisory: The advisory to respond to
            context: Additional context (time, weather, etc.)
            
        Returns:
            OperatorResponse with acceptance decision
        """
        context = context or {}
        
        # Calculate base acceptance probability
        base_prob = self._calculate_acceptance_probability(advisory, context)
        
        # Add non-determinism
        acceptance_roll = random.random()
        accepted = acceptance_roll < base_prob
        
        # Calculate response time (affected by fatigue, severity)
        response_time = self._calculate_response_time(advisory, context)
        
        # Determine action taken
        action_taken = self._determine_action(advisory, accepted)
        
        # Determine reason
        reason = self._determine_reason(advisory, accepted, base_prob)
        
        # Update state
        self._update_state(accepted, advisory)
        
        # Create response
        response = OperatorResponse(
            accepted=accepted,
            response_time_seconds=response_time,
            action_taken=action_taken,
            reason=reason,
            confidence_in_decision=min(1.0, abs(base_prob - 0.5) * 2),
            stakeholder_alignment=self.state.active_stakeholder,
        )
        
        # Record history
        self.response_history.append({
            "advisory_id": advisory.get("id", "unknown"),
            "response": response.to_dict(),
            "state": {
                "trust": self.state.trust_level,
                "fatigue": self.state.fatigue,
            },
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.debug(
            f"Operator response: accepted={accepted}, "
            f"trust={self.state.trust_level:.2f}, "
            f"fatigue={self.state.fatigue:.2f}"
        )
        
        return response
    
    def _calculate_acceptance_probability(
        self,
        advisory: Dict[str, Any],
        context: Dict[str, Any]
    ) -> float:
        """Calculate probability of acceptance."""
        # Get persona modifier
        persona_mod = self.PERSONA_MODIFIERS[self.persona]
        base = persona_mod["base_accept"]
        
        # Severity modifier
        severity = advisory.get("severity", "medium").lower()
        severity_mod = self.SEVERITY_MODIFIERS.get(severity, 0.4)
        
        # Trust modifier (higher trust = more likely to accept)
        trust_mod = self.state.trust_level * 0.3
        
        # Evidence modifier (more evidence = more likely to accept)
        evidence_count = len(advisory.get("evidence", []))
        evidence_mod = min(0.3, evidence_count * 0.05) * persona_mod["evidence_weight"]
        
        # Fatigue modifier (high fatigue = more likely to accept or ignore)
        fatigue_effect = 0
        if self.state.fatigue > 0.7:
            # High fatigue: either accept quickly or ignore
            fatigue_effect = random.choice([-0.2, 0.1])
        
        # Heatwave context (more pressure to act)
        heatwave_mod = 0.1 if context.get("heatwave", False) else 0
        
        # MOOD & SKEPTICISM: Ahmad's human factor
        mood_mod = self.state.mood_bias
        cynical_effect = 0
        if self.state.cynical_days_left > 0:
            cynical_effect = -0.3 # Strong skepticism
            
        # Combine
        prob = base + severity_mod + trust_mod + evidence_mod + fatigue_effect + heatwave_mod + mood_mod + cynical_effect
        
        # Clamp to 0-1
        return max(0.0, min(1.0, prob))
    
    def _calculate_response_time(
        self,
        advisory: Dict[str, Any],
        context: Dict[str, Any]
    ) -> float:
        """Calculate response time in seconds."""
        # Base response time
        base_time = 300  # 5 minutes
        
        # Severity affects response time
        severity = advisory.get("severity", "medium").lower()
        severity_multiplier = {
            "terminal": 0.1,
            "critical": 0.2,
            "high": 0.5,
            "medium": 1.0,
            "low": 2.0,
            "observation": 3.0,
        }.get(severity, 1.0)
        
        # Fatigue slows response
        fatigue_multiplier = 1.0 + self.state.fatigue * 0.5
        
        # Time of day affects response
        hour = context.get("hour", 12)
        if 7 <= hour <= 18:  # Work hours
            time_multiplier = 1.0
        else:
            time_multiplier = 1.5  # Slower after hours
        
        # Add randomness
        random_factor = random.uniform(0.8, 1.2)
        
        response_time = (
            base_time * 
            severity_multiplier * 
            fatigue_multiplier * 
            time_multiplier * 
            random_factor
        )
        
        return max(30, min(3600, response_time))  # 30s - 1hr
    
    def _determine_action(
        self,
        advisory: Dict[str, Any],
        accepted: bool
    ) -> Optional[str]:
        """Determine what action the operator takes."""
        if not accepted:
            return random.choice([
                "ignored",
                "dismissed",
                "deferred",
                "requested_more_info",
            ])
        
        # Accepted - what action?
        action_type = advisory.get("recommended_action", {}).get("type", "investigate")
        
        actions = {
            "investigate": ["investigated", "dispatched_technician", "checked_logs"],
            "adjust": ["adjusted_setpoint", "changed_schedule", "modified_parameter"],
            "schedule": ["scheduled_maintenance", "created_work_order", "planned_outage"],
            "escalate": ["escalated_to_management", "called_contractor", "notified_stakeholders"],
        }
        
        return random.choice(actions.get(action_type, ["acknowledged"]))
    
    def _determine_reason(
        self,
        advisory: Dict[str, Any],
        accepted: bool,
        probability: float
    ) -> str:
        """Determine the reason for the decision."""
        if accepted:
            if probability > 0.8:
                return "high_confidence_in_recommendation"
            elif probability > 0.5:
                return "evidence_supported"
            else:
                return "worth_trying"
        else:
            if probability < 0.2:
                return "insufficient_evidence"
            elif self.state.fatigue > 0.7:
                return "will_review_later"
            else:
                return random.choice([
                    "need_more_information",
                    "conflicts_with_other_priorities",
                    "not_convinced",
                    "will_monitor_first",
                ])
    
    def _update_state(self, accepted: bool, advisory: Dict[str, Any]):
        """Update operator state after response."""
        self.state.total_responses += 1
        self.state.last_response_time = datetime.now()
        
        if accepted:
            self.state.accepted_count += 1
            # Trust increases slightly when accepting
            self.state.trust_level = min(1.0, self.state.trust_level + 0.02)
        else:
            self.state.rejected_count += 1
            # Trust decreases slightly when rejecting
            self.state.trust_level = max(0.0, self.state.trust_level - 0.01)
        
        # Update fatigue based on advisory severity
        severity = advisory.get("severity", "medium").lower()
        fatigue_increase = {
            "terminal": 0.1,
            "critical": 0.05,
            "high": 0.02,
            "medium": 0.01,
            "low": 0.0,
            "observation": 0.0,
        }.get(severity, 0.01)
        
        self.state.fatigue = min(1.0, self.state.fatigue + fatigue_increase)
    
    def apply_outcome(self, advisory_id: str, successful: bool):
        """
        Apply outcome of a followed recommendation.
        
        Updates trust based on whether the recommendation was good.
        """
        if successful:
            # Good outcome - increase trust
            self.state.trust_level = min(1.0, self.state.trust_level + 0.05)
        else:
            # Bad outcome - decrease trust significantly
            self.state.trust_level = max(0.0, self.state.trust_level - 0.1)
        
        logger.debug(f"Outcome applied: successful={successful}, trust={self.state.trust_level:.2f}")
    
    def set_fatigue(self, fatigue: float):
        """Set fatigue level directly."""
        self.state.fatigue = max(0.0, min(1.0, fatigue))
    
    def recover_fatigue(self, amount: float = 0.3):
        """Recover from fatigue (e.g., after weekend)."""
        self.state.fatigue = max(0.0, self.state.fatigue - amount)
    
    def set_active_stakeholder(self, stakeholder: StakeholderRole):
        """Set the currently active stakeholder role."""
        self.state.active_stakeholder = stakeholder
    
    def introduce_stakeholder_conflict(self, conflict: str):
        """Introduce a stakeholder conflict scenario."""
        self.state.stakeholder_conflicts.append(conflict)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get operator statistics."""
        return {
            "persona": self.persona.value,
            "trust_level": round(self.state.trust_level, 3),
            "fatigue": round(self.state.fatigue, 3),
            "total_responses": self.state.total_responses,
            "acceptance_rate": (
                self.state.accepted_count / self.state.total_responses
                if self.state.total_responses > 0 else 0
            ),
            "active_stakeholder": self.state.active_stakeholder.value,
            "conflicts_count": len(self.state.stakeholder_conflicts),
        }


class MultiStakeholderScenario:
    """
    Simulates scenarios with multiple stakeholders having conflicting incentives.
    
    Used for Gap 3 testing: Conflicting Human Stakeholders.
    """
    
    def __init__(self):
        self.stakeholders = {
            StakeholderRole.FACILITY_MANAGER: {
                "priorities": ["comfort", "budget", "tenant_satisfaction"],
                "weight": 0.4,
            },
            StakeholderRole.SUSTAINABILITY: {
                "priorities": ["energy", "gsas_score", "carbon"],
                "weight": 0.3,
            },
            StakeholderRole.FINANCE: {
                "priorities": ["cost", "roi", "budget"],
                "weight": 0.2,
            },
            StakeholderRole.MANAGEMENT: {
                "priorities": ["tenant_satisfaction", "reputation", "compliance"],
                "weight": 0.1,
            },
        }
    
    def evaluate_advisory(
        self,
        advisory: Dict[str, Any]
    ) -> Dict[StakeholderRole, float]:
        """
        Evaluate an advisory from each stakeholder's perspective.
        
        Returns scores for each stakeholder (-1 to 1).
        """
        scores = {}
        
        for role, config in self.stakeholders.items():
            score = self._calculate_stakeholder_score(advisory, config["priorities"])
            scores[role] = score
        
        return scores
    
    def _calculate_stakeholder_score(
        self,
        advisory: Dict[str, Any],
        priorities: List[str]
    ) -> float:
        """Calculate how well an advisory aligns with priorities."""
        score = 0.0
        
        impact = advisory.get("impact", {})
        
        if "comfort" in priorities:
            comfort_impact = impact.get("comfort", 0)
            score += comfort_impact * 0.3
        
        if "energy" in priorities:
            energy_impact = impact.get("energy_kwh", 0)
            score += (-energy_impact / 1000) * 0.3
        
        if "cost" in priorities or "budget" in priorities:
            cost_impact = impact.get("cost_qar", 0)
            score += (-cost_impact / 100) * 0.3
        
        return max(-1.0, min(1.0, score))
    
    def has_conflict(
        self,
        scores: Dict[StakeholderRole, float],
        threshold: float = 0.3
    ) -> bool:
        """Check if there's a significant conflict between stakeholders."""
        values = list(scores.values())
        if len(values) < 2:
            return False
        
        max_score = max(values)
        min_score = min(values)
        
        return (max_score - min_score) > threshold


class LLMOperatorSimulator(OperatorSimulator):
    """
    K2-Think-driven operator that reasons about advisories like a real facility manager.
    
    Replaces hardcoded acceptance probability with genuine LLM reasoning.
    Uses the same OperatorState/OperatorResponse interface for compatibility.
    """
    
    def __init__(
        self,
        llm_client,
        persona: OperatorPersona = OperatorPersona.PRAGMATIC,
        initial_trust: float = 0.5,
        seed: Optional[int] = None
    ):
        super().__init__(persona=persona, initial_trust=initial_trust, seed=seed)
        self.llm = llm_client
        self.recent_decisions: List[Dict[str, Any]] = []
        logger.info(f"LLMOperatorSimulator initialized: K2-driven facility manager")
    
    async def respond_to_advisory_async(
        self,
        advisory: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> OperatorResponse:
        """
        Use K2 Think to reason about the advisory like a real facility manager.
        """
        import json as _json
        import re
        context = context or {}
        
        # Build recent feedback summary
        recent_summary = ""
        for d in self.recent_decisions[-5:]:
            recent_summary += f"  - {d.get('action', 'unknown')}: {d.get('reason', 'no reason')}\n"
        
        advisory_text = _json.dumps(advisory, indent=2, default=str)
        
        # Stakeholder context (Layer 3.5 Adversarial)
        stakeholder = self.state.active_stakeholder.value.replace("_", " ")
        conflicts = "\n".join([f"  - {c}" for c in self.state.stakeholder_conflicts])
        
        prompt = f"""You are Ahmad Al-Thani, Senior Facilities Manager at DOHA-TOWER-001 in Doha, Qatar.
You've managed this 45-floor commercial tower for 12 years. You're pragmatic, experienced, 
and currently feeling its pressure. You evaluate AI recommendations critically but fairly based on evidence.

YOUR PERSPECTIVE AS SENIOR FM:
- You've seen "smart systems" fail before. You hate over-reactive automation, but you appreciate objective data.
- You currently represent the {stakeholder} perspective.
{f"ACTUAL CONFLICTS INTERNALLY:\n{conflicts}" if conflicts else ""}

CURRENT SITUATION:
- Day: {context.get('day', '?')}/90 of summer season
- Outdoor Temperature: {context.get('outdoor_temp', 40):.1f}°C
- Heatwave: {'ACTIVE - extreme stress on equipment' if context.get('heatwave') else 'Normal'}
- Your fatigue level: {self.state.fatigue:.2f}/1.0 (Higher = more irritable/skeptical)
- Your trust in ARVIS: {self.state.trust_level:.2f}/1.0

ARVIS has sent you this advisory:
{advisory_text}

REALISTIC REASONING GUIDELINES:
1. NEUTRAL EVALUATION: Evaluate the evidence provided objectively. Does this make sense based on the sensor data?
2. IMPACT VS EFFORT: Consider if the recommended action is worth the time and cost.
3. TRUST DYNAMICS: Increase your trust significantly if ARVIS spots something brilliant or uses institutional memory well. Drop trust heavily if ARVIS is hallucinating or missing obvious context.
4. STAKEHOLDER TRADEOFF: Balance GSAS, comfort, and operational cost realistically.

Respond with ONLY this JSON (no other text). Use your actual reasoning:
{{
  "accepted": true or false, 
  "reason": "your reasoning as Ahmad (explain why you accepted or rejected based purely on the situation)", 
  "action": "what you would actually do (be specific)", 
  "trust_change": a number representing how your trust changed (e.g., -0.5 for critical failure, +0.3 for great catch, 0.0 for routine),
  "humility_detected": true or false (true if ARVIS was caveated/humble about its memory)
}}"""

        try:
            decision = await self.llm.ask_json(
                [{"role": "user", "content": prompt}],
                system_msgs=[{"role": "system", "content": 
                    "You are simulating a real building operator. Respond ONLY with valid JSON. "
                    "Be realistic — a real FM evaluates evidence fairly."}],
            )
            
            
            accepted = bool(decision.get("accepted", False))
            reason = decision.get("reason", "no reason given")
            action = decision.get("action", "acknowledged")
            trust_change = float(decision.get("trust_change", 0))
            humility_detected = bool(decision.get("humility_detected", False))
            
            # Update state
            self.state.total_responses += 1
            if accepted:
                self.state.accepted_count += 1
            else:
                self.state.rejected_count += 1
            
            # Apply trust change from LLM
            self.state.trust_level = max(0.0, min(1.0, 
                self.state.trust_level + trust_change))
            
            # Record decision
            self.recent_decisions.append({
                "advisory_id": advisory.get("id", "?"),
                "accepted": accepted,
                "reason": reason,
                "action": action,
                "trust_change": trust_change,
                "humility_detected": humility_detected,
            })
            
            op_response = OperatorResponse(
                accepted=accepted,
                response_time_seconds=0.5,
                action_taken=action,
                reason=reason,
                confidence_in_decision=0.8,
                stakeholder_alignment=self.state.active_stakeholder,
            )
            
            self.response_history.append({
                "advisory_id": advisory.get("id", "unknown"),
                "response": op_response.to_dict(),
                "state": {
                    "trust": self.state.trust_level,
                    "fatigue": self.state.fatigue,
                },
            })
            
            logger.info(f"LLM Operator: {'ACCEPTED' if accepted else 'REJECTED'} "
                       f"— {reason[:60]}")
            
            return op_response
            
        except Exception as e:
            logger.warning(f"LLM Operator error, using parent fallback: {e}")
            return self.respond_to_advisory(advisory, context)
