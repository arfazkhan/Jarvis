"""
Pytest configuration and shared fixtures for Home Agent test suite.

Provides fixtures for all core components with mocking and isolation.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock
from agent.event_bus.event_bus import EventBus
from agent.state_engine.state_engine import StateEngine
from agent.automations.automation_engine import AutomationEngine
from agent.learning.pattern_analyzer import PatternAnalyzer


@pytest.fixture
def event_bus():
    """Fresh EventBus instance for each test."""
    return EventBus()


@pytest.fixture
def state_engine(event_bus, tmp_path):
    """StateEngine with event bus integration and temp persistence."""
    state_file = tmp_path / "state.json"
    return StateEngine(event_bus, persist_path=str(state_file))


@pytest.fixture
def mock_device_controller():
    """Mocked device controller that doesn't require hardware."""
    mock = Mock()
    mock.control_relay = Mock(return_value=True)
    mock.get_device_state = Mock(return_value={"endpoints": {1: "off", 2: "off", 3: "off"}})
    return mock


@pytest.fixture
def automation_engine(event_bus, mock_device_controller, state_engine, tmp_path):
    """Automation engine with mocked device controller and temp persistence."""
    routines_file = tmp_path / "routines.json"
    return AutomationEngine(event_bus, device_controller=mock_device_controller, state_engine=state_engine, persist_path=str(routines_file))


@pytest.fixture
def pattern_analyzer():
    """Pattern analyzer instance."""
    return PatternAnalyzer()


@pytest.fixture
def tool_executor(event_bus, state_engine, automation_engine, mock_device_controller):
    """Create ToolExecutor instance."""
    from agent.tools.executor import ToolExecutor
    # ToolExecutor takes (device, state_engine, automations, event_bus)
    return ToolExecutor(mock_device_controller, state_engine, automation_engine, event_bus)


@pytest.fixture
def llm_agent():
    """Create mock LLM agent."""
    agent = Mock()
    agent.client = Mock()
    agent.process_event = Mock(return_value=[])
    return agent


@pytest.fixture
def learning_engine(event_bus, state_engine, automation_engine, tool_executor):
    """Create LearningEngine instance."""
    from agent.learning.learning_engine import LearningEngine
    # LearningEngine takes (event_bus, state_engine, automation_engine, tool_executor)
    return LearningEngine(event_bus, state_engine, automation_engine, tool_executor)


@pytest.fixture
def client():
    """Create Flask test client."""
    from agent.web.app import app
    app.config['TESTING'] = True
    
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_llm_client():
    """Mocked Groq LLM client with configurable responses."""
    mock = Mock()
    
    # Default valid response
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message.content = '''[
        {
            "tool_name": "log_note",
            "arguments": {"text": "Test note"}
        }
    ]'''
    
    mock.chat.completions.create = Mock(return_value=mock_response)
    return mock


@pytest.fixture
def mock_tool_executor():
    """Mocked tool executor."""
    mock = Mock()
    mock.execute = Mock(return_value=None)
    return mock


# ========== Test Helper Functions ==========

def create_valid_event(event_type="relay_toggled", **kwargs):
    """Create a valid event with default values."""
    defaults = {
        "type": event_type,
        "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
        "timestamp": time.time()
    }
    defaults.update(kwargs)
    return defaults


def create_out_of_order_events(count=10):
    """Create events with timestamps out of order."""
    events = []
    base_time = time.time()
    
    for i in range(count):
        timestamp = base_time - (count - i) * 10 + (i % 3) * 15
        events.append(create_valid_event(timestamp=timestamp))
    
    return events


def create_duplicate_events(original_event, count=5):
    """Create duplicate copies of an event."""
    return [original_event.copy() for _ in range(count)]


def create_event_burst(count=1000):
    """Create a burst of many events."""
    return [create_valid_event() for _ in range(count)]


def create_time_travel_event():
    """Create event with timestamp in the past."""
    old_time = time.time() - (365 * 24 * 3600)  # 1 year ago
    return create_valid_event(timestamp=old_time)


def create_llm_response(tool_calls=None, plain_text=False, malformed=False):
    """Create various LLM response types."""
    if plain_text:
        return "This is just plain text, not JSON"
    
    if malformed:
        return '{"tool_calls": [{"tool_name": "test",}]}'
    
    if tool_calls is None:
        tool_calls = [{"tool_name": "log_note", "arguments": {"text": "Test"}}]
    
    import json
    return json.dumps(tool_calls)


def create_invalid_tool_calls():
    """Create various invalid tool call scenarios."""
    return {
        "missing_tool_name": [{"arguments": {"text": "test"}}],
        "missing_arguments": [{"tool_name": "control_relay"}],
        "unknown_tool": [{"tool_name": "hack_the_planet", "arguments": {}}],
        "excessive": [{"tool_name": "log_note", "arguments": {"text": f"Note {i}"}} for i in range(20)],
        "conflicting": [
            {"tool_name": "control_relay", "arguments": {"endpoint": 1, "state": "on"}},
            {"tool_name": "control_relay", "arguments": {"endpoint": 1, "state": "off"}}
        ],
    }


def create_pattern_history(pattern_type="consistent_morning"):
    """Create history with specific patterns."""
    history = []
    base_time = time.time() - (30 * 24 * 3600)
    
    if pattern_type == "consistent_morning":
        for day in range(30):
            timestamp = base_time + (day * 24 * 3600) + (7 * 3600)
            history.append({
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
                "timestamp": timestamp
            })
    
    return history


# ========== Pytest Configuration ==========

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "stress: marks tests as stress tests")
    config.addinivalue_line("markers", "security: marks tests as security tests")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "critical: marks tests as critical")
    config.addinivalue_line("markers", "chaos: marks tests as chaos engineering")
