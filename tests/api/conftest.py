"""
Pytest configuration and fixtures for API integration tests.
"""

import asyncio
import os
import sys
from typing import AsyncGenerator, Generator
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_event_bus():
    """Mock EventBus for testing."""
    bus = MagicMock()
    bus.publish = MagicMock()
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    return bus


@pytest.fixture
def mock_state_engine():
    """Mock StateEngine for testing."""
    engine = MagicMock()
    engine.get_state = MagicMock(return_value={})
    engine.set_state = MagicMock()
    engine.get_device_state = MagicMock(return_value={})
    return engine


@pytest.fixture
def mock_llm_agent():
    """Mock LLM Agent for testing."""
    agent = MagicMock()
    agent.process = AsyncMock(return_value={"response": "Test response"})
    agent.is_ready = True
    return agent


@pytest.fixture
def mock_matter_controller():
    """Mock MatterController for testing."""
    controller = MagicMock()
    controller.discover = MagicMock(return_value=[
        {"id": "device_1", "name": "Living Room Light", "type": "light", "online": True},
        {"id": "device_2", "name": "Kitchen Thermostat", "type": "thermostat", "online": True},
    ])
    controller.emergency_stop = MagicMock(return_value={"stopped": 2})
    controller.get_node = MagicMock(return_value={"id": "device_1", "name": "Test Device"})
    controller.get_nodes = MagicMock(return_value=[
        {"id": "device_1", "name": "Living Room Light", "type": "light"},
        {"id": "device_2", "name": "Kitchen Thermostat", "type": "thermostat"},
    ])
    controller.get_state = MagicMock(return_value={"power": "on"})
    controller.get_device_config = MagicMock(return_value={
        "name": "Test Device",
        "firmware_version": "1.0.0",
        "manufacturer": "TestCorp",
    })
    return controller


@pytest.fixture
def mock_automation_engine():
    """Mock AutomationEngine for testing."""
    engine = MagicMock()
    engine.stop_all = MagicMock(return_value={"stopped": 5})
    engine.resume_all = MagicMock(return_value={"resumed": 5})
    engine.get_routines = MagicMock(return_value=[])
    engine.add_routine = MagicMock()
    engine.remove_routine = MagicMock()
    return engine


@pytest.fixture
def mock_learning_engine():
    """Mock LearningEngine for testing."""
    engine = MagicMock()
    engine.get_patterns = MagicMock(return_value=[])
    engine.add_observation = MagicMock()
    engine.train = AsyncMock()
    engine.is_training = False
    engine.pattern_count = 10
    engine.observation_count = 100
    return engine


@pytest.fixture
def mock_voice_coordinator():
    """Mock VoiceCoordinator for testing."""
    coordinator = MagicMock()
    coordinator.is_running = True
    coordinator.is_listening = False
    coordinator.is_speaking = False
    coordinator.start = AsyncMock()
    coordinator.stop = AsyncMock()
    coordinator.speak = AsyncMock()
    
    # Mock ears (VAD)
    ears = MagicMock()
    ears.vad_sensitivity = 0.5
    ears.silence_threshold_ms = 500
    ears.is_calibrating = False
    ears.total_speech_segments = 10
    ears.total_silence_segments = 5
    ears.false_positive_count = 1
    ears.false_negative_count = 0
    coordinator.ears = ears
    
    # Mock mouth (TTS)
    mouth = MagicMock()
    mouth.tts_engine = "kokoro"
    mouth.speak = AsyncMock()
    coordinator.mouth = mouth
    
    return coordinator


@pytest.fixture
def mock_system_state(
    mock_event_bus,
    mock_state_engine,
    mock_llm_agent,
    mock_matter_controller,
    mock_automation_engine,
    mock_learning_engine,
    mock_voice_coordinator,
):
    """Mock SystemContainer for testing."""
    from api.dependencies import SystemContainer
    
    return SystemContainer(
        event_bus=mock_event_bus,
        state_engine=mock_state_engine,
        llm_agent=mock_llm_agent,
        matter_controller=mock_matter_controller,
        automation_engine=mock_automation_engine,
        learning_engine=mock_learning_engine,
        voice_coordinator=mock_voice_coordinator,
    )


@pytest.fixture
def test_client(mock_system_state) -> Generator:
    """Create a test client with mocked dependencies."""
    # Patch the global state
    with patch("api.dependencies.global_state", mock_system_state):
        from api.main import app
        
        with TestClient(app) as client:
            yield client


@pytest.fixture
async def async_client(mock_system_state) -> AsyncGenerator:
    """Create an async test client with mocked dependencies."""
    with patch("api.dependencies.global_state", mock_system_state):
        from api.main import app
        
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


@pytest.fixture
def admin_headers():
    """Headers for admin API access."""
    return {"X-Admin-Key": "test-admin-key"}


@pytest.fixture
def api_headers():
    """Headers for general API access."""
    return {"X-API-Key": "test-api-key"}
