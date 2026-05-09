"""
ABI™ Verify Loop
================

The missing link in ARVIS intelligence — closes the feedback loop between
recommendations and outcomes.

Why This Matters:
- Without verification, every recommendation is an unvalidated hypothesis
- TrustGovernor has nothing to measure
- OnlineLearner has no ground truth
- ABI™ thesis breaks: no "Learn" → no adaptation

Architecture:
  Recommend → Log → Operator Acts? → Validate → Update Trust/Models
      │                              │
      └── RecommendationRegistry ────┘
                    │
              OutcomeValidator
                    │
              FeedbackProcessor ──→ TrustGovernor
                                 ──→ OnlineLearner
                                 ──→ PredictiveMaintenance

Usage:
    verify_loop = VerifyLoop(state_engine, memory)
    await verify_loop.register_recommendation(rec)
    await verify_loop.check_outcomes()  # Run periodically
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import json
import uuid

logger = logging.getLogger("arvis.verify_loop")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════

class RecommendationStatus(str, Enum):
    """Lifecycle states for a recommendation"""
    PENDING = "pending"           # Generated, not yet shown to operator
    ACKNOWLEDGED = "acknowledged" # Operator saw it
    ACCEPTED = "accepted"         # Operator agreed to act
    REJECTED = "rejected"         # Operator dismissed
    ACTED = "acted"               # Operator took action
    VALIDATED = "validated"       # Outcome verified
    FAILED = "failed"             # Action didn't achieve expected outcome
    EXPIRED = "expired"           # Time window passed without action
    SUPERSEDED = "superseded"     # Newer recommendation replaced this


class OutcomeVerdict(str, Enum):
    """Result of comparing predicted vs actual outcome"""
    SUCCESS = "success"           # Prediction matched reality
    PARTIAL = "partial"           # Partial improvement
    FAILURE = "failure"           # No improvement or worse
    INCONCLUSIVE = "inconclusive" # Cannot determine (missing data)
    TIMEOUT = "timeout"           # Validation window expired


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Recommendation:
    """A tracked recommendation with full lifecycle"""
    recommendation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # What was recommended
    title: str = ""
    description: str = ""
    recommendation_type: str = ""  # "energy", "maintenance", "comfort", "safety"
    priority: str = "medium"       # "critical", "high", "medium", "low"
    
    # Target
    equipment_id: Optional[str] = None
    building_id: Optional[str] = None
    zone_id: Optional[str] = None
    
    # The proposed action
    action_type: str = ""          # "setpoint_change", "maintenance", "override", etc.
    action_params: Dict[str, Any] = field(default_factory=dict)
    
    # Predicted outcome (what ABI™ said would happen)
    predicted_outcome: Dict[str, Any] = field(default_factory=dict)
    # Example: {"energy_savings_kwh": 50, "comfort_improvement": 0.1}
    
    # Confidence and reasoning
    confidence: float = 0.0
    reasoning: str = ""
    sources: List[str] = field(default_factory=list)
    
    # Lifecycle tracking
    status: RecommendationStatus = RecommendationStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    acknowledged_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    acted_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    
    # Validation window (how long to wait for outcome)
    validation_window_hours: float = 24.0
    expires_at: Optional[datetime] = None
    
    # Actual outcome (filled after validation)
    actual_outcome: Dict[str, Any] = field(default_factory=dict)
    outcome_verdict: Optional[OutcomeVerdict] = None
    outcome_error_score: float = 0.0  # 0.0 = perfect match, 1.0 = complete miss
    
    # Who interacted with it
    operator_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    # Feedback for learning
    feedback_notes: str = ""
    
    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(hours=self.validation_window_hours)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "description": self.description,
            "recommendation_type": self.recommendation_type,
            "priority": self.priority,
            "equipment_id": self.equipment_id,
            "status": self.status.value,
            "confidence": self.confidence,
            "predicted_outcome": self.predicted_outcome,
            "actual_outcome": self.actual_outcome,
            "outcome_verdict": self.outcome_verdict.value if self.outcome_verdict else None,
            "outcome_error_score": self.outcome_error_score,
            "created_at": self.created_at.isoformat(),
            "acted_at": self.acted_at.isoformat() if self.acted_at else None,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "operator_id": self.operator_id,
        }


@dataclass
class ValidationResult:
    """Result of validating a recommendation against actual outcome"""
    recommendation_id: str
    verdict: OutcomeVerdict
    error_score: float
    
    # What actually happened
    actual_values: Dict[str, float] = field(default_factory=dict)
    # Example: {"energy_kwh": 445, "comfort_score": 0.85}
    
    # What was predicted
    predicted_values: Dict[str, float] = field(default_factory=dict)
    
    # Per-metric errors
    metric_errors: Dict[str, float] = field(default_factory=dict)
    # Example: {"energy_kwh": 0.10, "comfort_score": 0.05}
    
    # Contributing factors (why prediction was right/wrong)
    factors: List[str] = field(default_factory=list)
    
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "verdict": self.verdict.value,
            "error_score": self.error_score,
            "actual_values": self.actual_values,
            "predicted_values": self.predicted_values,
            "metric_errors": self.metric_errors,
            "factors": self.factors,
            "timestamp": self.timestamp.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# RECOMMENDATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class RecommendationRegistry:
    """
    Persistent storage for recommendations and their lifecycle.
    
    In-memory for MVP, but designed for DB backing (SQLite/Postgres).
    """
    
    def __init__(self, persist_path: Optional[str] = None):
        self.recommendations: Dict[str, Recommendation] = {}
        self.persist_path = persist_path
        
        # Indexes for fast lookup
        self._by_equipment: Dict[str, List[str]] = {}
        self._by_status: Dict[RecommendationStatus, List[str]] = {}
        self._by_type: Dict[str, List[str]] = {}
        
        if persist_path:
            self._load_from_disk()
    
    def register(self, rec: Recommendation) -> str:
        """Add a new recommendation to the registry"""
        self.recommendations[rec.recommendation_id] = rec
        
        # Update indexes
        if rec.equipment_id:
            if rec.equipment_id not in self._by_equipment:
                self._by_equipment[rec.equipment_id] = []
            self._by_equipment[rec.equipment_id].append(rec.recommendation_id)
        
        if rec.status not in self._by_status:
            self._by_status[rec.status] = []
        self._by_status[rec.status].append(rec.recommendation_id)
        
        if rec.recommendation_type:
            if rec.recommendation_type not in self._by_type:
                self._by_type[rec.recommendation_type] = []
            self._by_type[rec.recommendation_type].append(rec.recommendation_id)
        
        if self.persist_path:
            self._save_to_disk()
        
        logger.info(f"Registered recommendation: {rec.recommendation_id} [{rec.recommendation_type}]")
        return rec.recommendation_id
    
    def get(self, recommendation_id: str) -> Optional[Recommendation]:
        """Get a recommendation by ID"""
        return self.recommendations.get(recommendation_id)
    
    def update(self, rec: Recommendation) -> None:
        """Update an existing recommendation"""
        if rec.recommendation_id not in self.recommendations:
            logger.warning(f"Attempted to update unknown recommendation: {rec.recommendation_id}")
            return
        
        old_rec = self.recommendations[rec.recommendation_id]
        
        # Update status index if changed
        if old_rec.status != rec.status:
            if old_rec.status in self._by_status:
                self._by_status[old_rec.status] = [
                    rid for rid in self._by_status[old_rec.status]
                    if rid != rec.recommendation_id
                ]
            if rec.status not in self._by_status:
                self._by_status[rec.status] = []
            self._by_status[rec.status].append(rec.recommendation_id)
        
        self.recommendations[rec.recommendation_id] = rec
        
        if self.persist_path:
            self._save_to_disk()
    
    def get_pending(self) -> List[Recommendation]:
        """Get all pending recommendations"""
        return [
            self.recommendations[rid]
            for rid in self._by_status.get(RecommendationStatus.PENDING, [])
        ]
    
    def get_acted_unvalidated(self) -> List[Recommendation]:
        """Get recommendations that were acted on but not yet validated"""
        return [
            self.recommendations[rid]
            for rid in self._by_status.get(RecommendationStatus.ACTED, [])
        ]
    
    def get_for_equipment(self, equipment_id: str) -> List[Recommendation]:
        """Get all recommendations for a specific equipment"""
        return [
            self.recommendations[rid]
            for rid in self._by_equipment.get(equipment_id, [])
        ]
    
    def get_recent(self, hours: int = 24, status: Optional[RecommendationStatus] = None) -> List[Recommendation]:
        """Get recommendations from the last N hours, optionally filtered by status"""
        cutoff = datetime.now() - timedelta(hours=hours)
        results = []
        
        for rec in self.recommendations.values():
            if rec.created_at < cutoff:
                continue
            if status and rec.status != status:
                continue
            results.append(rec)
        
        return sorted(results, key=lambda r: r.created_at, reverse=True)
    
    def get_accuracy_stats(self, recommendation_type: Optional[str] = None) -> Dict[str, Any]:
        """Calculate accuracy statistics for validated recommendations"""
        validated = [
            rec for rec in self.recommendations.values()
            if rec.status == RecommendationStatus.VALIDATED
            and (recommendation_type is None or rec.recommendation_type == recommendation_type)
        ]
        
        if not validated:
            return {"count": 0, "accuracy": None}
        
        successes = sum(1 for r in validated if r.outcome_verdict == OutcomeVerdict.SUCCESS)
        partials = sum(1 for r in validated if r.outcome_verdict == OutcomeVerdict.PARTIAL)
        failures = sum(1 for r in validated if r.outcome_verdict == OutcomeVerdict.FAILURE)
        
        return {
            "count": len(validated),
            "successes": successes,
            "partials": partials,
            "failures": failures,
            "accuracy": successes / len(validated) if validated else None,
            "success_or_partial_rate": (successes + partials) / len(validated) if validated else None,
            "avg_error_score": sum(r.outcome_error_score for r in validated) / len(validated),
        }
    
    def _save_to_disk(self):
        """Persist registry to disk"""
        import json
        data = {
            rid: rec.to_dict()
            for rid, rec in self.recommendations.items()
        }
        with open(self.persist_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def _load_from_disk(self):
        """Load registry from disk"""
        import json
        import os
        
        if not os.path.exists(self.persist_path):
            return
        
        try:
            with open(self.persist_path, 'r') as f:
                data = json.load(f)
            
            for rid, rec_dict in data.items():
                # Reconstruct Recommendation from dict
                rec = Recommendation(
                    recommendation_id=rid,
                    title=rec_dict.get("title", ""),
                    description=rec_dict.get("description", ""),
                    recommendation_type=rec_dict.get("recommendation_type", ""),
                    priority=rec_dict.get("priority", "medium"),
                    equipment_id=rec_dict.get("equipment_id"),
                    building_id=rec_dict.get("building_id"),
                    zone_id=rec_dict.get("zone_id"),
                    action_type=rec_dict.get("action_type", ""),
                    action_params=rec_dict.get("action_params", {}),
                    predicted_outcome=rec_dict.get("predicted_outcome", {}),
                    confidence=rec_dict.get("confidence", 0.0),
                    reasoning=rec_dict.get("reasoning", ""),
                    sources=rec_dict.get("sources", []),
                    status=RecommendationStatus(rec_dict.get("status", "pending")),
                    created_at=datetime.fromisoformat(rec_dict["created_at"]) if "created_at" in rec_dict else datetime.now(),
                    operator_id=rec_dict.get("operator_id"),
                    outcome_verdict=OutcomeVerdict(rec_dict["outcome_verdict"]) if rec_dict.get("outcome_verdict") else None,
                    outcome_error_score=rec_dict.get("outcome_error_score", 0.0),
                    actual_outcome=rec_dict.get("actual_outcome", {}),
                )
                self.recommendations[rid] = rec
            
            logger.info(f"Loaded {len(self.recommendations)} recommendations from disk")
        except Exception as e:
            logger.error(f"Failed to load recommendations: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# OUTCOME VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════

class OutcomeValidator:
    """
    Compares predicted outcomes against actual BMS state.
    
    The core of the "Learn" phase — measures if ABI™ was right.
    """
    
    def __init__(self, state_engine: Any, thresholds: Optional[Dict[str, float]] = None):
        self.state_engine = state_engine
        
        # Thresholds for what counts as "close enough"
        self.thresholds = thresholds or {
            "energy_kwh": 0.10,     # 10% tolerance
            "comfort_score": 0.05,  # 5% tolerance
            "temperature_c": 1.0,   # 1°C tolerance
            "pressure_pa": 50.0,    # 50 Pa tolerance
            "power_kw": 0.15,       # 15% tolerance
            "runtime_hours": 0.20,  # 20% tolerance
        }
    
    async def validate(self, rec: Recommendation) -> ValidationResult:
        """
        Compare predicted outcome against actual state.
        
        Returns a ValidationResult with verdict and error scores.
        """
        actual_values = await self._get_current_state(rec)
        predicted_values = rec.predicted_outcome.get("metrics", {})
        
        if not actual_values or not predicted_values:
            return ValidationResult(
                recommendation_id=rec.recommendation_id,
                verdict=OutcomeVerdict.INCONCLUSIVE,
                error_score=1.0,
                actual_values=actual_values,
                predicted_values=predicted_values,
                factors=["Insufficient data for validation"],
            )
        
        # Calculate per-metric errors
        metric_errors = {}
        factors = []
        
        for metric, predicted in predicted_values.items():
            actual = actual_values.get(metric)
            
            if actual is None:
                metric_errors[metric] = 1.0  # Missing = full error
                factors.append(f"Missing actual value for {metric}")
                continue
            
            # Get threshold for this metric
            threshold = self._get_threshold(metric)
            
            # Calculate relative error
            if predicted == 0:
                error = abs(actual) if actual != 0 else 0.0
            else:
                error = abs(actual - predicted) / abs(predicted)
            
            metric_errors[metric] = error
            
            # Add context for significant errors
            if error > threshold:
                factors.append(
                    f"{metric}: predicted {predicted:.2f}, actual {actual:.2f} "
                    f"(error: {error*100:.1f}%, threshold: {threshold*100:.1f}%)"
                )
        
        # Overall error score (average of metric errors)
        overall_error = sum(metric_errors.values()) / len(metric_errors) if metric_errors else 1.0
        
        # Determine verdict
        verdict = self._determine_verdict(overall_error, metric_errors)
        
        return ValidationResult(
            recommendation_id=rec.recommendation_id,
            verdict=verdict,
            error_score=overall_error,
            actual_values=actual_values,
            predicted_values=predicted_values,
            metric_errors=metric_errors,
            factors=factors if factors else ["All metrics within tolerance"],
        )
    
    async def _get_current_state(self, rec: Recommendation) -> Dict[str, float]:
        """Extract current state values relevant to the recommendation"""
        actual = {}
        
        if not self.state_engine:
            return actual
        
        # Get equipment-specific metrics
        if rec.equipment_id:
            points = self.state_engine.get_points_by_equipment(rec.equipment_id)
            for point in points:
                # Map point names to standard metrics
                metric_name = self._map_point_to_metric(point.point_id, point.name)
                if metric_name:
                    actual[metric_name] = point.value
        
        # Get building-level metrics
        if rec.building_id:
            # Energy consumption
            if hasattr(self.state_engine, 'get_energy_summary'):
                summary = self.state_engine.get_energy_summary()
                actual["energy_kwh"] = summary.get("current_kwh", 0)
            
            # Comfort score (if available)
            if hasattr(self.state_engine, 'get_comfort_score'):
                actual["comfort_score"] = self.state_engine.get_comfort_score(rec.building_id)
        
        return actual
    
    def _map_point_to_metric(self, point_id: str, point_name: str) -> Optional[str]:
        """Map a BMS point to a standard metric name"""
        point_lower = (point_id + " " + point_name).lower()
        
        mappings = [
            ("kw", "power_kw"),
            ("kwh", "energy_kwh"),
            ("temp", "temperature_c"),
            ("sat", "supply_air_temp_c"),
            ("rat", "return_air_temp_c"),
            ("chwst", "chilled_water_supply_temp_c"),
 ("chwrt", "chilled_water_return_temp_c"),
            ("pressure", "pressure_pa"),
            ("flow", "flow_rate"),
            ("load", "load_percent"),
            ("efficiency", "efficiency"),
            ("runtime", "runtime_hours"),
        ]
        
        for pattern, metric in mappings:
            if pattern in point_lower:
                return metric
        
        return None
    
    def _get_threshold(self, metric: str) -> float:
        """Get tolerance threshold for a metric"""
        for key, threshold in self.thresholds.items():
            if key in metric:
                return threshold
        return 0.15  # Default 15% tolerance
    
    def _determine_verdict(self, overall_error: float, metric_errors: Dict[str, float]) -> OutcomeVerdict:
        """Determine the overall verdict based on error scores"""
        if overall_error < 0.10:
            # < 10% error = success
            return OutcomeVerdict.SUCCESS
        elif overall_error < 0.25:
            # 10-25% error = partial success
            return OutcomeVerdict.PARTIAL
        elif overall_error < 0.50:
            # 25-50% error = partial (borderline)
            return OutcomeVerdict.PARTIAL
        else:
            # > 50% error = failure
            return OutcomeVerdict.FAILURE


# ═══════════════════════════════════════════════════════════════════════════
# FEEDBACK PROCESSOR
# ═══════════════════════════════════════════════════════════════════════════

class FeedbackProcessor:
    """
    Processes validation results and feeds back into ARVIS learning systems.
    
    Integrates with:
    - TrustGovernor: Adjust trust based on accuracy
    - OnlineLearner: Provide ground truth for model updates
    - PredictiveMaintenance: Update failure prediction models
    """
    
    def __init__(
        self,
        trust_governor: Optional[Any] = None,
        online_learner: Optional[Any] = None,
        memory: Optional[Any] = None,
    ):
        self.trust_governor = trust_governor
        self.online_learner = online_learner
        self.memory = memory
        
        # Callbacks for specific recommendation types
        self._callbacks: Dict[str, List[Callable]] = {}
    
    async def process(self, rec: Recommendation, validation: ValidationResult) -> Dict[str, Any]:
        """
        Process a validated recommendation.
        
        Updates trust, triggers learning, stores memories.
        """
        results = {
            "recommendation_id": rec.recommendation_id,
            "verdict": validation.verdict.value,
            "actions_taken": [],
        }
        
        # 1. Update TrustGovernor
        if self.trust_governor:
            trust_delta = self._calculate_trust_delta(rec, validation)
            await self._update_trust(rec, validation, trust_delta)
            results["trust_delta"] = trust_delta
            results["actions_taken"].append("trust_updated")
        
        # 2. Feed OnlineLearner
        if self.online_learner:
            self._feed_online_learner(rec, validation)
            results["actions_taken"].append("online_learner_updated")
        
        # 3. Store in memory
        if self.memory:
            await self._store_memory(rec, validation)
            results["actions_taken"].append("memory_stored")
        
        # 4. Trigger type-specific callbacks
        if rec.recommendation_type in self._callbacks:
            for callback in self._callbacks[rec.recommendation_type]:
                try:
                    await callback(rec, validation)
                    results["actions_taken"].append(f"callback_{callback.__name__}")
                except Exception as e:
                    logger.error(f"Callback error: {e}")
        
        logger.info(
            f"Processed recommendation {rec.recommendation_id}: "
            f"{validation.verdict.value} (error: {validation.error_score:.2f})"
        )
        
        return results
    
    def _calculate_trust_delta(self, rec: Recommendation, validation: ValidationResult) -> float:
        """
        Calculate how much trust should change based on outcome.
        
        Trust increases for successful predictions, decreases for failures.
        The magnitude depends on confidence and error score.
        """
        base_delta = {
            OutcomeVerdict.SUCCESS: 0.05,
            OutcomeVerdict.PARTIAL: 0.02,
            OutcomeVerdict.FAILURE: -0.10,
            OutcomeVerdict.INCONCLUSIVE: 0.0,
            OutcomeVerdict.TIMEOUT: -0.02,
        }.get(validation.verdict, 0.0)
        
        # Modulate by confidence
        # High confidence + failure = bigger trust penalty
        # Low confidence + success = smaller trust boost
        if base_delta > 0:
            # Success: scale by confidence (high confidence success is more valuable)
            trust_delta = base_delta * rec.confidence
        elif base_delta < 0:
            # Failure: scale by confidence (high confidence failure is more damaging)
            trust_delta = base_delta * rec.confidence
        else:
            trust_delta = 0.0
        
        return trust_delta
    
    async def _update_trust(
        self,
        rec: Recommendation,
        validation: ValidationResult,
        trust_delta: float,
    ) -> None:
        """Update TrustGovernor with the new trust delta"""
        if not self.trust_governor:
            return
        
        try:
            # Record this outcome
            if hasattr(self.trust_governor, 'record_outcome'):
                self.trust_governor.record_outcome(
                    recommendation_type=rec.recommendation_type,
                    verdict=validation.verdict.value,
                    confidence=rec.confidence,
                    error_score=validation.error_score,
                )
            
            # Update trust level
            if hasattr(self.trust_governor, 'adjust_trust'):
                self.trust_governor.adjust_trust(trust_delta)
                
        except Exception as e:
            logger.error(f"Failed to update trust: {e}")
    
    def _feed_online_learner(self, rec: Recommendation, validation: ValidationResult) -> None:
        """Feed ground truth to OnlineLearner"""
        if not self.online_learner:
            return
        
        try:
            # OnlineLearner expects (prediction, actual) pairs
            prediction = rec.predicted_outcome.get("metrics", {})
            actual = validation.actual_values
            
            if prediction and actual:
                self.online_learner.log_observation(prediction, actual)
                
        except Exception as e:
            logger.error(f"Failed to feed online learner: {e}")
    
    async def _store_memory(self, rec: Recommendation, validation: ValidationResult) -> None:
        """Store this experience in ARVIS memory for future reference"""
        if not self.memory:
            return
        
        try:
            # Create a memory entry
            memory_text = (
                f"Recommendation: {rec.title}\n"
                f"Type: {rec.recommendation_type}\n"
                f"Equipment: {rec.equipment_id}\n"
                f"Confidence: {rec.confidence:.2f}\n"
                f"Verdict: {validation.verdict.value}\n"
                f"Error: {validation.error_score:.2f}\n"
                f"Predicted: {validation.predicted_values}\n"
                f"Actual: {validation.actual_values}\n"
            )
            
            if hasattr(self.memory, 'remember'):
                self.memory.remember(
                    memory_text,
                    memory_type="recommendation_outcome",
                    metadata={
                        "recommendation_id": rec.recommendation_id,
                        "verdict": validation.verdict.value,
                        "error_score": validation.error_score,
                        "equipment_id": rec.equipment_id,
                    }
                )
                
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
    
    def register_callback(self, recommendation_type: str, callback: Callable) -> None:
        """Register a callback for a specific recommendation type"""
        if recommendation_type not in self._callbacks:
            self._callbacks[recommendation_type] = []
        self._callbacks[recommendation_type].append(callback)


# ═══════════════════════════════════════════════════════════════════════════
# VERIFY LOOP (MAIN ORCHESTRATOR)
# ═══════════════════════════════════════════════════════════════════════════

class VerifyLoop:
    """
    The main orchestrator for ABI™ feedback loop.
    
    Usage:
        verify_loop = VerifyLoop(state_engine, memory, trust_governor)
        
        # When a recommendation is generated
        await verify_loop.register_recommendation(rec)
        
        # When an operator acknowledges/accepts/rejects
        await verify_loop.acknowledge(rec_id, operator_id)
        await verify_loop.accept(rec_id, operator_id)
        await verify_loop.reject(rec_id, operator_id, reason)
        
        # When an action is taken
        await verify_loop.record_action(rec_id, operator_id, action_details)
        
        # Periodically check outcomes (run as background task)
        await verify_loop.check_outcomes()
        
        # Get statistics
        stats = verify_loop.get_statistics()
    """
    
    def __init__(
        self,
        state_engine: Any,
        memory: Optional[Any] = None,
        trust_governor: Optional[Any] = None,
        online_learner: Optional[Any] = None,
        persist_path: Optional[str] = "data/verify_loop/recommendations.json",
    ):
        self.registry = RecommendationRegistry(persist_path=persist_path)
        self.validator = OutcomeValidator(state_engine)
        self.processor = FeedbackProcessor(
            trust_governor=trust_governor,
            online_learner=online_learner,
            memory=memory,
        )
        
        self.state_engine = state_engine
        self._running = False
        self._check_interval = 300  # 5 minutes
    
    # ─── RECOMMENDATION LIFECYCLE ─────────────────────────────────────────
    
    async def register_recommendation(
        self,
        title: str,
        description: str,
        recommendation_type: str,
        action_type: str,
        predicted_outcome: Dict[str, Any],
        confidence: float,
        equipment_id: Optional[str] = None,
        building_id: Optional[str] = None,
        priority: str = "medium",
        reasoning: str = "",
        sources: Optional[List[str]] = None,
        validation_window_hours: float = 24.0,
    ) -> str:
        """Register a new recommendation"""
        rec = Recommendation(
            title=title,
            description=description,
            recommendation_type=recommendation_type,
            action_type=action_type,
            predicted_outcome=predicted_outcome,
            confidence=confidence,
            equipment_id=equipment_id,
            building_id=building_id,
            priority=priority,
            reasoning=reasoning,
            sources=sources or [],
            validation_window_hours=validation_window_hours,
        )
        
        return self.registry.register(rec)
    
    async def acknowledge(self, recommendation_id: str, operator_id: str) -> bool:
        """Mark recommendation as acknowledged by operator"""
        rec = self.registry.get(recommendation_id)
        if not rec:
            return False
        
        rec.status = RecommendationStatus.ACKNOWLEDGED
        rec.acknowledged_at = datetime.now()
        rec.operator_id = operator_id
        
        self.registry.update(rec)
        return True
    
    async def accept(self, recommendation_id: str, operator_id: str) -> bool:
        """Mark recommendation as accepted (operator will act on it)"""
        rec = self.registry.get(recommendation_id)
        if not rec:
            return False
        
        rec.status = RecommendationStatus.ACCEPTED
        rec.accepted_at = datetime.now()
        rec.operator_id = operator_id
        
        self.registry.update(rec)
        return True
    
    async def reject(
        self,
        recommendation_id: str,
        operator_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Mark recommendation as rejected by operator"""
        rec = self.registry.get(recommendation_id)
        if not rec:
            return False
        
        rec.status = RecommendationStatus.REJECTED
        rec.rejection_reason = reason
        rec.operator_id = operator_id
        
        self.registry.update(rec)
        
        # Rejected recommendations still count for trust calibration
        # (operators may reject because prediction was wrong)
        if reason:
            await self._analyze_rejection(rec, reason)
        
        return True
    
    async def record_action(
        self,
        recommendation_id: str,
        operator_id: str,
        action_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record that an action was taken"""
        rec = self.registry.get(recommendation_id)
        if not rec:
            return False
        
        rec.status = RecommendationStatus.ACTED
        rec.acted_at = datetime.now()
        rec.operator_id = operator_id
        
        if action_details:
            rec.action_params.update(action_details)
        
        self.registry.update(rec)
        
        logger.info(f"Recommendation {recommendation_id} marked as acted by {operator_id}")
        return True
    
    # ─── OUTCOME VALIDATION ───────────────────────────────────────────────
    
    async def check_outcomes(self) -> Dict[str, int]:
        """
        Check all acted-but-unvalidated recommendations.
        
        For each, compare predicted vs actual outcome.
        Should be run periodically (every 5-30 minutes).
        """
        results = {
            "checked": 0,
            "validated": 0,
            "expired": 0,
            "errors": 0,
        }
        
        # Get all recommendations awaiting validation
        pending = self.registry.get_acted_unvalidated()
        
        for rec in pending:
            results["checked"] += 1
            
            try:
                # Check if validation window has passed
                if datetime.now() < rec.acted_at + timedelta(hours=rec.validation_window_hours):
                    # Not enough time has passed yet
                    continue
                
                # Validate
                validation = await self.validator.validate(rec)
                
                # Update recommendation
                rec.actual_outcome = validation.actual_values
                rec.outcome_verdict = validation.verdict
                rec.outcome_error_score = validation.error_score
                rec.validated_at = datetime.now()
                rec.status = RecommendationStatus.VALIDATED
                
                self.registry.update(rec)
                
                # Process feedback
                await self.processor.process(rec, validation)
                
                results["validated"] += 1
                
            except Exception as e:
                logger.error(f"Validation error for {rec.recommendation_id}: {e}")
                results["errors"] += 1
        
        # Mark expired recommendations
        for rec in self.registry.get_pending():
            if datetime.now() > rec.expires_at:
                rec.status = RecommendationStatus.EXPIRED
                self.registry.update(rec)
                results["expired"] += 1
        
        if results["validated"] > 0:
            logger.info(
                f"Outcome check complete: {results['validated']} validated, "
                f"{results['expired']} expired"
            )
        
        return results
    
    async def start_periodic_checks(self, interval_seconds: int = 300) -> None:
        """Start a background task that checks outcomes periodically"""
        self._running = True
        self._check_interval = interval_seconds
        
        logger.info(f"Starting periodic outcome checks every {interval_seconds}s")
        
        while self._running:
            try:
                await self.check_outcomes()
            except Exception as e:
                logger.error(f"Periodic check error: {e}")
            
            await asyncio.sleep(self._check_interval)
    
    def stop_periodic_checks(self) -> None:
        """Stop the background outcome checker"""
        self._running = False
        logger.info("Stopped periodic outcome checks")
    
    # ─── STATISTICS & REPORTING ───────────────────────────────────────────
    
    def get_statistics(self, recommendation_type: Optional[str] = None) -> Dict[str, Any]:
        """Get accuracy and performance statistics"""
        stats = self.registry.get_accuracy_stats(recommendation_type)
        
        # Add recent activity
        recent_24h = self.registry.get_recent(hours=24)
        recent_7d = self.registry.get_recent(hours=168)
        
        stats["recent_24h"] = {
            "total": len(recent_24h),
            "pending": sum(1 for r in recent_24h if r.status == RecommendationStatus.PENDING),
            "acted": sum(1 for r in recent_24h if r.status == RecommendationStatus.ACTED),
            "validated": sum(1 for r in recent_24h if r.status == RecommendationStatus.VALIDATED),
        }
        
        stats["recent_7d"] = {
            "total": len(recent_7d),
            "validated": sum(1 for r in recent_7d if r.status == RecommendationStatus.VALIDATED),
        }
        
        # Add breakdown by type
        type_breakdown = {}
        for rec in recent_7d:
            rtype = rec.recommendation_type or "unknown"
            if rtype not in type_breakdown:
                type_breakdown[rtype] = {"count": 0, "validated": 0}
            type_breakdown[rtype]["count"] += 1
            if rec.status == RecommendationStatus.VALIDATED:
                type_breakdown[rtype]["validated"] += 1
        
        stats["by_type"] = type_breakdown
        
        return stats
    
    def get_recommendation(self, recommendation_id: str) -> Optional[Dict[str, Any]]:
        """Get a single recommendation's details"""
        rec = self.registry.get(recommendation_id)
        return rec.to_dict() if rec else None
    
    def get_recent_recommendations(
        self,
        hours: int = 24,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent recommendations, optionally filtered"""
        status_enum = RecommendationStatus(status) if status else None
        recs = self.registry.get_recent(hours=hours, status=status_enum)
        return [r.to_dict() for r in recs]
    
    # ─── PRIVATE HELPERS ──────────────────────────────────────────────────
    
    async def _analyze_rejection(self, rec: Recommendation, reason: str) -> None:
        """
        Analyze why a recommendation was rejected.
        
        This helps calibrate trust even when operators don't act.
        """
        # Common rejection reasons that indicate prediction error
        error_indicators = [
            "not necessary",
            "already done",
            "wrong equipment",
            "incorrect",
            "data is wrong",
            "prediction was wrong",
        ]
        
        reason_lower = reason.lower()
        
        if any(indicator in reason_lower for indicator in error_indicators):
            # This rejection suggests our prediction was wrong
            rec.outcome_verdict = OutcomeVerdict.FAILURE
            rec.outcome_error_score = 0.8  # High error
            self.registry.update(rec)
            
            # Feed back to trust system
            if self.processor.trust_governor:
                await self.processor._update_trust(rec, 
                    ValidationResult(
                        recommendation_id=rec.recommendation_id,
                        verdict=OutcomeVerdict.FAILURE,
                        error_score=0.8,
                    ),
                    trust_delta=-0.05
                )


# ═══════════════════════════════════════════════════════════════════════════
# TOOLS FOR LLM INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

def create_verify_loop_tools(verify_loop: VerifyLoop) -> List[Any]:
    """
    Create tools that allow the LLM to interact with the verify loop.
    
    These tools enable the agent to:
    - Register its own recommendations for tracking
    - Check if recommendations were acted on
    - Get feedback on past recommendations
    """
    from agent_unified.tools.base import BaseTool, ToolResult
    
    class RegisterRecommendation(BaseTool):
        name = "register_recommendation"
        description = "Register a recommendation for outcome tracking. Use this when making an actionable recommendation."
        parameters = {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the recommendation"},
                "description": {"type": "string", "description": "Detailed description"},
                "recommendation_type": {"type": "string", "description": "Type: energy, maintenance, comfort, safety"},
                "action_type": {"type": "string", "description": "Type of action: setpoint_change, override, maintenance, etc."},
                "equipment_id": {"type": "string", "description": "Target equipment ID"},
                "predicted_outcome": {"type": "object", "description": "What you predict will happen"},
                "confidence": {"type": "number", "description": "Confidence level 0.0-1.0"},
            },
            "required": ["title", "recommendation_type", "predicted_outcome", "confidence"],
        }
        
        verify_loop: VerifyLoop = None
        
        async def execute(self, **kwargs) -> ToolResult:
            rec_id = await self.verify_loop.register_recommendation(**kwargs)
            return self.success_response({"recommendation_id": rec_id, "status": "registered"})
    
    class GetRecommendationFeedback(BaseTool):
        name = "get_recommendation_feedback"
        description = "Get feedback on past recommendations for a specific equipment or type. Use this to learn from past predictions."
        parameters = {
            "type": "object",
            "properties": {
                "equipment_id": {"type": "string", "description": "Equipment ID to check"},
                "recommendation_type": {"type": "string", "description": "Type to filter by"},
                "hours": {"type": "integer", "description": "Lookback window in hours (default: 168 = 7 days)"},
            },
        }
        
        verify_loop: VerifyLoop = None
        
        async def execute(
            self,
            equipment_id: Optional[str] = None,
            recommendation_type: Optional[str] = None,
            hours: int = 168,
        ) -> ToolResult:
            stats = self.verify_loop.get_statistics(recommendation_type)
            
            recs = []
            if equipment_id:
                for rec in self.verify_loop.registry.get_for_equipment(equipment_id):
                    if rec.created_at > datetime.now() - timedelta(hours=hours):
                        recs.append(rec.to_dict())
            
            return self.success_response({
                "stats": stats,
                "recommendations": recs[:10],  # Limit to 10 most recent
            })
    
    # Bind verify_loop to tools
    tools = [RegisterRecommendation(), GetRecommendationFeedback()]
    for tool in tools:
        tool.verify_loop = verify_loop
    
    return tools
