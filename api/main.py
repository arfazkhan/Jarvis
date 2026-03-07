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
    voice, learning, auth, compatibility,
    # We will import others as we create them
)

# Import agent_home Components
# We import them here to initialize them in lifespan
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Determine Vertical Mode
import os
ARVIS_VERTICAL = os.getenv("ARVIS_VERTICAL", "RESIDENTIAL").upper()
logger = logging.getLogger("arvis_api")
logger.info(f"🌍 ARVIS MODE: {ARVIS_VERTICAL}")

# Shared Core
from arvis_core.event_bus.event_bus import EventBus

# Conditional Imports
if ARVIS_VERTICAL == "RESIDENTIAL":
    from agent_home.state_engine.state_engine import StateEngine
    from agent_home.controllers.matter_controller import MatterController
    from agent_home.automations.automation_engine import AutomationEngine
    from agent_home.tools.executor import ToolExecutor
    from agent_home.learning.learning_engine import LearningEngine
    from agent_home.llm_agent.llm_agent import LLMAgent
    from agent_unified.voice.coordinator import VoiceCoordinator
    # from agent_conversation.dialogue_manager import DialogueManager # Moved to Core?
    # from agent_mission.mission_manager import MissionManager # Moved to Core?
    from agent_unified.flows.planning import PlanningFlow

elif ARVIS_VERTICAL == "COMMERCIAL":
    from agent_commercial.bms_llm_agent import BMSLLMAgent
    from agent_unified.engines.real_bms import RealBMS # Used as adapter
    from agent_commercial.api.routes_omega import router as omega_router
    from agent_commercial.api.sim_service import SimServiceMaster
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.learning.learning_engine import BMSLearningEngine
    from agent_advisory.briefing_scheduler import BriefingScheduler
    from agent_advisory.goal_generator import GoalGenerator
    from agent_commercial.fleet_intelligence import FleetIntelligence
    # Commercial explicitly does NOT load Matter, AutomationEngine, etc.


# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis_api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ARVIS System on Startup."""
    logger.info(f"🚀 ARVIS Production API Starting in {ARVIS_VERTICAL} Mode...")
    
    # 1. Core Infrastructure (Always Needed)
    global_state.event_bus = EventBus()
    global_state.mode = ARVIS_VERTICAL

    if ARVIS_VERTICAL == "RESIDENTIAL":
        logger.info("🏠 Initializing RESIDENTIAL Stack...")
        # Residential Stack
        global_state.state_engine = StateEngine(global_state.event_bus)
        global_state.matter_controller = MatterController(use_virtual=True)
        
        global_state.automation_engine = AutomationEngine(
            global_state.event_bus,
            global_state.matter_controller,
            global_state.state_engine,
            persist_path="data/routines.json"
        )

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
        global_state.learning_engine.tool_executor = global_state.tool_executor

        global_state.llm_agent = LLMAgent(
            global_state.event_bus,
            global_state.state_engine,
            global_state.automation_engine,
            learning_engine=global_state.learning_engine,
            subscribe_to_voice=False 
        )
        global_state.learning_engine.set_llm_client(global_state.llm_agent)
        
        # global_state.mission_manager = MissionManager(global_state.event_bus)
        # global_state.dialogue_manager = DialogueManager(mission_manager=global_state.mission_manager)
        global_state.planning_flow = PlanningFlow()

        # Voice
        try:
            global_state.voice_coordinator = VoiceCoordinator()
            await global_state.voice_coordinator.start()
            logger.info("✅ Residential Voice Coordinator Active")
        except Exception as e:
                logger.warning(f"⚠️ Voice Init Failed: {e}")

    elif ARVIS_VERTICAL == "COMMERCIAL":
        logger.info("🏢 Initializing COMMERCIAL Stack...")
        
        # 1. BMS State Engine (The digital twin)
        from agent_commercial.database import BMSDatabase
        global_state.bms_state = BMSStateEngine()
        global_state.bms_state.set_database(BMSDatabase())
        app.state.bms_state = global_state.bms_state
        
        # 2. BMS Adapter
        global_state.real_bms = RealBMS(config={"bacnet": {"device_id": 9999}})
        
        # 3. Commercial Agent (Cognitive Layer)
        global_state.bms_agent = BMSLLMAgent(bms_state=global_state.bms_state)
        global_state.llm_agent = global_state.bms_agent # Alias for compatibility
        app.state.llm_agent = global_state.bms_agent
        
        # 4. Learning Engine
        global_state.learning_engine = BMSLearningEngine(llm_agent=global_state.bms_agent)
        await global_state.learning_engine.start()
        
        # 5. Simulation Service
        global_state.sim_service = SimServiceMaster()
        app.state.sim_service = global_state.sim_service
        global_state.sim_controller = global_state.sim_service.sim_controller
        app.state.sim_controller = global_state.sim_controller
        
        # 6. Briefing & Fleet Intelligence
        global_state.fleet_intel = FleetIntelligence(building_ids=["DOHA-TOWER-001"])
        global_state.goal_generator = GoalGenerator(fleet_intelligence=global_state.fleet_intel)
        global_state.briefing_engine = BriefingScheduler(goal_generator=global_state.goal_generator)
        
        logger.info("✅ Commercial BMS Stack Active (State + Agent + Sim + Briefing + Fleet)")

    logger.info("✅ System Fully Initialized.")
    yield
    
    logger.info("🛑 Shutting Down...")
    if global_state.voice_coordinator:
        await global_state.voice_coordinator.stop()
    if global_state.real_bms:
        await global_state.real_bms.disconnect()

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
# Register Routers
if ARVIS_VERTICAL == "RESIDENTIAL":
    app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
    app.include_router(automations.router, prefix="/api/v1/automations", tags=["Automations"])
    app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
    app.include_router(learning.router, prefix="/api/v1/learning", tags=["Learning"])
    app.include_router(llm.router, prefix="/api/v1/llm", tags=["Cognitive"]) # Residential LLM
    app.include_router(mission.router, prefix="/api/v1/mission", tags=["Mission"])
    app.include_router(personality.router, prefix="/api/v1/personality", tags=["Personality"])
    app.include_router(conversation.router, prefix="/api/v1/conversation", tags=["Conversation"])
    app.include_router(planning.router, prefix="/api/v1/planning", tags=["Planning"])

elif ARVIS_VERTICAL == "COMMERCIAL":
    app.include_router(bms_core.router, prefix="/api/v1/bms", tags=["BMS Core"])
    app.include_router(bms_energy.router, prefix="/api/v1/bms/energy", tags=["Energy"])
    app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["Maintenance"])
    app.include_router(advisory.router, prefix="/api/v1/advisory", tags=["Advisory"])
    app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["Knowledge"])
    app.include_router(sensors.router, prefix="/api/v1/sensors", tags=["Sensors"])
    app.include_router(learning.router, prefix="/api/v1/learning", tags=["Learning"])
    app.include_router(omega_router)

# Shared / Admin
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(infrastructure.router, prefix="/api/v1/infrastructure", tags=["Infrastructure"])
app.include_router(firmware.router, prefix="/api/v1/firmware", tags=["Firmware"])
app.include_router(core.router, prefix="/api/v1/core", tags=["Core"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(compatibility.router, prefix="/api/v1", tags=["Compatibility"])

@app.get("/")
async def root():
    return {
        "system": "ARVIS",
        "status": "online",
        "version": "1.0.0", 
        "mode": "PRODUCTION"
    }


@app.get("/health")
async def health():
    """Docker health check endpoint - lightweight ping for container orchestration."""
    return {"status": "healthy"}
