import time
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from agent.event_bus.event_bus import EventBus
from agent.controllers.matter_controller import MatterController
from agent.state_engine.state_engine import StateEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent.tools.executor import ToolExecutor
from agent.automations.automation_engine import AutomationEngine
from agent.learning.learning_engine import LearningEngine
from agent.simulation.scenarios import SimulationEngine
from agent.web.app import start_server
from agent.utils.logging_config import setup_logging
from config import settings

# Setup Logging
logger = setup_logging()

# Initialize components
logger.info("Initializing Home Agent components...")
event_bus = EventBus()
state = StateEngine(event_bus)
# Use MatterController which wraps virtual/real device
matter_controller = MatterController(use_virtual=True) 
automations = AutomationEngine(event_bus, device_controller=matter_controller, state_engine=state)
llm = LLMAgent(event_bus, state, automations)
executor = ToolExecutor(matter_controller, state, automations, event_bus)
learning = LearningEngine(event_bus, state, automations, executor, interval_minutes=settings.LEARNING_INTERVAL_MINUTES)
simulation = SimulationEngine(event_bus, matter_controller, state)

def main():
    logger.info("Home Agent started.")
    
    # Start Web Dashboard
    start_server(state, event_bus, simulation, learning)
    logger.info("Web Dashboard running at http://localhost:5000")
    
    # Simulate time tick every 5 seconds
    try:
        while True:
            event_bus.publish({
                "type": "time_tick",
                "payload": {},
                "timestamp": time.time()
            })
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Home Agent stopping...")

if __name__ == "__main__":
    main()
