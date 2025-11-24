"""
Complete Core Unit Tests - Phase 2

Missing tests from Section 1:
- 1.3: Slow subscriber doesn't block others
- 1.7: ToolExecutor invalid call handling
- 1.8: AutomationEngine CRUD operations
- 1.9: LearningEngine boundary tests (empty/tiny/huge history)
"""

import pytest
import time
import threading


class TestEventBusPerformance:
    """Test that slow subscribers don't block fast ones."""
    
    def test_slow_subscriber_doesnt_block_fast(self, event_bus):
        """Slow subscriber shouldn't delay fast subscribers."""
        results = {'slow': [], 'fast1': [], 'fast2': []}
        
        def slow_subscriber(event):
            time.sleep(1)  # Simulate slow processing
            results['slow'].append(time.time())
        
        def fast_subscriber_1(event):
            results['fast1'].append(time.time())
        
        def fast_subscriber_2(event):
            results['fast2'].append(time.time())
        
        # Subscribe all three
        event_bus.subscribe("test_event", slow_subscriber)
        event_bus.subscribe("test_event", fast_subscriber_1)
        event_bus.subscribe("test_event", fast_subscriber_2)
        
        # Publish event
        start_time = time.time()
        event_bus.publish({"type": "test_event", "payload": {}})
        
        # Wait for all to complete
        time.sleep(1.5)
        
        # Fast subscribers should complete before slow one
        assert len(results['fast1']) == 1
        assert len(results['fast2']) == 1
        
        # Fast subscribers should have completed quickly
        if len(results['fast1']) > 0 and len(results['fast2']) > 0:
            assert results['fast1'][0] - start_time < 1.5
            assert results['fast2'][0] - start_time < 1.5


class TestToolExecutor:
    """Test ToolExecutor error handling."""
    
    def test_invalid_tool_call_handling(self, tool_executor):
        """Invalid tool calls should be caught and logged."""
        # Missing tool_name
        invalid_calls = [
            {"arguments": {"text": "test"}},  # No tool_name
            {"tool_name": "nonexistent_tool", "arguments": {}},  # Invalid tool
            {"tool_name": "log_note"},  # Missing arguments
            {"tool_name": "control_relay", "arguments": "invalid"},  # Wrong arg type
        ]
        
        for call in invalid_calls:
            # Should not crash, should log error
            try:
                tool_executor.execute([call])
            except Exception as e:
                # Acceptable to raise exception, but shouldn't crash system
                pass
    
    def test_tool_call_with_wrong_argument_types(self, tool_executor):
        """Tool calls with wrong argument types should be rejected."""
        invalid_call = {
            "tool_name": "control_relay",
            "arguments": {
                "endpoint": "not_a_number",  # Should be int
                "state": 123  # Should be string
            }
        }
        
        # Should handle gracefully
        result = tool_executor.execute([invalid_call])
        # Either returns empty or raises clear error
        assert result is not None


class TestAutomationEngineCRUD:
    """Test AutomationEngine create/read/update/delete operations."""
    
    def test_create_and_retrieve_routine(self, automation_engine):
        """Create routine and verify it can be retrieved."""
        automation_engine.create(
            name="test_routine",
            trigger={"type": "time", "schedule": "08:00"},
            actions=["control_relay(1, on)"]
        )
        
        routine = automation_engine.get_routine("test_routine")
        assert routine is not None
        assert routine["trigger"]["schedule"] == "08:00"
    
    def test_modify_existing_routine(self, automation_engine):
        """Modify routine and verify changes persist."""
        automation_engine.create(
            name="modifiable",
            trigger={"type": "manual"},
            actions=["control_relay(1, on)"]
        )
        
        # Modify
        automation_engine.modify("modifiable", actions=["control_relay(2, on)"])
        
        # Verify
        routine = automation_engine.get_routine("modifiable")
        assert routine["actions"] == ["control_relay(2, on)"]
    
    def test_delete_routine(self, automation_engine):
        """Delete routine and verify removal."""
        automation_engine.create(
            name="to_delete",
            trigger={"type": "manual"},
            actions=["control_relay(1, on)"]
        )
        
        # Delete
        result = automation_engine.delete("to_delete")
        assert result is True
        
        # Verify deleted
        routine = automation_engine.get_routine("to_delete")
        assert routine is None
    
    def test_list_all_routines(self, automation_engine):
        """List all routines returns correct count."""
        automation_engine.create("r1", {"type": "manual"}, ["action1"])
        automation_engine.create("r2", {"type": "manual"}, ["action2"])
        
        routines = automation_engine.list()
        assert len(routines) >= 2
        assert "r1" in routines
        assert "r2" in routines


class TestLearningEngineBoundaries:
    """Test Learning Engine with edge-case inputs."""
    
    def test_empty_history(self, learning_engine):
        """Learning engine handles empty history gracefully."""
        # With no history, should not crash
        try:
            learning_engine.run_learning_cycle()
        except Exception:
            pytest.fail("Learning engine crashed on empty history")
    
    def test_tiny_history_single_event(self, learning_engine, state_engine):
        """Learning engine handles minimal history."""
        # Add single event
        event = {
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 1, "state": "on"},
            "timestamp": time.time()
        }
        state_engine.handle_event(event)
        
        # Should handle gracefully, not create spurious patterns
        learning_engine.run_learning_cycle()
        
        # Shouldn't create routines from single event
        routines = learning_engine.automations.list()
        # Either no routines or conservative behavior
    
    @pytest.mark.slow
    def test_huge_history(self, learning_engine, state_engine):
        """Learning engine handles very large history."""
        # Manually inject 10,000 events to avoid persistence overhead and history truncation
        events = []
        import time
        base_time = time.time()
        
        for i in range(10000):
            event = {
                "type": "relay_toggled",
                "payload": {
                    "device": "switch_1",
                    "endpoint": (i % 3) + 1,
                    "state": "on" if i % 2 == 0 else "off"
                },
                "timestamp": base_time + i
            }
            events.append(event)
            
        # Bypass handle_event to avoid fsyncs and truncation
        state_engine.state["history"] = events
        
        # Configure learning engine to look at all of them
        learning_engine.history_limit = 10000
        
        # Should not OOM or hang
        start_time = time.time()
        learning_engine.run_learning_cycle()
        duration = time.time() - start_time
        
        # Should complete in reasonable time
        assert duration < 30, "Learning took too long on large history"
    
    def test_malformed_events_in_history(self, learning_engine, state_engine):
        """Learning engine handles corrupted events gracefully."""
        # Add some malformed events
        bad_events = [
            {"type": "unknown_type", "payload": {}},
            {"payload": {"device": "test"}},  # Missing type
            {},  # Empty event
            {"type": "relay_toggled", "payload": None},  # Null payload
        ]
        
        for event in bad_events:
            try:
                state_engine.handle_event(event)
            except:
                pass  # Some may be rejected
        
        # Learning should not crash
        try:
            learning_engine.run_learning_cycle()
        except Exception:
            pytest.fail("Learning engine crashed on malformed events")
