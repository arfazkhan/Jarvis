import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_commercial.api.routes_omega import router
from agent_commercial.api.sse_broadcaster import SSEBroadcaster

# Mock Classes
class MockTerminalEngine:
    def get_active_advisory(self, building_id):
        return MagicMock(to_dict=lambda: {"id": "ADV-001", "type": "Safety Envelope Breach", "severity": "CRITICAL"})

class MockIntegrityMonitor:
    def get_active_alerts(self, building_id):
        return [MagicMock(to_dict=lambda: {"id": "INT-001", "type": "Greenwashing", "severity": "HIGH"})]

class MockTrustGovernor:
    def get_modifiers(self, building_id):
        modifiers = MagicMock()
        modifiers.trust_level.name = "HIGH"
        modifiers.trust_score = 0.95
        modifiers.confidence_ceiling = 0.9
        modifiers.proactive_throttle = 1.0
        return modifiers

class MockSimController:
    def __init__(self):
        self.paused = False
        self.speed = 1.0
    def pause(self): self.paused = True
    def resume(self): self.paused = False
    def set_speed(self, s): self.speed = s

# Setup App
app = FastAPI()
app.include_router(router)

# Inject Mocks
app.state.terminal_engine = MockTerminalEngine()
app.state.integrity_monitor = MockIntegrityMonitor()
app.state.trust_gov = MockTrustGovernor()
app.state.sim_controller = MockSimController()

client = TestClient(app)

def test_advisories_endpoint():
    response = client.get("/api/v1/advisories/active")
    assert response.status_code == 200
    data = response.json()
    assert "terminal" in data
    assert "integrity" in data
    assert len(data["terminal"]) == 1
    assert data["terminal"][0]["id"] == "ADV-001"
    assert len(data["integrity"]) == 1
    assert data["integrity"][0]["id"] == "INT-001"

def test_governance_endpoint():
    response = client.get("/api/v1/governance/status")
    assert response.status_code == 200
    data = response.json()
    assert "trust" in data
    assert "greenwashing" in data
    assert data["trust"]["level"] == "HIGH"
    assert data["trust"]["score"] == 0.95

def test_sim_control_endpoint():
    # Test Pause
    response = client.post("/api/v1/sim/control", json={"action": "PAUSE"})
    assert response.status_code == 200
    assert app.state.sim_controller.paused == True
    
    # Test Resume
    response = client.post("/api/v1/sim/control", json={"action": "RESUME"})
    assert response.status_code == 200
    assert app.state.sim_controller.paused == False
    
    # Test Speed
    response = client.post("/api/v1/sim/control", json={"action": "SET_SPEED", "speed": 5.0})
    assert response.status_code == 200
    assert app.state.sim_controller.speed == 5.0

def test_sse_endpoint_connection():
    # SSE is harder to test fully with TestClient but we can check connection
    # Check if endpoint exists
    # Note: TestClient doesn't support stream=True in this configuration easily
    # We just check if we can hit it. It will hang if we don't stream, 
    # but we can try to use a proper httpx client if needed or just skip valid connection check
    # For now, let's just use stream=True from httpx if available, or just omit stream=True and rely on it returning a generator (which validly returns 200 OK)
    
    # Actually, SSE Starlette returns an EventSourceResponse. 
    # Calling it normally with TestClient might try to read the whole stream (infinite).
    # We should use stream=True if the underlying client supports it.
    # Since TestClient(app) uses Starlette's TestClient which uses requests (sync),
    # let's try just instantiating the response handler or use a context manager if supported.
    
    try:
        with client.stream("GET", "/api/v1/stream/thoughts") as response:
            assert response.status_code == 200
            # content-type might be 'text/event-stream; charset=utf-8'
            assert "text/event-stream" in response.headers["content-type"]
    except AttributeError:
        # Fallback for older TestClient versions that don't have .stream()
        # We'll just skip this check or try a basic GET with timeout mock
        print("Skipping detailed SSE stream check due to TestClient version")
        pass

if __name__ == "__main__":
    # Manual run if pytest not available
    test_advisories_endpoint()
    test_governance_endpoint()
    test_sim_control_endpoint()
    test_sse_endpoint_connection()
    print("All tests passed!")
