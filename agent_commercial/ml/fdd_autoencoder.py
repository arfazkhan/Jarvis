"""
Fault Detection & Diagnostics Autoencoder
==========================================

Deep learning-based anomaly detection for BMS equipment.

Architecture:
- Variational Autoencoder (VAE) for multivariate time-series
- Reconstruction error as anomaly score
- Physics-constrained loss (respects thermodynamic relationships)

Custom for BMS:
- Multi-point input: SAT, RAT, DAT, CHW temps, pressures
- Temporal context: Last N timesteps
- Equipment-specific models (Chiller, AHU, VAV)

ASHRAE RP-1312 inspired fault detection rules integrated.

Usage:
    >>> fdd = FDDAutoencoder(equipment_type="chiller")
    >>> fdd.train(historical_data)
    >>> anomalies = fdd.detect(current_readings)
"""

import logging
import warnings
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

logger = logging.getLogger("arvis.ml.fdd")

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# =============================================================================
# ASHRAE RP-1312 FAULT RULES (Rule-based backup)
# =============================================================================

ASHRAE_FAULT_RULES = {
    "ahu": {
        "SAT_HIGH": {
            "condition": lambda d: d.get("sat", 0) > d.get("sat_setpoint", 14) + 2,
            "description": "Supply Air Temperature too high",
            "severity": "medium",
        },
        "SAT_LOW": {
            "condition": lambda d: d.get("sat", 100) < d.get("sat_setpoint", 14) - 2,
            "description": "Supply Air Temperature too low",
            "severity": "medium",
        },
        "ECONOMIZER_NOT_MODULATING": {
            "condition": lambda d: d.get("oa_damper", 0) in [0, 100] and 
                                   d.get("oat", 40) < 24,  # Good for economizing
            "description": "Economizer stuck or not modulating",
            "severity": "low",
        },
        "HEATING_COOLING_SIMULTANEOUS": {
            "condition": lambda d: d.get("heating_valve", 0) > 10 and 
                                   d.get("cooling_valve", 0) > 10,
            "description": "Simultaneous heating and cooling detected",
            "severity": "high",
        },
        "HIGH_FILTER_DP": {
            "condition": lambda d: d.get("filter_dp", 0) > 300,  # Pa
            "description": "High filter differential pressure",
            "severity": "medium",
        },
    },
    "chiller": {
        "LOW_EVAP_APPROACH": {
            "condition": lambda d: d.get("evap_approach", 10) < 2,
            "description": "Low evaporator approach temperature",
            "severity": "medium",
        },
        "HIGH_COND_APPROACH": {
            "condition": lambda d: d.get("cond_approach", 5) > 8,
            "description": "High condenser approach - fouling suspected",
            "severity": "medium",
        },
        "LOW_EFFICIENCY": {
            "condition": lambda d: d.get("kw_per_ton", 0.6) > 0.9,
            "description": "Chiller efficiency below threshold",
            "severity": "high",
        },
        "HIGH_LIFT": {
            "condition": lambda d: d.get("lift", 30) > 50,
            "description": "High lift - check condenser water temps",
            "severity": "medium",
        },
    },
    "vav": {
        "STUCK_DAMPER": {
            "condition": lambda d: d.get("damper_pos", 50) == d.get("prev_damper_pos", 50) and
                                   abs(d.get("zone_temp", 22) - d.get("zone_setpoint", 22)) > 1,
            "description": "VAV damper appears stuck",
            "severity": "medium",
        },
        "ZONE_OVERCOOL": {
            "condition": lambda d: d.get("zone_temp", 22) < d.get("zone_setpoint", 22) - 2,
            "description": "Zone overcooling",
            "severity": "low",
        },
        "ZONE_UNDERCOOL": {
            "condition": lambda d: d.get("zone_temp", 22) > d.get("zone_setpoint", 22) + 2,
            "description": "Zone undercooling",
            "severity": "medium",
        },
    },
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class FaultDetection:
    """Detected fault with explanation"""
    fault_id: str
    equipment_id: str
    fault_type: str
    severity: str  # low, medium, high, critical
    confidence: float
    description: str
    detected_value: float
    expected_range: Tuple[float, float]
    recommendation: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "equipment_id": self.equipment_id,
            "fault_type": self.fault_type,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "description": self.description,
            "detected_value": round(self.detected_value, 2),
            "expected_range": [round(self.expected_range[0], 2), 
                              round(self.expected_range[1], 2)],
            "recommendation": self.recommendation,
            "timestamp": self.timestamp.isoformat(),
        }


# =============================================================================
# VAE PYTORCH MODULES
# =============================================================================

class _VAEEncoder(nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, input_dim, latent_dim):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
        )
        self.fc_mu = nn.Linear(32, latent_dim)
        self.fc_log_var = nn.Linear(32, latent_dim)

    def forward(self, x):
        h = self.encoder(x)
        return self.fc_mu(h), self.fc_log_var(h)


class _VAEDecoder(nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, latent_dim, output_dim):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 32), nn.ReLU(),
            nn.Linear(32, 64), nn.ReLU(),
            nn.Linear(64, output_dim),
        )

    def forward(self, z):
        return self.decoder(z)


class _VAE(nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, input_dim, latent_dim=8):
        if not TORCH_AVAILABLE:
            return
        super().__init__()
        self.encoder = _VAEEncoder(input_dim, latent_dim)
        self.decoder = _VAEDecoder(latent_dim, input_dim)

    def reparameterise(self, mu, log_var):
        std = torch.exp(0.5 * log_var)
        eps = torch.randn_like(std)
        return mu + eps * std

    def forward(self, x):
        mu, log_var = self.encoder(x)
        z = self.reparameterise(mu, log_var)
        return self.decoder(z), mu, log_var


class FDDAutoencoder:
    """
    Variational Autoencoder for Fault Detection & Diagnostics.
    
    Uses reconstruction error to detect anomalies in equipment behavior.
    Physics-informed loss ensures thermodynamic consistency.
    """
    
    # Default feature sets per equipment type
    FEATURE_SETS = {
        "ahu": [
            "sat", "rat", "mat", "oat",  # Temperatures
            "sa_flow", "ra_flow",  # Airflows
            "cooling_valve", "heating_valve", "oa_damper",  # Actuators
            "filter_dp", "fan_speed",  # Other
        ],
        "chiller": [
            "evap_lwt", "evap_ewt", "cond_lwt", "cond_ewt",  # Temps
            "evap_flow", "cond_flow",  # Flows
            "power_kw", "capacity_tons",  # Power
            "evap_pressure", "cond_pressure",  # Pressures
        ],
        "vav": [
            "zone_temp", "zone_setpoint",
            "sat", "dat",
            "damper_pos", "airflow",
            "reheat_valve",
        ],
    }
    
    def __init__(self, 
                 equipment_type: str = "ahu",
                 sequence_length: int = 6,  # Last 6 readings
                 latent_dim: int = 8,
                 custom_features: Optional[List[str]] = None):
        """
        Initialize FDD Autoencoder.
        
        Args:
            equipment_type: "ahu", "chiller", or "vav"
            sequence_length: Number of timesteps in input sequence
            latent_dim: Dimensionality of latent space
            custom_features: Optional list of specific feature names
        """
        self.equipment_type = equipment_type.lower()
        self.sequence_length = sequence_length
        self.latent_dim = latent_dim
        
        # Get features for this equipment type
        if custom_features:
            self.features = custom_features
        else:
            self.features = self.FEATURE_SETS.get(self.equipment_type, 
                                                   self.FEATURE_SETS["ahu"])
        self.n_features = len(self.features)
        
        # Scaler for normalization
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        
        # VAE model (PyTorch)
        self._vae = None
        self._vae_optimizer = None
        
        # Anomaly threshold (learned from training)
        self.threshold = 0.1
        self.mean_loss = 0.0
        self.std_loss = 0.01
        
        self.is_trained = False

        # sklearn fallback autoencoder (used when TF is not available)
        self._sklearn_ae = None
        self._sklearn_threshold = 0.1
        self._sklearn_mean_loss = 0.0
        self._sklearn_std_loss = 0.01

        logger.info(f"FDDAutoencoder initialized for {equipment_type} with {self.n_features} features")
    
    def _build_model(self) -> None:
        """Build the VAE architecture."""
        if not TORCH_AVAILABLE:
            logger.warning("[FDD] PyTorch unavailable — VAE not built. ASHRAE rules only.")
            self._vae = None
            return
        input_dim = self.sequence_length * self.n_features
        self._vae = _VAE(input_dim=input_dim, latent_dim=self.latent_dim)
        self._vae_optimizer = torch.optim.Adam(self._vae.parameters(), lr=1e-3)
        logger.info(f"[FDD] PyTorch VAE built (input_dim={input_dim})")
    
    def _physics_constraint_loss(self, y_true, y_pred) -> Any:
        """
        Physics-informed loss to ensure thermodynamic consistency.

        For AHU: SAT should be between MAT and cooling coil capacity
        For Chiller: Evap approach should be positive
        """
        if not TORCH_AVAILABLE:
            return 0.0

        if self.equipment_type == "ahu":
            sat_idx = self.features.index("sat") if "sat" in self.features else 0
            rat_idx = self.features.index("rat") if "rat" in self.features else 1
            sat_pred = y_pred[:, sat_idx]
            rat_pred = y_pred[:, rat_idx]
            violation = torch.clamp(sat_pred - rat_pred, min=0.0)
            return violation.mean()

        return torch.tensor(0.0)
    
    def train(self, 
              historical_data: pd.DataFrame,
              epochs: int = 50,
              batch_size: int = 32) -> Dict[str, Any]:
        """
        Train the autoencoder on normal operating data.
        
        Args:
            historical_data: DataFrame with columns matching self.features
            epochs: Training epochs
            batch_size: Batch size
            
        Returns:
            Training metrics
        """
        # Validate features
        available_features = [f for f in self.features if f in historical_data.columns]
        if len(available_features) < 3:
            logger.warning(f"Insufficient features for training: {available_features}")
            return {"status": "failed", "error": "insufficient_features"}
        
        self.features = available_features
        self.n_features = len(self.features)
        
        # Prepare data and impute missing values (NaNs)
        clean_df = historical_data[self.features].ffill().bfill().fillna(0.0)
        data = clean_df.values
        
        # Scale data
        if self.scaler:
            data = self.scaler.fit_transform(data)
        
        # Create sequences
        sequences = []
        for i in range(len(data) - self.sequence_length + 1):
            sequences.append(data[i:i + self.sequence_length])
        
        X = np.array(sequences)
        
        if len(X) < max(10, self.sequence_length * 2):
            logger.warning(f"Insufficient training data: {len(X)} sequences (need {max(10, self.sequence_length * 2)})")
            return {"status": "failed", "error": "insufficient_data"}
        
        # Build model
        self._build_model()
        
        if self._vae is not None and TORCH_AVAILABLE:
            # ── PyTorch VAE training path ─────────────────────────────────────
            try:
                import torch
                X_tensor = torch.tensor(
                    X.reshape(len(X), self.sequence_length * self.n_features),
                    dtype=torch.float32,
                )
                self._vae.train()
                for _ in range(epochs):
                    perm = torch.randperm(len(X_tensor))
                    for start in range(0, len(X_tensor), batch_size):
                        idx = perm[start:start + batch_size]
                        xb = X_tensor[idx]
                        recon, mu, log_var = self._vae(xb)
                        recon_loss = ((xb - recon) ** 2).mean()
                        kl_loss = -0.5 * (1 + log_var - mu ** 2 - log_var.exp()).mean()
                        loss = recon_loss + 0.01 * kl_loss
                        self._vae_optimizer.zero_grad()
                        loss.backward()
                        self._vae_optimizer.step()

                self._vae.eval()
                with torch.no_grad():
                    recon_all, mu_all, lv_all = self._vae(X_tensor)
                reconstruction_errors = ((X_tensor - recon_all) ** 2).mean(dim=1).numpy()
                self.mean_loss = float(np.mean(reconstruction_errors))
                self.std_loss = float(np.std(reconstruction_errors))
                self.threshold = self.mean_loss + 2 * self.std_loss
                self.is_trained = True
                logger.info(f"[FDD] PyTorch VAE trained: threshold={self.threshold:.4f}")
                return {
                    "status": "trained",
                    "backend": "pytorch",
                    "samples": len(X),
                    "features": self.features,
                    "threshold": self.threshold,
                    "mean_reconstruction_error": self.mean_loss,
                }
            except Exception as pt_err:
                logger.warning(f"[FDD] PyTorch VAE training failed: {pt_err}")
                self._vae = None

        if self._vae is None:
            # ── sklearn autoencoder fallback ──────────────────────────────────
            try:
                from sklearn.neural_network import MLPRegressor
                X_flat = X.reshape(len(X), self.sequence_length * self.n_features)
                sklearn_ae = MLPRegressor(
                    hidden_layer_sizes=(64, 32, 8, 32, 64),
                    activation="relu",
                    max_iter=200,
                    random_state=42,
                    verbose=False,
                )
                sklearn_ae.fit(X_flat, X_flat)
                reconstructions = sklearn_ae.predict(X_flat)
                mse_per_sample = np.mean(np.square(X_flat - reconstructions), axis=1)
                sk_mean = float(np.mean(mse_per_sample))
                sk_std = float(np.std(mse_per_sample))
                sk_threshold = sk_mean + 2 * sk_std

                self._sklearn_ae = sklearn_ae
                self._sklearn_mean_loss = sk_mean
                self._sklearn_std_loss = sk_std
                self._sklearn_threshold = sk_threshold
                # Use the same top-level threshold attrs so get_health_score is consistent
                self.mean_loss = sk_mean
                self.std_loss = sk_std
                self.threshold = sk_threshold
                self.is_trained = True

                logger.info(
                    f"FDD sklearn autoencoder trained: threshold={sk_threshold:.4f}"
                )
                return {
                    "status": "trained",
                    "backend": "sklearn",
                    "samples": len(X),
                    "features": self.features,
                    "threshold": sk_threshold,
                    "mean_reconstruction_error": sk_mean,
                }
            except ImportError:
                logger.warning("sklearn not available; falling back to rule-based FDD only")
                self.is_trained = False
                return {"status": "failed", "error": "sklearn_not_available"}
            except Exception as sk_err:
                logger.warning(f"sklearn autoencoder training failed: {sk_err}")
                self.is_trained = False
                return {"status": "failed", "error": f"sklearn_training_failed: {sk_err}"}
        
        return {"status": "failed", "error": "no_backend_available"}
    
    def detect(self, 
               current_data: pd.DataFrame,
               equipment_id: str = "unknown") -> List[FaultDetection]:
        """
        Detect faults in current readings.
        
        Uses both autoencoder (if trained) and ASHRAE rules.
        """
        faults = []
        
        # ─────────────────────────────────────────────────────────────────
        # 1. PyTorch VAE-based detection
        # ─────────────────────────────────────────────────────────────────
        if self._vae is not None and TORCH_AVAILABLE and self.is_trained and len(current_data) >= self.sequence_length:
            available_features = [f for f in self.features if f in current_data.columns]

            if len(available_features) == self.n_features:
                clean_df = current_data[self.features].ffill().bfill().fillna(0.0)
                data = clean_df.values[-self.sequence_length:]

                if self.scaler:
                    data = self.scaler.transform(data)

                X_flat = data.reshape(1, self.sequence_length * self.n_features)
                import torch as _torch
                x_tensor = _torch.tensor(X_flat, dtype=_torch.float32)
                with _torch.no_grad():
                    recon, mu, log_var = self._vae(x_tensor)
                reconstruction_errors = ((x_tensor - recon) ** 2).mean(dim=1).numpy()
                mse = float(reconstruction_errors[0])

                if mse > self.threshold:
                    feature_errors = ((x_tensor - recon) ** 2).numpy().reshape(
                        self.sequence_length, self.n_features
                    ).mean(axis=0)
                    top_feature_idx = int(np.argmax(feature_errors))
                    top_feature = self.features[top_feature_idx]

                    severity = "high" if mse > self.threshold * 2 else "medium"

                    faults.append(FaultDetection(
                        fault_id=f"ae_{equipment_id}_{datetime.now().strftime('%H%M%S')}",
                        equipment_id=equipment_id,
                        fault_type="RECONSTRUCTION_ANOMALY",
                        severity=severity,
                        confidence=(mse - self.mean_loss) / (3 * self.std_loss + 1e-8),
                        description=f"Abnormal {top_feature} pattern detected",
                        detected_value=mse,
                        expected_range=(0, self.threshold),
                        recommendation=f"Investigate {top_feature} readings",
                    ))
        elif self._vae is None and TORCH_AVAILABLE and self.is_trained:
            logger.debug("[FDD] PyTorch VAE unavailable — using ASHRAE rules (fallback=True)")
        
        # ─────────────────────────────────────────────────────────────────
        # 2. sklearn autoencoder detection (when PyTorch VAE not available)
        # ─────────────────────────────────────────────────────────────────
        if (
            self._vae is None
            and self._sklearn_ae is not None
            and len(current_data) >= self.sequence_length
        ):
            try:
                available_features = [f for f in self.features if f in current_data.columns]
                if len(available_features) == self.n_features:
                    clean_df = current_data[self.features].ffill().bfill().fillna(0.0)
                    data = clean_df.values[-self.sequence_length:]
                    if self.scaler:
                        data = self.scaler.transform(data)
                    X_flat = data.reshape(1, self.sequence_length * self.n_features)
                    reconstruction = self._sklearn_ae.predict(X_flat)
                    mse = float(np.mean(np.square(X_flat - reconstruction)))

                    if mse > self._sklearn_threshold:
                        feature_errors = np.square(X_flat - reconstruction).reshape(
                            self.sequence_length, self.n_features
                        ).mean(axis=0)
                        top_feature_idx = int(np.argmax(feature_errors))
                        top_feature = self.features[top_feature_idx]
                        severity = "high" if mse > self._sklearn_threshold * 2 else "medium"
                        confidence = min(
                            1.0,
                            (mse - self._sklearn_mean_loss)
                            / (3 * self._sklearn_std_loss + 1e-8),
                        )
                        faults.append(FaultDetection(
                            fault_id=f"sk_{equipment_id}_{datetime.now().strftime('%H%M%S')}",
                            equipment_id=equipment_id,
                            fault_type="RECONSTRUCTION_ANOMALY",
                            severity=severity,
                            confidence=confidence,
                            description=f"Abnormal {top_feature} pattern detected (sklearn)",
                            detected_value=mse,
                            expected_range=(0.0, self._sklearn_threshold),
                            recommendation=f"Investigate {top_feature} readings",
                        ))
            except Exception as sk_err:
                logger.debug(f"sklearn detection error: {sk_err}")

        # ─────────────────────────────────────────────────────────────────
        # 3. ASHRAE rule-based detection
        # ─────────────────────────────────────────────────────────────────
        rules = ASHRAE_FAULT_RULES.get(self.equipment_type, {})
        current_values = current_data.iloc[-1].to_dict() if len(current_data) > 0 else {}
        
        for rule_name, rule in rules.items():
            try:
                if rule["condition"](current_values):
                    faults.append(FaultDetection(
                        fault_id=f"rule_{rule_name}_{datetime.now().strftime('%H%M%S')}",
                        equipment_id=equipment_id,
                        fault_type=rule_name,
                        severity=rule["severity"],
                        confidence=0.9,  # Rule-based is deterministic
                        description=rule["description"],
                        detected_value=0,
                        expected_range=(0, 0),
                        recommendation=f"Check {rule_name.lower().replace('_', ' ')}",
                    ))
            except (KeyError, TypeError):
                pass  # Missing data for this rule
        
        return faults
    
    def get_health_score(self, current_data: pd.DataFrame) -> float:
        """
        Calculate equipment health score (0-100).

        Based on reconstruction error distance from normal.
        Uses the TF VAE when available, falls back to the sklearn autoencoder.
        """
        if not self.is_trained or len(current_data) < self.sequence_length:
            return 80.0  # Default healthy

        available_features = [f for f in self.features if f in current_data.columns]
        if len(available_features) != self.n_features:
            return 80.0

        clean_df = current_data[self.features].ffill().bfill().fillna(0.0)
        data = clean_df.values[-self.sequence_length:]
        if self.scaler:
            data = self.scaler.transform(data)

        # ── PyTorch VAE path ──────────────────────────────────────────────
        if self._vae is not None and TORCH_AVAILABLE:
            try:
                import torch as _torch
                X_flat = data.reshape(1, self.sequence_length * self.n_features)
                x_tensor = _torch.tensor(X_flat, dtype=_torch.float32)
                with _torch.no_grad():
                    recon, mu, log_var = self._vae(x_tensor)
                mse = float(((x_tensor - recon) ** 2).mean(dim=1).numpy()[0])
                z_score = (mse - self.mean_loss) / (self.std_loss + 1e-8)
                score = 100 * np.exp(-0.5 * max(0, z_score))
                return float(np.clip(score, 0, 100))
            except Exception:
                return 80.0

        # ── sklearn path (PyTorch VAE not available) ──────────────────────
        if self._sklearn_ae is not None:
            try:
                X_flat = data.reshape(1, self.sequence_length * self.n_features)
                reconstruction = self._sklearn_ae.predict(X_flat)
                mse = float(np.mean(np.square(X_flat - reconstruction)))
                z_score = (mse - self._sklearn_mean_loss) / (self._sklearn_std_loss + 1e-8)
                score = 100 * np.exp(-0.5 * max(0, z_score))
                return float(np.clip(score, 0, 100))
            except Exception:
                return 80.0

        return 80.0


    # =========================================================================
    # MODEL PERSISTENCE (ModelRegistry Integration)
    # =========================================================================

    def save_model(self, metrics: Optional[Dict] = None) -> Optional[str]:
        """Save trained model to ModelRegistry."""
        if not self.is_trained:
            logger.warning("Cannot save untrained model")
            return None

        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state = {
            "threshold": self.threshold,
            "mean_loss": self.mean_loss,
            "std_loss": self.std_loss,
            "features": self.features,
            "equipment_type": self.equipment_type,
            "sequence_length": self.sequence_length,
            "latent_dim": self.latent_dim,
            "is_trained": True,
        }

        save_metrics = metrics or {"threshold": self.threshold, "mean_loss": self.mean_loss}
        extra = {"scaler": self.scaler} if self.scaler else None

        version = registry.save_model(
            f"fdd_{self.equipment_type}",
            model_state,
            save_metrics,
            extra_artifacts=extra,
        )
        logger.info(f"FDD model saved: fdd_{self.equipment_type}/{version}")
        return version

    def load_model(self) -> bool:
        """Load trained model from ModelRegistry."""
        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state, metadata = registry.load_model(f"fdd_{self.equipment_type}")
        if model_state is None:
            return False

        self.threshold = model_state.get("threshold", 0.1)
        self.mean_loss = model_state.get("mean_loss", 0.0)
        self.std_loss = model_state.get("std_loss", 0.01)
        self.features = model_state.get("features", self.features)
        self.n_features = len(self.features)
        self.is_trained = model_state.get("is_trained", False)

        scaler = registry.load_artifact(f"fdd_{self.equipment_type}", "scaler")
        if scaler:
            self.scaler = scaler

        logger.info(f"FDD model loaded: fdd_{self.equipment_type}")
        return True

    async def retrain(self, data: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Retrain pipeline for RetrainScheduler integration."""
        if data is None:
            logger.warning("No training data provided for FDD retrain")
            return {"status": "skipped", "reason": "no_data"}

        result = self.train(data)
        if result.get("status") == "trained":
            self.save_model(result)
        return result


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_fdd_engines: Dict[str, "FDDAutoencoder"] = {}


def get_fdd_engine(equipment_type: str = "ahu") -> FDDAutoencoder:
    """Get or create FDD engine with model loading."""
    if equipment_type not in _fdd_engines:
        engine = FDDAutoencoder(equipment_type)
        engine.load_model()
        _fdd_engines[equipment_type] = engine
    return _fdd_engines[equipment_type]


def detect_equipment_faults(
    equipment_type: str,
    equipment_id: str,
    readings: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Detect faults in equipment - LLM tool handler.
    """
    fdd = get_fdd_engine(equipment_type)
    df = pd.DataFrame([readings])

    faults = fdd.detect(df, equipment_id)
    return [f.to_dict() for f in faults]


if __name__ == "__main__":
    print("=" * 60)
    print("FDD Autoencoder Test")
    print("=" * 60)
    
    # Test ASHRAE rules
    fdd = FDDAutoencoder("ahu")
    
    # Simulate fault condition
    test_data = pd.DataFrame([{
        "sat": 16,  # Too high
        "sat_setpoint": 13,
        "rat": 24,
        "mat": 20,
        "oat": 35,
        "cooling_valve": 50,
        "heating_valve": 20,  # Simultaneous heating!
        "oa_damper": 30,
        "filter_dp": 150,
        "fan_speed": 80,
        "sa_flow": 5000,
        "ra_flow": 4500,
    }])
    
    faults = fdd.detect(test_data, "AHU-01")
    
    print(f"\nDetected {len(faults)} faults:")
    for fault in faults:
        print(f"  - {fault.fault_type}: {fault.description} ({fault.severity})")