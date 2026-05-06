"""
ABI™ Integration — Wire All Three Engines
==========================================

Orchestrates the complete ABI™ cycle:
  Observe → Understand → Act → Verify → Learn

Engines:
  1. PredictionEngine → Predict future states
  2. VerifyLoop → Validate predictions against reality
  3. OnlineLearner → Detect drift, trigger retraining

Architecture:
  ┌─────────────────────────────────────────────────────────────────┐
  │                      ABI Orchestrator                            │
  ├─────────────────────────────────────────────────────────────────┤
  │                                                                   │
  │  ┌─────────────────┐     ┌─────────────────┐                     │
  │  │  Prediction     │     │    Verify       │                     │
  │  │    Engine       │────▶│     Loop        │                     │
  │  └────────┬────────┘     └────────┬────────┘                     │
  │           │                       │                               │
  │           │                       ▼                               │
  │           │              ┌─────────────────┐                      │
  │           │              │    Online       │                      │
  │           │              │    Learner      │                      │
  │           │              └────────┬────────┘                      │
  │           │                       │                               │
  │           └───────────────────────┘                               │
  │                     Retrain Trigger                                │
  │                                                                   │
  └─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional

from agent_cognitive.prediction_engine import PredictionEngine, PredictionType
from agent_advisory.verify_loop import VerifyLoop, RecommendationStatus
from agent_advisory.online_learner import OnlineLearner, DriftReport

logger = logging.getLogger("arvis.abi.integration")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ABICycleResult:
    """Result of a complete ABI cycle"""
    cycle_id: str
    started_at: datetime
    completed_at: datetime
    
    # Prediction
    prediction: Optional[Dict[str, Any]] = None
    prediction_confidence: float = 0.0
    
    # Validation
    validated: bool = False
    validation_error: float = 0.0
    outcome_status: str = "pending"
    
    # Learning
    drift_detected: bool = False
    retraining_triggered: bool = False
    
    # Metrics
    cycle_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "prediction": self.prediction,
            "prediction_confidence": self.prediction_confidence,
            "validated": self.validated,
            "validation_error": self.validation_error,
            "outcome_status": self.outcome_status,
            "drift_detected": self.drift_detected,
            "retraining_triggered": self.retraining_triggered,
            "cycle_time_ms": self.cycle_time_ms,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ABI ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

class ABIOrchestrator:
    """
    Wires together PredictionEngine, VerifyLoop, and OnlineLearner.
    
    This is the main entry point for the ABI™ system.
    
    Usage:
        orchestrator = ABIOrchestrator()
        
        # Run a prediction cycle
        result = await orchestrator.run_prediction_cycle(
            prediction_type="energy_demand",
            context={"building_id": "DOHA-TOWER-001"},
        )
        
        # Validate after getting actual readings
        result = await orchestrator.validate_prediction(
            prediction_id="pred_123",
            actual_values={"total_power_kw": 450.0},
        )
    """
    
    def __init__(
        self,
        prediction_engine: Optional[PredictionEngine] = None,
        verify_loop: Optional[VerifyLoop] = None,
        online_learner: Optional[OnlineLearner] = None,
        auto_retrain: bool = True,
    ):
        # Initialize or use provided engines
        self.prediction_engine = prediction_engine or PredictionEngine()
        self.verify_loop = verify_loop or VerifyLoop(state_engine=None)
        self.online_learner = online_learner or OnlineLearner()
        
        self.auto_retrain = auto_retrain
        
        # Wire callbacks
        self._wire_callbacks()
        
        # Statistics
        self._stats = {
            "total_cycles": 0,
            "successful_cycles": 0,
            "drift_detections": 0,
            "retrains_triggered": 0,
        }
        
        logger.info("ABI Orchestrator initialized")
    
    def _wire_callbacks(self):
        """Wire the feedback loops between engines"""
        
        # When learner detects drift → trigger retraining in prediction engine
        def on_drift(report: DriftReport):
            logger.warning(f"Drift detected: {report.drift_type.value} score={report.drift_score:.2f}")
            self._stats["drift_detections"] += 1
            
            if report.needs_retraining and self.auto_retrain:
                logger.info("Auto-retraining triggered by drift detection")
                self._trigger_retraining()
        
        # When learner requests retraining
        def on_retrain():
            if self.auto_retrain:
                self._trigger_retraining()
        
        self.online_learner.on_drift_detected(on_drift)
        self.online_learner.on_retraining_needed(on_retrain)
    
    def _trigger_retraining(self):
        """Trigger retraining in prediction engine"""
        # Get training data from learner
        training_records = self.online_learner.get_records_for_training(limit=100)
        
        if not training_records:
            logger.warning("No training records available for retraining")
            return
        
        # Call prediction engine's learn method
        self.prediction_engine.learn(training_records)
        
        self._stats["retrains_triggered"] += 1
        logger.info(f"Retraining completed with {len(training_records)} records")
    
    # ═══════════════════════════════════════════════════════════════════════
    # MAIN API
    # ═══════════════════════════════════════════════════════════════════════
    
    async def run_prediction_cycle(
        self,
        prediction_type: str,
        context: Dict[str, Any],
        horizon_minutes: int = 60,
    ) -> ABICycleResult:
        """
        Run a complete prediction cycle.
        
        This generates a prediction and registers it for later validation.
        
        Args:
            prediction_type: "energy_demand", "equipment_performance", etc.
            context: Current state and context for prediction
            horizon_minutes: How far ahead to predict
            
        Returns:
            ABICycleResult with prediction details
        """
        import uuid
        cycle_id = f"cycle_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now()
        
        try:
            # 1. Generate prediction
            pred_type = PredictionType(prediction_type) if prediction_type in [e.value for e in PredictionType] else PredictionType.ENERGY_DEMAND
            
            prediction = await self.prediction_engine.predict(
                prediction_type=pred_type,
                context=context,
                horizon_minutes=horizon_minutes,
            )
            
            # 2. Track prediction internally for validation (simplified)
            self._pending_predictions = getattr(self, '_pending_predictions', {})
            self._pending_predictions[prediction.prediction_id] = {
                "predicted_values": prediction.predicted,
                "context": prediction.context,
                "prediction_type": prediction_type,
                "confidence": prediction.confidence,
            }
            
            completed_at = datetime.now()
            cycle_time = (completed_at - started_at).total_seconds() * 1000
            
            self._stats["total_cycles"] += 1
            self._stats["successful_cycles"] += 1
            
            return ABICycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=completed_at,
                prediction={
                    "prediction_id": prediction.prediction_id,
                    "type": prediction.prediction_type.value,
                    "predicted_state": prediction.predicted,
                },
                prediction_confidence=prediction.confidence,
                cycle_time_ms=cycle_time,
            )
            
        except Exception as e:
            logger.error(f"Prediction cycle failed: {e}")
            completed_at = datetime.now()
            
            return ABICycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=completed_at,
                outcome_status="error",
            )
    
    async def validate_prediction(
        self,
        prediction_id: str,
        actual_values: Dict[str, float],
        operator_accepted: Optional[bool] = None,
        operator_feedback: str = "",
    ) -> ABICycleResult:
        """
        Validate a prediction against actual outcomes.
        
        This completes the ABI cycle: validate → learn → detect drift.
        
        Args:
            prediction_id: ID of prediction to validate
            actual_values: What actually happened (from sensors)
            operator_accepted: Did operator accept the recommendation?
            operator_feedback: Optional free-text feedback
            
        Returns:
            ABICycleResult with validation details
        """
        import uuid
        cycle_id = f"val_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now()
        
        try:
            # 1. Get tracked prediction
            self._pending_predictions = getattr(self, '_pending_predictions', {})
            pred_record = self._pending_predictions.get(prediction_id, {})
            
            predicted_values = pred_record.get("predicted_values", {})
            context = pred_record.get("context", {})
            prediction_type = pred_record.get("prediction_type", "unknown")
            
            # 2. Compute validation error
            errors = []
            for key in predicted_values:
                if key in actual_values:
                    pred_val = predicted_values[key]
                    act_val = actual_values[key]
                    if isinstance(pred_val, (int, float)) and isinstance(act_val, (int, float)):
                        errors.append(abs(pred_val - act_val))
            
            validation_error = sum(errors) / len(errors) if errors else 0.0
            
            # 3. Log to OnlineLearner
            record = await self.online_learner.log_observation(
                prediction_type=prediction_type,
                predicted_values=predicted_values,
                actual_values=actual_values,
                prediction_confidence=pred_record.get("confidence", 0.5),
                prediction_id=prediction_id,
                context=context,
            )
            
            # 4. Log operator feedback if provided
            if operator_accepted is not None:
                await self.online_learner.log_operator_feedback(
                    prediction_id=prediction_id,
                    accepted=operator_accepted,
                    feedback=operator_feedback,
                )
            
            completed_at = datetime.now()
            cycle_time = (completed_at - started_at).total_seconds() * 1000
            
            return ABICycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=completed_at,
                prediction={"prediction_id": prediction_id},
                validated=True,
                validation_error=validation_error,
                outcome_status="validated",
                drift_detected=False,  # Checked separately
                cycle_time_ms=cycle_time,
            )
            
        except Exception as e:
            logger.error(f"Validation cycle failed: {e}")
            completed_at = datetime.now()
            
            return ABICycleResult(
                cycle_id=cycle_id,
                started_at=started_at,
                completed_at=completed_at,
                outcome_status="error",
            )
    
    async def check_drift(self) -> Optional[DriftReport]:
        """
        Check for concept drift.
        
        Returns:
            DriftReport if drift detected, None otherwise
        """
        return await self.online_learner._check_for_drift()
    
    # ═══════════════════════════════════════════════════════════════════════
    # BATCH OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def run_continuous_learning(
        self,
        interval_seconds: int = 300,  # 5 minutes
        max_iterations: int = 100,
    ):
        """
        Run continuous learning loop.
        
        This is for background operation:
        - Periodically check for drift
        - Retrain if needed
        - Report performance
        
        Args:
            interval_seconds: How often to check
            max_iterations: Maximum iterations (0 = infinite)
        """
        iteration = 0
        
        while max_iterations == 0 or iteration < max_iterations:
            try:
                # Check for drift
                report = await self.check_drift()
                
                if report:
                    logger.info(
                        f"Drift check: score={report.drift_score:.2f} "
                        f"type={report.drift_type.value}"
                    )
                
                # Log performance
                perf = self.online_learner.get_performance_summary()
                logger.info(
                    f"Performance: observations={perf['total_observations']} "
                    f"recent_rmse={perf.get('recent_rmse', 0):.2f}"
                )
                
            except Exception as e:
                logger.error(f"Continuous learning error: {e}")
            
            iteration += 1
            await asyncio.sleep(interval_seconds)
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATUS & METRICS
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall ABI system status"""
        self._pending_predictions = getattr(self, '_pending_predictions', {})
        return {
            "prediction_engine": {
                "stats": self.prediction_engine.get_stats(),
            },
            "pending_predictions": len(self._pending_predictions),
            "online_learner": self.online_learner.get_performance_summary(),
            "orchestrator": {
                "total_cycles": self._stats["total_cycles"],
                "successful_cycles": self._stats["successful_cycles"],
                "drift_detections": self._stats["drift_detections"],
                "retrains_triggered": self._stats["retrains_triggered"],
            },
        }
    
    def get_learning_report(self) -> Dict[str, Any]:
        """Generate a learning report for operators"""
        perf = self.online_learner.get_performance_summary()
        
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_predictions": perf["total_observations"],
                "current_accuracy": 1.0 - perf.get("recent_mape", 0.0),
                "baseline_accuracy": 1.0 - (perf.get("baseline_mape", 0.0) or 0.0),
                "drift_status": "detected" if perf["drift_detections"] > 0 else "stable",
            },
            "performance_trend": "improving" if perf.get("recent_rmse", 1.0) < (perf.get("baseline_rmse", 1.0) or 1.0) else "degrading",
            "recommendations": self._generate_recommendations(perf),
        }
    
    def _generate_recommendations(self, perf: Dict[str, Any]) -> List[str]:
        """Generate actionable recommendations based on performance"""
        recommendations = []
        
        if perf.get("drift_detections", 0) > 0:
            recommendations.append("Review recent equipment changes or sensor calibrations")
        
        if perf.get("recent_rmse", 0) > (perf.get("baseline_rmse", 0) or 0) * 1.5:
            recommendations.append("Prediction accuracy is degrading - consider baseline reset")
        
        if perf.get("total_observations", 0) < 50:
            recommendations.append("Collect more samples before trusting drift detection")
        
        if not recommendations:
            recommendations.append("System performance is stable")
        
        return recommendations


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY
# ═══════════════════════════════════════════════════════════════════════════

def create_abi_system(
    auto_retrain: bool = True,
    drift_threshold: float = 1.5,
    buffer_size: int = 1000,
    state_engine: Any = None,
) -> ABIOrchestrator:
    """
    Factory function to create a fully-wired ABI system.
    
    Args:
        auto_retrain: Automatically retrain on drift detection
        drift_threshold: RMSE ratio threshold for drift
        buffer_size: Experience buffer size
        state_engine: BMS state engine (optional for testing)
        
    Returns:
        Fully configured ABIOrchestrator
    """
    prediction_engine = PredictionEngine()
    verify_loop = VerifyLoop(state_engine=state_engine)
    online_learner = OnlineLearner(
        buffer_size=buffer_size,
        drift_threshold=drift_threshold,
    )
    
    return ABIOrchestrator(
        prediction_engine=prediction_engine,
        verify_loop=verify_loop,
        online_learner=online_learner,
        auto_retrain=auto_retrain,
    )
