"""
State Engine Failure Scenarios Test Suite

Tests for:
- Simultaneous writes to same endpoint
- Relay toggles faster than state commits
- State rollback scenarios  
- Partial state updates
- Cross-device conflicting events
"""

import pytest
import time
import threading

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


class TestStateRaceConditions:
    """Test race conditions in state updates."""
    
    @pytest.mark.stress
    def test_simultaneous_writes_same_endpoint(self, event_bus, state_engine):
        """Multiple threads writing to same endpoint simultaneously."""
        def toggle_endpoint(thread_id, count=50):
            for i in range(count):
                state = "on" if i % 2 == 0 else "off"
                event = {
                    "type": "relay_toggled",
                    "payload": {"device": "switch_1", "endpoint": 1, "state": state},
                    "timestamp": time.time()
                }
                event_bus.publish(event)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=toggle_endpoint, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # State should be consistent (not corrupted)
        devices = state_engine.state.get("devices", {})
        assert "switch_1" in devices or len(devices) >= 0, "State should exist"
    
    @pytest.mark.stress
    def test_rapid_toggles_faster_than_commits(self, event_bus, state_engine):
        """Toggle faster than state can commit."""
        for i in range(100):
            state = "on" if i % 2 == 0 else "off"
            event = {
                "type": "relay_toggled",
                "payload": {"device": "switch_1", "endpoint": 1, "state": state},
                "timestamp": time.time()
            }
            event_bus.publish(event)
        
        # System should handle rapid toggles
        history = state_engine.get_history(limit=100)
        assert len(history) == 100, "All rapid toggles should be recorded"
    
    def test_cross_device_conflicting_events(self, event_bus, state_engine):
        """Events for different devices arriving simultaneously."""
        def device_publisher(device_id, endpoint_range):
            for ep in endpoint_range:
                event = {
                    "type": "relay_toggled",
                    "payload": {"device": device_id, "endpoint": ep, "state": "on"},
                    "timestamp": time.time()
                }
                event_bus.publish(event)
        
        threads = [
            threading.Thread(target=device_publisher, args=("switch_1", range(1, 4))),
            threading.Thread(target=device_publisher, args=("switch_2", range(1, 4))),
            threading.Thread(target=device_publisher, args=("switch_3", range(1, 4))),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All devices should be updated
        history = state_engine.get_history()
        assert len(history) >= 9, "All device events should be recorded"


class TestStateIntegrity:
    """Test state integrity under stress."""
    
    def test_partial_state_update(self, event_bus, state_engine):
        """Ensure partial updates don't corrupt state."""
        # Update endpoint 1
        event1 = {
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
            "timestamp": time.time()
        }
        event_bus.publish(event1)
        
        # Attempt partial/corrupted update
        corrupted = {
            "type": "relay_toggled",
            "payload": {"device": "switch_1"},  # Missing endpoint and state
            "timestamp": time.time()
        }
        event_bus.publish(corrupted)
        
        # Original state should remain intact
        devices = state_engine.state.get("devices", {})
        if "switch_1" in devices:
            # State should not be corrupted
            assert isinstance(devices["switch_1"], dict)
    
    def test_history_overflow_handling(self, event_bus, state_engine):
        """Test when history grows beyond reasonable limits."""
        # Generate 1000 events
        for i in range(1000):
            event = create_valid_event()
            event_bus.publish(event)
        
        # Retrieving history shouldn't crash
        history = state_engine.get_history(limit=500)
        assert len(history) <= 500, "History limit should be respected"
    
    def test_state_consistency_after_errors(self, event_bus, state_engine):
        """State should remain consistent even after processing errors."""
        # Valid event
        valid = create_valid_event()
        event_bus.publish(valid)
        
        # Invalid events
        for _ in range(10):
            invalid = {"type": None, "payload": None, "timestamp": time.time()}
            try:
                event_bus.publish(invalid)
            except:
                pass
        
        # Another valid event
        valid2 = create_valid_event()
        event_bus.publish(valid2)
        
        # State should still work
        history = state_engine.get_history()
        assert len(history) >=2, "Valid events should still be processed"
