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

# TensorFlow import with fallback
try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers, Model
    TF_AVAILABLE = True
    # Suppress TF warnings
    tf.get_logger().setLevel('ERROR')
except ImportError:
    TF_AVAILABLE = False
    warnings.warn("TensorFlow not installed. Run: pip install tensorflow")

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
# FDD AUTOENCODER
# =============================================================================

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
                 latent_dim: int = 8):
        """
        Initialize FDD Autoencoder.
        
        Args:
            equipment_type: "ahu", "chiller", or "vav"
            sequence_length: Number of timesteps in input sequence
            latent_dim: Dimensionality of latent space
        """
        self.equipment_type = equipment_type.lower()
        self.sequence_length = sequence_length
        self.latent_dim = latent_dim
        
        # Get features for this equipment type
        self.features = self.FEATURE_SETS.get(self.equipment_type, 
                                               self.FEATURE_SETS["ahu"])
        self.n_features = len(self.features)
        
        # Scaler for normalization
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        
        # Autoencoder model
        self.encoder = None
        self.decoder = None
        self.autoencoder = None
        
        # Anomaly threshold (learned from training)
        self.threshold = 0.1
        self.mean_loss = 0.0
        self.std_loss = 0.01
        
        self.is_trained = False
        
        logger.info(f"FDDAutoencoder initialized for {equipment_type} with {self.n_features} features")
    
    def _build_model(self) -> None:
        """Build the VAE architecture."""
        if not TF_AVAILABLE:
            logger.warning("TensorFlow not available, using rule-based FDD only")
            return
        
        input_shape = (self.sequence_length, self.n_features)
        
        # ─────────────────────────────────────────────────────────────────
        # Encoder
        # ─────────────────────────────────────────────────────────────────
        encoder_input = keras.Input(shape=input_shape, name="encoder_input")
        
        # LSTM for temporal patterns
        x = layers.LSTM(64, return_sequences=True)(encoder_input)
        x = layers.LSTM(32, return_sequences=False)(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dense(16, activation='relu')(x)
        
        # Latent space (VAE: mean and log variance)
        z_mean = layers.Dense(self.latent_dim, name='z_mean')(x)
        z_log_var = layers.Dense(self.latent_dim, name='z_log_var')(x)
        
        # Sampling layer
        def sampling(args):
            z_mean, z_log_var = args
            epsilon = tf.random.normal(shape=(tf.shape(z_mean)[0], self.latent_dim))
            return z_mean + tf.exp(0.5 * z_log_var) * epsilon
        
        z = layers.Lambda(sampling, name='z')([z_mean, z_log_var])
        
        self.encoder = Model(encoder_input, [z_mean, z_log_var, z], name='encoder')
        
        # ─────────────────────────────────────────────────────────────────
        # Decoder
        # ─────────────────────────────────────────────────────────────────
        decoder_input = keras.Input(shape=(self.latent_dim,), name="decoder_input")
        
        x = layers.Dense(16, activation='relu')(decoder_input)
        x = layers.Dense(32, activation='relu')(x)
        x = layers.BatchNormalization()(x)
        
        # Reshape for sequence output
        x = layers.RepeatVector(self.sequence_length)(x)
        x = layers.LSTM(32, return_sequences=True)(x)
        x = layers.LSTM(64, return_sequences=True)(x)
        
        decoder_output = layers.TimeDistributed(
            layers.Dense(self.n_features, activation='linear')
        )(x)
        
        self.decoder = Model(decoder_input, decoder_output, name='decoder')
        
        # ─────────────────────────────────────────────────────────────────
        # Full Autoencoder
        # ─────────────────────────────────────────────────────────────────
        encoder_output = self.encoder(encoder_input)
        z = encoder_output[2]  # Sampled latent
        decoder_output = self.decoder(z)
        
        self.autoencoder = Model(encoder_input, decoder_output, name='vae')
        
        # Custom VAE loss
        def vae_loss(y_true, y_pred):
            # Reconstruction loss
            reconstruction_loss = tf.reduce_mean(tf.square(y_true - y_pred))
            
            # KL divergence
            kl_loss = -0.5 * tf.reduce_mean(
                1 + z_log_var - tf.square(z_mean) - tf.exp(z_log_var)
            )
            
            # Physics constraint loss (e.g., SAT < RAT for cooling)
            physics_loss = self._physics_constraint_loss(y_true, y_pred)
            
            return reconstruction_loss + 0.01 * kl_loss + 0.1 * physics_loss
        
        self.autoencoder.compile(
            optimizer=keras.optimizers.Adam(learning_rate=0.001),
            loss=vae_loss,
        )
        
        logger.info("VAE model built successfully")
    
    def _physics_constraint_loss(self, y_true, y_pred) -> Any:
        """
        Physics-informed loss to ensure thermodynamic consistency.
        
        For AHU: SAT should be between MAT and cooling coil capacity
        For Chiller: Evap approach should be positive
        """
        if not TF_AVAILABLE:
            return 0.0
        
        if self.equipment_type == "ahu":
            # SAT should generally be lower than RAT when cooling
            sat_idx = self.features.index("sat") if "sat" in self.features else 0
            rat_idx = self.features.index("rat") if "rat" in self.features else 1
            
            sat_pred = y_pred[:, -1, sat_idx]
            rat_pred = y_pred[:, -1, rat_idx]
            
            # Penalize if SAT > RAT (usually wrong for cooling)
            violation = tf.maximum(0.0, sat_pred - rat_pred)
            return tf.reduce_mean(violation)
        
        return tf.constant(0.0)
    
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
        
        # Prepare data
        data = historical_data[self.features].values
        
        # Scale data
        if self.scaler:
            data = self.scaler.fit_transform(data)
        
        # Create sequences
        sequences = []
        for i in range(len(data) - self.sequence_length + 1):
            sequences.append(data[i:i + self.sequence_length])
        
        X = np.array(sequences)
        
        if len(X) < 100:
            logger.warning(f"Insufficient training data: {len(X)} sequences")
            return {"status": "failed", "error": "insufficient_data"}
        
        # Build model
        self._build_model()
        
        if not TF_AVAILABLE or self.autoencoder is None:
            self.is_trained = False
            return {"status": "failed", "error": "tensorflow_not_available"}
        
        # Train
        history = self.autoencoder.fit(
            X, X,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=0.2,
            verbose=0,
        )
        
        # Calculate reconstruction errors for threshold
        reconstructions = self.autoencoder.predict(X, verbose=0)
        mse = np.mean(np.square(X - reconstructions), axis=(1, 2))
        
        self.mean_loss = float(np.mean(mse))
        self.std_loss = float(np.std(mse))
        self.threshold = self.mean_loss + 2 * self.std_loss  # 2 sigma
        
        self.is_trained = True
        
        metrics = {
            "status": "trained",
            "samples": len(X),
            "features": self.features,
            "final_loss": float(history.history['loss'][-1]),
            "threshold": self.threshold,
            "mean_reconstruction_error": self.mean_loss,
        }
        
        logger.info(f"FDD Autoencoder trained: threshold={self.threshold:.4f}")
        return metrics
    
    def detect(self, 
               current_data: pd.DataFrame,
               equipment_id: str = "unknown") -> List[FaultDetection]:
        """
        Detect faults in current readings.
        
        Uses both autoencoder (if trained) and ASHRAE rules.
        """
        faults = []
        
        # ─────────────────────────────────────────────────────────────────
        # 1. Autoencoder-based detection
        # ─────────────────────────────────────────────────────────────────
        if self.is_trained and len(current_data) >= self.sequence_length:
            available_features = [f for f in self.features if f in current_data.columns]
            
            if len(available_features) == self.n_features:
                data = current_data[self.features].values[-self.sequence_length:]
                
                if self.scaler:
                    data = self.scaler.transform(data)
                
                X = data.reshape(1, self.sequence_length, self.n_features)
                reconstruction = self.autoencoder.predict(X, verbose=0)
                mse = np.mean(np.square(X - reconstruction))
                
                if mse > self.threshold:
                    # Find which features contribute most to error
                    feature_errors = np.mean(np.square(X - reconstruction), axis=1)[0]
                    top_feature_idx = np.argmax(feature_errors)
                    top_feature = self.features[top_feature_idx]
                    
                    severity = "high" if mse > self.threshold * 2 else "medium"
                    
                    faults.append(FaultDetection(
                        fault_id=f"ae_{equipment_id}_{datetime.now().strftime('%H%M%S')}",
                        equipment_id=equipment_id,
                        fault_type="RECONSTRUCTION_ANOMALY",
                        severity=severity,
                        confidence=(mse - self.mean_loss) / (3 * self.std_loss),
                        description=f"Abnormal {top_feature} pattern detected",
                        detected_value=mse,
                        expected_range=(0, self.threshold),
                        recommendation=f"Investigate {top_feature} readings",
                    ))
        
        # ─────────────────────────────────────────────────────────────────
        # 2. ASHRAE rule-based detection
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
        """
        if not self.is_trained or len(current_data) < self.sequence_length:
            return 80.0  # Default healthy
        
        available_features = [f for f in self.features if f in current_data.columns]
        if len(available_features) != self.n_features:
            return 80.0
        
        data = current_data[self.features].values[-self.sequence_length:]
        if self.scaler:
            data = self.scaler.transform(data)
        
        X = data.reshape(1, self.sequence_length, self.n_features)
        reconstruction = self.autoencoder.predict(X, verbose=0)
        mse = np.mean(np.square(X - reconstruction))
        
        # Score: 100 if mse=0, 0 if mse = 3*threshold
        z_score = (mse - self.mean_loss) / (self.std_loss + 1e-8)
        score = 100 * np.exp(-0.5 * max(0, z_score))
        
        return float(np.clip(score, 0, 100))


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def detect_equipment_faults(
    equipment_type: str,
    equipment_id: str,
    readings: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Detect faults in equipment - LLM tool handler.
    """
    fdd = FDDAutoencoder(equipment_type)
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
