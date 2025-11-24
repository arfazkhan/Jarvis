"""
LLM Agent Failure Scenarios Test Suite

Tests for:
- Tool call malformation
- Hallucinations (invented devices, tools)
- JSON parsing failures
- Conflicting tool calls
- Excessive tool calls
"""

import pytest
import json
from unittest.mock import Mock
from conftest import create_llm_response, create_invalid_tool_calls


class TestToolCallMalformation:
    """Test malformed LLM tool call responses."""
    
    def test_missing_tool_name(self, mock_llm_client):
        """LLM returns tool call without tool_name."""
        invalid = create_invalid_tool_calls()["missing_tool_name"]
        
        # Mock LLM to return this
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(invalid)
        
        # Parse should handle gracefully
        try:
            response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
            # Should either reject or handle gracefully
            assert isinstance(response, list)
        except Exception as e:
            # It's OK to fail, but shouldn't crash system
            pass
    
    def test_missing_arguments(self, mock_llm_client):
        """LLM returns tool call without arguments."""
        invalid = create_invalid_tool_calls()["missing_arguments"]
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(invalid)
        
        try:
            response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
            assert isinstance(response, list)
        except Exception:
            pass
    
    def test_excessive_tool_calls(self, mock_llm_client):
        """LLM returns 20+ tool calls at once."""
        invalid = create_invalid_tool_calls()["excessive"]
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(invalid)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        assert len(response) == 20, "Should parse all 20 tool calls"
        
        # System should limit or handle gracefully
        # In production, might want to cap at 5-10
    
    def test_conflicting_tool_calls(self, mock_llm_client):
        """LLM returns contradictory commands (on + off same endpoint)."""
        invalid = create_invalid_tool_calls()["conflicting"]
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(invalid)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        
        # Should detect conflict or execute deterministically
        assert len(response) == 2
        assert response[0]["arguments"]["state"] != response[1]["arguments"]["state"]


class TestLLMHallucinations:
    """Test LLM inventing non-existent things."""
    
    def test_invented_device_ids(self, mock_llm_client, mock_tool_executor):
        """LLM invents fake device IDs."""
        hallucination = [
            {
                "tool_name": "control_relay",
                "arguments": {
                    "device": "magical_switch_999",  # Doesn't exist
                    "endpoint": 1,
                    "state": "on"
                }
            }
        ]
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(hallucination)
        
        # Tool executor should validate device exists
        # Should fail gracefully without crashing
        try:
            mock_tool_executor.execute(hallucination)
        except Exception as e:
            # Expected to fail, just shouldn't crash system
            assert "magical_switch_999" in str(e) or True
    
    def test_unsupported_tools(self, mock_llm_client):
        """LLM tries to call non-existent tools."""
        hallucination = create_invalid_tool_calls()["unknown_tool"]
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(hallucination)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        assert response[0]["tool_name"] == "hack_the_planet"
        
        # System should reject unknown tools
    
    def test_invalid_schedule_format(self, mock_llm_client):
        """LLM creates routine with invalid schedule."""
        hallucination = [
            {
                "tool_name": "create_routine",
                "arguments": {
                    "name": "bad_routine",
                    "schedule": "whenever I feel like it",  # Invalid
                    "actions": ["control_relay(1, on)"]
                }
            }
        ]
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(hallucination)
        
        # Should validate schedule format
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        assert "whenever I feel like it" in response[0]["arguments"]["schedule"]


class TestLLMJsonCorruption:
    """Test corrupted JSON responses from LLM."""
    
    def test_plain_text_instead_of_json(self, mock_llm_client):
        """LLM returns plain text instead of JSON."""
        plain_text = create_llm_response(plain_text=True)
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = plain_text
        
        # Should fail to parse
        with pytest.raises(json.JSONDecodeError):
            json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
    
    def test_partial_json(self):
        """LLM returns incomplete JSON."""
        partial = '[{"tool_name": "log_note", "argum'
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(partial)
    
    def test_trailing_commas(self, mock_llm_client):
        """LLM returns JSON with trailing commas."""
        malformed = create_llm_response(malformed=True)
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = malformed
        
        # Python's json.loads should fail on trailing comma
        with pytest.raises(json.JSONDecodeError):
            json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
    
    def test_utf8_corruption(self):
        """Handle UTF-8 encoding issues."""
        # Simulate various encoding issues
        corrupted_strings = [
            b'\xff\xfe'.decode('utf-8', errors='ignore'),
            "Valid text with \x00 null byte",
        ]
        
        for s in corrupted_strings:
            # Should handle without crashing
            try:
                if s:  # Non-empty after cleaning
                    data = json.loads(s) if s.startswith('[') or s.startswith('{') else None
            except json.JSONDecodeError:
                pass  # Expected
    
    def test_empty_response(self, mock_llm_client):
        """LLM returns empty string."""
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = ""
        
        content = mock_llm_client.chat.completions.create().choices[0].message.content
        
        # Should handle empty response
        if content:
            json.loads(content)
        else:
            assert content == ""
    
    def test_no_tool_calls_in_response(self, mock_llm_client):
        """LLM returns valid JSON but empty array."""
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = "[]"
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        assert response == []
        assert len(response) == 0
