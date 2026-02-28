import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

# Add project root to path
sys.path.append(os.getcwd())

from agent_commercial.energy_analyzer import EnergyAnalyzer
from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine, EquipmentFeatures
from agent_commercial.bms_data_model import EnergyReading

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_ml")

def generate_mock_energy_data(days=30):
    """Generate mock historical energy data"""
    start_date = datetime.now() - timedelta(days=days)
    data = []
    for i in range(days * 24):
        ts = start_date + timedelta(hours=i)
        # Base consumption with daily pattern
        base = 50 + 20 * np.sin(2 * np.pi * ts.hour / 24)
        # Random noise
        val = base + np.random.normal(0, 2)
        data.append({
            'timestamp': ts,
            'value': val,
            'outdoor_temp': 30 + 5 * np.sin(2 * np.pi * ts.hour / 24),
            'occupancy': 0.8 if 8 <= ts.hour <= 18 else 0.1
        })
    return pd.DataFrame(data)

def generate_mock_maintenance_data(samples=1000):
    """Generate mock historical maintenance data with complete feature set"""
    data = []
    labels = []
    feature_names = [
        "runtime_hours", "start_stop_cycles", "days_since_maintenance", "age_years",
        "avg_load_percent", "efficiency", "efficiency_trend", "delta_t",
        "delta_t_deviation", "supply_temp_deviation", "motor_current",
        "current_deviation", "vibration_rms", "fault_count_30d",
        "minor_fault_count", "major_fault_count"
    ]
    
    for i in range(samples):
        # healthy sample
        features = {
            'runtime_hours': 1000 + i * 10,
            'start_stop_cycles': i,
            'days_since_maintenance': i % 90,
            'age_years': 2.5,
            'avg_load_percent': 60 + np.random.normal(0, 5),
            'efficiency': 0.95 + np.random.normal(0, 0.01),
            'efficiency_trend': 0.0,
            'delta_t': 12.0,
            'delta_t_deviation': 0.5,
            'supply_temp_deviation': 0.2,
            'motor_current': 15.0,
            'current_deviation': 0.1,
            'vibration_rms': 0.05,
            'fault_count_30d': 0,
            'minor_fault_count': 0,
            'major_fault_count': 0
        }
        data.append(features)
        labels.append(0)
        
    # Add some failures
    for i in range(20):
        features = {
            'runtime_hours': 5000,
            'start_stop_cycles': 500,
            'days_since_maintenance': 200,
            'age_years': 5.0,
            'avg_load_percent': 90,
            'efficiency': 0.65,
            'efficiency_trend': -0.1,
            'delta_t': 5.0,
            'delta_t_deviation': 7.0,
            'supply_temp_deviation': 4.0,
            'motor_current': 25.0,
            'current_deviation': 5.0,
            'vibration_rms': 0.5,
            'fault_count_30d': 10,
            'minor_fault_count': 5,
            'major_fault_count': 2
        }
        data.append(features)
        labels.append(1)
        
    return pd.DataFrame(data), pd.Series(labels)

def verify_energy_analyzer():
    logger.info("--- Verifying EnergyAnalyzer Upgrade ---")
    analyzer = EnergyAnalyzer()
    
    # 1. Train
    hist_data = generate_mock_energy_data(45) # Need enough for sequences
    logger.info("Training EnergyAnalyzer...")
    analyzer.train_baseline("meter_001", hist_data)
    
    # 2. Test Real-time detection
    logger.info("Testing anomaly detection...")
    current_reading = EnergyReading(
        meter_id="meter_001",
        timestamp=datetime.now(),
        value=150.0, # High spike
        unit="kWh",
        outdoor_temp=35.0
    )
    
    # Fill history for VAE
    for _, row in hist_data.iterrows():
        analyzer.add_reading(EnergyReading(
            meter_id="meter_001",
            timestamp=row['timestamp'],
            value=row['value'],
            unit="kWh",
            outdoor_temp=row['outdoor_temp']
        ))
        
    anomalies = analyzer.detect_anomalies_realtime(current_reading)
    logger.info(f"Detected {len(anomalies)} anomalies in spike reading.")
    for a in anomalies:
        logger.info(f"Anomaly: {a.anomaly_type} - {a.description} (Severity: {a.severity:.2f})")
    
    assert len(anomalies) > 0, "Should have detected at least one anomaly"
    logger.info("EnergyAnalyzer verification passed.")

def verify_predictive_maintenance():
    logger.info("--- Verifying PredictiveMaintenanceEngine Upgrade ---")
    pm = PredictiveMaintenanceEngine()
    
    # 1. Train
    hist_data, labels = generate_mock_maintenance_data(150)
    logger.info("Training PredictiveMaintenanceEngine...")
    pm.train(hist_data, labels)
    
    # 2. Test Failure Prediction
    logger.info("Testing failure prediction with VAE integration...")
    failing_features = EquipmentFeatures(
        equipment_id="ahu_001",
        vibration_rms=5.0, # Very high vibration
        supply_temp_deviation=10.0, # Large deviation
        efficiency=0.4, # Very low efficiency
        start_stop_cycles=1000,
        days_since_maintenance=500,
        fault_count_30d=20,
        major_fault_count=5
    )
    
    # Fill equipment history for VAE
    pm.equipment_history["ahu_001"] = []
    # Generate some normal history for VAE sequence
    for i in range(50):
        pm.equipment_history["ahu_001"].append(EquipmentFeatures(
            equipment_id="ahu_001",
            vibration_rms=np.random.normal(0.5, 0.1),
            efficiency=0.95
        ))
    
    prediction = pm.predict_failure("ahu_001", failing_features, equipment_type="ahu")
    logger.info(f"Failure Prediction: Risk={prediction.risk_level}, Probability={prediction.failure_probability:.2f}")
    
    # 3. Test Anomaly Detection
    anomalies = pm.detect_anomalies("ahu_001", failing_features, equipment_type="ahu")
    logger.info(f"Detected {len(anomalies)} anomalies.")
    for a in anomalies:
        logger.info(f"Anomaly: {a.anomaly_type} - {a.description}")
        
    assert prediction.risk_level in ["high", "critical"], f"Expected high/critical risk, got {prediction.risk_level}"
    logger.info("PredictiveMaintenanceEngine verification passed.")

if __name__ == "__main__":
    try:
        verify_energy_analyzer()
        verify_predictive_maintenance()
        logger.info("--- ALL VERIFICATIONS PASSED ---")
    except Exception as e:
        logger.error(f"VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
