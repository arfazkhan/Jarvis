import pytest
from datetime import datetime, timedelta
from agent_commercial.water_meter_adapter import WaterMeterAdapter
from agent_commercial.gsas_reporter import GSASReporter

@pytest.fixture
def water_adapter():
    # Baseline 1000 m3/month -> 33.33 m3/day
    adapter = WaterMeterAdapter(baseline_m3_monthly=1000.0, building_id="TEST-BLDG")
    return adapter

def test_water_adapter_tracks_readings(water_adapter):
    """Test that readings are correctly ingested and consumption calculated."""
    now = datetime.now()
    
    # Day 1: Start at 100
    water_adapter.ingest_reading("MAIN", 100.0, now - timedelta(days=2))
    # Day 2: 120 (Consumption = 20)
    water_adapter.ingest_reading("MAIN", 120.0, now - timedelta(days=1))
    # Day 3: 150 (Consumption = 30)
    water_adapter.ingest_reading("MAIN", 150.0, now)
    
    # 2 days of readings (Day 1 to Day 3)
    consumption = water_adapter.get_consumption(days=2)
    assert consumption == 50.0 # 150 - 100

def test_baseline_comparison(water_adapter):
    """Test percentage reduction calculation against baseline."""
    now = datetime.now()
    
    # Baseline is 1000/30 = 33.33 per day
    # We want 15% reduction -> 28.33 per day
    
    # 30 days ago
    water_adapter.ingest_reading("MAIN", 1000.0, now - timedelta(days=30))
    # Today
    water_adapter.ingest_reading("MAIN", 1000.0 + (28.33 * 30), now)
    
    reduction = water_adapter.get_consumption_vs_baseline()
    # Expected: (1 - 28.33/33.33) * 100 = 15%
    assert 14.0 < reduction < 16.0

def test_gsas_water_data_format(water_adapter):
    """Verify the output format for GSASReporter."""
    water_adapter.total_zones = 10
    water_adapter.ingest_reading("SUB-01", 10.0)
    water_adapter.ingest_reading("SUB-02", 15.0)
    
    data = water_adapter.get_gsas_water_data()
    assert "consumption_vs_baseline" in data
    assert "submetering_coverage" in data
    assert data["submetering_coverage"] == 20.0 # 2 submeters / 10 zones

def test_water_data_flows_to_gsas_reporter(water_adapter):
    """Test the full flow from adapter to reporter."""
    reporter = GSASReporter("TEST", "TEST")
    reporter.initialize_criteria()
    
    # 35% reduction, 100% coverage
    water_adapter.total_zones = 1
    water_adapter.ingest_reading("SUB-01", 5.0)
    
    # Simulate 35% reduction
    now = datetime.now()
    water_adapter.ingest_reading("MAIN", 100.0, now - timedelta(days=30))
    water_adapter.ingest_reading("MAIN", 100.0 + (water_adapter.baseline.daily_m3 * 0.65 * 30), now)
    
    gsas_data = water_adapter.get_gsas_water_data()
    reporter.update_from_bms(water_data=gsas_data)
    
    status = reporter.get_status()
    water_cat = status["categories"]["W"]
    # W.1 (3.0) + W.3 (2.0) = 5.0 out of 10.0 max = 50%
    assert water_cat["percentage"] >= 50
    assert reporter.criteria["W.1"].current_points == 3.0
    assert reporter.criteria["W.3"].current_points == 2.0
