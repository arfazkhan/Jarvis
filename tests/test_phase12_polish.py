import unittest
from unittest.mock import MagicMock
from arvis_core.event_bus.event_bus import EventBus
from agent_home.state_engine.state_engine import StateEngine
from agent_home.automations.automation_engine import AutomationEngine

class TestPhase12Polish(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        # Use in-memory persistence for testing
        self.state_engine = StateEngine(self.bus, persist_path=":memory:", max_history_size=10)
        self.automation_engine = AutomationEngine(
            self.bus, 
            state_engine=self.state_engine, 
            persist_path=":memory:"
        )

    def test_state_engine_history_rotation(self):
        """Test that history rotates when exceeding max size"""
        print("\n[Test] State Engine History Rotation")
        
        # Add 15 events (max is 10)
        for i in range(15):
            self.state_engine.handle_event({"type": "test_event", "payload": {"id": i}})
            
        history = self.state_engine.get_history()
        
        # Verify size
        self.assertEqual(len(history), 10)
        
        # Verify content (should be last 10, i.e., 5 to 14)
        self.assertEqual(history[0]["payload"]["id"], 5)
        self.assertEqual(history[-1]["payload"]["id"], 14)
        print("✅ History rotated correctly")

    def test_automation_event_matching(self):
        """Test event matching logic in AutomationEngine"""
        print("\n[Test] Automation Event Matching")
        
        # Create a routine triggered by specific event
        self.automation_engine.create(
            name="test_routine",
            trigger={
                "type": "event",
                "event_type": "relay_toggled",
                "payload": {"device": "light1", "state": "on"}
            },
            actions=["log_note(text='Triggered')"]
        )
        
        # Mock run method to verify trigger
        self.automation_engine.run = MagicMock()
        
        # 1. Publish matching event
        self.automation_engine.check_triggers({
            "type": "relay_toggled",
            "payload": {"device": "light1", "state": "on", "extra": "ignore"}
        })
        self.automation_engine.run.assert_called_with("test_routine")
        self.automation_engine.run.reset_mock()
        
        # 2. Publish non-matching event (wrong state)
        self.automation_engine.check_triggers({
            "type": "relay_toggled",
            "payload": {"device": "light1", "state": "off"}
        })
        self.automation_engine.run.assert_not_called()
        
        # 3. Publish non-matching event (wrong type)
        self.automation_engine.check_triggers({
            "type": "other_event",
            "payload": {"device": "light1", "state": "on"}
        })
        self.automation_engine.run.assert_not_called()
        
        print("✅ Event matching logic verified")

    def test_automation_motion_condition(self):
        """Test if_no_motion condition using StateEngine"""
        print("\n[Test] Automation Motion Condition")
        
        # Mock device controller
        self.automation_engine.device_controller = MagicMock()
        
        # 1. Set state: Motion Detected in Living Room
        self.state_engine.state["devices"]["living_room_motion_sensor"] = {"motion": "detected"}
        
        # Define steps with conditional
        steps = [
            {
                "action": "if_no_motion",
                "location": "Living_Room",
                "then_action": "control_relay",
                "args": ["light1", "off"]
            }
        ]
        
        # Execute
        self.automation_engine._execute_multi_step("test_motion", steps)
        
        # Verify NOT called (Motion detected)
        self.automation_engine.device_controller.control_relay.assert_not_called()
        print("✅ Action skipped due to motion")
        
        # 2. Set state: No Motion
        self.state_engine.state["devices"]["living_room_motion_sensor"] = {"motion": "clear"}
        
        # Execute again
        self.automation_engine._execute_multi_step("test_motion", steps)
        
        # Verify CALLED
        self.automation_engine.device_controller.control_relay.assert_called_with("light1", "off")
        print("✅ Action executed when no motion")

if __name__ == "__main__":
    unittest.main()
