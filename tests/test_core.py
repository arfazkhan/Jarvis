import unittest
from arvis_core.event_bus.event_bus import EventBus
from agent_home.state_engine.state_engine import StateEngine
from agent_home.controllers.virtual_device import VirtualMatterDevice

class TestCoreComponents(unittest.TestCase):
    def test_event_bus(self):
        bus = EventBus()
        received = []
        
        def callback(event):
            received.append(event)
            
        bus.subscribe("test_event", callback)
        bus.publish({"type": "test_event", "payload": "hello"})
        
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["payload"], "hello")

    def test_state_engine(self):
        bus = EventBus()
        state = StateEngine(bus)
        
        bus.publish({
            "type": "relay_toggled",
            "payload": {"device": "switch_1", "endpoint": 1, "state": "on"}
        })
        
        self.assertEqual(state.state["devices"]["switch_1"][1], "on")

    def test_virtual_device(self):
        dev = VirtualMatterDevice()
        dev.turn_on(1)
        self.assertEqual(dev.get_state()[1], "on")
        dev.turn_off(1)
        self.assertEqual(dev.get_state()[1], "off")

if __name__ == "__main__":
    unittest.main()
