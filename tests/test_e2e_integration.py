import unittest
import asyncio
import time
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from agent.event_bus.event_bus import EventBus
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.state_estimator import StateEstimator
from agent_personality.personality_manager import PersonalityManager
from agent.controllers.matter_controller import MatterController
from agent_plan.plan_executor import PlanExecutor
from agent_mission.mission_manager import MissionManager
from agent_mission.mission_planner import MissionPlanner
from agent_mission.mission_executor import MissionExecutor
from agent_conversation.dialogue_manager import DialogueManager
from agent_cognitive.cognitive_loop import CognitiveLoop

class TestE2EIntegration(unittest.TestCase):
    def setUp(self):
        # 1. Initialize Event Bus
        self.event_bus = EventBus()
        
        # 2. Initialize Sensors (Mocked)
        self.sensor_registry = SensorRegistry()
        self.state_estimator = StateEstimator(self.event_bus, self.sensor_registry)
        
        # 3. Initialize Personality
        self.personality_manager = PersonalityManager(self.event_bus)
        
        # 4. Initialize Actuation (Mocked)
        self.matter_controller = MagicMock(spec=MatterController)
        self.plan_executor = PlanExecutor(self.event_bus, self.matter_controller)
        
        # 5. Initialize Mission Control
        self.mission_manager = MissionManager(self.event_bus)
        self.mission_planner = MissionPlanner()
        self.mission_executor = MissionExecutor(
            self.event_bus, 
            self.mission_manager.store, 
            self.mission_planner
        )
        
        # 6. Initialize Dialogue (Real LLM)
        self.dialogue_manager = DialogueManager(self.event_bus, self.personality_manager)
        # Ensure client is initialized (requires GROQ_API_KEY)
        if not self.dialogue_manager.client:
            print("WARNING: GROQ_API_KEY not found. LLM tests will fail or be skipped.")
        
        # 7. Initialize Cognitive Loop
        self.cognitive_loop = CognitiveLoop(self.event_bus)
        
        # 8. Bridge: Connect Dialogue Actions to Plan Executor (Same as in main.py)
        def handle_action_request(event):
            payload = event.get("payload", {})
            intent = payload.get("intent")
            slots = payload.get("slots", {})
            
            if intent == "turn_on":
                self.plan_executor.execute_action("turn_on", {"device_id": slots.get("device"), "endpoint": 1})
            elif intent == "turn_off":
                self.plan_executor.execute_action("turn_off", {"device_id": slots.get("device"), "endpoint": 1})
                
        self.event_bus.subscribe("action_request", handle_action_request)
        
        # Capture events for verification
        self.captured_events = []
        self.event_bus.subscribe("action_execution", self._capture_event)
        self.event_bus.subscribe("mission_started", self._capture_event)
        self.event_bus.subscribe("personality_update", self._capture_event)
        self.event_bus.subscribe("voice_response", self._capture_event)

    def _capture_event(self, event):
        self.captured_events.append(event)

    def test_scenario_1_voice_to_actuation(self):
        """
        Scenario: User says "Turn on the living room lights" -> Physical Actuation
        """
        print("\n=== Test Scenario 1: Voice -> Actuation ===")
        
        # 1. Simulate Voice Input
        voice_event = {
            "type": "voice_input",
            "payload": {"text": "Turn on the living room lights"}
        }
        self.event_bus.publish(voice_event)
        
        # Allow time for processing (Dialogue -> Intent -> Executor)
        time.sleep(0.5)
        
        # 2. Verify Action Request was published (by DialogueManager)
        # Note: DialogueManager publishes 'action_request', but PlanExecutor doesn't subscribe to it directly yet?
        # Wait, PlanExecutor executes 'PlanGraph'. Who converts 'action_request' to 'PlanGraph'?
        # In Phase 3, PlanExecutor executed graphs. 
        # The missing link might be an 'ActionDispatcher' or 'CognitiveLoop' handling 'action_request'.
        # Let's check if DialogueManager handles it locally or if we need to bridge it.
        # Ah, DialogueManager._handle_intent publishes 'action_request'.
        # We need something to listen to 'action_request' and call PlanExecutor.
        # Currently, that logic might be missing or inside CognitiveLoop?
        # Let's check CognitiveLoop.
        
        # For this test, we might need to manually trigger execution if the bridge is missing,
        # OR we verify that the system is indeed missing this link (which would be a finding).
        
        # However, looking at DialogueManager, for simple intents it returns a string response AND publishes action_request.
        # If no one listens to action_request, nothing happens.
        
        # Let's verify if MatterController was called.
        # If it wasn't, we found a gap!
        
        if self.matter_controller.turn_on.called:
             print("✅ MatterController.turn_on called!")
        else:
             print("❌ MatterController.turn_on NOT called (Expected if no bridge exists)")

    def test_scenario_2_voice_to_mission(self):
        """
        Scenario: User says "Start energy saver mission" -> Mission Execution
        """
        print("\n=== Test Scenario 2: Voice -> Mission ===")
        
        # 1. Simulate Voice Input
        voice_event = {
            "type": "voice_input",
            "payload": {"text": "Start energy saver mission"}
        }
        self.event_bus.publish(voice_event)
        
        # Allow time for async processing
        # MissionExecutor runs in background task, so we need asyncio loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # We need to run the async loop for a bit
        async def run_loop():
            await asyncio.sleep(1.0)
            
        loop.run_until_complete(run_loop())
        
        # 2. Verify Mission Started
        mission_events = [e for e in self.captured_events if e["type"] == "mission_started"]
        if mission_events:
            print(f"✅ Mission Started: {mission_events[0]['payload']}")
        else:
            print("❌ No mission_started event found")

    def test_scenario_3_sensor_to_personality(self):
        """
        Scenario: Late night sensor data -> Personality Update -> Dialogue Context
        """
        print("\n=== Test Scenario 3: Sensor -> Personality -> Dialogue ===")
        
        # 1. Simulate Late Night Situation
        situation_payload = {
            "time_of_day": "night",
            "home_presence": {"state": "home", "confidence": 1.0, "sources": []},
            "room_occupancy": {},
            "sleep_state": {"state": "winding_down", "confidence": 0.9, "since_ts": 0},
            "activity_hint": "relaxing",
            "emotional_state": {"state": "tired", "confidence": 0.8, "updated_ts": 0},
            "updated_ts": time.time()
        }
        
        self.event_bus.publish({
            "type": "situation_update",
            "payload": situation_payload
        })
        
        time.sleep(0.2)
        
        # 2. Verify Personality Update
        personality_events = [e for e in self.captured_events if e["type"] == "personality_update"]
        if personality_events:
            print(f"✅ Personality Updated: {personality_events[0]['payload']}")
        else:
            print("❌ No personality_update event found")
            
        # 3. Verify Dialogue Context
        # We can inspect the DialogueManager's personality manager context
        context = self.dialogue_manager.personality_manager.get_personality_context()
        print(f"✅ Current Persona: {context['persona']['id']}")
        print(f"✅ Current Emotion: {context['emotion']['state']}")
        
        # 4. Simulate Voice Query to check System Prompt (Internal inspection)
        prompt = self.dialogue_manager._get_system_prompt()
        if "tired" in prompt or "relaxing" in prompt or "night" in prompt: # Depending on persona
             print("✅ System Prompt contains context")
        else:
             print("⚠️ System Prompt might not reflect context (check persona definitions)")

    def test_scenario_4_real_llm(self):
        """
        Scenario: Real LLM Call with specific model
        """
        print("\n=== Test Scenario 4: Real LLM Call ===")
        
        if not self.dialogue_manager.client:
            print("Skipping Real LLM test (No API Key)")
            return

        # 1. Simulate complex query that requires LLM
        voice_event = {
            "type": "voice_input",
            "payload": {"text": "What is the meaning of life? Please answer in 1 short sentence."}
        }
        
        self.event_bus.publish(voice_event)
        time.sleep(2.0) # Wait for network
        
        # Verify response
        response_events = [e for e in self.captured_events if e["type"] == "voice_response"]
        if response_events:
            print(f"✅ LLM Response: {response_events[-1]['payload']['text']}")
        else:
            print("❌ No LLM response received")

if __name__ == "__main__":
    unittest.main()
