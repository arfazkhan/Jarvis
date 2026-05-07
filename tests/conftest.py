"""
Pytest Configuration and Shared Fixtures
=========================================

This file is automatically loaded by pytest and provides shared fixtures
for all test files.

Philosophy:
- Mock EXTERNAL dependencies (LLM, BACnet, network)
- TEST internal logic (business rules, algorithms)
- Keep tests fast, deterministic, and isolated

"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List
from datetime import datetime, timedelta

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import test utilities
from tests.mocks import (
    MockLLM,
    MockBACnetAdapter,
    MockBMSStateEngine,
    MockDatabase,
    create_mock_llm_with_responses,
    create_mock_bacnet_with_equipment,
    create_mock_bms_state_with_equipment,
)
from tests.factories import (
    EquipmentFactory,
    DataPointFactory,
    AlarmFactory,
    EnergyReadingFactory,
    GSASFactory,
    RecommendationFactory,
)
from tests.utils.helpers import (
    Timer,
    assert_valid_tool_result,
    assert_valid_recommendation,
    assert_valid_prediction,
    assert_valid_gsas_score,
    assert_valid_alarm,
    assert_valid_briefing,
    assert_valid_verification,
    ScenarioBuilder,
)


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (integration, stress, e2e)"
    )
    parser.addoption(
        "--run-smoke",
        action="store_true",
        default=False,
        help="Run smoke tests with real external services"
    )


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "slow: mark test as slow")
    config.addinivalue_line("markers", "smoke: mark test as smoke test")
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "stress: mark test as stress test")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end")


def pytest_collection_modifyitems(config, items):
    """Skip tests based on markers and options."""
    # Skip slow tests unless --run-slow
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="Need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    
    # Skip smoke tests unless --run-smoke
    if not config.getoption("--run-smoke"):
        skip_smoke = pytest.mark.skip(reason="Need --run-smoke option to run")
        for item in items:
            if "smoke" in item.keywords:
                item.add_marker(skip_smoke)


# ============================================================================
# EVENT LOOP FIXTURE
# ============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """
    Create an instance of the default event loop for each test case.
    
    Using session scope for efficiency with async tests.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_llm() -> MockLLM:
    """Mock LLM with configurable responses."""
    return MockLLM(latency_ms=10.0)  # Fast for tests


@pytest.fixture
def mock_llm_with_responses() -> MockLLM:
    """Mock LLM with preconfigured responses."""
    return create_mock_llm_with_responses({
        "status": '{"equipment": "running"}',
        "alarm": '{"severity": "critical"}',
        "prediction": '{"confidence": 0.85}',
    })


@pytest.fixture
def mock_bacnet() -> MockBACnetAdapter:
    """Mock BACnet adapter with sample equipment."""
    return create_mock_bacnet_with_equipment(chillers=2, ahus=4, meters=1)


@pytest.fixture
def mock_bms_state() -> MockBMSStateEngine:
    """Mock BMS state engine with sample equipment."""
    return create_mock_bms_state_with_equipment()


@pytest.fixture
def mock_database() -> MockDatabase:
    """In-memory mock database."""
    return MockDatabase()


# ============================================================================
# REAL ENGINES (with mocks injected)
# ============================================================================

@pytest.fixture
def alarm_engine(mock_bms_state: MockBMSStateEngine):
    """Real AlarmEngine with mock state."""
    from agent_commercial.alarm_engine import AlarmEngine
    return AlarmEngine(state_engine=mock_bms_state)


@pytest.fixture
def energy_analyzer(mock_bms_state: MockBMSStateEngine):
    """Real EnergyAnalyzer with mock state."""
    from agent_commercial.energy_analyzer import EnergyAnalyzer
    return EnergyAnalyzer(bms_state=mock_bms_state)


@pytest.fixture
def predictive_maintenance(mock_bms_state: MockBMSStateEngine):
    """Real PredictiveMaintenanceEngine with mock state."""
    from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine
    return PredictiveMaintenanceEngine(bms_state=mock_bms_state)


@pytest.fixture
def gsas_reporter():
    """Real GSASReporter with default config."""
    from agent_commercial.gsas_reporter import GSASReporter
    return GSASReporter(
        building_id="TEST-BUILDING-001",
        building_name="Test Building",
        target_rating=4,
    )


@pytest.fixture
def gsas_optimizer(gsas_reporter):
    """Real GSASOptimizer with GSASReporter."""
    from agent_commercial.gsas_optimizer import GSASOptimizer
    return GSASOptimizer(gsas_reporter=gsas_reporter)


@pytest.fixture
def prediction_engine(mock_bms_state: MockBMSStateEngine, mock_llm: MockLLM):
    """Real PredictionEngine with mocks."""
    from agent_cognitive.prediction_engine import PredictionEngine
    return PredictionEngine(
        bms_state=mock_bms_state,
        llm=mock_llm,
    )


@pytest.fixture
def verify_loop(mock_bms_state: MockBMSStateEngine, mock_llm: MockLLM):
    """Real VerifyLoop with mocks."""
    from agent_advisory.verify_loop import VerifyLoop
    return VerifyLoop(
        bms_state=mock_bms_state,
        llm=mock_llm,
    )


@pytest.fixture
def online_learner(mock_llm: MockLLM):
    """Real OnlineLearner with mock LLM."""
    from agent_advisory.online_learner import OnlineLearner
    return OnlineLearner(llm=mock_llm)


# ============================================================================
# TEST DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_equipment() -> Dict[str, Any]:
    """Sample equipment for tests."""
    return EquipmentFactory.chiller()


@pytest.fixture
def sample_alarms() -> List[Dict[str, Any]]:
    """Sample alarms for tests."""
    return [
        AlarmFactory.critical_chiller(),
        AlarmFactory.warning_ahu(),
        AlarmFactory.info_zone(),
    ]


@pytest.fixture
def sample_energy_readings() -> List[Dict[str, Any]]:
    """Sample energy readings for tests."""
    return EnergyReadingFactory.last_24_hours()


@pytest.fixture
def sample_gsas_criteria() -> List[Dict[str, Any]]:
    """Sample GSAS criteria for tests."""
    return GSASFactory.energy_criteria()


@pytest.fixture
def sample_recommendations() -> List[Dict[str, Any]]:
    """Sample recommendations for tests."""
    return [
        RecommendationFactory.energy_optimization(),
        RecommendationFactory.maintenance_alert(),
        RecommendationFactory.gsas_improvement(),
    ]


# ============================================================================
# STRESS TEST FIXTURES
# ============================================================================

@pytest.fixture
def alarm_flood() -> List[Dict[str, Any]]:
    """Large number of alarms for stress testing."""
    return AlarmFactory.flood(count=500)


@pytest.fixture
def equipment_fleet() -> List[Dict[str, Any]]:
    """Large fleet of equipment for stress testing."""
    return EquipmentFactory.fleet(chillers=10, ahus=20)


# ============================================================================
# SCENARIO FIXTURES
# ============================================================================

@pytest.fixture
def scenario_builder():
    """Scenario builder for complex test cases."""
    from tests.utils.helpers import ScenarioBuilder
    return ScenarioBuilder()


@pytest.fixture
def chiller_trip_scenario(scenario_builder):
    """Pre-built chiller trip scenario."""
    from tests.factories import AlarmFactory
    
    scenario = (scenario_builder
        .add_chiller("CH-01", status="fault")
        .add_ahu("AHU-01")
        .add_ahu("AHU-02")
        .add_critical_alarm("CH-01")
    )
    
    # Add cascade alarms
    for i in range(5):
        scenario.add_warning_alarm(f"ZONE-{i+1:02d}")
    
    return scenario.build()


# ============================================================================
# TIME FIXTURES
# ============================================================================

@pytest.fixture
def mock_time():
    """Mock time for testing time-dependent logic."""
    return Timer("test")


@pytest.fixture
def monday_morning():
    """Monday 7am timestamp for testing morning routines."""
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=7, minute=0, second=0, microsecond=0)


# ============================================================================
# ASSERTION HELPERS
# ============================================================================

# Make assertions available as fixtures
assert_valid_tool_result = staticmethod(assert_valid_tool_result)
assert_valid_recommendation = staticmethod(assert_valid_recommendation)
assert_valid_prediction = staticmethod(assert_valid_prediction)
assert_valid_gsas_score = staticmethod(assert_valid_gsas_score)
assert_valid_alarm = staticmethod(assert_valid_alarm)
assert_valid_briefing = staticmethod(assert_valid_briefing)
assert_valid_verification = staticmethod(assert_valid_verification)


# ============================================================================
# CLEANUP
# ============================================================================

@pytest.fixture(autouse=True)
def cleanup_mock_state(mock_bms_state):
    """Automatically cleanup mock state after each test."""
    yield
    mock_bms_state.clear()


# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment variables."""
    # Set required environment variables for tests
    os.environ.setdefault("GROQ_API_KEY", "test_key_for_testing")
    os.environ.setdefault("ENV", "test")
    os.environ.setdefault("DEBUG", "true")
    os.environ.setdefault("ARVIS_VERTICAL", "COMMERCIAL")
    
    yield
    
    # Cleanup is automatic with setdefault


# ============================================================================
# LOGGING SETUP
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def setup_logging():
    """Configure logging for tests."""
    import logging
    
    # Reduce noise during tests
    logging.getLogger("arvis").setLevel(logging.WARNING)
    logging.getLogger("arvis.tests").setLevel(logging.DEBUG)
    
    # Console handler for test failures
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    
    yield
