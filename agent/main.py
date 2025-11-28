import time
import os
import asyncio
import threading
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from agent.utils.logging_config import setup_logging
from agent.event_bus.event_bus import EventBus

# Phase 0: Foundation (Legacy & Core)
from agent.state_engine.state_engine import StateEngine
from agent.controllers.matter_controller import MatterController
from agent.automations.automation_engine import AutomationEngine
from agent.tools.executor import ToolExecutor
from agent.learning.learning_engine import LearningEngine
from agent.simulation.scenarios import SimulationEngine

# Phase 4: Sensors (Modern)
from agent_sensors.sensor_registry import SensorRegistry
from agent_sensors.state_estimator import StateEstimator

# Phase 5: Personality
from agent_personality.personality_manager import PersonalityManager

# Phase 3: Execution
from agent_plan.plan_executor import PlanExecutor

# Phase 6: Mission
from agent_mission.mission_manager import MissionManager
from agent_mission.mission_planner import MissionPlanner
from agent_mission.mission_executor import MissionExecutor

# Phase 2: Dialogue
from agent_conversation.dialogue_manager import DialogueManager

# Phase 1: Cognitive
from agent_cognitive.cognitive_loop import CognitiveLoop

# Web UI
from agent.web.app import start_server

# Setup Logging
logger = setup_logging()

def main():
    logger.info("=== ARVIS System Starting ===")
    
    # 1. Event Bus (The Spine)
    event_bus = EventBus()
    logger.info("✅ EventBus initialized")
    
    # 1.5 Arbitration Manager (The Judge)
    from agent.agent_core.arbitration_manager import ArbitrationManager
    arbitration_manager = ArbitrationManager()
    logger.info("✅ Arbitration Manager initialized")

    # 2. Controllers & State (The Body)
    # Use virtual=False for real devices if configured, else True
    use_virtual = os.getenv("USE_VIRTUAL_DEVICES", "true").lower() == "true"
    matter_controller = MatterController(use_virtual=use_virtual, arbitration_manager=arbitration_manager)
    
    # Legacy State Engine (for Web UI & Device History)
    state_engine = StateEngine(event_bus)
    
    # Modern Sensor Fusion (for Context Awareness)
    sensor_registry = SensorRegistry()
    state_estimator = StateEstimator(event_bus, sensor_registry)
    logger.info("✅ State & Sensors initialized")
    
    # 3. Automations & Tools (The Reflexes)
    automation_engine = AutomationEngine(event_bus, matter_controller, state_engine)
    tool_executor = ToolExecutor(matter_controller, state_engine, automation_engine, event_bus)
    logger.info("✅ Automations initialized")
    
    # 4. Learning & Simulation (The Subconscious)
    learning_engine = LearningEngine(event_bus, state_engine, automation_engine, tool_executor)
    simulation_engine = SimulationEngine(event_bus, matter_controller, state_engine)
    logger.info("✅ Learning & Simulation initialized")
    
    # 5. Personality Engine (The Soul)
    personality_manager = PersonalityManager(event_bus)
    logger.info("✅ Personality Engine initialized")
    
    # 6. Plan Execution (The Hands)
    plan_executor = PlanExecutor(event_bus, matter_controller)
    
    # Bridge: Connect Dialogue Actions to Plan Executor
    def handle_action_request(event):
        payload = event.get("payload", {})
        intent = payload.get("intent")
        slots = payload.get("slots", {})
        
        # Map intents to actions
        if intent == "turn_on":
            plan_executor.execute_action("turn_on", {"device_id": slots.get("device"), "endpoint": 1})
        elif intent == "turn_off":
            plan_executor.execute_action("turn_off", {"device_id": slots.get("device"), "endpoint": 1})
            
    event_bus.subscribe("action_request", handle_action_request)
    
    logger.info(f"✅ Plan Executor initialized (Virtual: {use_virtual})")
    
    # 7. Mission Control (The Strategy)
    mission_manager = MissionManager(event_bus)
    mission_planner = MissionPlanner()
    mission_executor = MissionExecutor(
        event_bus=event_bus, 
        store=mission_manager.store, 
        planner=mission_planner
    )
    logger.info("✅ Mission Control initialized")
    
    # 8. Dialogue System (The Voice)
    # 8. Dialogue System (The Voice)
    dialogue_manager = DialogueManager(personality_manager) # Removed event_bus arg
    from agent_conversation.interaction_loop import InteractionLoop
    interaction_loop = InteractionLoop(event_bus, dialogue_manager)
    logger.info("✅ Dialogue System & Interaction Loop initialized")
    
    # 9. Unified Cognitive Loop (The Meta-Agent)
    from agent.agent_cognitive.meta_agent import MetaAgent
    # We pass safety_validator=None for now as it's not yet fully decoupled, 
    # but MetaAgent is designed to accept it.
    meta_agent = MetaAgent(event_bus, state_engine, mission_manager, safety_validator=None)
    meta_agent.start()
    logger.info("✅ MetaAgent (Unified Cognitive Loop) started")
    
    # 10. Web Dashboard
    try:
        # Pass legacy components as expected by Web UI
        t_web = threading.Thread(
            target=start_server, 
            args=(state_engine, event_bus, simulation_engine, learning_engine),
            daemon=True
        )
        t_web.start()
        logger.info("✅ Web Dashboard running at http://localhost:5000")
    except Exception as e:
        logger.warning(f"⚠️ Web Dashboard failed to start: {e}")

    logger.info("🚀 ARVIS is ONLINE and READY.")
    
    # Main Loop
    try:
        while True:
            # Heartbeat / Time Tick
            event_bus.publish({
                "type": "time_tick",
                "payload": {},
                "timestamp": time.time()
            })
            time.sleep(1.0)
            
    except KeyboardInterrupt:
        logger.info("🛑 ARVIS stopping...")
        meta_agent.stop()

if __name__ == "__main__":
    main()
