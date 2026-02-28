"""
End-to-end integration tests for ARVIS API.

Tests complete workflows across multiple endpoints and components.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import concurrent.futures


class TestEmergencyWorkflow:
    """Test emergency shutdown and recovery workflow."""
    
    def test_emergency_shutdown_and_resume(self, test_client, admin_headers):
        """Test complete emergency shutdown and resume cycle."""
        # 1. Trigger emergency stop
        response = test_client.post(
            "/admin/safety-override",
            json={"reason": "Integration test emergency", "force": False},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SHUTDOWN_INITIATED"
        
        # 2. Check health shows degraded
        response = test_client.get("/admin/health", headers=admin_headers)
        assert response.status_code == 200
        
        # 3. Resume operations
        response = test_client.post(
            "/admin/resume",
            json={"confirm": True},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "RESUMED"


class TestVoiceInteractionWorkflow:
    """Test voice interaction workflow."""
    
    def test_voice_interaction_cycle(self, test_client, api_headers):
        """Test complete voice interaction cycle."""
        # 1. Check voice status
        response = test_client.get("/voice/status", headers=api_headers)
        assert response.status_code == 200
        
        # 2. Configure VAD
        response = test_client.post(
            "/voice/vad/config",
            json={"sensitivity": 0.6},
            headers=api_headers,
        )
        assert response.status_code == 200
        
        # 3. Start voice system
        response = test_client.post("/voice/start", headers=api_headers)
        assert response.status_code == 200
        
        # 4. Stop voice system
        response = test_client.post("/voice/stop", headers=api_headers)
        assert response.status_code == 200


class TestSystemHealthWorkflow:
    """Test system health monitoring workflow."""
    
    def test_health_monitoring_workflow(self, test_client, admin_headers):
        """Test health monitoring and diagnostics workflow."""
        # 1. Basic health check
        response = test_client.get("/admin/health", headers=admin_headers)
        assert response.status_code == 200
        basic_health = response.json()
        
        # 2. Detailed health check
        response = test_client.get("/admin/health/detailed", headers=admin_headers)
        assert response.status_code == 200
        detailed_health = response.json()
        
        # 3. Startup status
        response = test_client.get("/admin/startup-status", headers=admin_headers)
        assert response.status_code == 200
        startup_status = response.json()
        
        # 4. Configuration
        response = test_client.get("/admin/config", headers=admin_headers)
        assert response.status_code == 200
        config = response.json()
        
        # Verify all responses are valid
        assert "overall" in basic_health
        assert "status" in detailed_health
        assert "initialized" in startup_status
        assert "voice_enabled" in config


class TestErrorRecoveryWorkflow:
    """Test error handling and recovery workflows."""
    
    def test_component_failure_recovery(self, test_client, admin_headers, mock_system_state):
        """Test recovery from component failure."""
        # Simulate component failure
        mock_system_state.voice_coordinator = None
        
        # 1. Health check shows degraded
        response = test_client.get("/admin/health", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["overall"] == "degraded"
        
        # 2. Other endpoints still work
        response = test_client.get("/admin/config", headers=admin_headers)
        assert response.status_code == 200


class TestAuthenticationWorkflow:
    """Test authentication and authorization."""
    
    def test_admin_endpoints_require_admin_key(self, test_client):
        """Test that admin endpoints require admin key."""
        # Without admin key
        response = test_client.get("/admin/health")
        assert response.status_code in [401, 403, 422]  # Unauthorized or validation error


class TestConcurrencyWorkflow:
    """Test concurrent operations."""
    
    def test_concurrent_health_checks(self, test_client, admin_headers):
        """Test multiple concurrent health check requests."""
        def make_request():
            return test_client.get("/admin/health", headers=admin_headers)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            results = [f.result() for f in futures]
        
        # All requests should succeed
        for response in results:
            assert response.status_code == 200


class TestFirmwareWorkflow:
    """Test firmware update workflow."""
    
    def test_firmware_check_workflow(self, test_client, admin_headers):
        """Test firmware check workflow."""
        # 1. List devices
        response = test_client.get("/firmware/devices", headers=admin_headers)
        assert response.status_code == 200
        
        # 2. Check for updates
        response = test_client.post(
            "/firmware/check",
            json={
                "device_id": "device_1",
                "current_version": "1.0.0",
            },
            headers=admin_headers,
        )
        assert response.status_code == 200
        
        # 3. Get status
        response = test_client.get("/firmware/status/device_1", headers=admin_headers)
        assert response.status_code == 200
