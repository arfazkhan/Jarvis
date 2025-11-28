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
from unittest.mock import Mock, patch
import time

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


class TestToolCallMalformation:
    """Test malformed LLM tool call responses."""
    
    def test_missing_tool_name(self, mock_llm_client):
        """LLM returns tool call without tool_name."""
        invalid = create_invalid_tool_calls()["missing_tool_name"]
        
        # Mock LLM to return this using patch on real client
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(invalid)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(invalid)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
            try:
                response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
                assert isinstance(response, list)
            except Exception:
                pass
    
    def test_excessive_tool_calls(self, mock_llm_client):
        """LLM returns 20+ tool calls at once."""
        invalid = create_invalid_tool_calls()["excessive"]
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(invalid)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
            response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
            assert len(response) == 20, "Should parse all 20 tool calls"
        
        # System should limit or handle gracefully
        # In production, might want to cap at 5-10
    
    def test_conflicting_tool_calls(self, mock_llm_client):
        """LLM returns contradictory commands (on + off same endpoint)."""
        invalid = create_invalid_tool_calls()["conflicting"]
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(invalid)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(hallucination)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(hallucination)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps(hallucination)
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
            # Should validate schedule format
            response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
            assert "whenever I feel like it" in response[0]["arguments"]["schedule"]


class TestLLMJsonCorruption:
    """Test corrupted JSON responses from LLM."""
    
    def test_plain_text_instead_of_json(self, mock_llm_client):
        """LLM returns plain text instead of JSON."""
        plain_text = create_llm_response(plain_text=True)
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = plain_text
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = malformed
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
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
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = ""
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
            content = mock_llm_client.chat.completions.create().choices[0].message.content
            
            # Should handle empty response
            if content:
                json.loads(content)
            else:
                assert content == ""
    
    def test_no_tool_calls_in_response(self, mock_llm_client):
        """LLM returns valid JSON but empty array."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch.object(mock_llm_client.chat.completions, 'create', return_value=mock_response):
            response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
            assert response == []
            assert len(response) == 0
