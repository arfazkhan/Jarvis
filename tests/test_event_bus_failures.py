"""
Event Bus Failure Scenarios Test Suite

Tests for:
- Out-of-order event delivery
- Duplicate events
- Missing events
- Event bursts (1000+/sec)
- Time-travel events
- Clock drift
"""

import pytest
import time
import threading
from conftest import (
    create_valid_event,
    create_out_of_order_events,
    create_duplicate_events,
    create_event_burst,
    create_time_travel_event
)


class TestEventOrdering:
    """Test event ordering edge cases."""
    
    def test_out_of_order_events(self, event_bus, state_engine):
        """Events arriving out of order should be handled gracefully."""
        events = create_out_of_order_events(count=10)
        
        for event in events:
            event_bus.publish(event)
        
        # State should handle these gracefully
        history = state_engine.get_history()
        assert len(history) == 10, "All events should be recorded"
    
    def test_duplicate_events(self, event_bus, state_engine):
        """Duplicate events should be detected or handled."""
        original = create_valid_event()
        duplicates = create_duplicate_events(original, count=5)
        
        for event in duplicates:
            event_bus.publish(event)
        
        history = state_engine.get_history()
        # System should handle duplicates gracefully
        assert len(history) >= 1, "At least one event should be recorded"
    
    def test_missing_events_skipped_index(self, event_bus, state_engine):
        """Missing events in sequence shouldn't break the system."""
        base_time = time.time()
        
        # Publish events 1, 2, 4, 5 (skip 3)
        for i in [1, 2, 4, 5]:
            event = create_valid_event(timestamp=base_time + i)
            event_bus.publish(event)
        
        history = state_engine.get_history()
        assert len(history) == 4, "System should work with gaps"
    
    @pytest.mark.stress
    def test_event_burst_1000_per_second(self, event_bus, state_engine):
        """System should handle burst of 1000 events."""
        events = create_event_burst(count=1000)
        
        start_time = time.time()
        for event in events:
            event_bus.publish(event)
        duration = time.time() - start_time
        
        # All events should be published within reasonable time
        assert duration < 2.0, f"Burst took too long: {duration}s"
        
        # System should remain functional
        history = state_engine.get_history(limit=1000)
        assert len(history) == 1000, "All burst events should be recorded"
    
    def test_time_travel_events(self, event_bus, state_engine):
        """Events with old timestamps should be handled."""
        old_event = create_time_travel_event()
        current_event = create_valid_event()
        
        event_bus.publish(old_event)
        event_bus.publish(current_event)
        
        history = state_engine.get_history()
        assert len(history) == 2, "Both events should be recorded"
    
    def test_clock_drift_forward(self, event_bus, state_engine):
        """Simulate system clock moving forward."""
        base_time = time.time()
        
        # Event at current time
        event1 = create_valid_event(timestamp=base_time)
        event_bus.publish(event1)
        
        # Event at "future" time (simulate clock jump forward)
        event2 = create_valid_event(timestamp=base_time + 3600)
        event_bus.publish(event2)
        
        # Event back to "normal" time
        event3 = create_valid_event(timestamp=base_time + 10)
        event_bus.publish(event3)
        
        history = state_engine.get_history()
        assert len(history) == 3, "System should handle clock drift"


class TestEventPayloadCorruption:
    """Test corrupted event payloads."""
    
    def test_missing_required_fields(self, event_bus, state_engine):
        """Events missing required fields should not crash."""
        corrupted = {
            "type": "relay_toggled",
            # Missing payload
            "timestamp": time.time()
        }
        
        # Should not crash
        try:
            event_bus.publish(corrupted)
        except Exception as e:
            pytest.fail(f"Event bus crashed on missing field: {e}")
    
    def test_wrong_field_types(self, event_bus, state_engine):
        """Events with wrong types should be handled."""
        corrupted = {
            "type": "relay_toggled",
            "payload": {
                "device": "switch_1",
                "endpoint": "abc",  # Should be int
                "state": "on"
            },
            "timestamp": time.time()
        }
        
        try:
            event_bus.publish(corrupted)
        except Exception as e:
            # It's OK to reject, just shouldn't crash system
            pass
    
    def test_null_values_in_critical_fields(self, event_bus, state_engine):
        """Null values should not crash the system."""
        corrupted = {
            "type": None,
            "payload": None,
            "timestamp": time.time()
        }
        
        try:
            event_bus.publish(corrupted)
        except Exception as e:
            # It's OK to reject, shouldn't crash
            pass
    
    def test_extra_unexpected_fields(self, event_bus, state_engine):
        """Extra fields should be ignored gracefully."""
        event_with_extras = {
            "type": "relay_toggled",
            "payload": {
                "device": "switch_1",
                "endpoint": 1,
                "state": "on",
                "unexpected_field": "surprise!"
            },
            "timestamp": time.time(),
            "another_unexpected": {"nested": "data"}
        }
        
        # Should handle gracefully
        event_bus.publish(event_with_extras)
        history = state_engine.get_history()
        assert len(history) >= 1


class TestEventBusRaceConditions:
    """Test race conditions in event bus."""
    
    @pytest.mark.stress
    def test_concurrent_publishers(self, event_bus, state_engine):
        """Multiple threads publishing simultaneously."""
        def publisher_thread(thread_id, count=100):
            for i in range(count):
                event = create_valid_event()
                event_bus.publish(event)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=publisher_thread, args=(i, 50))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have published 10 * 50 = 500 events
        history = state_engine.get_history(limit=500)
        assert len(history) == 500, "All concurrent events should be recorded"
    
    @pytest.mark.stress
    def test_concurrent_subscribers(self, event_bus):
        """Multiple subscribers listening to same events."""
        received_counts = {i: 0 for i in range(5)}
        
        def subscriber(sub_id):
            def handler(event):
                received_counts[sub_id] += 1
            return handler
        
        # Subscribe 5 handlers
        for i in range(5):
            event_bus.subscribe("test_event", subscriber(i))
        
        # Publish 100 events
        for _ in range(100):
            event_bus.publish({"type": "test_event", "payload": {}, "timestamp": time.time()})
        
        time.sleep(0.1)  # Let events propagate
        
        # All subscribers should receive all events
        for sub_id, count in received_counts.items():
            assert count == 100, f"Subscriber {sub_id} received {count} instead of 100"
    
    def test_publish_during_subscription_change(self, event_bus):
        """Publishing while subscribers are being added/removed."""
        received = []
        
        def handler(event):
            received.append(event)
        
        def modifier_thread():
            for _ in range(20):
                event_bus.subscribe("test", handler)
                time.sleep(0.01)
        
        def publisher_thread():
            for _ in range(100):
                event_bus.publish({"type": "test", "payload": {}, "timestamp": time.time()})
                time.sleep(0.001)
        
        t1 = threading.Thread(target=modifier_thread)
        t2 = threading.Thread(target=publisher_thread)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Should not crash and should deliver some events
        assert len(received) > 0, "Some events should be delivered"
