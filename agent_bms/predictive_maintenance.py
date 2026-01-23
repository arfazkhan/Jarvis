"""
Predictive Maintenance Engine
=============================

ML-based predictive maintenance using a HYBRID approach:
1. XGBoost - Failure classification (will equipment fail in 7 days?)
2. Isolation Forest - Anomaly detection in equipment behavior
3. Weibull - Remaining Useful Life (RUL) estimation
4. LSTM - Sequential pattern learning (Phase 2, when sufficient data)

NOT LLM-reliant — uses classical ML algorithms trained on equipment data.

Technical Details:
- XGBoost: Gradient boosting for binary classification
- Isolation Forest: Unsupervised anomaly detection
- Weibull Analysis: Survival/reliability modeling using lifelines
- Feature Engineering: Runtime hours, cycles, efficiency trends, etc.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import warnings

import numpy as np
import pandas as pd

# ML Libraries
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    warnings.warn("XGBoost not installed. Run: pip install xgboost")

try:
    from lifelines import WeibullFitter
    LIFELINES_AVAILABLE = True
except ImportError:
    LIFELINES_AVAILABLE = False
    warnings.warn("Lifelines not installed. Run: pip install lifelines")

from agent_bms.bms_data_model import (
    Equipment,
    EquipmentType,
    BMSDataPoint,
    FailurePrediction,
    Anomaly,
)

logger = logging.getLogger("arvis.bms.predictive")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES FOR ML FEATURES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EquipmentFeatures:
    """
    Feature vector for equipment health prediction.
    
    These features are derived from BMS data points and equipment metadata.
    They're designed to capture degradation patterns that precede failures.
    """
    equipment_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Operational Metrics
    runtime_hours: float = 0.0          # Total operating hours
    start_stop_cycles: int = 0           # Number of starts (wear indicator)
    days_since_maintenance: int = 0      # Days since last service
    age_years: float = 0.0               # Equipment age
    
    # Performance Indicators
    avg_load_percent: float = 0.0        # Average load (0-100)
    efficiency: float = 0.0              # Current efficiency (0-1)
    efficiency_trend: float = 0.0        # Efficiency change over 7 days
    
    # HVAC-Specific (for AHU, Chiller, VAV)
    delta_t: float = 0.0                 # Temperature differential
    delta_t_deviation: float = 0.0       # Deviation from design delta-T
    supply_temp_deviation: float = 0.0   # Deviation from setpoint
    
    # Motor/Rotating Equipment
    motor_current: float = 0.0           # Motor current (amps)
    current_deviation: float = 0.0       # Deviation from baseline
    vibration_rms: float = 0.0           # Vibration level (if available)
    
    # Fault Indicators
    fault_count_30d: int = 0             # Alarms in last 30 days
    minor_fault_count: int = 0           # Minor issues
    major_fault_count: int = 0           # Major issues
    
    def to_array(self) -> np.ndarray:
        """Convert to numpy array for ML model"""
        return np.array([
            self.runtime_hours,
            self.start_stop_cycles,
            self.days_since_maintenance,
            self.age_years,
            self.avg_load_percent,
            self.efficiency,
            self.efficiency_trend,
            self.delta_t,
            self.delta_t_deviation,
            self.supply_temp_deviation,
            self.motor_current,
            self.current_deviation,
            self.vibration_rms,
            self.fault_count_30d,
            self.minor_fault_count,
            self.major_fault_count,
        ])
    
    @staticmethod
    def feature_names() -> List[str]:
        """Get feature names for model interpretation"""
        return [
            "runtime_hours",
            "start_stop_cycles", 
            "days_since_maintenance",
            "age_years",
            "avg_load_percent",
            "efficiency",
            "efficiency_trend",
            "delta_t",
            "delta_t_deviation",
            "supply_temp_deviation",
            "motor_current",
            "current_deviation",
            "vibration_rms",
            "fault_count_30d",
            "minor_fault_count",
            "major_fault_count",
        ]


@dataclass
class FeatureFactor:
    """A feature that contributed to a prediction"""
    name: str
    importance: float
    current_value: float
    threshold: Optional[float] = None
    is_concerning: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# PREDICTIVE MAINTENANCE ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class PredictiveMaintenanceEngine:
    """
    Hybrid ML engine for predictive maintenance.
    
    Uses multiple algorithms for robust predictions:
    - XGBoost: Main failure classification
    - Isolation Forest: Anomaly detection
    - Weibull: RUL estimation with limited data
    
    NOT LLM-reliant — pure statistical/ML approach.
    
    Example:
        >>> engine = PredictiveMaintenanceEngine()
        >>> engine.train(historical_data, failure_labels)
        >>> prediction = engine.predict_failure(equipment_id, current_features)
    """
    
    def __init__(self):
        """Initialize the predictive maintenance engine"""
        
        # ─────────────────────────────────────────────────────────────────
        # XGBoost: Failure Classification
        # ─────────────────────────────────────────────────────────────────
        if XGBOOST_AVAILABLE:
            self.failure_classifier = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                objective='binary:logistic',
                eval_metric='auc',
                use_label_encoder=False,
                random_state=42,
            )
        else:
            self.failure_classifier = None
            logger.warning("XGBoost not available, using fallback rules")
        
        # ─────────────────────────────────────────────────────────────────
        # Isolation Forest: Anomaly Detection
        # ─────────────────────────────────────────────────────────────────
        self.anomaly_detector = IsolationForest(
            n_estimators=100,
            contamination=0.1,  # Expect ~10% anomalies
            random_state=42,
        )
        
        # ─────────────────────────────────────────────────────────────────
        # Feature Scaling
        # ─────────────────────────────────────────────────────────────────
        self.scaler = StandardScaler()
        
        # ─────────────────────────────────────────────────────────────────
        # Weibull: RUL Estimation (per equipment type)
        # ─────────────────────────────────────────────────────────────────
        self.weibull_models: Dict[str, Any] = {}  # type -> WeibullFitter
        
        # ─────────────────────────────────────────────────────────────────
        # State
        # ─────────────────────────────────────────────────────────────────
        self.is_trained = False
        self.feature_names = EquipmentFeatures.feature_names()
        self.equipment_history: Dict[str, List[EquipmentFeatures]] = {}
        self.equipment_baselines: Dict[str, Dict[str, float]] = {}
        
        # Thresholds for rule-based fallback
        self.thresholds = {
            "runtime_hours_critical": 50000,
            "efficiency_low": 0.6,
            "days_overdue_maintenance": 30,
            "fault_count_high": 5,
        }
        
        logger.info("PredictiveMaintenanceEngine initialized")
    
    # ═══════════════════════════════════════════════════════════════════════
    # TRAINING
    # ═══════════════════════════════════════════════════════════════════════
    
    def train(
        self, 
        historical_data: pd.DataFrame, 
        failure_labels: pd.Series
    ) -> Dict[str, float]:
        """
        Train XGBoost classifier and anomaly detector on historical data.
        
        Args:
            historical_data: DataFrame with columns matching EquipmentFeatures
            failure_labels: Binary series (0=healthy, 1=failed within 7 days)
            
        Returns:
            Dict with training metrics (accuracy, precision, recall, auc)
        """
        if not XGBOOST_AVAILABLE:
            logger.warning("XGBoost not available, skipping training")
            return {}
        
        logger.info(f"Training on {len(historical_data)} samples...")
        
        # Ensure column alignment
        X = historical_data[self.feature_names].values
        y = failure_labels.values
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train XGBoost
        self.failure_classifier.fit(X_scaled, y)
        
        # Train anomaly detector (unsupervised, uses healthy equipment only)
        healthy_mask = y == 0
        if healthy_mask.sum() > 10:
            self.anomaly_detector.fit(X_scaled[healthy_mask])
        
        self.is_trained = True
        
        # Calculate training metrics
        y_pred = self.failure_classifier.predict(X_scaled)
        y_proba = self.failure_classifier.predict_proba(X_scaled)[:, 1]
        
        from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
        
        metrics = {
            "accuracy": accuracy_score(y, y_pred),
            "precision": precision_score(y, y_pred, zero_division=0),
            "recall": recall_score(y, y_pred, zero_division=0),
            "auc": roc_auc_score(y, y_proba) if len(np.unique(y)) > 1 else 0.0,
            "samples": len(y),
            "failures": int(y.sum()),
        }
        
        logger.info(f"Training complete: AUC={metrics['auc']:.3f}, "
                   f"Precision={metrics['precision']:.3f}, "
                   f"Recall={metrics['recall']:.3f}")
        
        return metrics
    
    def train_weibull(
        self, 
        equipment_type: str,
        durations: List[float],
        event_observed: List[bool]
    ) -> None:
        """
        Train Weibull model for RUL estimation.
        
        Args:
            equipment_type: Type of equipment (e.g., "AHU", "Chiller")
            durations: Time to event (failure or censoring) in days
            event_observed: Whether failure was observed (True) or censored (False)
        """
        if not LIFELINES_AVAILABLE:
            logger.warning("Lifelines not available, skipping Weibull training")
            return
        
        wf = WeibullFitter()
        wf.fit(durations, event_observed)
        self.weibull_models[equipment_type] = wf
        
        logger.info(f"Weibull model trained for {equipment_type}: "
                   f"lambda={wf.lambda_:.2f}, rho={wf.rho_:.2f}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # PREDICTION
    # ═══════════════════════════════════════════════════════════════════════
    
    def predict_failure(
        self, 
        equipment_id: str,
        features: EquipmentFeatures,
        equipment_type: Optional[str] = None
    ) -> FailurePrediction:
        """
        Predict failure probability for equipment.
        
        Uses hybrid approach:
        1. XGBoost for classification probability
        2. Anomaly score from Isolation Forest
        3. Weibull for RUL estimation
        4. Rule-based checks for critical thresholds
        
        Args:
            equipment_id: Equipment identifier
            features: Current equipment feature vector
            equipment_type: Optional type for Weibull RUL
            
        Returns:
            FailurePrediction with probability, risk level, RUL, and recommendations
        """
        X = features.to_array().reshape(1, -1)
        
        # ─────────────────────────────────────────────────────────────────
        # 1. XGBoost: Get failure probability
        # ─────────────────────────────────────────────────────────────────
        if self.is_trained and self.failure_classifier is not None:
            X_scaled = self.scaler.transform(X)
            failure_proba = self.failure_classifier.predict_proba(X_scaled)[0, 1]
            confidence = 0.8  # Trained model
        else:
            # Fallback to rule-based
            failure_proba = self._rule_based_probability(features)
            confidence = 0.5  # Lower confidence for rule-based
        
        # ─────────────────────────────────────────────────────────────────
        # 2. Isolation Forest: Anomaly boost
        # ─────────────────────────────────────────────────────────────────
        if self.is_trained:
            X_scaled = self.scaler.transform(X)
            anomaly_score = -self.anomaly_detector.decision_function(X_scaled)[0]
            # Normalize to 0-1 range (higher = more anomalous)
            anomaly_score = max(0, min(1, (anomaly_score + 0.5)))
            
            # Boost failure probability if highly anomalous
            if anomaly_score > 0.7:
                failure_proba = min(1.0, failure_proba * 1.3)
        else:
            anomaly_score = 0.0
        
        # ─────────────────────────────────────────────────────────────────
        # 3. Weibull: RUL estimation
        # ─────────────────────────────────────────────────────────────────
        rul_days = self._estimate_rul(equipment_type, features)
        
        # ─────────────────────────────────────────────────────────────────
        # 4. Determine risk level
        # ─────────────────────────────────────────────────────────────────
        if failure_proba > 0.8 or (rul_days is not None and rul_days < 7):
            risk_level = "critical"
        elif failure_proba > 0.6 or (rul_days is not None and rul_days < 30):
            risk_level = "high"
        elif failure_proba > 0.3:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        # ─────────────────────────────────────────────────────────────────
        # 5. Get contributing factors
        # ─────────────────────────────────────────────────────────────────
        contributing_factors = self._get_contributing_factors(features)
        
        # ─────────────────────────────────────────────────────────────────
        # 6. Generate recommendation
        # ─────────────────────────────────────────────────────────────────
        recommendation = self._generate_recommendation(
            risk_level, 
            contributing_factors, 
            features
        )
        
        return FailurePrediction(
            equipment_id=equipment_id,
            failure_probability=float(failure_proba),
            risk_level=risk_level,
            predicted_rul_days=rul_days if rul_days is not None else -1,
            confidence=confidence,
            recommendation=recommendation,
            contributing_factors=[
                {
                    "name": f.name,
                    "importance": f.importance,
                    "current_value": f.current_value,
                    "is_concerning": f.is_concerning,
                }
                for f in contributing_factors
            ],
        )
    
    def _rule_based_probability(self, features: EquipmentFeatures) -> float:
        """
        Fallback rule-based failure probability when model not trained.
        
        This provides reasonable estimates before sufficient training data.
        """
        score = 0.0
        
        # Runtime hours
        if features.runtime_hours > self.thresholds["runtime_hours_critical"]:
            score += 0.2
        elif features.runtime_hours > self.thresholds["runtime_hours_critical"] * 0.8:
            score += 0.1
        
        # Efficiency degradation
        if features.efficiency < self.thresholds["efficiency_low"]:
            score += 0.25
        elif features.efficiency < 0.75:
            score += 0.1
        
        # Maintenance overdue
        if features.days_since_maintenance > self.thresholds["days_overdue_maintenance"]:
            score += 0.15
        
        # Recent faults
        if features.fault_count_30d > self.thresholds["fault_count_high"]:
            score += 0.2
        elif features.fault_count_30d > 2:
            score += 0.1
        
        # Age
        if features.age_years > 15:
            score += 0.15
        elif features.age_years > 10:
            score += 0.05
        
        # Efficiency trend (declining)
        if features.efficiency_trend < -0.05:
            score += 0.1
        
        return min(1.0, score)
    
    def _estimate_rul(
        self, 
        equipment_type: Optional[str],
        features: EquipmentFeatures
    ) -> Optional[int]:
        """
        Estimate Remaining Useful Life using Weibull or heuristics.
        """
        # Try Weibull model if available
        if equipment_type and equipment_type in self.weibull_models:
            wf = self.weibull_models[equipment_type]
            # Current age in days
            current_age = features.age_years * 365
            # Median remaining time
            median_rul = wf.median_survival_time_ - current_age
            return max(0, int(median_rul))
        
        # Fallback: Simple heuristic based on efficiency trend
        if features.efficiency_trend < -0.01:
            # Declining efficiency: estimate time to 50% efficiency
            current_eff = features.efficiency
            decline_rate = abs(features.efficiency_trend) / 7  # Per day
            if decline_rate > 0:
                days_to_50 = (current_eff - 0.5) / decline_rate
                return max(7, int(days_to_50))
        
        # Cannot estimate
        return None
    
    def _get_contributing_factors(
        self, 
        features: EquipmentFeatures
    ) -> List[FeatureFactor]:
        """
        Identify top contributing factors to failure prediction.
        
        Uses XGBoost feature importance if trained, else rule-based.
        """
        factors = []
        feature_values = features.to_array()
        
        # Get feature importances
        if self.is_trained and self.failure_classifier is not None:
            importances = self.failure_classifier.feature_importances_
        else:
            # Fallback importances (domain knowledge)
            importances = np.array([
                0.12,  # runtime_hours
                0.08,  # start_stop_cycles
                0.10,  # days_since_maintenance
                0.05,  # age_years
                0.08,  # avg_load_percent
                0.15,  # efficiency
                0.10,  # efficiency_trend
                0.06,  # delta_t
                0.04,  # delta_t_deviation
                0.03,  # supply_temp_deviation
                0.05,  # motor_current
                0.04,  # current_deviation
                0.02,  # vibration_rms
                0.04,  # fault_count_30d
                0.02,  # minor_fault_count
                0.02,  # major_fault_count
            ])
        
        # Create factors list
        for i, (name, importance) in enumerate(zip(self.feature_names, importances)):
            value = feature_values[i]
            
            # Check if concerning
            is_concerning = self._is_value_concerning(name, value)
            
            factors.append(FeatureFactor(
                name=name,
                importance=float(importance),
                current_value=float(value),
                is_concerning=is_concerning,
            ))
        
        # Sort by importance and return top 5
        factors.sort(key=lambda f: f.importance, reverse=True)
        return factors[:5]
    
    def _is_value_concerning(self, feature_name: str, value: float) -> bool:
        """Check if a feature value is in concerning range"""
        thresholds = {
            "runtime_hours": (40000, float('inf')),
            "days_since_maintenance": (60, float('inf')),
            "efficiency": (0, 0.7),
            "efficiency_trend": (float('-inf'), -0.03),
            "fault_count_30d": (3, float('inf')),
        }
        
        if feature_name in thresholds:
            low, high = thresholds[feature_name]
            return low <= value <= high
        
        return False
    
    def _generate_recommendation(
        self,
        risk_level: str,
        factors: List[FeatureFactor],
        features: EquipmentFeatures
    ) -> str:
        """Generate actionable recommendation based on prediction"""
        
        if risk_level == "critical":
            if features.days_since_maintenance > 60:
                return "URGENT: Schedule immediate maintenance. Equipment is overdue and showing degradation."
            else:
                return "URGENT: Inspect equipment immediately. High failure risk detected."
        
        elif risk_level == "high":
            concerning = [f.name for f in factors if f.is_concerning]
            if "efficiency" in concerning:
                return f"Schedule maintenance within 2 weeks. Efficiency has dropped to {features.efficiency:.0%}."
            elif "fault_count_30d" in concerning:
                return f"Investigate recurring faults ({features.fault_count_30d} in last 30 days). Consider preventive maintenance."
            else:
                return "Schedule maintenance within 30 days. Multiple indicators suggest degradation."
        
        elif risk_level == "medium":
            if features.days_since_maintenance > 90:
                return f"Maintenance recommended. Last service was {features.days_since_maintenance} days ago."
            else:
                return "Monitor closely. Some indicators trending toward concern."
        
        else:  # low
            return "Equipment operating normally. Continue standard monitoring."
    
    # ═══════════════════════════════════════════════════════════════════════
    # ANOMALY DETECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    def detect_anomalies(
        self, 
        equipment_id: str,
        features: EquipmentFeatures
    ) -> List[Anomaly]:
        """
        Detect anomalies in equipment behavior using Isolation Forest.
        
        Returns list of detected anomalies with explanations.
        """
        anomalies = []
        X = features.to_array().reshape(1, -1)
        
        if self.is_trained:
            X_scaled = self.scaler.transform(X)
            prediction = self.anomaly_detector.predict(X_scaled)[0]
            score = -self.anomaly_detector.decision_function(X_scaled)[0]
            
            if prediction == -1:  # Anomaly detected
                # Identify which features are anomalous
                anomalous_features = self._identify_anomalous_features(features)
                
                for feature_name, deviation in anomalous_features:
                    anomalies.append(Anomaly(
                        anomaly_type="equipment_behavior",
                        severity=min(1.0, abs(score)),
                        source_id=equipment_id,
                        detected_value=getattr(features, feature_name, 0),
                        expected_value=0,  # Would need baseline
                        deviation_percent=deviation,
                        description=f"Unusual {feature_name.replace('_', ' ')}: {deviation:.1%} deviation from normal",
                    ))
        
        return anomalies
    
    def _identify_anomalous_features(
        self, 
        features: EquipmentFeatures
    ) -> List[Tuple[str, float]]:
        """Identify which specific features are anomalous"""
        # Simple z-score based detection
        anomalous = []
        
        # Check key features against expected ranges
        checks = [
            ("efficiency", 0.85, 1.0),
            ("delta_t", 8, 15),
            ("motor_current", 0, 100),
        ]
        
        for name, expected_low, expected_high in checks:
            value = getattr(features, name, None)
            if value is not None:
                if value < expected_low:
                    deviation = (expected_low - value) / expected_low
                    anomalous.append((name, -deviation))
                elif value > expected_high:
                    deviation = (value - expected_high) / expected_high
                    anomalous.append((name, deviation))
        
        return anomalous
    
    # ═══════════════════════════════════════════════════════════════════════
    # HISTORY MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    
    def add_to_history(
        self, 
        equipment_id: str, 
        features: EquipmentFeatures
    ) -> None:
        """Add feature snapshot to equipment history for trend analysis"""
        if equipment_id not in self.equipment_history:
            self.equipment_history[equipment_id] = []
        
        self.equipment_history[equipment_id].append(features)
        
        # Keep last 90 days of daily snapshots
        if len(self.equipment_history[equipment_id]) > 90:
            self.equipment_history[equipment_id].pop(0)
    
    def get_efficiency_trend(self, equipment_id: str, days: int = 7) -> float:
        """Calculate efficiency trend over specified days"""
        history = self.equipment_history.get(equipment_id, [])
        
        if len(history) < 2:
            return 0.0
        
        recent = history[-days:] if len(history) >= days else history
        
        if len(recent) < 2:
            return 0.0
        
        # Simple linear trend: (last - first) / first
        first_eff = recent[0].efficiency
        last_eff = recent[-1].efficiency
        
        if first_eff > 0:
            return (last_eff - first_eff) / first_eff
        
        return 0.0
