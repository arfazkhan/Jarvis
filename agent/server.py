import os
import sys
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.event_bus.event_bus import EventBus
from agent.state_engine.state_engine import StateEngine
from agent.controllers.matter_controller import MatterController
from agent.automations.automation_engine import AutomationEngine
from agent.tools.executor import ToolExecutor
from agent.learning.learning_engine import LearningEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent.voice.transcriber import VoiceTranscriber
from agent.voice.pipeline import VoicePipeline
from agent.llm_agent.local_agent import LocalAgent
from agent.llm_agent.hybrid_orchestrator import HybridOrchestrator

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("arvis_server")

# ═══════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════
class SystemState:
    event_bus: EventBus
    state_engine: StateEngine
    matter_controller: MatterController
    automation_engine: AutomationEngine
    tool_executor: ToolExecutor
    learning_engine: LearningEngine
    llm_agent: LLMAgent
    voice_pipeline: VoicePipeline
    local_agent: Optional[LocalAgent] = None
    hybrid_orchestrator: Optional[HybridOrchestrator] = None

arvis = SystemState()

# ═══════════════════════════════════════════════════════════
# LIFECYCLE
# ═══════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ARVIS components on startup."""
    logger.info("🚀 Starting ARVIS Brain...")
    
    # 1. Core Infrastructure
    arvis.event_bus = EventBus()
    arvis.state_engine = StateEngine(arvis.event_bus)
    arvis.matter_controller = MatterController(use_virtual=True) # Switch to real later
    
    # 2. Automation & Learning
    # TODO: Real automation scheduler
    class MockAutomation:
         def list(self): return []
         def create(self, *args): pass
         def run(self, *args): return []
    arvis.automation_engine = MockAutomation() # Placeholder
    
    arvis.learning_engine = LearningEngine(
        arvis.event_bus,
        arvis.state_engine,
        arvis.automation_engine,
        tool_executor=None 
    )
    
    # 3. Execution
    arvis.tool_executor = ToolExecutor(
        arvis.matter_controller,
        arvis.state_engine,
        arvis.automation_engine,
        arvis.event_bus,
        learning_engine=arvis.learning_engine
    )
    arvis.learning_engine.tool_executor = arvis.tool_executor
    
    # 4. Voice (For server, we might NOT need local mic/speaker, 
    #    but we DO need the pipeline for processing incoming audio streams)
    #    For now, we just init the pipeline for STT/TTS logic if needed server-side
    tts_engine = os.environ.get("TTS_ENGINE", "vibevoice")
    arvis.voice_pipeline = VoicePipeline(tts_engine=tts_engine)
    # We don't call start() here because we might not want local playback
    # But for now, let's allow it for debugging
    arvis.voice_pipeline.start()

    # 5. Agents
    # Initialize LocalAgent (Qwen) - Optional for heavy servers
    # For now, load it to support Hybrid mode
    SHARED_MEMORY_DIR = "./data/memories"
    try:
        arvis.local_agent = LocalAgent(persistence_dir=SHARED_MEMORY_DIR)
        logger.info("✅ LocalAgent initialized")
    except Exception as e:
        logger.warning(f"⚠️ LocalAgent failed to load: {e}")
        arvis.local_agent = None

    arvis.llm_agent = LLMAgent(
        arvis.event_bus,
        arvis.state_engine,
        arvis.automation_engine,
        learning_engine=arvis.learning_engine,
        subscribe_to_voice=False # We handle voice via API/WS
    )
    arvis.learning_engine.set_llm_client(arvis.llm_agent)
    
    # 6. Hybrid Orchestrator
    if arvis.local_agent:
        arvis.hybrid_orchestrator = HybridOrchestrator(
            arvis.event_bus, 
            arvis.local_agent, 
            arvis.llm_agent, 
            arvis.tool_executor
        )
    
    logger.info("✅ ARVIS Brain Fully Loaded")
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down...")
    if arvis.voice_pipeline:
        arvis.voice_pipeline.shutdown()

# ═══════════════════════════════════════════════════════════
# API APP
# ═══════════════════════════════════════════════════════════
app = FastAPI(title="ARVIS Brain API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════
class CommandRequest(BaseModel):
    text: str
    source: str = "mobile_app"

class CommandResponse(BaseModel):
    status: str
    message: str
    tool_calls: List[Dict[str, Any]] = []

# ═══════════════════════════════════════════════════════════
# REST ENDPOINTS
# ═══════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return {"status": "online", "system": "ARVIS Brain v1.0"}

@app.get("/state")
async def get_state():
    """Get full system state (devices, rooms, etc)."""
    return arvis.state_engine.summary()

@app.post("/command", response_model=CommandResponse)
async def execute_command(cmd: CommandRequest):
    """Execute a text command (synchronous for now)."""
    logger.info(f"Received command: {cmd.text}")
    
    # 1. Send to Agent
    # For now, using LLM Agent directly (bypassing Hybrid for simplicity if LocalAgent missing)
    # Ideally should use HybridOrchestrator.process(cmd.text)
    
    event = {
        "type": "user_command", 
        "payload": {"text": cmd.text, "source": cmd.source}
    }
    
    response_text = ""
    start_time = asyncio.get_event_loop().time()
    
    # Streaming handler (collects full response)
    # TODO: Make this truly async/streaming
    tokens = []
    
    # We need to run the generator in a way that doesn't block FastAPI
    # Since handle_streaming is synchronous (uses requests/serial logic), 
    # we might wrap it or just accept blocking for MVP
    
    try:
        # Use LLM Agent to process
        generator = arvis.llm_agent.handle_streaming(event)
        for token in generator:
            tokens.append(token)
            
        response_text = "".join(tokens)
        
        # Check for tool calls (pending tools in pipeline? or we need to intercept them)
        # LLMAgent emits `tool_calls_generated` event, we can't easily capture it here 
        # without subscribing. 
        # For HTTP, this is tricky. WebSockets are better!
        
        return {
            "status": "success",
            "message": response_text,
            "tool_calls": [] # TODO: Capture tool calls
        }
        
    except Exception as e:
        logger.error(f"Command failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════
# WEBSOCKET MANAGER
# ═══════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)
            
manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo for now
            await websocket.send_text(f"Echo: {data}")
            
            # Here we will implement the full JSON protocol:
            # { "type": "voice_audio", "data": "base64..." }
            # { "type": "text_command", "text": "turn on lights" }
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    # Run with: python agent/server.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
