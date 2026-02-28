"""
Integration tests for Voice API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


class TestVoiceStatus:
    """Tests for /voice/status endpoint."""
    
    def test_get_status(self, test_client, api_headers):
        """Test getting voice system status."""
        response = test_client.get("/voice/status", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "is_running" in data
        assert "is_listening" in data
        assert "is_speaking" in data
        assert "coordinator_active" in data
    
    def test_get_status_with_vad(self, test_client, api_headers):
        """Test getting status includes VAD info."""
        response = test_client.get("/voice/status", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # VAD info should be included
        assert "vad" in data


class TestVoiceVADConfig:
    """Tests for /voice/vad/config endpoints."""
    
    def test_get_vad_config(self, test_client, api_headers):
        """Test getting VAD configuration."""
        response = test_client.get("/voice/vad/config", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "sensitivity" in data
        assert "silence_threshold_ms" in data
        assert "speech_threshold" in data
    
    def test_set_vad_config(self, test_client, api_headers):
        """Test setting VAD configuration."""
        response = test_client.post(
            "/voice/vad/config",
            json={
                "sensitivity": 0.7,
                "silence_threshold_ms": 600,
                "speech_threshold": 0.4,
                "min_speech_duration_ms": 300,
                "max_speech_duration_ms": 25000,
            },
            headers=api_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "updated"
        assert data["config"]["sensitivity"] == 0.7
    
    def test_set_vad_config_invalid_sensitivity(self, test_client, api_headers):
        """Test setting invalid sensitivity value."""
        response = test_client.post(
            "/voice/vad/config",
            json={"sensitivity": 1.5},  # Invalid: > 1.0
            headers=api_headers,
        )
        
        assert response.status_code == 400


class TestVoiceVADCalibrate:
    """Tests for /voice/vad/calibrate endpoint."""
    
    def test_calibrate_vad(self, test_client, api_headers):
        """Test starting VAD calibration."""
        response = test_client.post(
            "/voice/vad/calibrate",
            json={"duration_seconds": 10, "sample_rate": 16000},
            headers=api_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "calibration_started"
        assert "duration_seconds" in data


class TestVoiceVADMetrics:
    """Tests for /voice/vad/metrics endpoints."""
    
    def test_get_vad_metrics(self, test_client, api_headers):
        """Test getting VAD performance metrics."""
        response = test_client.get("/voice/vad/metrics", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total_speech_segments" in data
        assert "total_silence_segments" in data
        assert "estimated_accuracy" in data
    
    def test_reset_vad_metrics(self, test_client, api_headers):
        """Test resetting VAD metrics."""
        response = test_client.post("/voice/vad/reset-metrics", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "metrics_reset"


class TestVoiceTTS:
    """Tests for TTS endpoints."""
    
    def test_list_engines(self, test_client, api_headers):
        """Test listing available TTS engines."""
        response = test_client.get("/voice/tts/engines", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "engines" in data
        assert len(data["engines"]) > 0
    
    def test_list_voices(self, test_client, api_headers):
        """Test listing available TTS voices."""
        response = test_client.get("/voice/tts/voices", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "voices" in data
    
    def test_config_tts(self, test_client, api_headers):
        """Test configuring TTS engine."""
        response = test_client.post(
            "/voice/tts/config",
            json={"engine": "kokoro", "speed": 1.2},
            headers=api_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "updated"


class TestVoiceStartStop:
    """Tests for /voice/start and /voice/stop endpoints."""
    
    def test_start_voice(self, test_client, api_headers):
        """Test starting the voice system."""
        response = test_client.post("/voice/start", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "started"
    
    def test_stop_voice(self, test_client, api_headers):
        """Test stopping the voice system."""
        response = test_client.post("/voice/stop", headers=api_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "stopped"


class TestVoiceWebSocket:
    """Tests for /voice/stream WebSocket endpoint."""
    
    def test_websocket_connection(self, test_client):
        """Test WebSocket connection for voice streaming."""
        with test_client.websocket_connect("/voice/stream") as websocket:
            # Send control message
            websocket.send_json({
                "type": "control",
                "command": "get_status",
            })
            
            # Receive response
            data = websocket.receive_json()
            
            assert data["type"] == "status"
            assert "is_running" in data
    
    def test_websocket_start_listening(self, test_client):
        """Test WebSocket start listening command."""
        with test_client.websocket_connect("/voice/stream") as websocket:
            # Send start listening command
            websocket.send_json({
                "type": "control",
                "command": "start_listening",
            })
            
            # Receive status update
            data = websocket.receive_json()
            
            assert data["type"] == "status"
            assert data["listening"] is True
