"""
Integration tests for Firmware API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestFirmwareDevices:
    """Tests for /firmware/devices endpoints."""
    
    def test_list_devices(self, test_client, admin_headers):
        """Test listing all devices with firmware info."""
        response = test_client.get("/firmware/devices", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return a list
        assert isinstance(data, list)
    
    def test_get_device_firmware(self, test_client, admin_headers):
        """Test getting firmware info for a specific device."""
        response = test_client.get("/firmware/devices/device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["device_id"] == "device_1"
        assert "firmware_version" in data
    
    def test_get_device_not_found(self, test_client, admin_headers, mock_system_state):
        """Test getting firmware for non-existent device."""
        # Make discover return empty list
        mock_system_state.matter_controller.discover = MagicMock(return_value=[])
        mock_system_state.matter_controller.get_nodes = MagicMock(return_value=[])
        
        response = test_client.get("/firmware/devices/nonexistent", headers=admin_headers)
        
        assert response.status_code == 404


class TestFirmwareCheck:
    """Tests for /firmware/check endpoint."""
    
    def test_check_for_updates(self, test_client, admin_headers):
        """Test checking for updates."""
        response = test_client.post(
            "/firmware/check",
            json={
                "device_id": "device_1",
                "current_version": "1.0.0",
                "device_name": "Test Device",
                "manufacturer": "TestCorp",
                "model": "TD-100",
            },
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "update_available" in data
        assert data["device_id"] == "device_1"


class TestFirmwareCheckAll:
    """Tests for /firmware/check-all endpoint."""
    
    def test_check_all_devices(self, test_client, admin_headers):
        """Test checking updates for all devices."""
        response = test_client.post("/firmware/check-all", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "checking"
        assert "device_count" in data


class TestFirmwareStatus:
    """Tests for /firmware/status endpoints."""
    
    def test_get_update_status_idle(self, test_client, admin_headers):
        """Test getting status when no update in progress."""
        response = test_client.get("/firmware/status/device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["device_id"] == "device_1"
        assert data["status"] == "idle"
    
    def test_get_all_status(self, test_client, admin_headers):
        """Test getting all update statuses."""
        response = test_client.get("/firmware/status", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "updates" in data
        assert "count" in data


class TestFirmwareClear:
    """Tests for /firmware/clear endpoint."""
    
    def test_clear_update_data(self, test_client, admin_headers):
        """Test clearing update data."""
        response = test_client.delete("/firmware/clear/device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "cleared"


class TestFirmwareHealth:
    """Tests for /firmware/health endpoint."""
    
    def test_get_device_health(self, test_client, admin_headers):
        """Test getting device health."""
        response = test_client.get("/firmware/health/device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["device_id"] == "device_1"
        assert "healthy" in data


class TestFirmwareLogs:
    """Tests for /firmware/logs endpoint."""
    
    def test_get_logs_all_devices(self, test_client, admin_headers):
        """Test getting logs summary for all devices."""
        response = test_client.get("/firmware/logs", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "available_devices" in data
    
    def test_get_device_logs(self, test_client, admin_headers):
        """Test getting logs for a specific device."""
        response = test_client.get("/firmware/logs?device_id=device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "logs" in data


class TestFirmwareHistory:
    """Tests for /firmware/history endpoint."""
    
    def test_get_update_history(self, test_client, admin_headers):
        """Test getting update history."""
        response = test_client.get("/firmware/history/device_1", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["device_id"] == "device_1"
        assert "history" in data
