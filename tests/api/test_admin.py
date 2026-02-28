"""
Integration tests for Admin API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestAdminHealthEndpoint:
    """Tests for /admin/health endpoint."""
    
    def test_health_check_all_healthy(self, test_client, admin_headers):
        """Test health check when all components are healthy."""
        response = test_client.get("/admin/health", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["overall"] == "healthy"
        assert data["event_bus"] is True
        assert data["state_engine"] is True
        assert data["llm_agent"] is True
        assert data["voice"] is True
        assert data["matter_controller"] is True
        assert data["automation_engine"] is True
        assert data["learning_engine"] is True
    
    def test_health_check_degraded(self, test_client, admin_headers, mock_system_state):
        """Test health check when some components are unavailable."""
        # Set some components to None
        mock_system_state.voice_coordinator = None
        mock_system_state.learning_engine = None
        
        response = test_client.get("/admin/health", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["overall"] == "degraded"
        assert data["voice"] is False
        assert data["learning_engine"] is False


class TestAdminKillSwitch:
    """Tests for /admin/safety-override endpoint."""
    
    def test_emergency_stop_success(self, test_client, admin_headers):
        """Test successful emergency stop."""
        response = test_client.post(
            "/admin/safety-override",
            json={"reason": "Test emergency", "force": False},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "SHUTDOWN_INITIATED"
        assert data["reason"] == "Test emergency"
        assert len(data["actions_taken"]) > 0
        
        # Check that automation stop was attempted
        automation_action = next(
            (a for a in data["actions_taken"] if a["action"] == "automation_stop"),
            None
        )
        assert automation_action is not None
        assert automation_action["status"] == "success"
    
    def test_emergency_stop_partial_failure(self, test_client, admin_headers, mock_system_state):
        """Test emergency stop with some failures."""
        # Make automation engine fail
        mock_system_state.automation_engine.stop_all.side_effect = Exception("Test error")
        
        response = test_client.post(
            "/admin/safety-override",
            json={"reason": "Test emergency", "force": False},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check that failure is recorded
        automation_action = next(
            (a for a in data["actions_taken"] if a["action"] == "automation_stop"),
            None
        )
        assert automation_action is not None
        assert automation_action["status"] == "failed"
        assert "Test error" in automation_action["error"]


class TestAdminResume:
    """Tests for /admin/resume endpoint."""
    
    def test_resume_requires_confirmation(self, test_client, admin_headers):
        """Test that resume requires explicit confirmation."""
        response = test_client.post(
            "/admin/resume",
            json={"confirm": False},
            headers=admin_headers,
        )
        
        assert response.status_code == 400
        assert "confirmation" in response.json()["detail"].lower()
    
    def test_resume_success(self, test_client, admin_headers):
        """Test successful resume after emergency stop."""
        response = test_client.post(
            "/admin/resume",
            json={"confirm": True},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "RESUMED"
        assert len(data["actions_taken"]) > 0


class TestAdminShutdown:
    """Tests for /admin/shutdown endpoint."""
    
    def test_graceful_shutdown(self, test_client, admin_headers):
        """Test graceful shutdown initiation."""
        response = test_client.post(
            "/admin/shutdown",
            json={"reason": "Maintenance", "timeout": 30.0, "force": False},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert data["reason"] == "Maintenance"


class TestAdminStartupStatus:
    """Tests for /admin/startup-status endpoint."""
    
    def test_startup_status(self, test_client, admin_headers):
        """Test getting startup status."""
        response = test_client.get("/admin/startup-status", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "initialized" in data
        assert "components" in data
        assert "progress_percent" in data
        assert "initialized_count" in data
        assert "total_components" in data


class TestAdminDetailedHealth:
    """Tests for /admin/health/detailed endpoint."""
    
    def test_detailed_health_check(self, test_client, admin_headers):
        """Test detailed health check with diagnostics."""
        response = test_client.get("/admin/health/detailed", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "status" in data
        assert "components" in data
        assert "critical_failures" in data


class TestAdminConfig:
    """Tests for /admin/config endpoint."""
    
    def test_get_config(self, test_client, admin_headers):
        """Test getting active configuration."""
        response = test_client.get("/admin/config", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "voice_enabled" in data
        assert "learning_enabled" in data
        assert "safety_guardrails" in data
