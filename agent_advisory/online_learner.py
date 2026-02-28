"""
Online Learning Engine
======================

Tracks model performance in real-time and triggers incremental updates or 
full retraining when concept drift is detected.

Capabilities:
1. Performance monitoring (RMSE, Accuracy).
2. Drift detection (CUSUM or simple threshold).
3. Experience buffering for batch updates.
4. Automated model deployment (swap active model).
"""

import logging
import time
import json
import numpy as np
from typing import Dict, List, Any, Optional
from collections import deque
from datetime import datetime

logger = logging.getLogger("arvis.advisory.online_learning")

class OnlineLearner:
    """
    Monitors the delta between World Model predictions and actual BMS outcomes.
    If the error exceeds thresholds, it triggers retraining.
    """
    
    def __init__(self, 
                 world_model: Any, 
                 drift_threshold: float = 1.5,
                 min_samples_for_update: int = 50):
        self.world_model = world_model
        self.drift_threshold = drift_threshold
        self.min_samples_for_update = min_samples_for_update
        
        # Buffer to store (prediction, actual) pairs
        self.experience_buffer = deque(maxlen=1000)
        self.baseline_rmse = 0.0 # Will be populated dynamically after buffer fills
        
    def log_observation(self, prediction: Dict[str, Any], actual: Dict[str, Any]):
        """
        Log a paired prediction and actual observation.
        
        Args:
            prediction: Features predicted by World Model (e.g., {"total_power_kw": 450})
            actual: Actual sensor readings from BMS
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "prediction": prediction,
            "actual": actual,
            "error": self._calculate_error(prediction, actual)
        }
        self.experience_buffer.append(record)
        
        # Check for drift every 10 samples
        if len(self.experience_buffer) % 10 == 0:
            self._check_for_drift()

    def _calculate_error(self, pred: Dict, actual: Dict) -> float:
        """Calculate mean squared error for numeric features"""
        errors = []
        for key in pred:
            if key in actual and isinstance(pred[key], (int, float)) and isinstance(actual[key], (int, float)):
                errors.append((pred[key] - actual[key])**2)
        
        return np.sqrt(np.mean(errors)) if errors else 0.0

    def _check_for_drift(self):
        """Analyze buffer for concept drift"""
        if len(self.experience_buffer) < 20:
            return
            
        recent_errors = [r["error"] for r in list(self.experience_buffer)[-20:]]
        current_rmse = np.mean(recent_errors)
        
        # Update baseline if this is the first real run
        if self.baseline_rmse <= 0.0 and len(self.experience_buffer) > 50:
            self.baseline_rmse = np.mean([r["error"] for r in list(self.experience_buffer)[:50]])
            logger.info(f"Established baseline RMSE: {self.baseline_rmse:.3f}")
            
        drift_ratio = current_rmse / self.baseline_rmse if self.baseline_rmse > 0 else 1.0
        
        if drift_ratio > self.drift_threshold:
            logger.warning(f"Concept Drift Detected! Ratio: {drift_ratio:.2f}. Triggering retraining...")
            self._trigger_retraining()
            # Reset baseline after trigger to avoid immediate re-trigger
            self.baseline_rmse = current_rmse

    def _trigger_retraining(self):
        """Trigger the training logic in the transition model"""
        logger.info("Retraining models with recent experience buffer data...")
        
        # Extract training data from buffer and format as scenarios
        historical_scenarios = []
        for rec in self.experience_buffer:
            # S_t is 'prediction' context, A_t is implied or stored, S_{t+1} is 'actual'
            # For the prototype, we wrap the actual reading as a scenario
            scenario = {
                "context": rec["actual"],
                "operator_decision": "no_op", # Simplification: assume drift happens during no-op
                "outcome": {"utility_score": rec.get("utility_score", getattr(self.world_model, 'calculate_utility', lambda s: 0.0)(rec["actual"]))}
            }
            historical_scenarios.append(scenario)
            
        if hasattr(self.world_model, "transition_model"):
            try:
                # The train method expects historical_scenarios
                self.world_model.transition_model.train(historical_scenarios)
                logger.info("World Model transition models updated successfully.")
            except Exception as e:
                logger.error(f"Retraining failed: {e}")

    def get_performance_summary(self) -> Dict[str, Any]:
        """Return metrics for trust calibration"""
        if not self.experience_buffer:
            return {"status": "no_data"}
            
        errors = [r["error"] for r in self.experience_buffer]
        return {
            "current_rmse": np.mean(errors[-20:]),
            "long_term_rmse": np.mean(errors),
            "sample_count": len(self.experience_buffer),
            "drift_ratio": np.mean(errors[-20:]) / self.baseline_rmse if self.baseline_rmse > 0 else 1.0
        }
