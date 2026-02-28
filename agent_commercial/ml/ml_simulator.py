"""
ML-Enhanced What-If Simulator
=============================

Gaussian Process + LightGBM ensemble for uncertainty-aware predictions.

Features:
- Gaussian Process Regression for uncertainty quantification
- LightGBM for feature-based prediction
- Monte Carlo simulation for risk assessment
- Historical similar-change lookup

Custom for BMS:
- Building thermal dynamics kernel
- Weather-aware predictions
- Comfort model integration

Usage:
    >>> simulator = MLSimulator("tower_a")
    >>> simulator.train(historical_changes)
    >>> result = simulator.simulate_with_uncertainty(change)
"""

import logging
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

logger = logging.getLogger("arvis.ml.simulator")

try:
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel, Matern
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    warnings.warn("scikit-learn not available")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False


# =============================================================================
# CONSTANTS
# =============================================================================

# Energy savings per degree setpoint change (BMS industry standard)
SAVINGS_PER_DEGREE = 0.07  # 7% per degree

# Comfort thresholds
PPD_THRESHOLD = 10  # Predicted Percentage Dissatisfied


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class SimulationPrediction:
    """Prediction with uncertainty bounds"""
    mean: float
    lower_bound: float
    upper_bound: float
    confidence: float
    std_dev: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mean": round(self.mean, 2),
            "lower_bound": round(self.lower_bound, 2),
            "upper_bound": round(self.upper_bound, 2),
            "confidence": round(self.confidence, 3),
            "std_dev": round(self.std_dev, 3),
        }


@dataclass
class MLSimulationResult:
    """Complete ML simulation result"""
    change_type: str
    current_value: float
    proposed_value: float
    
    # Energy predictions
    energy_impact: SimulationPrediction
    cost_impact_qar: SimulationPrediction
    
    # Comfort predictions
    comfort_impact: SimulationPrediction
    
    # Risk from Monte Carlo
    risk_of_reversion: float  # Probability of needing to revert
    risk_factors: List[str]
    
    # Similar historical changes
    similar_changes: List[Dict[str, Any]]
    
    # Model info
    model_used: str
    simulation_time: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_type": self.change_type,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "energy_impact": self.energy_impact.to_dict(),
            "cost_impact_qar": self.cost_impact_qar.to_dict(),
            "comfort_impact": self.comfort_impact.to_dict(),
            "risk_of_reversion": round(self.risk_of_reversion, 3),
            "risk_factors": self.risk_factors,
            "similar_changes": self.similar_changes,
            "model_used": self.model_used,
        }


# =============================================================================
# ML SIMULATOR
# =============================================================================

class MLSimulator:
    """
    ML-enhanced What-If Simulator with uncertainty quantification.
    
    Uses Gaussian Process for uncertainty bounds and LightGBM for
    feature-based predictions.
    """
    
    def __init__(self, 
                 building_id: str = "default",
                 building_area_m2: float = 10000):
        self.building_id = building_id
        self.building_area = building_area_m2
        
        # Gaussian Process for energy impact
        if SKLEARN_AVAILABLE:
            # Matern kernel for building thermal dynamics
            kernel = Matern(length_scale=1.0, nu=2.5) + WhiteKernel(noise_level=0.1)
            self.gp_energy = GaussianProcessRegressor(
                kernel=kernel,
                n_restarts_optimizer=5,
                normalize_y=True,
            )
        else:
            self.gp_energy = None
        
        # LightGBM for feature-based prediction
        self.lgbm_energy = None
        self.lgbm_comfort = None
        
        # Scalers
        self.feature_scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        
        # Historical changes for similarity lookup
        self.change_history: List[Dict[str, Any]] = []
        
        self.is_trained = False
        
        logger.info(f"MLSimulator initialized for {building_id}")
    
    def add_historical_change(self, change: Dict[str, Any]) -> None:
        """Add a historical change and its outcome for learning."""
        self.change_history.append({
            "change_type": change.get("change_type"),
            "delta": change.get("proposed_value", 0) - change.get("current_value", 0),
            "outdoor_temp": change.get("outdoor_temp", 35),
            "energy_delta_pct": change.get("energy_delta_pct", 0),
            "comfort_complaints": change.get("comfort_complaints", 0),
            "was_reverted": change.get("was_reverted", False),
            "timestamp": change.get("timestamp", datetime.now()),
        })
    
    def train(self, 
              historical_changes: List[Dict[str, Any]],
              outcomes: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Train models on historical operational changes.
        
        Args:
            historical_changes: List of change dictionaries
            outcomes: Optional DataFrame with change outcomes
            
        Returns:
            Training metrics
        """
        for change in historical_changes:
            self.add_historical_change(change)
        
        if len(self.change_history) < 10:
            logger.warning("Insufficient history for training")
            return {"status": "insufficient_data", "samples": len(self.change_history)}
        
        # Prepare features
        df = pd.DataFrame(self.change_history)
        
        features = ["delta", "outdoor_temp"]
        X = df[features].values
        
        # ─────────────────────────────────────────────────────────────────
        # Train Gaussian Process for energy impact
        # ─────────────────────────────────────────────────────────────────
        if self.gp_energy and "energy_delta_pct" in df.columns:
            y_energy = df["energy_delta_pct"].values
            
            X_scaled = self.feature_scaler.fit_transform(X)
            self.gp_energy.fit(X_scaled, y_energy)
            
            logger.info("GP model trained for energy prediction")
        
        # ─────────────────────────────────────────────────────────────────
        # Train LightGBM for comfort prediction
        # ─────────────────────────────────────────────────────────────────
        if LIGHTGBM_AVAILABLE and "comfort_complaints" in df.columns:
            y_comfort = df["comfort_complaints"].values
            
            train_data = lgb.Dataset(X, label=y_comfort)
            params = {
                "objective": "regression",
                "metric": "rmse",
                "verbose": -1,
            }
            self.lgbm_comfort = lgb.train(params, train_data, num_boost_round=100)
            
            logger.info("LightGBM trained for comfort prediction")
        
        self.is_trained = True
        
        return {
            "status": "trained",
            "samples": len(self.change_history),
            "features": features,
        }
    
    def simulate_with_uncertainty(self,
                                   change: Dict[str, Any],
                                   outdoor_temp: float = 35,
                                   n_monte_carlo: int = 1000) -> MLSimulationResult:
        """
        Simulate change impact with uncertainty bounds.
        
        Uses GP for uncertainty and Monte Carlo for risk.
        """
        change_type = change.get("change_type", "setpoint")
        current = float(change.get("current_value", 22))
        proposed = float(change.get("proposed_value", 23))
        delta = proposed - current
        
        # ─────────────────────────────────────────────────────────────────
        # Energy Impact Prediction
        # ─────────────────────────────────────────────────────────────────
        if self.is_trained and self.gp_energy:
            X_new = np.array([[delta, outdoor_temp]])
            X_scaled = self.feature_scaler.transform(X_new)
            
            mean, std = self.gp_energy.predict(X_scaled, return_std=True)
            energy_mean = float(mean[0])
            energy_std = float(std[0])
        else:
            # Fallback: physics-based estimate
            energy_mean = delta * SAVINGS_PER_DEGREE * 100  # As percentage
            energy_std = abs(energy_mean) * 0.2  # 20% uncertainty
        
        # Convert to kWh
        baseline_kwh = self.building_area * 0.15  # 150 Wh/m²/day
        energy_delta_kwh = baseline_kwh * energy_mean / 100
        
        # Cost calculation (average rate)
        # CALIBRATION: Avoid negative QAR (it's either a cost or a saving)
        # energy_delta_kwh can be negative (savings), but cost impact should be absolute
        # or clearly signed. We'll use signed: + is cost, - is saving.
        cost_mean = energy_delta_kwh * 0.05  # QAR 0.05/kWh average
        
        # SUPPRESSION: If impact is tiny, round to 0 to avoid "rubbish" noise
        if abs(cost_mean) < 0.1:
            cost_mean = 0.0
            
        cost_std = abs(cost_mean) * 0.2
        
        energy_impact = SimulationPrediction(
            mean=energy_mean,
            lower_bound=energy_mean - 2 * energy_std,
            upper_bound=energy_mean + 2 * energy_std,
            confidence=0.95,
            std_dev=energy_std,
        )
        
        cost_impact = SimulationPrediction(
            mean=cost_mean * 30,  # Monthly
            lower_bound=(cost_mean - 2 * cost_std) * 30,
            upper_bound=(cost_mean + 2 * cost_std) * 30,
            confidence=0.95,
            std_dev=cost_std * 30,
        )
        
        # ─────────────────────────────────────────────────────────────────
        # Comfort Impact Prediction
        # ─────────────────────────────────────────────────────────────────
        if self.lgbm_comfort:
            X_new = np.array([[delta, outdoor_temp]])
            comfort_pred = self.lgbm_comfort.predict(X_new)[0]
            # CALIBRATION: Suppression of tiny/negative comfort complaints
            if comfort_pred < 0.5:
                comfort_pred = 0.0
            comfort_std = abs(comfort_pred) * 0.3
        else:
            # Fallback: simple model
            # Each degree warmer increases complaints by 5%
            comfort_pred = max(0.0, delta * 5.0)  # Complaints percentage
            # CALIBRATION: If delta is cooling (negative), complaints are 0
            if delta <= 0:
                comfort_pred = 0.0
            comfort_std = 2.0
        
        comfort_impact = SimulationPrediction(
            mean=comfort_pred,
            lower_bound=max(0, comfort_pred - 2 * comfort_std),
            upper_bound=comfort_pred + 2 * comfort_std,
            confidence=0.90,
            std_dev=comfort_std,
        )
        
        # ─────────────────────────────────────────────────────────────────
        # Monte Carlo Risk Assessment
        # ─────────────────────────────────────────────────────────────────
        risk_of_reversion, risk_factors = self._monte_carlo_risk(
            delta, outdoor_temp, energy_std, comfort_pred, n_monte_carlo
        )
        
        # ─────────────────────────────────────────────────────────────────
        # Find Similar Historical Changes
        # ─────────────────────────────────────────────────────────────────
        similar = self._find_similar_changes(delta, outdoor_temp)
        
        return MLSimulationResult(
            change_type=change_type,
            current_value=current,
            proposed_value=proposed,
            energy_impact=energy_impact,
            cost_impact_qar=cost_impact,
            comfort_impact=comfort_impact,
            risk_of_reversion=risk_of_reversion,
            risk_factors=risk_factors,
            similar_changes=similar,
            model_used="gp_lgbm" if self.is_trained else "physics",
        )
    
    def _monte_carlo_risk(self,
                          delta: float,
                          outdoor_temp: float,
                          energy_std: float,
                          comfort_mean: float,
                          n_samples: int) -> Tuple[float, List[str]]:
        """
        Monte Carlo simulation for risk assessment.
        
        Simulates various scenarios to estimate probability of needing to revert.
        """
        risk_factors = []
        reversion_count = 0
        
        for _ in range(n_samples):
            # Sample energy outcome
            energy_outcome = np.random.normal(delta * 7, energy_std)
            
            # Sample comfort outcome
            comfort_outcome = np.random.normal(comfort_mean, comfort_mean * 0.3 + 1)
            
            # Sample outdoor temp variation
            temp_variation = np.random.normal(outdoor_temp, 3)
            
            # Check for reversion triggers
            revert = False
            
            # Trigger 1: High complaints
            if comfort_outcome > 10:
                revert = True
            
            # Trigger 2: Extreme weather + insufficient comfort
            if temp_variation > 42 and delta > 0:  # Raised setpoint in extreme heat
                if np.random.random() < 0.3:
                    revert = True
            
            # Trigger 3: Negative energy impact (unexpected)
            if delta > 0 and energy_outcome < -5:  # Expected savings but got increase
                if np.random.random() < 0.2:
                    revert = True
            
            if revert:
                reversion_count += 1
        
        risk_of_reversion = reversion_count / n_samples
        
        # Identify risk factors
        if delta > 2:
            risk_factors.append("Large setpoint change (>2°C)")
        if outdoor_temp > 42:
            risk_factors.append("Extreme outdoor temperature")
        if comfort_mean > 5:
            risk_factors.append("Predicted comfort complaints")
        
        return risk_of_reversion, risk_factors
    
    def _find_similar_changes(self, 
                              delta: float, 
                              outdoor_temp: float,
                              top_k: int = 3) -> List[Dict[str, Any]]:
        """Find similar historical changes."""
        similar = []
        
        for change in self.change_history:
            # Similarity based on delta and temperature
            delta_diff = abs(change["delta"] - delta)
            temp_diff = abs(change["outdoor_temp"] - outdoor_temp)
            
            similarity = 1 / (1 + delta_diff + temp_diff * 0.1)
            
            similar.append({
                "delta": change["delta"],
                "outdoor_temp": change["outdoor_temp"],
                "outcome": change.get("energy_delta_pct", 0),
                "was_reverted": change.get("was_reverted", False),
                "similarity": round(similarity, 2),
            })
        
        # Sort by similarity
        similar.sort(key=lambda x: x["similarity"], reverse=True)
        
        return similar[:top_k]


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def simulate_with_ml(
    change_type: str,
    current_value: float,
    proposed_value: float,
    building_id: str = "default",
    outdoor_temp: float = 35,
) -> Dict[str, Any]:
    """
    ML-enhanced simulation - LLM tool handler.
    """
    simulator = MLSimulator(building_id)
    
    result = simulator.simulate_with_uncertainty({
        "change_type": change_type,
        "current_value": current_value,
        "proposed_value": proposed_value,
    }, outdoor_temp=outdoor_temp)
    
    return result.to_dict()


if __name__ == "__main__":
    print("=" * 60)
    print("ML Simulator Test")
    print("=" * 60)
    
    simulator = MLSimulator("tower_a")
    
    # Add some historical changes
    historical = [
        {"change_type": "setpoint", "current_value": 22, "proposed_value": 23,
         "outdoor_temp": 35, "energy_delta_pct": 6.5, "comfort_complaints": 3, "was_reverted": False},
        {"change_type": "setpoint", "current_value": 22, "proposed_value": 24,
         "outdoor_temp": 38, "energy_delta_pct": 12, "comfort_complaints": 8, "was_reverted": True},
        {"change_type": "setpoint", "current_value": 23, "proposed_value": 24,
         "outdoor_temp": 32, "energy_delta_pct": 7, "comfort_complaints": 2, "was_reverted": False},
        {"change_type": "setpoint", "current_value": 22, "proposed_value": 23,
         "outdoor_temp": 40, "energy_delta_pct": 5, "comfort_complaints": 5, "was_reverted": False},
    ]
    
    for h in historical:
        simulator.add_historical_change(h)
    
    # Simulate new change
    result = simulator.simulate_with_uncertainty({
        "change_type": "setpoint",
        "current_value": 22,
        "proposed_value": 23,
    }, outdoor_temp=36)
    
    print(f"\nSimulation: 22°C → 23°C at 36°C outdoor")
    print(f"\nEnergy Impact:")
    print(f"  Mean: {result.energy_impact.mean:+.1f}%")
    print(f"  95% CI: [{result.energy_impact.lower_bound:.1f}%, {result.energy_impact.upper_bound:.1f}%]")
    
    print(f"\nCost Impact (monthly):")
    print(f"  Mean: QAR {result.cost_impact_qar.mean:+.0f}")
    print(f"  95% CI: [QAR {result.cost_impact_qar.lower_bound:.0f}, QAR {result.cost_impact_qar.upper_bound:.0f}]")
    
    print(f"\nComfort Impact:")
    print(f"  Predicted complaints: {result.comfort_impact.mean:.1f}%")
    
    print(f"\nRisk Assessment:")
    print(f"  Reversion probability: {result.risk_of_reversion:.1%}")
    for risk in result.risk_factors:
        print(f"  ⚠️ {risk}")
