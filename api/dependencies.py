from typing import Generator, Optional
from fastapi import Request

# Import the system state class (we might need to refactor where it lives eventually)
# For now, we will define a Global System Container here or import it.
# To avoid circular imports, we'll define a simple holder or import the one from agent.

class SystemContainer:
    """Holds the singleton instance of the ARVIS system components."""
    def __init__(self):
        self.event_bus = None
        self.state_engine = None
        self.matter_controller = None
        self.automation_engine = None
        self.tool_executor = None
        self.learning_engine = None
        self.llm_agent = None
        self.voice_coordinator = None
        self.mission_manager = None
        self.dialogue_manager = None
        self.planning_flow = None
        self.orchestrator = None

# Global Singleton
global_state = SystemContainer()

def get_system_state() -> SystemContainer:
    """Dependency to get the initialized system state."""
    # In a real app, we might raise HTTP 503 if not initialized
    if not global_state.state_engine:
        # It might be starting up
        pass
    return global_state

def get_event_bus():
    return global_state.event_bus

def get_llm_agent():
    return global_state.llm_agent
