# ARVIS Testing Overhaul Plan

**Goal:** Transform fragile tests into idiot-proof, production-ready verification.

**Current State:** 30 tests, mostly happy paths, mock everything, no edge cases, no stress tests, no failure scenarios.

**Target State:** 385+ tests covering edge cases, failures, stress, and real workflows. Confidence to deploy to pilot.

---

## Philosophy

### What Tests Are For

| Purpose | Test Type | Priority |
| --- | --- | --- |
| **Prevent regressions** | Unit tests (fast, isolated) | HIGH |
| **Verify workflows** | Integration tests (real dependencies) | HIGH |
| **Find breaking points** | Stress tests (load, timing, failures) | MEDIUM |
| **Prove use cases** | E2E scenarios (operator stories) | HIGH |
| **Validate LLM connectivity** | Smoke tests (real API calls) | LOW (manual) |

### What We Test

```markdown
┌─────────────────────────────────────────────────────────────┐
│                        ARVIS TESTING                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 30+ TOOLS   │  │ 6 ENGINES   │  │ 4 LEARNING  │         │
│  │             │  │             │  │   LOOPS     │         │
│  │ Each tool:  │  │ Each engine:│  │             │         │
│  │ - Happy     │  │ - Happy     │  │ - ABI       │         │
│  │ - Edge      │  │ - Edge      │  │ - Prediction│         │
│  │ - Failure   │  │ - Failure   │  │ - Verify    │         │
│  │ - Stress    │  │ - Stress    │  │ - Online    │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              INTEGRATION & E2E TESTS                │   │
│  │                                                     │   │
│  │  - Operator morning routine                         │   │
│  │  - Alarm cascade response                           │   │
│  │  - Energy anomaly detection                         │   │
│  │  - GSAS optimization workflow                        │   │
│  │  - Predictive maintenance alert                     │   │
│  │  - Natural language queries (EN + AR)                │   │
│  │  - Hybrid RAG retrieval                              │   │
│  │  - ABI full loop (predict → verify → learn)          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### What We Mock

| Component | Mock Strategy | Reason |
| --- | --- | --- |
| **LLM** | `MockLLM` with predefined responses | Fast, deterministic, free |
| **BACnet** | `MockBACnetAdapter` with configurable responses | No hardware needed |
| **BMS State** | `MockBMSStateEngine` with test data | Isolated unit tests |
| **Database** | In-memory SQLite | Fast, clean state |
| **Time** | `freezegun` or manual injection | Test time-dependent logic |

### What We Don't Mock

| Component | Why Real |
| --- | --- |
| **Tools logic** | That's what we're testing |
| **Engine logic** | That's what we're testing |
| **Alarm clustering** | Business logic under test |
| **GSAS scoring** | Business logic under test |
| **Prediction ML** | Use small real models or saved predictions |

---

## Test Architecture

### Directory Structure

```markdown
tests/
├── conftest.py              # Pytest fixtures, shared across all tests
├── factories.py             # Test data factories (equipment, alarms, readings)
├── mocks.py                 # MockLLM, MockBACnet, MockBMSState
├── utils.py                 # Test helpers, assertions, timing
│
├── unit/                    # Fast, isolated tests (target: 300+ tests)
│   ├── test_tools/          # Each tool tested thoroughly
│   │   ├── test_equipment_tools.py
│   │   ├── test_alarm_tools.py
│   │   ├── test_energy_tools.py
│   │   ├── test_maintenance_tools.py
│   │   ├── test_gsas_tools.py
│   │   ├── test_advisory_tools.py
│   │   └── test_ml_tools.py
│   │
│   ├── test_engines/        # Each engine tested in isolation
│   │   ├── test_alarm_engine.py
│   │   ├── test_energy_analyzer.py
│   │   ├── test_predictive_maintenance.py
│   │   ├── test_briefing_engine.py
│   │   ├── test_gsas_optimizer.py
│   │   └── test_fleet_intelligence.py
│   │
│   ├── test_learning/       # ABI loops in isolation
│   │   ├── test_prediction_engine.py
│   │   ├── test_verify_loop.py
│   │   ├── test_online_learner.py
│   │   └── test_abi_integration.py
│   │
│   └── test_utils/          # Utility functions
│       ├── test_smart_chunker.py
│       └── test_prompt_builder.py
│
├── integration/             # Real dependencies, slow (target: 15 tests)
│   ├── test_bms_connectivity.py      # BACnet adapter + StateEngine
│   ├── test_llm_agent_flow.py        # LLMAgent + Tools + StateEngine
│   ├── test_alarm_cascade.py         # AlarmEngine + clustering + root cause
│   ├── test_energy_flow.py           # EnergyAnalyzer + BMS data
│   ├── test_gsas_full_flow.py        # GSASOptimizer + GSASReporter
│   ├── test_rag_retrieval.py         # HybridRAG + KnowledgeBase
│   ├── test_briefing_flow.py         # BriefingEngine + GoalGenerator
│   └── test_abi_full_loop.py         # Predict → Verify → Learn
│
├── stress/                  # Load and failure tests (target: 20 tests)
│   ├── test_alarm_flood.py           # 500 alarms in 10s
│   ├── test_concurrent_queries.py    # 100 concurrent tool calls
│   ├── test_llm_timeouts.py          # LLM timeout handling
│   ├── test_llm_rate_limits.py       # 429 response handling
│   ├── test_memory_leaks.py          # Long-running process
│   ├── test_database_pressure.py     # 1M+ rows
│   └── test_malformed_data.py        # Garbage BACnet responses
│
├── e2e/                     # Full operator scenarios (target: 10 tests)
│   ├── test_morning_routine.py       # Operator logs in at 7am
│   ├── test_alarm_response.py        # Chiller trips → cascade → resolution
│   ├── test_energy_anomaly.py       # Waste detected → investigated → fixed
│   ├── test_gsas_improvement.py      # Target 4 stars → recommendations → actions
│   ├── test_maintenance_prediction.py # Failure predicted → scheduled → verified
│   ├── test_bilingual_queries.py     # English and Arabic queries
│   └── test_pilot_readiness.py       # Full system validation
│
├── smoke/                   # Real external services (manual, optional)
│   ├── test_real_llm.py              # Verify API key works
│   ├── test_real_bacnet.py           # Verify BACnet connectivity
│   └── test_real_database.py         # Verify SQLite persistence
│
└── legacy/                  # Keep existing gauntlet tests
    ├── gauntlet_omega.py
    ├── gauntlet_alpha_gsas.py
    ├── gauntlet_explainability.py
    └── super_gauntlet.py
```

---

## Phase Breakdown

### Phase 1: Test Infrastructure (1 day)

**Goal:** Foundation for all future tests.

**Deliverables:**

#### 1.1 `file conftest.py` - Shared Fixtures

```python
# tests/conftest.py

import pytest
import asyncio
from pathlib import Path
from typing import Dict, List, Any

from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.alarm_engine import AlarmEngine
from agent_commercial.energy_analyzer import EnergyAnalyzer
from agent_commercial.predictive_maintenance import PredictiveMaintenanceEngine
from agent_commercial.gsas_reporter import GSASReporter
from agent_commercial.gsas_optimizer import GSASOptimizer
from agent_advisory.verify_loop import VerifyLoop
from agent_cognitive.prediction_engine import PredictionEngine
from agent_advisory.online_learner import OnlineLearner

from tests.factories import (
    EquipmentFactory,
    AlarmFactory,
    DataPointFactory,
    EnergyReadingFactory,
)
from tests.mocks import MockLLM, MockBACnetAdapter, MockBMSStateEngine

# ============================================================================
# EVENT LOOP
# ============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# ============================================================================
# MOCKS
# ============================================================================

@pytest.fixture
def mock_llm():
    """Mock LLM with configurable responses."""
    return MockLLM()

@pytest.fixture
def mock_bacnet():
    """Mock BACnet adapter with test data."""
    return MockBACnetAdapter()

@pytest.fixture
def mock_bms_state():
    """Mock BMS state engine with sample equipment."""
    state = MockBMSStateEngine()
    state.add_equipment(EquipmentFactory.chiller())
    state.add_equipment(EquipmentFactory.ahu())
    state.add_equipment(EquipmentFactory.meter())
    return state

# ============================================================================
# REAL ENGINES (with mocks injected)
# ============================================================================

@pytest.fixture
def alarm_engine(mock_bms_state):
    """Real AlarmEngine with mock state."""
    return AlarmEngine(state_engine=mock_bms_state)

@pytest.fixture
def energy_analyzer(mock_bms_state):
    """Real EnergyAnalyzer with mock state."""
    return EnergyAnalyzer(bms_state=mock_bms_state)

@pytest.fixture
def predictive_maintenance(mock_bms_state):
    """Real PredictiveMaintenanceEngine with mock state."""
    return PredictiveMaintenanceEngine(bms_state=mock_bms_state)

@pytest.fixture
def gsas_reporter():
    """Real GSASReporter with default config."""
    return GSASReporter(
        building_id="TEST-BUILDING-001",
        building_name="Test Building",
        target_rating=4,
    )

@pytest.fixture
def gsas_optimizer(gsas_reporter):
    """Real GSASOptimizer with GSASReporter."""
    return GSASOptimizer(gsas_reporter=gsas_reporter)

@pytest.fixture
def prediction_engine(mock_bms_state, mock_llm):
    """Real PredictionEngine with mocks."""
    return PredictionEngine(
        bms_state=mock_bms_state,
        llm=mock_llm,
    )

@pytest.fixture
def verify_loop(mock_bms_state, mock_llm):
    """Real VerifyLoop with mocks."""
    return VerifyLoop(
        bms_state=mock_bms_state,
        llm=mock_llm,
    )

@pytest.fixture
def online_learner(mock_llm):
    """Real OnlineLearner with mock LLM."""
    return OnlineLearner(llm=mock_llm)

# ============================================================================
# TEST DATA
# ============================================================================

@pytest.fixture
def sample_equipment():
    """Sample equipment for tests."""
    return EquipmentFactory.chiller()

@pytest.fixture
def sample_alarms():
    """Sample alarms for tests."""
    return [
        AlarmFactory.critical_chiller(),
        AlarmFactory.warning_ahu(),
        AlarmFactory.info_zone(),
    ]

@pytest.fixture
def sample_energy_readings():
    """Sample energy readings for tests."""
    return EnergyReadingFactory.last_24_hours()

# ============================================================================
# ASSERTIONS
# ============================================================================

def assert_valid_tool_result(result: Dict[str, Any]):
    """Assert tool result has required fields."""
    assert "status" in result, "Tool result must have 'status'"
    assert result["status"] in ["success", "error"], "Status must be 'success' or 'error'"
    if result["status"] == "success":
        assert "data" in result, "Successful result must have 'data'"
    else:
        assert "error" in result, "Error result must have 'error'"

def assert_valid_recommendation(rec: Dict[str, Any]):
    """Assert recommendation has required fields."""
    assert "recommendation_id" in rec
    assert "equipment_id" in rec
    assert "action" in rec
    assert "confidence" in rec
    assert "gsas_aligned" in rec
    assert 0.0 <= rec["confidence"] <= 1.0

# Register custom assertions
pytest.register_assert_rewrite("tests.conftest")
```

#### 1.2 `file factories.py` - Test Data Generation

```python
# tests/factories.py

"""
Test Data Factories
===================

Easy generation of realistic test data.
All factories return dictionaries that can be converted to dataclass instances.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import random
import uuid

class EquipmentFactory:
    """Generate equipment test data."""
    
    @staticmethod
    def chiller(
        equipment_id: str = "CH-01",
        name: str = "Chiller 1",
        status: str = "running",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "chiller",
            "status": status,
            "location": "Central Plant",
            "capacity_tr": 1200,
            "runtime_hours": 4523.5,
            "efficiency": 0.94,
            "active_alarms": 0,
            **kwargs
        }
    
    @staticmethod
    def ahu(
        equipment_id: str = "AHU-01",
        name: str = "Air Handler 1",
        status: str = "running",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "ahu",
            "status": status,
            "location": "Floor 1 Core",
            "design_cfm": 20000,
            "runtime_hours": 3892.0,
            "efficiency": 0.91,
            "active_alarms": 0,
            **kwargs
        }
    
    @staticmethod
    def meter(
        equipment_id: str = "METER-01",
        name: str = "Main Electric Meter",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "equipment_id": equipment_id,
            "name": name,
            "equipment_type": "meter_electric",
            "status": "online",
            "location": "Main Distribution Panel",
            **kwargs
        }
    
    @staticmethod
    def multiple_chillers(count: int = 3) -> List[Dict[str, Any]]:
        return [
            EquipmentFactory.chiller(equipment_id=f"CH-{i:02d}", name=f"Chiller {i}")
            for i in range(1, count + 1)
        ]
    
    @staticmethod
    def multiple_ahus(count: int = 5) -> List[Dict[str, Any]]:
        return [
            EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}", name=f"Air Handler {i}")
            for i in range(1, count + 1)
        ]

class AlarmFactory:
    """Generate alarm test data."""
    
    @staticmethod
    def critical_chiller(
        alarm_id: str = None,
        equipment_id: str = "CH-01",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": "Chiller high vibration detected",
            "severity": "critical",
            "state": "active",
            "triggered_at": datetime.now().isoformat(),
            "duration_minutes": 15.0,
            "cluster_id": None,
            "suggested_actions": ["Inspect compressor", "Check bearing wear"],
            **kwargs
        }
    
    @staticmethod
    def warning_ahu(
        alarm_id: str = None,
        equipment_id: str = "AHU-01",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": "Supply air temperature above setpoint",
            "severity": "warning",
            "state": "active",
            "triggered_at": datetime.now().isoformat(),
            "duration_minutes": 30.0,
            **kwargs
        }
    
    @staticmethod
    def info_zone(
        alarm_id: str = None,
        equipment_id: str = "ZONE-01",
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "alarm_id": alarm_id or f"ALM-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "message": "Zone temperature deviation detected",
            "severity": "info",
            "state": "active",
            "triggered_at": datetime.now().isoformat(),
            "duration_minutes": 60.0,
            **kwargs
        }
    
    @staticmethod
    def cascade(count: int = 5, root_equipment: str = "CH-01") -> List[Dict[str, Any]]:
        """Generate a cascade of alarms from one root cause."""
        alarms = [AlarmFactory.critical_chiller(equipment_id=root_equipment)]
        for i in range(count - 1):
            alarms.append(AlarmFactory.warning_ahu(
                equipment_id=f"AHU-{i+1:02d}",
                message=f"Zone temp high due to {root_equipment} trip"
            ))
        return alarms

class DataPointFactory:
    """Generate data point test data."""
    
    @staticmethod
    def chw_supply_temp(
        point_id: str = "CH-01/CHWST",
        value: float = 7.0,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "point_id": point_id,
            "name": "Chilled Water Supply Temperature",
            "value": value,
            "unit": "°C",
            "timestamp": datetime.now().isoformat(),
            "equipment_id": "CH-01",
            "point_type": "sensor",
            "quality": "good",
            **kwargs
        }
    
    @staticmethod
    def supply_air_temp(
        point_id: str = "AHU-01/SAT",
        value: float = 14.0,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "point_id": point_id,
            "name": "Supply Air Temperature",
            "value": value,
            "unit": "°C",
            "timestamp": datetime.now().isoformat(),
            "equipment_id": "AHU-01",
            "point_type": "sensor",
            "quality": "good",
            **kwargs
        }
    
    @staticmethod
    def power_kw(
        point_id: str = "METER-01/KW",
        value: float = 450.0,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "point_id": point_id,
            "name": "Building Power",
            "value": value,
            "unit": "kW",
            "timestamp": datetime.now().isoformat(),
            "equipment_id": "METER-01",
            "point_type": "sensor",
            "quality": "good",
            **kwargs
        }
    
    @staticmethod
    def garbage_value(point_id: str = "CH-01/GARBAGE") -> Dict[str, Any]:
        """Generate a data point with garbage value."""
        return {
            "point_id": point_id,
            "name": "Garbage Point",
            "value": "ERROR",
            "unit": "°C",
            "timestamp": datetime.now().isoformat(),
            "equipment_id": "CH-01",
            "point_type": "sensor",
            "quality": "bad",
        }

class EnergyReadingFactory:
    """Generate energy reading test data."""
    
    @staticmethod
    def current(
        building_id: str = "TEST-BUILDING-001",
        total_kw: float = 450.0,
        hvac_kw: float = 320.0,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "reading_id": f"ENG-{uuid.uuid4().hex[:8]}",
            "building_id": building_id,
            "timestamp": datetime.now().isoformat(),
            "total_kw": total_kw,
            "hvac_kw": hvac_kw,
            "lighting_kw": 80.0,
            "other_kw": 50.0,
            "total_kwh_cumulative": 125000.0,
            **kwargs
        }
    
    @staticmethod
    def last_24_hours(
        building_id: str = "TEST-BUILDING-001",
        base_kw: float = 450.0,
    ) -> List[Dict[str, Any]]:
        """Generate 24 hourly readings with realistic variation."""
        readings = []
        for hour in range(24):
            # Simulate daily pattern
            if 6 <= hour <= 18:  # Working hours
                kw = base_kw * (1.0 + random.uniform(-0.1, 0.2))
            else:  # After hours
                kw = base_kw * (0.3 + random.uniform(-0.05, 0.1))
            
            timestamp = datetime.now() - timedelta(hours=23-hour)
            readings.append({
                "reading_id": f"ENG-{uuid.uuid4().hex[:8]}",
                "building_id": building_id,
                "timestamp": timestamp.isoformat(),
                "total_kw": round(kw, 2),
                "hvac_kw": round(kw * 0.7, 2),
            })
        return readings

class RecommendationFactory:
    """Generate recommendation test data."""
    
    @staticmethod
    def reduce_setpoint(
        equipment_id: str = "AHU-01",
        confidence: float = 0.85,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "recommendation_id": f"REC-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "action": "reduce_setpoint",
            "action_type": "energy_optimization",
            "target_value": 24.0,
            "current_value": 22.0,
            "description": "Reduce cooling setpoint to reduce energy waste",
            "confidence": confidence,
            "impact_estimate": {
                "energy_savings_kwh_day": 15.0,
                "gsas_points": 0.3,
            },
            "gsas_aligned": True,
            "priority": "medium",
            **kwargs
        }
    
    @staticmethod
    def schedule_maintenance(
        equipment_id: str = "CH-01",
        confidence: float = 0.92,
        **kwargs
    ) -> Dict[str, Any]:
        return {
            "recommendation_id": f"REC-{uuid.uuid4().hex[:8]}",
            "equipment_id": equipment_id,
            "action": "schedule_maintenance",
            "action_type": "predictive_maintenance",
            "description": "Schedule bearing inspection within 7 days",
            "confidence": confidence,
            "failure_probability": 0.75,
            "rul_days": 14,
            "gsas_aligned": True,
            "priority": "high",
            **kwargs
        }
```

#### 1.3 `file mocks.py` - Mock Classes

```python
# tests/mocks.py

"""
Mock Classes for Testing
========================

Deterministic mocks that simulate real components without external dependencies.
"""

import asyncio
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import uuid

class MockLLM:
    """
    Mock LLM for testing.
    
    Usage:
        # Predefined responses
        llm = MockLLM(responses={
            "equipment": '{"status": "running", "confidence": 0.9}',
            "alarm": '{"severity": "critical", "action": "escalate"}',
        })
        
        # Callable response generator
        llm = MockLLM(response_fn=lambda prompt: '{"status": "ok"}')
    """
    
    def __init__(
        self,
        responses: Dict[str, str] = None,
        response_fn: Callable[[str], str] = None,
        fail_rate: float = 0.0,
        delay_seconds: float = 0.0,
    ):
        self.responses = responses or {}
        self.response_fn = response_fn
        self.fail_rate = fail_rate
        self.delay_seconds = delay_seconds
        
        # Track calls for assertions
        self.call_count = 0
        self.last_prompt = None
        self.prompts: List[str] = []
        
    async def ask(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.prompts.append(prompt)
        
        # Simulate delay
        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)
        
        # Simulate random failures
        import random
        if random.random() < self.fail_rate:
            raise TimeoutError("Mock LLM timeout")
        
        # Use callable if provided
        if self.response_fn:
            return self.response_fn(prompt)
        
        # Match predefined responses
        for key, response in self.responses.items():
            if key.lower() in prompt.lower():
                return response
        
        # Default response
        return '{"status": "ok", "confidence": 0.85}'
    
    async def ask_tool(
        self,
        prompt: str,
        tools: List[Dict],
        **kwargs
    ) -> Dict[str, Any]:
        """Return structured tool call."""
        response_text = await self.ask(prompt, **kwargs)
        
        # Try to parse as JSON
        import json
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Return default tool call
            return {
                "tool": tools[0]["name"] if tools else "unknown",
                "arguments": {},
                "confidence": 0.8
            }
    
    def reset(self):
        """Reset call tracking."""
        self.call_count = 0
        self.last_prompt = None
        self.prompts = []

class MockBACnetAdapter:
    """
    Mock BACnet adapter for testing.
    
    Usage:
        adapter = MockBACnetAdapter()
        adapter.set_device(1001, {"name": "Chiller 1", "address": "192.168.1.101"})
        adapter.set_point("CH-01/CHWST", 7.0)
        
        value = await adapter.read_point(...)  # Returns 7.0
    """
    
    def __init__(self):
        self.devices: Dict[int, Dict[str, Any]] = {}
        self.points: Dict[str, Any] = {}
        self.call_count = 0
        
    def set_device(self, device_id: int, device_info: Dict[str, Any]):
        """Set mock device info."""
        self.devices[device_id] = device_info
    
    def set_point(self, point_id: str, value: Any):
        """Set mock point value."""
        self.points[point_id] = value
    
    async def connect(self) -> bool:
        return True
    
    async def disconnect(self):
        pass
    
    async def discover_devices(self, timeout: int = 5) -> List[Dict]:
        """Return mock devices."""
        return [
            {"device_id": did, **info}
            for did, info in self.devices.items()
        ]
    
    async def read_property(
        self,
        device_address: str,
        object_type: str,
        object_instance: int,
        property_name: str = "presentValue"
    ) -> Optional[Any]:
        """Return mock value."""
        self.call_count += 1
        point_key = f"{object_type}:{object_instance}"
        return self.points.get(point_key)
    
    async def read_all_points(self) -> List[Dict]:
        """Return all mock points."""
        return [
            {"point_id": pid, "value": val}
            for pid, val in self.points.items()
        ]

class MockBMSStateEngine:
    """
    Mock BMS state engine for testing.
    
    Usage:
        state = MockBMSStateEngine()
        state.add_equipment(EquipmentFactory.chiller())
        state.update_point("CH-01/CHWST", 7.0)
        
        equipment = state.get_equipment("CH-01")  # Returns mock equipment
        point = state.get_point("CH-01/CHWST")    # Returns mock point
    """
    
    def __init__(self):
        self.equipment: Dict[str, Dict[str, Any]] = {}
        self.points: Dict[str, Dict[str, Any]] = {}
        self.alarms: List[Dict[str, Any]] = []
        
    def add_equipment(self, equipment: Dict[str, Any]):
        """Add mock equipment."""
        self.equipment[equipment["equipment_id"]] = equipment
    
    def update_point(self, point_id: str, value: Any, **kwargs):
        """Update mock point value."""
        self.points[point_id] = {
            "point_id": point_id,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
    
    def add_alarm(self, alarm: Dict[str, Any]):
        """Add mock alarm."""
        self.alarms.append(alarm)
    
    def get_equipment(self, equipment_id: str) -> Optional[Dict[str, Any]]:
        return self.equipment.get(equipment_id)
    
    def get_all_equipment(self) -> List[Dict[str, Any]]:
        return list(self.equipment.values())
    
    def get_point(self, point_id: str) -> Optional[Dict[str, Any]]:
        return self.points.get(point_id)
    
    def get_points_by_equipment(self, equipment_id: str) -> List[Dict[str, Any]]:
        return [
            p for p in self.points.values()
            if p.get("equipment_id") == equipment_id
        ]
    
    def get_active_alarms(self, severity_filter: str = None) -> List[Dict[str, Any]]:
        if severity_filter:
            return [a for a in self.alarms if a.get("severity") == severity_filter]
        return self.alarms
    
    def clear(self):
        """Clear all mock data."""
        self.equipment.clear()
        self.points.clear()
        self.alarms.clear()
```

#### 1.4 `file utils.py` - Test Utilities

```python
# tests/utils.py

"""
Test Utilities
==============

Helper functions and assertions for tests.
"""

import time
import asyncio
from typing import Callable, Any, Dict, List
import pytest

class Timer:
    """Context manager for timing code execution."""
    
    def __init__(self):
        self.elapsed = 0.0
        self._start = 0.0
    
    def __enter__(self):
        self._start = time.time()
        return self
    
    def __exit__(self, *args):
        self.elapsed = time.time() - self._start

async def run_concurrently(tasks: List[Callable], count: int = 10) -> List[Any]:
    """Run multiple copies of a task concurrently."""
    async_tasks = [asyncio.create_task(task()) for _ in range(count) for task in tasks]
    return await asyncio.gather(*async_tasks, return_exceptions=True)

def assert_json_structure(data: Dict, required_keys: List[str]):
    """Assert JSON has required keys."""
    for key in required_keys:
        assert key in data, f"Missing required key: {key}"

def assert_valid_uuid(value: str):
    """Assert string is valid UUID."""
    import uuid
    try:
        uuid.UUID(value)
    except ValueError:
        pytest.fail(f"Invalid UUID: {value}")

def assert_confidence_range(value: float):
    """Assert confidence is between 0 and 1."""
    assert 0.0 <= value <= 1.0, f"Confidence {value} out of range [0, 1]"

def assert_garbage_handled(result: Dict[str, Any]):
    """Assert garbage input was handled gracefully."""
    assert result.get("status") in ["success", "error"], "Result must have status"
    if result.get("status") == "error":
        assert "error" in result, "Error result must have error message"
        # Should not crash, should provide helpful error
        assert result["error"] != "Unknown error", "Error message should be specific"
```

---

**Phase 1 Deliverables Summary:**

| File | Lines | Purpose |
| --- | --- | --- |
|  | \~200 | Shared fixtures for all tests |
|  | \~300 | Easy test data generation |
|  | \~200 | Deterministic component mocks |
|  | \~80 | Test helpers and assertions |
| **Total** | **\~780** | Foundation for all tests |

---

### Phase 2: Tool Tests (2 days)

**Goal:** Thoroughly test all 30+ tools.

**Approach:** For each tool, test:

- Happy path (normal operation)
- Edge cases (empty data, missing fields)
- Failure modes (engine unavailable, garbage input)
- Stress (concurrent calls, large data)

#### 2.1 Tool Test Template

```python
# tests/unit/test_tools/test_equipment_tools.py

import pytest
from agent_commercial.tools.equipment_tools import (
    GetEquipmentStatus,
    GetAllEquipment,
    GetDataPoints,
)
from tests.factories import EquipmentFactory, DataPointFactory
from tests.conftest import assert_valid_tool_result

class TestGetEquipmentStatus:
    """Test GetEquipmentStatus tool thoroughly."""
    
    # ==================== HAPPY PATHS ====================
    
    @pytest.mark.asyncio
    async def test_returns_equipment_with_all_points(self, mock_bms_state):
        """Normal case: equipment exists with multiple points."""
        # Setup
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point("CH-01/CHWST", 7.0, equipment_id="CH-01")
        mock_bms_state.update_point("CH-01/KW", 250.0, equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Execute
        result = await tool.execute(equipment_id="CH-01")
        
        # Verify
        assert result.success
        assert "equipment_id" in result.output
        assert result.output["equipment_id"] == "CH-01"
        assert "points" in result.output
        assert len(result.output["points"]) == 2
    
    @pytest.mark.asyncio
    async def test_returns_equipment_with_no_alarms(self, mock_bms_state):
        """Normal case: equipment running cleanly."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="running"))
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert result.output["active_alarms"] == 0
    
    # ==================== EDGE CASES ====================
    
    @pytest.mark.asyncio
    async def test_equipment_not_found_returns_error(self, mock_bms_state):
        """Equipment ID doesn't exist in state engine."""
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="NONEXISTENT-01")
        
        assert not result.success
        assert "not found" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_equipment_with_no_points(self, mock_bms_state):
        """Equipment exists but has no data points configured."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert result.output["points"] == []
    
    @pytest.mark.asyncio
    async def test_equipment_with_stale_data(self, mock_bms_state):
        """Last update was 5 hours ago - should warn."""
        from datetime import datetime, timedelta
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point(
            "CH-01/CHWST",
            7.0,
            equipment_id="CH-01",
            timestamp=(datetime.now() - timedelta(hours=5)).isoformat()
        )
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should still succeed but warn about stale data
        assert result.success
        # Optional: assert result.output.get("stale_warning") == True
    
    # ==================== FAILURE MODES ====================
    
    @pytest.mark.asyncio
    async def test_bms_state_engine_unavailable(self):
        """State engine crashed or not initialized."""
        tool = GetEquipmentStatus()
        tool.bms_state = None  # Engine unavailable
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert not result.success
        assert "not available" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_point_value_is_none(self, mock_bms_state):
        """BACnet read returned None - should handle gracefully."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point("CH-01/CHWST", None, equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should still succeed, but point value should be None or indicate unavailable
        assert result.success
        point = result.output["points"][0]
        assert point["value"] is None or "unavailable" in str(point.get("quality", "")).lower()
    
    @pytest.mark.asyncio
    async def test_point_value_is_garbage(self, mock_bms_state):
        """BACnet returned 'ERROR' string instead of float."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point("CH-01/GARBAGE", "ERROR", equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        # Should handle gracefully, not crash
        assert result.success or result.error  # Either succeed with warning or fail gracefully
        if result.error:
            assert "invalid" in result.error.lower() or "garbage" in result.error.lower()
    
    # ==================== STRESS ====================
    
    @pytest.mark.asyncio
    async def test_concurrent_calls_same_equipment(self, mock_bms_state):
        """100 concurrent requests for same equipment."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        from tests.utils import run_concurrently
        
        results = await run_concurrently(
            [lambda: tool.execute(equipment_id="CH-01")],
            count=100
        )
        
        # All should succeed
        assert all(r.success for r in results if not isinstance(r, Exception))
    
    @pytest.mark.asyncio
    async def test_large_equipment_list(self, mock_bms_state):
        """Equipment with 500+ data points."""
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add 500 points
        for i in range(500):
            mock_bms_state.update_point(f"CH-01/P{i:04d}", float(i), equipment_id="CH-01")
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        result = await tool.execute(equipment_id="CH-01")
        
        assert result.success
        assert len(result.output["points"]) == 500
```

#### 2.2 Tool Test Coverage

| Tool Category | Tools | Tests per Tool | Total Tests |
| --- | --- | --- | --- |
| Equipment | 5 | 10 | 50 |
| Alarms | 6 | 12 | 72 |
| Energy | 5 | 12 | 60 |
| Maintenance | 4 | 15 | 60 |
| GSAS | 4 | 10 | 40 |
| Advisory | 4 | 12 | 48 |
| ML | 3 | 15 | 45 |
| **Total** | **31** | **\~10 avg** | **\~375** |

---

### Phase 3: Integration Tests (2 days)

**Goal:** Test real workflows, not just function calls.

#### 3.1 Integration Test Examples

```python
# tests/integration/test_alarm_cascade.py

import pytest
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.alarm_engine import AlarmEngine
from tests.factories import AlarmFactory, EquipmentFactory

class TestAlarmCascadeResponse:
    """
    Real-world scenario: Chiller trips → 5 zone alarms.
    
    Tests the full flow:
    1. BMS publishes 6 alarm events
    2. AlarmEngine clusters into cascade
    3. Root cause identified as CH-01
    4. Operator asks "what happened?"
    5. BMSLLMAgent explains cascade
    """
    
    @pytest.mark.asyncio
    async def test_chiller_trip_creates_cascade(self):
        """Chiller trip should create alarm cascade."""
        # Setup
        state_engine = BMSStateEngine()
        state_engine.add_equipment(EquipmentFactory.chiller())
        for i in range(1, 6):
            state_engine.add_equipment(EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}"))
        
        alarm_engine = AlarmEngine(state_engine=state_engine)
        
        # Trigger cascade
        cascade_alarms = AlarmFactory.cascade(count=6, root_equipment="CH-01")
        for alarm in cascade_alarms:
            state_engine.add_alarm(alarm)
        
        # Execute clustering
        clusters = alarm_engine.cluster_alarms(state_engine.get_active_alarms())
        
        # Verify
        assert len(clusters) == 1, "Should cluster into single cascade"
        cluster = clusters[0]
        assert len(cluster.alarm_ids) == 6, "Should include all 6 alarms"
        assert cluster.root_cause_equipment_id == "CH-01", "Root cause should be chiller"
        assert cluster.root_cause_confidence > 0.7, "Should be confident in root cause"
    
    @pytest.mark.asyncio
    async def test_cascade_explanation_generated(self, mock_llm):
        """LLM should explain cascade in human terms."""
        from agent_commercial.bms_llm_agent import BMSLLMAgent
        
        # Setup LLM to return explanation
        mock_llm.responses["cascade"] = json.dumps({
            "explanation": "Chiller 1 tripped due to high vibration, causing 5 zone alarms",
            "root_cause": "CH-01 bearing wear",
            "affected_zones": ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"],
            "recommended_action": "Schedule CH-01 maintenance within 48 hours"
        })
        
        agent = BMSLLMAgent(llm=mock_llm)
        
        # Ask about cascade
        response = await agent.ask("What happened with the alarms?")
        
        # Verify
        assert "CH-01" in response
        assert "bearing" in response.lower()
        assert mock_llm.call_count == 1
```

---

### Phase 4: Stress Tests (1 day)

**Goal:** Find where ARVIS breaks.

#### 4.1 Stress Test Examples

```python
# tests/stress/test_alarm_flood.py

import pytest
import asyncio
from agent_commercial.alarm_engine import AlarmEngine
from tests.factories import AlarmFactory

class TestAlarmFlood:
    """What happens when 500 alarms arrive in 10 seconds?"""
    
    @pytest.mark.asyncio
    async def test_alarm_flood_500_in_10s(self, mock_bms_state):
        """Generate 500 alarms, verify system doesn't crash."""
        alarm_engine = AlarmEngine(state_engine=mock_bms_state)
        
        # Generate 500 alarms
        alarms = [AlarmFactory.critical_chiller(alarm_id=f"ALM-{i}") for i in range(500)]
        
        # Process all
        start = time.time()
        for alarm in alarms:
            mock_bms_state.add_alarm(alarm)
        
        clusters = alarm_engine.cluster_alarms(alarms)
        elapsed = time.time() - start
        
        # Verify
        assert elapsed < 5.0, "Should process 500 alarms in under 5 seconds"
        assert len(clusters) > 0, "Should cluster alarms"
        # Memory check (optional)
        # import tracemalloc
        # assert current_memory < max_memory
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_calls_100(self, mock_bms_state):
        """100 concurrent tool calls should all succeed."""
        from agent_commercial.tools.equipment_tools import GetEquipmentStatus
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        tool = GetEquipmentStatus()
        tool.bms_state = mock_bms_state
        
        # Run 100 concurrent calls
        tasks = [tool.execute(equipment_id="CH-01") for _ in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
        
        # Verify all succeeded
        successes = [r for r in results if hasattr(r, 'success') and r.success]
        assert len(successes) == 100
```

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/tests.yml

name: ARVIS Tests

on:
  push:
    branches: [commercial-bms]
  pull_request:
    branches: [commercial-bms]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run unit tests
      run: pytest tests/unit/ -v --cov=agent_commercial --cov=agent_advisory --cov-report=xml
    
    - name: Run integration tests
      run: pytest tests/integration/ -v
    
    - name: Run stress tests
      run: pytest tests/stress/ -v --timeout=300
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
```

### Test Execution Commands

```bash
# Run all tests
pytest

# Run specific test types
pytest tests/unit/              # Fast unit tests
pytest tests/integration/       # Integration tests (slower)
pytest tests/stress/            # Stress tests (slowest)
pytest tests/e2e/               # End-to-end scenarios

# Run with coverage
pytest --cov=agent_commercial --cov=agent_advisory

# Run specific test file
pytest tests/unit/test_tools/test_equipment_tools.py

# Run specific test
pytest tests/unit/test_tools/test_equipment_tools.py::TestGetEquipmentStatus::test_returns_equipment_with_all_points

# Run tests matching pattern
pytest -k "alarm"

# Run with verbose output
pytest -v

# Run with timing
pytest --durations=10

# Run smoke tests (real LLM, requires API key)
pytest tests/smoke/ -m smoke --run-slow
```

---

## Success Metrics

| Metric | Target | Why |
| --- | --- | --- |
| **Total tests** | 385+ | Coverage of all tools, engines, flows |
| **Test execution time** | &lt;60s for unit tests | Fast feedback loop |
| **Coverage** | &gt;80% | Confidence in code paths |
| **Flaky tests** | 0 | Reliability |
| **Edge cases covered** | 100% of tools | Production robustness |
| **Stress scenarios** | 20+ | Know system limits |
| **Integration scenarios** | 15+ | Verify real workflows |

---

## Timeline

| Day | Phase | Deliverable |
| --- | --- | --- |
| **Day 1** | Infrastructure | `file conftest.py`, `file factories.py`, `file mocks.py`, `file utils.py` |
| **Day 2-3** | Tool Tests | 300+ unit tests for all 30+ tools |
| **Day 4-5** | Integration Tests | 15 integration tests for real workflows |
| **Day 6** | Stress Tests | 20 stress tests for breaking points |
| **Day 7** | CI/CD | GitHub Actions, coverage reports |

---

## Post-Implementation

### Maintenance

- **New tool?** → Add 10+ tests following template
- **Bug found?** → Write test that reproduces it, then fix
- **Refactor?** → Tests should still pass
- **New feature?** → Write tests first (TDD)

### Test Quality Checks

```bash
# Check for missing tests
pytest --cov-report=term-missing

# Find slow tests
pytest --durations=20

# Find flaky tests
pytest --flaky-report

# Check coverage
pytest --cov-fail-under=80
```

---

## Appendix: Test Patterns

### Pattern 1: Happy Path

```python
async def test_normal_operation(self, mock_state):
    """Test that normal inputs produce expected outputs."""
    # Setup
    tool = MyTool()
    tool.state = mock_state
    
    # Execute
    result = await tool.execute(param="value")
    
    # Verify
    assert result.success
    assert result.output == expected_output
```

### Pattern 2: Edge Case

```python
async def test_empty_input(self):
    """Test with empty/missing input."""
    tool = MyTool()
    result = await tool.execute(param="")
    
    # Should handle gracefully
    assert result.success or result.error
    if result.error:
        assert "empty" in result.error.lower()
```

### Pattern 3: Failure Mode

```python
async def test_dependency_failure(self):
    """Test when dependency is unavailable."""
    tool = MyTool()
    tool.state = None  # Dependency unavailable
    
    result = await tool.execute(param="value")
    
    assert not result.success
    assert "not available" in result.error.lower()
```

### Pattern 4: Stress

```python
async def test_high_load(self):
    """Test under high load."""
    tool = MyTool()
    
    tasks = [tool.execute(param=f"value_{i}") for i in range(1000)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Should not crash
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert len(exceptions) == 0
```

---

**Plan Complete.**

This gives you idiot-proof tests that will catch issues before they hit production.