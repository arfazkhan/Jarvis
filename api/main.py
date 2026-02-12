import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from api.dependencies import global_state
from api.routers import (
    agent, bms_core, admin, 
    mission, advisory, knowledge,
    bms_energy, maintenance, personality, sensors,
    automations, llm, firmware,
    core, conversation, planning, infrastructure,
    voice, learning,
    # We will import others as we create them
)

# Import Agent Components
# We import them here to initialize them in lifespan
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.event_bus.event_bus import EventBus
from agent.state_engine.state_engine import StateEngine
from agent.controllers.matter_controller import MatterController
from agent.automations.automation_engine import AutomationEngine
from agent.tools.executor import ToolExecutor
from agent.learning.learning_engine import LearningEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent_unified.voice.coordinator import VoiceCoordinator
from agent_conversation.dialogue_manager import DialogueManager
from agent_mission.mission_manager import MissionManager
from agent_unified.flows.planning import PlanningFlow

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis_api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ARVIS System on Startup."""
    logger.info("🚀 ARVIS Production API Starting...")
    
    # 1. Core Infrastructure
    global_state.event_bus = EventBus()
    global_state.state_engine = StateEngine(global_state.event_bus)
    global_state.matter_controller = MatterController(use_virtual=True)
    
    # 2. Automation
    global_state.automation_engine = AutomationEngine(
        global_state.event_bus,
        global_state.matter_controller,
        global_state.state_engine,
        persist_path="data/routines.json"
    )

    # 3. Learning & Execution
    global_state.learning_engine = LearningEngine(
        global_state.event_bus,
        global_state.state_engine,
        global_state.automation_engine,
        tool_executor=None
    )
    
    global_state.tool_executor = ToolExecutor(
        global_state.matter_controller,
        global_state.state_engine,
        global_state.automation_engine,
        global_state.event_bus,
        learning_engine=global_state.learning_engine
    )
    global_state.learning_engine.tool_executor = global_state.tool_executor # Circular fix

    # 4. Cognitive Layers
    global_state.llm_agent = LLMAgent(
        global_state.event_bus,
        global_state.state_engine,
        global_state.automation_engine,
        learning_engine=global_state.learning_engine,
        subscribe_to_voice=False # API handles voice
    )
    global_state.learning_engine.set_llm_client(global_state.llm_agent)
    
    global_state.mission_manager = MissionManager(global_state.event_bus)
    global_state.dialogue_manager = DialogueManager(mission_manager=global_state.mission_manager)
    global_state.planning_flow = PlanningFlow() # Unified Flow
    
    # 5. Voice
    try:
        global_state.voice_coordinator = VoiceCoordinator()
        await global_state.voice_coordinator.start()
        logger.info("✅ Voice Coordinator Active")
    except Exception as e:
         logger.warning(f"⚠️ Voice Init Failed: {e}")

    logger.info("✅ System Fully Initialized.")
    yield
    
    logger.info("🛑 Shutting Down...")
    if global_state.voice_coordinator:
        await global_state.voice_coordinator.stop()

app = FastAPI(
    title="ARVIS Production API",
    version="1.0.0",
    lifespan=lifespan,
    description="Comprehensive Neural Operating System API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
app.include_router(bms_core.router, prefix="/api/v1/bms", tags=["BMS Core"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
# Batch 2
app.include_router(mission.router, prefix="/api/v1/mission", tags=["Mission"])
app.include_router(advisory.router, prefix="/api/v1/advisory", tags=["Advisory"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["Knowledge"])
# Batch 3
app.include_router(bms_energy.router, prefix="/api/v1/bms/energy", tags=["Energy"])
app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["Maintenance"])
app.include_router(personality.router, prefix="/api/v1/personality", tags=["Personality"])
app.include_router(sensors.router, prefix="/api/v1/sensors", tags=["Sensors"])
# Batch 4
app.include_router(automations.router, prefix="/api/v1/automations", tags=["Automations"])
app.include_router(llm.router, prefix="/api/v1/llm", tags=["Cognitive"])
app.include_router(firmware.router, prefix="/api/v1/firmware", tags=["Firmware"])
# Batch 5
app.include_router(core.router, prefix="/api/v1/core", tags=["Core"])
app.include_router(conversation.router, prefix="/api/v1/conversation", tags=["Conversation"])
app.include_router(planning.router, prefix="/api/v1/planning", tags=["Planning"])
app.include_router(infrastructure.router, prefix="/api/v1/infrastructure", tags=["Infrastructure"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
app.include_router(learning.router, prefix="/api/v1/learning", tags=["Learning"])

@app.get("/")
async def root():
    return {
        "system": "ARVIS",
        "status": "online",
        "version": "1.0.0", 
        "mode": "PRODUCTION"
    }
