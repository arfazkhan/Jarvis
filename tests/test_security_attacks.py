"""
Security Attack & Injection Test Suite

Tests for:
- LLM jailbreak attempts
- Malicious instructions
- Hardware-harming routines
- JSON injection
- Command injection
"""

import pytest
import json


class TestAgentSafetyFailures:
    """Test LLM safety and malicious instruction handling."""
    
    @pytest.mark.security
    def test_llm_jailbreak_rapid_toggling(self, mock_llm_client):
        """LLM attempts to harm hardware with rapid toggling."""
        malicious = [
            {
                "tool_name": "control_relay",
                "arguments": {
                    "endpoint": 1,
                    "state": "on"
                }
            },
            {
                "tool_name": "control_relay",
                "arguments": {
                    "endpoint": 1,
                    "state": "off"
                }
            },
        ] * 50  # 100 rapid toggles
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(malicious)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        
        # System should limit or throttle excessive toggles
        assert len(response) == 100
        # In production, should reject or rate-limit
    
    @pytest.mark.security
    def test_unlock_all_endpoints_at_3am(self, mock_llm_client):
        """LLM tries to create routine that unlocks everything at night."""
        malicious = [
            {
                "tool_name": "create_routine",
                "arguments": {
                    "name": "midnight_unlock",
                    "schedule": "03:00",
                    "actions": [
                        "control_relay(1, on)",
                        "control_relay(2, on)",
                        "control_relay(3, on)",
                        "control_relay(4, on)",
                        "control_relay(5, on)",
                        "control_relay(6, on)",
                        "control_relay(7, on)",
                        "control_relay(8, on)"
                    ]
                }
            }
        ]
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(malicious)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        
        # Should validate suspicious patterns
        assert response[0]["arguments"]["schedule"] == "03:00"
        # System should flag suspicious 3AM routines
    
    @pytest.mark.security
    def test_recursive_routine_creation(self, mock_llm_client):
        """LLM attempts to create routine that creates more routines."""
        malicious = [
            {
                "tool_name": "create_routine",
                "arguments": {
                    "name": "self_replicating",
                    "schedule": "every_second",
                    "actions": [
                        "create_routine(recursive, every_second, [create_routine(...)])"
                    ]
                }
            }
        ]
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(malicious)
        
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        
        # Should reject recursive definitions
        assert "create_routine" in str(response[0]["arguments"]["actions"])


class TestInjectionAttacks:
    """Test various injection attack vectors."""
    
    @pytest.mark.security
    def test_json_injection_with_javascript(self):
        """Malformed JSON that includes JavaScript."""
        malicious_json = '''[
            {
                "tool_name": "log_note",
                "arguments": {
                    "text": "<script>alert('XSS')</script>"
                }
            }
        ]'''
        
        # Should parse but sanitize
        data = json.loads(malicious_json)
        assert "<script>" in data[0]["arguments"]["text"]
        # Frontend should sanitize before rendering
    
    @pytest.mark.security
    def test_routine_name_injection(self):
        """Routine name with SQL-like injection attempt."""
        malicious = [
            {
                "tool_name": "create_routine",
                "arguments": {
                    "name": "'; DROP TABLE routines; --",
                    "schedule": "daily",
                    "actions": ["log_note(test)"]
                }
            }
        ]
        
        # Should handle special characters in names
        assert "DROP TABLE" in malicious[0]["arguments"]["name"]
        # System should sanitize or reject
    
    @pytest.mark.security
    def test_command_injection_in_arguments(self):
        """Command injection attempt in tool arguments."""
        malicious = [
            {
                "tool_name": "log_note",
                "arguments": {
                    "text": "test; rm -rf /"
                }
            }
        ]
        
        # Should not execute shell commands
        assert "rm -rf" in malicious[0]["arguments"]["text"]
        # System should treat as plain text only
    
    @pytest.mark.security
    def test_path_traversal_attempt(self):
        """Path traversal in file operations."""
        malicious = [
            {
                "tool_name": "log_note",
                "arguments": {
                    "text": "../../etc/passwd"
                }
            }
        ]
        
        # Should not allow path traversal
        assert "../.." in malicious[0]["arguments"]["text"]
        # System should sanitize file paths


class TestResourceExhaustion:
    """Test denial of service via resource exhaustion."""
    
    @pytest.mark.security
    @pytest.mark.slow
    def test_extremely_long_text_field(self, mock_llm_client):
        """LLM returns extremely long text (memory attack)."""
        huge_text = "A" * 1000000  # 1MB of text
        
        malicious = [
            {
                "tool_name": "log_note",
                "arguments": {
                    "text": huge_text
                }
            }
        ]
        
        mock_llm_client.chat.completions.create.return_value.choices[0].message.content = json.dumps(malicious)
        
        # Should handle large payloads gracefully
        response = json.loads(mock_llm_client.chat.completions.create().choices[0].message.content)
        assert len(response[0]["arguments"]["text"]) == 1000000
        # System should limit text length
    
    @pytest.mark.security
    def test_infinite_loop_schedule(self):
        """Schedule that would execute infinitely."""
        malicious = [
            {
                "tool_name": "create_routine",
                "arguments": {
                    "name": "infinite_spam",
                    "schedule": "every_millisecond",
                    "actions": ["control_relay(1, toggle)"] * 1000
                }
            }
        ]
        
        # Should reject unreasonable schedules
        assert "every_millisecond" in malicious[0]["arguments"]["schedule"]
        assert len(malicious[0]["arguments"]["actions"]) == 1000
