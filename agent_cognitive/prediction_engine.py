"""
ABI™ Prediction Engine
======================

The prediction layer of ABI™ (Adaptive Building Intelligence).

Predicts BMS states, equipment performance, and energy demand to enable:
1. Baseline establishment for anomaly detection
2. Drift detection (predicted vs actual)
3. Proactive alerts before issues cascade
4. Model adaptation from feedback

This is NOT home automation. This is commercial building intelligence.

Capabilities:
- Energy demand forecasting (time-of-day, weather, occupancy)
- Equipment performance prediction (kW/ton, efficiency trends)
- State transition prediction (if X happens, Y follows)
- Drift scoring (how far is reality from prediction?)
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import uuid

logger = logging.getLogger("arvis.abi.prediction")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class PredictionType(str, Enum):
    ENERGY_DEMAND = "energy_demand"
    EQUIPMENT_PERFORMANCE = "equipment_performance"
    STATE_TRANSITION = "state_transition"
    DRIFT_INDICATOR = "drift_indicator"


@dataclass
class PredictedState:
    """A predicted BMS state at a future time."""
    prediction_type: PredictionType
    timestamp: datetime
    horizon_minutes: int  # How far ahead
    
    # Predicted values
    predicted: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    
    # Context used for prediction
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Tracking
    prediction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    
    # Validation (filled later by verify loop)
    actual: Optional[Dict[str, float]] = None
    validated_at: Optional[datetime] = None
    error: Optional[float] = None  # RMSE or similar
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "type": self.prediction_type.value,
            "horizon_minutes": self.horizon_minutes,
            "predicted": self.predicted,
            "confidence": round(self.confidence, 3),
            "actual": self.actual,
            "error": round(self.error, 3) if self.error else None,
            "validated": self.validated_at is not None,
        }


@dataclass
class DriftReport:
    """Report on prediction drift over time."""
    building_id: str
    time_window_hours: int
    
    # Metrics
    mean_error: float = 0.0
    max_error: float = 0.0
    drift_score: float = 0.0  # 0-1 normalized
    
    # Breakdown by type
    energy_error: float = 0.0
    performance_error: float = 0.0
    
    # Trend
    error_trend: str = "stable"  # "improving", "stable", "worsening"
    
    # ML lineage (M5.2)
    model_id: Optional[str] = None

    # Recommendation
    needs_retraining: bool = False
    alerts: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "building_id": self.building_id,
            "drift_score": round(self.drift_score, 3),
            "error_trend": self.error_trend,
            "needs_retraining": self.needs_retraining,
            "alerts": self.alerts,
        }
        if self.model_id is not None:
            d["model_id"] = self.model_id
        return d


# ═══════════════════════════════════════════════════════════════════════════
# PREDICTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class PredictionEngine:
    """
    ABI™ Prediction Engine for commercial buildings.
    
    Predicts:
    - Energy demand (kW) based on time, weather, occupancy
    - Equipment performance (efficiency, temperatures)
    - State transitions (cascade effects)
    
    Integrates with:
    - Verify Loop for validation
    - Online Learner for adaptation
    - Trust Governor for confidence calibration
    """
    
    def __init__(
        self,
        building_id: str = "default",
        bms_state_engine: Any = None,
        online_learner: Any = None,
    ):
        self.building_id = building_id
        self.bms_state = bms_state_engine
        self.online_learner = online_learner
        
        # Prediction history for drift detection
        self._prediction_history: List[PredictedState] = []
        self._max_history = 1000
        
        # Baseline models (simple statistical, upgradeable to ML)
        self._energy_baseline: Dict[str, float] = {}  # hour -> avg_kW
        self._performance_baselines: Dict[str, Dict[str, float]] = {}  # equipment -> metrics
        self._transition_patterns: Dict[str, List[str]] = {}  # state -> next_states
        
        # Learning state
        self._samples_seen = 0
        self._last_retraining = datetime.now()
        
        logger.info(f"PredictionEngine initialized for building {building_id}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # MAIN PREDICTION INTERFACE
    # ═══════════════════════════════════════════════════════════════════════
    
    async def predict(
        self,
        prediction_type: PredictionType,
        horizon_minutes: int = 60,
        context: Optional[Dict[str, Any]] = None,
    ) -> PredictedState:
        """
        Generate a prediction for the specified type and horizon.
        
        Args:
            prediction_type: What to predict
            horizon_minutes: How far ahead (15, 60, 240, 1440)
            context: Additional context (weather, events, etc.)
            
        Returns:
            PredictedState with predicted values and confidence
        """
        context = context or {}
        
        # Get current BMS state if available
        if self.bms_state:
            if asyncio.iscoroutinefunction(self.bms_state.get_summary):
                context["current_state"] = await self.bms_state.get_summary()
            else:
                context["current_state"] = self.bms_state.get_summary()
        
        # Dispatch to appropriate predictor
        if prediction_type == PredictionType.ENERGY_DEMAND:
            predicted, confidence = await self._predict_energy(horizon_minutes, context)
        elif prediction_type == PredictionType.EQUIPMENT_PERFORMANCE:
            predicted, confidence = await self._predict_performance(horizon_minutes, context)
        elif prediction_type == PredictionType.STATE_TRANSITION:
            predicted, confidence = await self._predict_transition(horizon_minutes, context)
        else:
            predicted, confidence = {}, 0.0
        
        prediction = PredictedState(
            prediction_type=prediction_type,
            timestamp=datetime.now() + timedelta(minutes=horizon_minutes),
            horizon_minutes=horizon_minutes,
            predicted=predicted,
            confidence=confidence,
            context=context,
        )
        
        # Store for later validation
        self._prediction_history.append(prediction)
        if len(self._prediction_history) > self._max_history:
            self._prediction_history.pop(0)
        
        logger.debug(f"Prediction {prediction.prediction_id}: {prediction_type.value} -> {predicted}")
        return prediction
    
    async def predict_energy_demand(
        self,
        horizon_minutes: int = 60,
        weather: Optional[Dict] = None,
        occupancy_hint: Optional[str] = None,
    ) -> PredictedState:
        """Convenience method for energy demand prediction."""
        context = {}
        if weather:
            context["weather"] = weather
        if occupancy_hint:
            context["occupancy_hint"] = occupancy_hint
        
        return await self.predict(PredictionType.ENERGY_DEMAND, horizon_minutes, context)
    
    # ═══════════════════════════════════════════════════════════════════════
    # SPECIFIC PREDICTORS
    # ═══════════════════════════════════════════════════════════════════════
    
    async def _predict_energy(
        self,
        horizon_minutes: int,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, float], float]:
        """
        Predict building energy demand.
        
        Uses:
        - Time-of-day patterns (baseline)
        - Weather adjustment (temperature, humidity)
        - Occupancy adjustment
        - Historical trends
        """
        now = datetime.now()
        target_hour = (now + timedelta(minutes=horizon_minutes)).hour
        
        # 1. Get baseline for target hour
        baseline_kw = self._energy_baseline.get(str(target_hour), 400.0)
        
        # 2. Weather adjustment
        weather = context.get("weather", {})
        if weather:
            temp = weather.get("temperature", 30)
            # Qatar: higher temp = higher cooling load
            temp_factor = 1.0 + (temp - 30) * 0.02  # +2% per °C above 30
            baseline_kw *= temp_factor
        
        # 3. Time-of-day pattern
        if 12 <= target_hour <= 18:
            # Peak hours in Qatar
            baseline_kw *= 1.3
        elif 22 <= target_hour or target_hour <= 6:
            # Night
            baseline_kw *= 0.7
        
        # 4. Occupancy hint
        occupancy = context.get("occupancy_hint", "normal")
        if occupancy == "high":
            baseline_kw *= 1.15
        elif occupancy == "low":
            baseline_kw *= 0.85
        elif occupancy == "empty":
            baseline_kw *= 0.6
        
        # 5. Historical trend adjustment
        if self._samples_seen > 50:
            recent_errors = [p.error for p in self._prediction_history[-20:] if p.error]
            if recent_errors:
                # Bias correction based on recent prediction errors
                avg_error = np.mean(recent_errors)
                baseline_kw *= (1 - avg_error / baseline_kw)
        
        predicted = {
            "total_power_kw": round(baseline_kw, 1),
            "hvac_power_kw": round(baseline_kw * 0.6, 1),  # ~60% HVAC in Qatar
            "lighting_power_kw": round(baseline_kw * 0.15, 1),
            "other_power_kw": round(baseline_kw * 0.25, 1),
        }
        
        # Confidence based on data availability
        confidence = 0.5  # Base confidence
        if self._energy_baseline:
            confidence += 0.2
        if weather:
            confidence += 0.1
        if self._samples_seen > 100:
            confidence += 0.2
        
        confidence = min(confidence, 0.95)
        
        return predicted, confidence
    
    async def _predict_performance(
        self,
        horizon_minutes: int,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, float], float]:
        """
        Predict equipment performance metrics.
        
        Returns efficiency indicators:
        - Chiller kW/ton
        - AHU CFM
        - Temperature deltas
        """
        predicted = {}
        confidence = 0.5
        
        current_state = context.get("current_state", {})
        
        # Chiller performance
        if self.bms_state:
            chillers = self.bms_state.get_equipment_by_type("chiller")
            for chiller in chillers:
                eq_id = chiller.equipment_id
                
                # Get baseline performance
                baseline = self._performance_baselines.get(eq_id, {
                    "kw_per_ton": 0.7,
                    "chwst": 7.0,
                    "chwrt": 12.0,
                })
                
                # Predict based on current load and conditions
                current_load = current_state.get(f"{eq_id}_load", 80)
                
                # Higher load = better efficiency (to a point)
                kw_per_ton = baseline["kw_per_ton"]
                if current_load > 80:
                    kw_per_ton *= 0.95  # Better at high load
                elif current_load < 40:
                    kw_per_ton *= 1.15  # Worse at low load
                
                predicted[f"{eq_id}_kw_per_ton"] = round(kw_per_ton, 2)
                predicted[f"{eq_id}_chwst"] = baseline["chwst"]
                predicted[f"{eq_id}_chwrt"] = baseline["chwrt"] + (current_load - 50) * 0.02
                confidence += 0.1
        
        # AHU performance
        if self.bms_state:
            ahus = self.bms_state.get_equipment_by_type("ahu")
            for ahu in ahus[:3]:  # Top 3 AHUs
                eq_id = ahu.equipment_id
                predicted[f"{eq_id}_sat"] = 14.0  # Supply air temp
                predicted[f"{eq_id}_rat"] = 24.0  # Return air temp
                predicted[f"{eq_id}_cfm"] = 20000  # Airflow
                confidence += 0.05
        
        confidence = min(confidence, 0.9)
        return predicted, confidence
    
    async def _predict_transition(
        self,
        horizon_minutes: int,
        context: Dict[str, Any],
    ) -> Tuple[Dict[str, float], float]:
        """
        Predict state transitions (cascade effects).
        
        Example: If Chiller-01 trips, what happens to AHUs?
        """
        predicted = {}
        confidence = 0.4
        
        current_state = context.get("current_state", {})
        
        # Check for known transition patterns
        for trigger, outcomes in self._transition_patterns.items():
            # If trigger condition is met
            if self._check_trigger(trigger, current_state):
                for outcome in outcomes:
                    predicted[f"cascade_{outcome}"] = 1.0
                    confidence = min(confidence + 0.2, 0.85)
        
        # Default cascade rules (domain knowledge)
        # Chiller trip → zone temp rise
        if current_state.get("chiller_status") == "fault":
            predicted["zone_temp_rise_rate"] = 0.5  # °C per hour
            predicted["affected_zones"] = 3
            confidence = 0.7
        
        return predicted, confidence
    
    def _check_trigger(self, trigger: str, state: Dict) -> bool:
        """Check if a transition trigger condition is met."""
        # Simple pattern matching for now
        # Format: "equipment_status == value"
        if "==" in trigger:
            key, value = trigger.split("==")
            key = key.strip()
            value = value.strip()
            actual = state.get(key, "")
            return str(actual) == value
        return False
    
    # ═══════════════════════════════════════════════════════════════════════
    # DRIFT DETECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def compute_drift(
        self,
        time_window_hours: int = 24,
    ) -> DriftReport:
        """
        Analyze prediction accuracy and detect drift.
        
        Compares predicted vs validated predictions to determine:
        - Model accuracy
        - Whether drift is occurring
        - Need for retraining
        """
        cutoff = datetime.now() - timedelta(hours=time_window_hours)
        
        # Get validated predictions in window
        validated = [
            p for p in self._prediction_history
            if p.validated_at and p.validated_at > cutoff
        ]
        
        if len(validated) < 5:
            return DriftReport(
                building_id=self.building_id,
                time_window_hours=time_window_hours,
                alerts=["Insufficient validation data for drift analysis"],
                model_id=f"prediction_engine:{self.building_id}",
            )
        
        # Compute errors
        errors = []
        energy_errors = []
        performance_errors = []
        
        for pred in validated:
            if pred.error is not None:
                errors.append(pred.error)
                
                if pred.prediction_type == PredictionType.ENERGY_DEMAND:
                    energy_errors.append(pred.error)
                elif pred.prediction_type == PredictionType.EQUIPMENT_PERFORMANCE:
                    performance_errors.append(pred.error)
        
        if not errors:
            return DriftReport(
                building_id=self.building_id,
                time_window_hours=time_window_hours,
                alerts=["No errors computed in validation data"],
                model_id=f"prediction_engine:{self.building_id}",
            )
        
        mean_error = np.mean(errors)
        max_error = np.max(errors)
        
        # Normalize drift score (0 = perfect, 1 = very bad)
        # For energy, 10% error = drift score 0.5
        drift_score = min(mean_error / 100.0, 1.0)
        
        # Determine trend
        if len(errors) >= 10:
            recent = np.mean(errors[-5:])
            older = np.mean(errors[-10:-5])
            
            if recent < older * 0.9:
                error_trend = "improving"
            elif recent > older * 1.1:
                error_trend = "worsening"
            else:
                error_trend = "stable"
        else:
            error_trend = "unknown"
        
        # Determine retraining need
        needs_retraining = (
            drift_score > 0.5 or
            error_trend == "worsening" or
            (datetime.now() - self._last_retraining).days > 30
        )
        
        # Generate alerts
        alerts = []
        if drift_score > 0.3:
            alerts.append(f"High drift score: {drift_score:.2f}")
        if error_trend == "worsening":
            alerts.append("Prediction accuracy is degrading")
        if needs_retraining:
            alerts.append("Model retraining recommended")
        
        report = DriftReport(
            building_id=self.building_id,
            time_window_hours=time_window_hours,
            mean_error=round(mean_error, 2),
            max_error=round(max_error, 2),
            drift_score=round(drift_score, 3),
            energy_error=round(np.mean(energy_errors), 2) if energy_errors else 0.0,
            performance_error=round(np.mean(performance_errors), 2) if performance_errors else 0.0,
            error_trend=error_trend,
            needs_retraining=needs_retraining,
            alerts=alerts,
            model_id=f"prediction_engine:{self.building_id}",
        )

        # M4.2: Feed drift into RetrainScheduler — immediate trigger if threshold breached
        if needs_retraining:
            try:
                from agent_commercial.ml.retrain_scheduler import get_retrain_scheduler
                _scheduler = get_retrain_scheduler()
                await _scheduler.on_drift_detected(
                    model_id=f"prediction_engine:{self.building_id}",
                    drift_score=drift_score,
                )
                logger.info(f"[PredictionEngine] Drift {drift_score:.3f} → immediate retrain triggered")
            except Exception as _e:
                logger.debug(f"[PredictionEngine] RetrainScheduler feed failed: {_e}")

        return report
    
    # ═══════════════════════════════════════════════════════════════════════
    # LEARNING & ADAPTATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def learn_from_validation(
        self,
        prediction_id: str,
        actual_state: Dict[str, float],
    ) -> Optional[float]:
        """
        Called by Verify Loop when a prediction is validated.
        
        Updates baselines and triggers learning.
        
        Args:
            prediction_id: ID of the prediction being validated
            actual_state: The actual observed state
            
        Returns:
            Error metric (RMSE) or None if prediction not found
        """
        # Find the prediction
        prediction = None
        for pred in self._prediction_history:
            if pred.prediction_id == prediction_id:
                prediction = pred
                break
        
        if not prediction:
            logger.warning(f"Prediction {prediction_id} not found for validation")
            return None
        
        # Compute error
        error = self._compute_error(prediction.predicted, actual_state)
        
        # Update prediction with validation
        prediction.actual = actual_state
        prediction.error = error
        prediction.validated_at = datetime.now()
        
        # Update baselines from actual data
        self._update_baselines(prediction, actual_state)
        
        # Feed to online learner if available
        if self.online_learner:
            self.online_learner.log_observation(prediction.predicted, actual_state)
        
        self._samples_seen += 1
        
        logger.info(f"Validated {prediction_id}: error={error:.2f}")
        return error
    
    def _compute_error(
        self,
        predicted: Dict[str, float],
        actual: Dict[str, float],
    ) -> float:
        """Compute RMSE between predicted and actual."""
        errors = []
        for key in predicted:
            if key in actual:
                errors.append((predicted[key] - actual[key]) ** 2)
        
        return np.sqrt(np.mean(errors)) if errors else 0.0
    
    def _update_baselines(
        self,
        prediction: PredictedState,
        actual: Dict[str, float],
    ) -> None:
        """Update baseline models from validated data."""
        
        # Update energy baseline
        if prediction.prediction_type == PredictionType.ENERGY_DEMAND:
            hour = prediction.timestamp.hour
            actual_kw = actual.get("total_power_kw", 0)
            
            if actual_kw > 0:
                # Exponential moving average update
                old_baseline = self._energy_baseline.get(str(hour), actual_kw)
                alpha = 0.1  # Learning rate
                new_baseline = alpha * actual_kw + (1 - alpha) * old_baseline
                self._energy_baseline[str(hour)] = new_baseline
        
        # Update performance baselines
        elif prediction.prediction_type == PredictionType.EQUIPMENT_PERFORMANCE:
            # Extract equipment ID from key (e.g., "CH-01_kw_per_ton")
            for key, value in actual.items():
                if "_kw_per_ton" in key:
                    eq_id = key.replace("_kw_per_ton", "")
                    if eq_id not in self._performance_baselines:
                        self._performance_baselines[eq_id] = {}
                    self._performance_baselines[eq_id]["kw_per_ton"] = value
    
    async def trigger_retraining(self) -> Dict[str, Any]:
        """
        Trigger model retraining using accumulated validation data.
        
        Returns:
            Training result summary
        """
        logger.info("Triggering model retraining...")
        
        # Get validated data
        validated = [
            p for p in self._prediction_history
            if p.validated_at and p.actual
        ]
        
        if len(validated) < 20:
            return {
                "status": "skipped",
                "reason": "Insufficient validated data",
                "samples": len(validated),
            }
        
        # Extract training data
        training_data = []
        for pred in validated:
            training_data.append({
                "hour": pred.timestamp.hour,
                "predicted": pred.predicted,
                "actual": pred.actual,
                "error": pred.error,
            })
        
        # Simple baseline update (in production, would use ML)
        # Group by hour and recompute baselines
        hour_samples = {}
        for sample in training_data:
            hour = sample["hour"]
            if hour not in hour_samples:
                hour_samples[hour] = []
            hour_samples[hour].append(sample["actual"].get("total_power_kw", 0))
        
        # Update baselines with mean
        for hour, values in hour_samples.items():
            if values:
                self._energy_baseline[str(hour)] = np.mean(values)
        
        self._last_retraining = datetime.now()
        
        logger.info(f"Retraining complete. Updated {len(hour_samples)} hour baselines.")
        
        return {
            "status": "success",
            "samples_used": len(validated),
            "baselines_updated": len(hour_samples),
            "last_retraining": self._last_retraining.isoformat(),
        }
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_prediction(self, prediction_id: str) -> Optional[PredictedState]:
        """Retrieve a prediction by ID."""
        for pred in self._prediction_history:
            if pred.prediction_id == prediction_id:
                return pred
        return None
    
    def get_pending_predictions(self, max_age_hours: int = 2) -> List[PredictedState]:
        """Get predictions awaiting validation."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        return [
            p for p in self._prediction_history
            if not p.validated_at and p.created_at > cutoff
        ]
    
    # ═══════════════════════════════════════════════════════════════════════
    # PERSISTENCE (Warm-Start)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _ensure_baselines_schema(conn) -> None:
        """Self-heal the prediction_baselines table. It may pre-exist (created by an
        older/other component) WITHOUT the building_id column the engine now needs,
        which caused 'no such column: building_id' on every load/save. Create it if
        missing, ALTER in building_id if absent. Idempotent."""
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS prediction_baselines ("
            "building_id TEXT DEFAULT 'default', hour INTEGER, metric TEXT, "
            "value REAL, samples INTEGER DEFAULT 0, updated_at TEXT)"
        )
        cols = [r[1] for r in cur.execute("PRAGMA table_info(prediction_baselines)")]
        if "building_id" not in cols:
            cur.execute("ALTER TABLE prediction_baselines ADD COLUMN building_id TEXT DEFAULT 'default'")
        conn.commit()

    def save_baselines(self, db=None) -> bool:
        """Persist baselines to DB for warm-start recovery."""
        try:
            if db is None:
                from agent_commercial.database import get_database
                db = get_database()

            import sqlite3
            conn = sqlite3.connect(str(db.db_path))
            self._ensure_baselines_schema(conn)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM prediction_baselines WHERE building_id = ?", (self.building_id,))

            for hour, value in self._energy_baseline.items():
                cursor.execute(
                    "INSERT INTO prediction_baselines (building_id, hour, metric, value, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (self.building_id, int(hour), "energy_kw", value, datetime.now().isoformat()),
                )

            for eq_id, metrics in self._performance_baselines.items():
                for metric_name, value in metrics.items():
                    cursor.execute(
                        "INSERT INTO prediction_baselines (building_id, hour, metric, value, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (self.building_id, -1, f"perf_{eq_id}_{metric_name}", value, datetime.now().isoformat()),
                    )

            conn.commit()
            conn.close()
            logger.info(f"Saved {len(self._energy_baseline)} energy baselines + {len(self._performance_baselines)} performance baselines")
            return True
        except Exception as e:
            logger.error(f"Failed to save baselines: {e}")
            return False

    def load_baselines(self, db=None) -> bool:
        """Load baselines from DB on startup (warm-start)."""
        try:
            if db is None:
                from agent_commercial.database import get_database
                db = get_database()

            import sqlite3
            conn = sqlite3.connect(str(db.db_path))
            self._ensure_baselines_schema(conn)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT hour, metric, value FROM prediction_baselines WHERE building_id = ?",
                (self.building_id,),
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                logger.info("No stored baselines found — cold start")
                return False

            energy_count = 0
            perf_count = 0
            for hour, metric, value in rows:
                if metric == "energy_kw":
                    self._energy_baseline[str(hour)] = value
                    energy_count += 1
                elif metric.startswith("perf_"):
                    parts = metric[5:].rsplit("_", 1)
                    if len(parts) == 2:
                        eq_id, metric_name = parts
                        if eq_id not in self._performance_baselines:
                            self._performance_baselines[eq_id] = {}
                        self._performance_baselines[eq_id][metric_name] = value
                        perf_count += 1

            logger.info(f"Warm-start: loaded {energy_count} energy baselines, {perf_count} performance baselines")
            return True
        except Exception as e:
            logger.error(f"Failed to load baselines: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get prediction engine statistics."""
        validated = [p for p in self._prediction_history if p.validated_at]
        errors = [p.error for p in validated if p.error is not None]

        return {
            "total_predictions": len(self._prediction_history),
            "validated_predictions": len(validated),
            "pending_predictions": len(self._prediction_history) - len(validated),
            "mean_error": round(np.mean(errors), 3) if errors else None,
            "baselines_trained": len(self._energy_baseline),
            "samples_seen": self._samples_seen,
            "last_retraining": self._last_retraining.isoformat(),
        }
