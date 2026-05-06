"""
ABI™ Online Learner
==================

The learning layer of ABI™: tracks prediction accuracy, detects concept drift,
and triggers incremental model updates.

Part of the ABI™ Observe → Understand → Act → Verify → Learn cycle.

Architecture:
  PredictionEngine ─────┐
                         │
                         ▼
  ┌─────────────────────────────────────────────────────────┐
  │                  Online Learner                          │
  │                                                          │
  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐    │
  │  │  Experience │   │    Drift    │   │   Model     │    │
  │  │   Buffer    │ → │  Detector   │ → │  Updater    │    │
  │  └─────────────┘   └─────────────┘   └─────────────┘    │
  │         ▲                                    │           │
  │         │                                    ▼           │
  │  VerifyLoop ──────────────────────> PredictionEngine    │
  └─────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Deque
from enum import Enum
import uuid

logger = logging.getLogger("arvis.abi.learner")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class DriftType(str, Enum):
    """Types of concept drift"""
    GRADUAL = "gradual"      # Slow degradation over time
    SUDDEN = "sudden"        # Abrupt change (equipment failure, retrofit)
    INCREMENTAL = "incremental"  # Steady improvement (operator learning)
    RECURRING = "recurring"  # Seasonal/cyclical patterns


@dataclass
class ExperienceRecord:
    """A single (prediction, actual, outcome) tuple for learning"""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    
    # The prediction
    prediction_type: str = ""           # "energy_demand", "equipment_performance"
    predicted_values: Dict[str, float] = field(default_factory=dict)
    prediction_confidence: float = 0.0
    prediction_id: str = ""
    
    # The actual outcome (from VerifyLoop)
    actual_values: Dict[str, float] = field(default_factory=dict)
    validation_time: Optional[datetime] = None
    
    # Computed error
    error_metrics: Dict[str, float] = field(default_factory=dict)
    mape: float = 0.0    # Mean Absolute Percentage Error
    rmse: float = 0.0   # Root Mean Square Error
    
    # Context for learning
    context: Dict[str, Any] = field(default_factory=dict)
    equipment_id: str = ""
    building_id: str = ""
    
    # Operator feedback (if any)
    operator_accepted: Optional[bool] = None
    operator_feedback: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp.isoformat(),
            "prediction_type": self.prediction_type,
            "predicted_values": self.predicted_values,
            "actual_values": self.actual_values,
            "error_metrics": self.error_metrics,
            "mape": self.mape,
            "rmse": self.rmse,
            "equipment_id": self.equipment_id,
            "building_id": self.building_id,
            "operator_accepted": self.operator_accepted,
        }


@dataclass
class DriftReport:
    """Report on detected concept drift"""
    drift_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = field(default_factory=datetime.now)
    
    drift_type: DriftType = DriftType.GRADUAL
    severity: float = 0.0         # 0-1 scale
    drift_score: float = 0.0      # Ratio of recent/baseline error
    
    # What changed
    affected_features: List[str] = field(default_factory=list)
    baseline_performance: float = 0.0
    current_performance: float = 0.0
    
    # Recommendations
    recommended_actions: List[str] = field(default_factory=list)
    needs_retraining: bool = False
    needs_baselines_reset: bool = False
    
    # Evidence
    sample_count: int = 0
    time_window_days: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "drift_id": self.drift_id,
            "detected_at": self.detected_at.isoformat(),
            "drift_type": self.drift_type.value,
            "severity": self.severity,
            "drift_score": self.drift_score,
            "affected_features": self.affected_features,
            "baseline_performance": self.baseline_performance,
            "current_performance": self.current_performance,
            "recommended_actions": self.recommended_actions,
            "needs_retraining": self.needs_retraining,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ONLINE LEARNER
# ═══════════════════════════════════════════════════════════════════════════

class OnlineLearner:
    """
    The learning layer of ABI™.
    
    Responsibilities:
    1. Buffer (prediction, actual) pairs from VerifyLoop
    2. Compute error metrics (MAPE, RMSE)
    3. Detect concept drift (CUSUM, threshold-based)
    4. Trigger incremental model updates
    5. Provide performance metrics for TrustGovernor
    
    Integration Points:
    - PredictionEngine: receives predictions to track
    - VerifyLoop: receives (predicted, actual) pairs
    - TrustGovernor: provides drift metrics for confidence adjustment
    - PredictionEngine.learn(): triggers baseline updates
    """
    
    def __init__(
        self,
        buffer_size: int = 1000,
        drift_threshold: float = 1.5,
        sudden_drift_threshold: float = 2.5,
        min_samples_for_baseline: int = 20,
        min_samples_for_drift: int = 10,
        retrain_cooldown_hours: float = 24.0,
    ):
        self.buffer_size = buffer_size
        self.drift_threshold = drift_threshold
        self.sudden_drift_threshold = sudden_drift_threshold
        self.min_samples_for_baseline = min_samples_for_baseline
        self.min_samples_for_drift = min_samples_for_drift
        self.retrain_cooldown_hours = retrain_cooldown_hours
        
        # Experience buffer
        self._buffer: Deque[ExperienceRecord] = deque(maxlen=buffer_size)
        
        # Baseline performance (established after min_samples_for_baseline)
        self._baseline_rmse: Optional[float] = None
        self._baseline_mape: Optional[float] = None
        self._baseline_established_at: Optional[datetime] = None
        
        # Drift tracking
        self._last_drift_detection: Optional[datetime] = None
        self._last_retraining: Optional[datetime] = None
        self._cumulative_drift_score: float = 0.0
        
        # Callbacks for retraining
        self._on_drift_detected: List[Callable[[DriftReport], None]] = []
        self._on_retraining_needed: List[Callable[[], None]] = []
        
        # Statistics
        self._stats = {
            "total_observations": 0,
            "drift_detections": 0,
            "retrains_triggered": 0,
            "avg_recent_rmse": 0.0,
        }
        
        logger.info(f"OnlineLearner initialized (buffer={buffer_size}, drift_threshold={drift_threshold})")
    
    # ═══════════════════════════════════════════════════════════════════════
    # CORE API
    # ═══════════════════════════════════════════════════════════════════════
    
    async def log_observation(
        self,
        prediction_type: str,
        predicted_values: Dict[str, float],
        actual_values: Dict[str, float],
        prediction_confidence: float = 0.0,
        prediction_id: str = "",
        context: Optional[Dict[str, Any]] = None,
        equipment_id: str = "",
        building_id: str = "",
    ) -> ExperienceRecord:
        """
        Log a (prediction, actual) pair for learning.
        
        Called by VerifyLoop after validation.
        
        Args:
            prediction_type: Type of prediction ("energy_demand", "equipment_performance")
            predicted_values: What the model predicted
            actual_values: What actually happened (from sensors)
            prediction_confidence: Model's confidence at prediction time
            prediction_id: ID from PredictionEngine for traceability
            context: Additional context (weather, occupancy, etc.)
            equipment_id: Related equipment if applicable
            building_id: Building identifier
            
        Returns:
            ExperienceRecord with computed error metrics
        """
        # Create record
        record = ExperienceRecord(
            prediction_type=prediction_type,
            predicted_values=predicted_values,
            actual_values=actual_values,
            prediction_confidence=prediction_confidence,
            prediction_id=prediction_id,
            context=context or {},
            equipment_id=equipment_id,
            building_id=building_id,
            validation_time=datetime.now(),
        )
        
        # Compute error metrics
        record.error_metrics = self._compute_errors(predicted_values, actual_values)
        record.mape = record.error_metrics.get("mape", 0.0)
        record.rmse = record.error_metrics.get("rmse", 0.0)
        
        # Add to buffer
        self._buffer.append(record)
        self._stats["total_observations"] += 1
        
        # Update running stats
        if len(self._buffer) >= 10:
            recent = list(self._buffer)[-20:]
            self._stats["avg_recent_rmse"] = np.mean([r.rmse for r in recent])
        
        logger.debug(
            f"Logged observation: {prediction_type} "
            f"MAPE={record.mape:.2%} RMSE={record.rmse:.2f}"
        )
        
        # Check for drift (every 10 samples)
        if len(self._buffer) % 10 == 0:
            await self._check_for_drift()
        
        return record
    
    async def log_operator_feedback(
        self,
        prediction_id: str,
        accepted: bool,
        feedback: str = "",
    ) -> bool:
        """
        Log operator feedback on a recommendation.
        
        This is crucial for learning operator preferences and trust calibration.
        
        Args:
            prediction_id: ID of the prediction/recommendation
            accepted: Did operator accept the recommendation?
            feedback: Optional free-text feedback
            
        Returns:
            True if prediction was found and updated
        """
        # Find record by prediction_id
        for record in self._buffer:
            if record.prediction_id == prediction_id:
                record.operator_accepted = accepted
                record.operator_feedback = feedback
                logger.info(
                    f"Operator feedback logged: prediction={prediction_id} "
                    f"accepted={accepted}"
                )
                return True
        
        logger.warning(f"Prediction {prediction_id} not found in buffer")
        return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # DRIFT DETECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _check_for_drift(self) -> Optional[DriftReport]:
        """
        Analyze buffer for concept drift.
        
        Uses a combination of:
        1. Threshold-based detection (recent RMSE / baseline RMSE)
        2. Trend analysis (is error increasing?)
        3. CUSUM-style cumulative drift tracking
        
        Returns:
            DriftReport if drift detected, None otherwise
        """
        n = len(self._buffer)
        
        # Need minimum samples
        if n < self.min_samples_for_drift:
            return None
        
        # Establish baseline if not done
        if self._baseline_rmse is None and n >= self.min_samples_for_baseline:
            initial_records = list(self._buffer)[:self.min_samples_for_baseline]
            self._baseline_rmse = np.mean([r.rmse for r in initial_records])
            self._baseline_mape = np.mean([r.mape for r in initial_records])
            self._baseline_established_at = datetime.now()
            logger.info(
                f"Baseline established: RMSE={self._baseline_rmse:.2f} "
                f"MAPE={self._baseline_mape:.2%}"
            )
            return None
        
        # Compute recent performance
        recent_records = list(self._buffer)[-20:]
        recent_rmse = np.mean([r.rmse for r in recent_records])
        recent_mape = np.mean([r.mape for r in recent_records])
        
        # Drift score
        drift_score = recent_rmse / self._baseline_rmse if self._baseline_rmse > 0 else 1.0
        
        # Trend analysis
        errors = [r.rmse for r in recent_records]
        trend = np.polyfit(range(len(errors)), errors, 1)[0]  # Slope
        error_trend = "improving" if trend < 0 else "worsening" if trend > 0 else "stable"
        
        # Cumulative drift (CUSUM-like)
        self._cumulative_drift_score = max(0, self._cumulative_drift_score + (drift_score - 1.0))
        
        # Detect drift type
        drift_type = DriftType.GRADUAL
        severity = min(1.0, (drift_score - 1.0) / (self.sudden_drift_threshold - 1.0))
        
        if drift_score >= self.sudden_drift_threshold:
            drift_type = DriftType.SUDDEN
            severity = min(1.0, drift_score / self.sudden_drift_threshold)
        elif trend < 0 and drift_score < 1.0:
            drift_type = DriftType.INCREMENTAL  # Model is improving
        
        # Determine if we need to raise an alert
        needs_alert = False
        recommended_actions = []
        
        if drift_score >= self.drift_threshold:
            needs_alert = True
            recommended_actions.append("High drift score detected")
            recommended_actions.append("Review recent predictions for systematic errors")
        
        if drift_score >= self.sudden_drift_threshold:
            recommended_actions.append("CRITICAL: Sudden drift - check for equipment changes")
            recommended_actions.append("Reset baselines after investigating cause")
        
        if self._cumulative_drift_score > 5.0:
            needs_alert = True
            recommended_actions.append("Cumulative drift exceeds threshold")
        
        # Check retrain cooldown
        can_retrain = True
        if self._last_retraining:
            hours_since_retrain = (datetime.now() - self._last_retraining).total_seconds() / 3600
            if hours_since_retrain < self.retrain_cooldown_hours:
                can_retrain = False
        
        if not needs_alert:
            self._last_drift_detection = None
            return None
        
        # Create drift report
        report = DriftReport(
            drift_type=drift_type,
            severity=severity,
            drift_score=drift_score,
            baseline_performance=self._baseline_rmse,
            current_performance=recent_rmse,
            recommended_actions=recommended_actions,
            needs_retraining=drift_score >= self.drift_threshold and can_retrain,
            needs_baselines_reset=drift_score >= self.sudden_drift_threshold,
            sample_count=n,
            time_window_days=(datetime.now() - self._baseline_established_at).total_seconds() / 86400
            if self._baseline_established_at else 0.0,
        )
        
        # Identify affected features
        report.affected_features = self._identify_affected_features(recent_records)
        
        self._last_drift_detection = datetime.now()
        self._stats["drift_detections"] += 1
        
        logger.warning(
            f"Drift detected: type={drift_type.value} score={drift_score:.2f} "
            f"severity={severity:.2f}"
        )
        
        # Notify callbacks
        for callback in self._on_drift_detected:
            try:
                callback(report)
            except Exception as e:
                logger.error(f"Drift callback error: {e}")
        
        # Trigger retraining if needed
        if report.needs_retraining:
            await self._trigger_retraining()
        
        return report
    
    def _identify_affected_features(self, records: List[ExperienceRecord]) -> List[str]:
        """Identify which features have the highest error"""
        if not records:
            return []
        
        # Aggregate errors by feature
        feature_errors: Dict[str, List[float]] = {}
        
        for record in records:
            for key, error in record.error_metrics.items():
                if key.startswith("error_"):
                    feature_name = key.replace("error_", "")
                    if feature_name not in feature_errors:
                        feature_errors[feature_name] = []
                    feature_errors[feature_name].append(abs(error))
        
        # Find features with highest average error
        avg_errors = {
            feat: np.mean(errs) for feat, errs in feature_errors.items()
        }
        
        # Return top 3
        sorted_features = sorted(avg_errors.items(), key=lambda x: x[1], reverse=True)
        return [feat for feat, _ in sorted_features[:3]]
    
    async def _trigger_retraining(self):
        """Trigger model retraining via callbacks"""
        logger.info("Triggering model retraining...")
        
        self._last_retraining = datetime.now()
        self._stats["retrains_triggered"] += 1
        
        # Notify callbacks
        for callback in self._on_retraining_needed:
            try:
                callback()
            except Exception as e:
                logger.error(f"Retraining callback error: {e}")
        
        # Reset cumulative drift after retraining
        self._cumulative_drift_score = 0.0
    
    # ═══════════════════════════════════════════════════════════════════════
    # ERROR COMPUTATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def _compute_errors(
        self,
        predicted: Dict[str, float],
        actual: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Compute comprehensive error metrics.
        
        Returns:
            Dict with: mape, rmse, mae, and per-feature errors
        """
        errors = {}
        
        # Find common keys
        common_keys = set(predicted.keys()) & set(actual.keys())
        
        if not common_keys:
            errors["mape"] = 0.0
            errors["rmse"] = 0.0
            errors["mae"] = 0.0
            return errors
        
        # Per-feature errors
        abs_errors = []
        squared_errors = []
        ape_errors = []  # Absolute Percentage Errors
        
        for key in common_keys:
            pred_val = predicted[key]
            act_val = actual[key]
            
            if not isinstance(pred_val, (int, float)) or not isinstance(act_val, (int, float)):
                continue
            
            abs_error = abs(pred_val - act_val)
            abs_errors.append(abs_error)
            squared_errors.append(abs_error ** 2)
            
            # Avoid division by zero
            if abs(act_val) > 0.001:
                ape_errors.append(abs_error / abs(act_val))
            
            errors[f"error_{key}"] = abs_error
        
        # Aggregate metrics
        if abs_errors:
            errors["mae"] = np.mean(abs_errors)
            errors["rmse"] = np.sqrt(np.mean(squared_errors))
            errors["mape"] = np.mean(ape_errors) if ape_errors else 0.0
        else:
            errors["mae"] = 0.0
            errors["rmse"] = 0.0
            errors["mape"] = 0.0
        
        return errors
    
    # ═══════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════
    
    def on_drift_detected(self, callback: Callable[[DriftReport], None]):
        """Register callback for drift detection events"""
        self._on_drift_detected.append(callback)
    
    def on_retraining_needed(self, callback: Callable[[], None]):
        """Register callback for retraining trigger events"""
        self._on_retraining_needed.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════════
    # QUERY API
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get current performance metrics.
        
        Used by TrustGovernor for confidence adjustment.
        """
        if not self._buffer:
            return {
                "status": "no_data",
                "total_observations": 0,
            }
        
        recent = list(self._buffer)[-50:]
        
        return {
            "status": "active",
            "total_observations": self._stats["total_observations"],
            "buffer_size": len(self._buffer),
            "baseline_rmse": self._baseline_rmse,
            "baseline_mape": self._baseline_mape,
            "baseline_established_at": self._baseline_established_at.isoformat() if self._baseline_established_at else None,
            "recent_rmse": np.mean([r.rmse for r in recent]),
            "recent_mape": np.mean([r.mape for r in recent]),
            "drift_detections": self._stats["drift_detections"],
            "retrains_triggered": self._stats["retrains_triggered"],
            "cumulative_drift_score": self._cumulative_drift_score,
            "last_drift_detection": self._last_drift_detection.isoformat() if self._last_drift_detection else None,
            "last_retraining": self._last_retraining.isoformat() if self._last_retraining else None,
        }
    
    def get_recent_records(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent experience records"""
        recent = list(self._buffer)[-limit:]
        return [r.to_dict() for r in recent]
    
    def get_records_for_training(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get records formatted for model training.
        
        Returns (predicted, actual, context) tuples.
        """
        records = list(self._buffer)[-limit:]
        
        return [
            {
                "predicted": r.predicted_values,
                "actual": r.actual_values,
                "context": r.context,
                "error": r.rmse,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in records
        ]
    
    def reset_baselines(self):
        """Reset baselines (after major equipment changes)"""
        self._baseline_rmse = None
        self._baseline_mape = None
        self._baseline_established_at = None
        self._cumulative_drift_score = 0.0
        logger.info("Baselines reset")
