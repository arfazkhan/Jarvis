"""
Tests for ARVIS Ops Copilot BMS Module
======================================

Unit tests for core BMS functionality:
- Data models
- State engine
- Predictive maintenance (ML)
- Energy analyzer
- Alarm engine
"""

import pytest
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from agent_bms.bms_data_model import (
    BMSDataPoint,
    Equipment,
    EquipmentType,
    EquipmentStatus,
    PointType,
    Alarm,
    AlarmSeverity,
    AlarmState,
    EnergyReading,
    FailurePrediction,
)
from agent_bms.bms_state_engine import BMSStateEngine
from agent_bms.predictive_maintenance import (
    PredictiveMaintenanceEngine,
    EquipmentFeatures,
)
from agent_bms.energy_analyzer import EnergyAnalyzer
from agent_bms.alarm_engine import AlarmEngine


class TestBMSDataModel:
    """Tests for BMS data models"""
    
    def test_equipment_creation(self):
        """Test Equipment dataclass"""
        eq = Equipment(
            equipment_id="AHU-01",
            name="Air Handler Unit 1",
            equipment_type=EquipmentType.AHU,
            location="Building A, Floor 3, Zone 1",
            status=EquipmentStatus.RUNNING,
            runtime_hours=15000,
        )
        
        assert eq.equipment_id == "AHU-01"
        assert eq.equipment_type == EquipmentType.AHU
        assert eq.runtime_hours == 15000
    
    def test_data_point_creation(self):
        """Test BMSDataPoint dataclass"""
        point = BMSDataPoint(
            point_id="AHU-01/SAT",
            name="Supply Air Temperature",
            value=18.5,
            unit="°C",
            equipment_id="AHU-01",
            point_type=PointType.SENSOR,
        )
        
        assert point.point_id == "AHU-01/SAT"
        assert point.value == 18.5
        assert point.unit == "°C"
    
    def test_data_point_to_dict(self):
        """Test serialization"""
        point = BMSDataPoint(
            point_id="AHU-01/SAT",
            name="Supply Air Temperature",
            value=18.5,
            unit="°C",
            equipment_id="AHU-01",
        )
        
        d = point.to_dict()
        assert d["point_id"] == "AHU-01/SAT"
        assert d["value"] == 18.5
        assert "timestamp" in d
    
    def test_alarm_duration(self):
        """Test alarm duration calculation"""
        alarm = Alarm(
            source_point_id="AHU-01/SAT",
            equipment_id="AHU-01",
            message="High temperature",
            severity=AlarmSeverity.HIGH,
            triggered_at=datetime.now() - timedelta(hours=2),
        )
        
        duration = alarm.duration_minutes()
        assert 119 < duration < 121  # About 120 minutes
    
    def test_energy_reading_features(self):
        """Test EnergyReading feature extraction"""
        reading = EnergyReading(
            meter_id="M1",
            value=150.0,
            unit="kW",
            timestamp=datetime(2026, 1, 15, 14, 30),  # Wed 2:30 PM
            outdoor_temp=35.0,
            occupancy=0.8,
        )
        
        assert reading.hour_of_day == 14
        assert reading.day_of_week == 3  # Thursday (Jan 15, 2026)
        
        features = reading.to_feature_vector()
        assert len(features) == 5


class TestBMSStateEngine:
    """Tests for BMS State Engine"""
    
    @pytest.fixture
    def state_engine(self):
        return BMSStateEngine()
    
    def test_register_equipment(self, state_engine):
        """Test equipment registration"""
        eq = Equipment(
            equipment_id="AHU-01",
            name="Air Handler 1",
            equipment_type=EquipmentType.AHU,
            location="Building A, Floor 1, Zone 1",
        )
        
        state_engine.register_equipment_sync(eq)
        
        result = state_engine.get_equipment_sync("AHU-01")
        assert result is not None
        assert result.equipment_id == "AHU-01"
    
    def test_update_point(self, state_engine):
        """Test data point updates"""
        point = BMSDataPoint(
            point_id="AHU-01/SAT",
            name="Supply Air Temp",
            value=18.5,
            unit="°C",
            equipment_id="AHU-01",
        )
        
        state_engine.update_point_sync(point)
        
        result = state_engine.get_point_sync("AHU-01/SAT")
        assert result is not None
        assert result.value == 18.5
    
    def test_point_history(self, state_engine):
        """Test history buffer"""
        point = BMSDataPoint(
            point_id="AHU-01/SAT",
            name="Supply Air Temp",
            value=18.0,
            unit="°C",
            equipment_id="AHU-01",
        )
        
        state_engine.update_point_sync(point)
        
        # Update with new value
        point.value = 19.0
        point.timestamp = datetime.now()
        state_engine.update_point_sync(point)
        
        result = state_engine.get_point_sync("AHU-01/SAT")
        assert len(result.history) >= 1


class TestPredictiveMaintenanceEngine:
    """Tests for ML-based predictive maintenance"""
    
    @pytest.fixture
    def pm_engine(self):
        return PredictiveMaintenanceEngine()
    
    def test_feature_vector(self):
        """Test EquipmentFeatures conversion"""
        features = EquipmentFeatures(
            equipment_id="AHU-01",
            runtime_hours=15000,
            start_stop_cycles=5000,
            days_since_maintenance=45,
            age_years=5.0,
            efficiency=0.85,
        )
        
        arr = features.to_array()
        assert len(arr) == 16
        assert arr[0] == 15000  # runtime_hours
        assert arr[3] == 5.0    # age_years
    
    def test_rule_based_prediction(self, pm_engine):
        """Test prediction without training (rule-based fallback)"""
        features = EquipmentFeatures(
            equipment_id="AHU-01",
            runtime_hours=55000,  # High runtime
            days_since_maintenance=90,  # Overdue
            efficiency=0.55,  # Low efficiency
            fault_count_30d=6,  # Many faults
        )
        
        prediction = pm_engine.predict_failure("AHU-01", features)
        
        assert isinstance(prediction, FailurePrediction)
        assert prediction.failure_probability > 0.3  # Should be elevated
        assert prediction.risk_level in ("medium", "high", "critical")
        assert len(prediction.recommendation) > 0
    
    def test_contributing_factors(self, pm_engine):
        """Test feature importance extraction"""
        features = EquipmentFeatures(
            equipment_id="AHU-01",
            runtime_hours=45000,
            efficiency=0.6,
            fault_count_30d=4,
        )
        
        prediction = pm_engine.predict_failure("AHU-01", features)
        
        assert len(prediction.contributing_factors) > 0
        assert "name" in prediction.contributing_factors[0]
        assert "importance" in prediction.contributing_factors[0]


class TestEnergyAnalyzer:
    """Tests for energy anomaly detection"""
    
    @pytest.fixture
    def analyzer(self):
        return EnergyAnalyzer(electricity_rate_qar=0.15)
    
    def test_add_reading(self, analyzer):
        """Test reading ingestion"""
        reading = EnergyReading(
            meter_id="M1",
            value=150.0,
            timestamp=datetime.now(),
        )
        
        analyzer.add_reading(reading)
        
        assert len(analyzer.history["M1"]) == 1
    
    def test_baseline_training(self, analyzer):
        """Test baseline model training"""
        # Generate synthetic data
        data = []
        base_time = datetime.now() - timedelta(days=7)
        
        for i in range(168):  # 1 week hourly
            hour = i % 24
            # Higher during work hours
            value = 50 if hour < 7 or hour > 20 else 150
            value += np.random.normal(0, 10)
            
            data.append({
                "timestamp": base_time + timedelta(hours=i),
                "value": max(0, value),
            })
        
        df = pd.DataFrame(data)
        baseline = analyzer.train_baseline("M1", df)
        
        assert baseline.meter_id == "M1"
        assert baseline.mean > 0
        assert baseline.base_load > 0
        assert len(baseline.hourly_means) > 0
    
    def test_expected_value(self, analyzer):
        """Test expected value calculation with baseline"""
        # Manual baseline
        analyzer.baselines["M1"] = type('Baseline', (), {
            "meter_id": "M1",
            "hourly_means": {h: 100 + h * 2 for h in range(24)},
            "daily_means": {d: 120 for d in range(7)},
            "temp_coefficient": 2.0,
            "base_load": 50,
            "mean": 120,
            "std": 30,
        })()
        
        expected = analyzer.get_expected_value(
            "M1",
            datetime(2026, 1, 15, 14, 0),  # 2 PM
            outdoor_temp=35.0
        )
        
        assert expected > 0


class TestAlarmEngine:
    """Tests for alarm processing"""
    
    @pytest.fixture
    def engine(self):
        engine = AlarmEngine()
        
        # Set up equipment topology
        chiller = Equipment(
            equipment_id="CH-01",
            name="Chiller 1",
            equipment_type=EquipmentType.CHILLER,
            child_equipment_ids=["AHU-01", "AHU-02"],
        )
        ahu1 = Equipment(
            equipment_id="AHU-01",
            name="AHU 1",
            equipment_type=EquipmentType.AHU,
            parent_equipment_id="CH-01",
            location="Building A, Floor 1",
        )
        ahu2 = Equipment(
            equipment_id="AHU-02",
            name="AHU 2",
            equipment_type=EquipmentType.AHU,
            parent_equipment_id="CH-01",
            location="Building A, Floor 2",
        )
        
        engine.set_equipment_topology([chiller, ahu1, ahu2])
        return engine
    
    def test_ingest_alarm(self, engine):
        """Test basic alarm ingestion"""
        alarm = Alarm(
            source_point_id="CH-01/STATUS",
            equipment_id="CH-01",
            message="Chiller trip",
            severity=AlarmSeverity.CRITICAL,
        )
        
        processed = engine.ingest_alarm(alarm)
        
        assert processed.alarm.alarm_id == alarm.alarm_id
        assert not processed.suppressed
        assert processed.rank > 0
        assert len(processed.suggested_actions) > 0
    
    def test_priority_queue(self, engine):
        """Test priority queue ranking"""
        # Add critical alarm
        critical = Alarm(
            equipment_id="CH-01",
            message="Chiller trip",
            severity=AlarmSeverity.CRITICAL,
        )
        engine.ingest_alarm(critical)
        
        # Add low alarm
        low = Alarm(
            equipment_id="AHU-01",
            message="Filter dirty",
            severity=AlarmSeverity.LOW,
        )
        engine.ingest_alarm(low)
        
        queue = engine.get_priority_queue()
        
        assert len(queue) == 2
        assert queue[0].alarm.severity == AlarmSeverity.CRITICAL
    
    def test_alarm_clustering(self, engine):
        """Test alarm correlation and clustering"""
        now = datetime.now()
        
        # Chiller trips first
        chiller_alarm = Alarm(
            equipment_id="CH-01",
            message="Chiller trip",
            severity=AlarmSeverity.CRITICAL,
            triggered_at=now,
        )
        engine.ingest_alarm(chiller_alarm)
        
        # Then AHU high temp (caused by chiller)
        ahu_alarm = Alarm(
            equipment_id="AHU-01",
            message="High supply air temperature",
            severity=AlarmSeverity.HIGH,
            triggered_at=now + timedelta(minutes=2),
        )
        processed = engine.ingest_alarm(ahu_alarm)
        
        # Should be clustered
        clusters = engine.get_clusters()
        assert len(clusters) >= 1
    
    def test_suppression(self, engine):
        """Test nuisance alarm suppression"""
        # First alarm
        alarm = Alarm(
            equipment_id="AHU-01",
            source_point_id="AHU-01/SAT",
            message="High temp",
        )
        engine.ingest_alarm(alarm)
        
        # Duplicate - should be suppressed
        duplicate = Alarm(
            equipment_id="AHU-01",
            source_point_id="AHU-01/SAT",
            message="High temp",
        )
        processed = engine.ingest_alarm(duplicate)
        
        assert processed.suppressed
        assert "duplicate" in processed.suppression_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
