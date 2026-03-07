"""
Omega v1.1 Simulation API Router
================================

Exposes specific endpoints for the detailed Omega simulation:
- Glass Box AI Stream (SSE)
- Terminal Advisories & Safety Envelopes
- Trust Governance & Greenwashing Detection
- Simulation Control (Pause/Resume)

Usage:
    app.include_router(omega_router)
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from typing import Dict, Any, List, Optional
import asyncio
import json
import logging
import uuid
from datetime import datetime

from agent_commercial.api.sse_broadcaster import SSEBroadcaster

logger = logging.getLogger("arvis.api.omega")

class ConfigSetupRequest(BaseModel):
    provider: str
    model: str
    api_key: str

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = Field(default=None, description="Optional UUID to resume a conversation")

class EquipmentOverrideRequest(BaseModel):
    equipment_id: str
    value: Any
    intent: Optional[str] = "Manual Control"

class StressTestConfigRequest(BaseModel):
    days: int = 90
    time_scale: int = 5000
    building_id: str = "DOHA-TOWER-001"
    persona: str = "skeptical_steve"

router = APIRouter(prefix="/api/v1", tags=["Omega Simulation"])
broadcaster = SSEBroadcaster()

# ═══════════════════════════════════════════════════════════════════════════
# GLASS BOX AI STREAM (SSE)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/stream/thoughts")
async def stream_thoughts(request: Request):
    """
    Stream live AI thought process (K2 Think blocks), plans, and tool usage.
    """
    from fastapi.responses import StreamingResponse
    
    async def event_generator():
        async for data in broadcaster.subscribe():
            if await request.is_disconnected():
                break
            
            # Extract event and data from broadcaster message
            event = data.get("event", "message")
            payload = data.get("data", "{}")
            
            # Format as SSE event
            yield f"event: {event}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "X-ARVIS-KEY, Authorization, Content-Type",
            "Access-Control-Allow-Methods": "GET, OPTIONS"
        }
    )

# ═══════════════════════════════════════════════════════════════════════════
# ADVISORIES (Terminal & Integrity)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/advisories/active")
async def get_active_advisories(request: Request):
    """
    Get all active Terminal Advisories and Integrity Alerts.
    These are distinct from standard "Alarms".
    """
    # Retrieve engines from app state (injected by simulation script)
    terminal_engine = getattr(request.app.state, "terminal_engine", None)
    integrity_monitor = getattr(request.app.state, "integrity_monitor", None)
    
    response = {
        "terminal": [],
        "integrity": []
    }

    if terminal_engine:
        # Get active advisory for the main building
        adv = terminal_engine.get_active_advisory("West Bay Tower")
        if adv:
            response["terminal"].append(adv.to_dict())

    if integrity_monitor:
        alerts = integrity_monitor.get_active_alerts("West Bay Tower")
        response["integrity"] = [a.to_dict() for a in alerts]
        
    return response

# ═══════════════════════════════════════════════════════════════════════════
# TRUST & GOVERNANCE
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/governance/status")
async def get_governance_status(request: Request):
    """
    Get real-time Trust Score and Greenwashing status.
    """
    trust_gov = getattr(request.app.state, "trust_gov", None)
    
    response = {
        "trust": {"level": "UNKNOWN", "score": 0.0},
        "greenwashing": {"level": "UNKNOWN"}
    }
    
    if trust_gov:
        try:
            modifiers = trust_gov.get_modifiers("West Bay Tower")
            response["trust"] = {
                "level": modifiers.trust_level.name,
                "score": modifiers.trust_score,
                "confidence_ceiling": modifiers.confidence_ceiling,
                "throttle": modifiers.proactive_throttle
            }
        except (AttributeError, KeyError, TypeError) as e:
            logger.debug(f"Trust governance lookup fallback: {e}")
            
    return response

# ═══════════════════════════════════════════════════════════════════════════
# SIMULATION CONTROL
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/sim/control")
async def control_simulation(payload: Dict[str, Any], request: Request):
    """
    Control simulation lifecycle: START, END, NEXT_DAY, RUN_BATCH, etc.
    """
    action = payload.get("action")
    controller = getattr(request.app.state, "sim_controller", None)
    
    if not controller:
        raise HTTPException(503, "Simulation controller not connected")
        
    if action == "PAUSE":
        controller.pause()
    elif action == "RESUME":
        controller.resume()
    elif action == "SET_SPEED":
        speed = payload.get("speed", 1.0)
        controller.set_speed(speed)
    elif action == "PULSE" or action == "NEXT_DAY":
        # Supports target_day for batch runs
        target = payload.get("target_day")
        controller.pulse(target_day=target)
    elif action == "SET_MANUAL":
        controller.manual_mode = payload.get("enabled", True)
        
    return {"status": "success", "action": action, "pilot_day": getattr(controller, 'pilot_day', 0)}

# ═══════════════════════════════════════════════════════════════════════════
# OMEGA INFINITY STRESS TEST (90-DAY)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/omega/stress-test/start")
async def start_omega_stress_test(payload: StressTestConfigRequest, request: Request):
    """Launch the 90-day Omega Infinity Stress Test as a background service."""
    sim_service = getattr(request.app.state, "sim_service", None)
    if not sim_service:
        raise HTTPException(503, "Simulation service not connected to app state")
        
    result = await sim_service.start_simulation(
        days=payload.days,
        time_scale=payload.time_scale,
        building_id=payload.building_id,
        persona=payload.persona
    )
    if result["status"] == "error":
        raise HTTPException(400, result["message"])
    return result

@router.post("/omega/stress-test/stop")
async def stop_omega_stress_test(request: Request):
    """Abort the running Omega Infinity Stress Test."""
    sim_service = getattr(request.app.state, "sim_service", None)
    if not sim_service:
        raise HTTPException(503, "Simulation service not connected")
        
    result = await sim_service.stop_simulation()
    return result

@router.get("/omega/stress-test/status")
async def get_omega_status(request: Request):
    """Get the live status of the 90-day stress test."""
    sim_service = getattr(request.app.state, "sim_service", None)
    if not sim_service:
        raise HTTPException(503, "Simulation service not connected")
        
    return sim_service.get_status().dict()

@router.post("/simulation/equipment/override")
async def override_equipment(payload: EquipmentOverrideRequest, request: Request):
    """Manually override building equipment state."""
    controller = getattr(request.app.state, "sim_controller", None)
    if not controller:
        raise HTTPException(503, "Simulation controller not connected")
    
    controller.add_override(payload.equipment_id, payload.value, payload.intent)
    return {"status": "success", "equipment_id": payload.equipment_id, "value": payload.value}

@router.post("/sim/rewind")
async def rewind_simulation(request: Request):
    """Rewind the current day (RESTORE CHECKPOINT)."""
    controller = getattr(request.app.state, "sim_controller", None)
    engine = getattr(request.app.state, "bms_state", None) # Injected by create_api
    
    if not controller or not engine:
        raise HTTPException(503, "Simulation state not available")
    
    # Simple logic: Reset sim_time to 00:00 of current day
    engine.sim_time = engine.sim_time.replace(hour=0, minute=0)
    # Clear pulse event to force wait
    controller.pulse_event.clear()
    
    return {"status": "success", "message": "Simulation rewound to start of day"}

@router.post("/config/setup")
async def setup_config(payload: ConfigSetupRequest, request: Request):
    """Dynamically update LLM configuration."""
    agent = getattr(request.app.state, "llm_agent", None)
    if not agent:
        raise HTTPException(503, "LLM Agent not initialized")
    
    success = agent.update_config(
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key
    )
    
    if not success:
        raise HTTPException(400, "Failed to update LLM configuration. Check credentials.")
        
    return {"status": "success", "provider": payload.provider, "model": payload.model}

@router.post("/sim/scenario")
async def set_scenario(payload: Dict[str, str], request: Request):
    """Override simulation scenario stressors."""
    controller = getattr(request.app.state, "sim_controller", None)
    if not controller:
        raise HTTPException(503, "Simulation controller not connected")
    
    scenario_id = payload.get("scenario_id", "default")
    controller.scenario_id = scenario_id
    return {"status": "success", "scenario_id": scenario_id}

@router.post("/sim/persona")
async def set_persona(payload: Dict[str, str], request: Request):
    """Override simulation operator persona."""
    controller = getattr(request.app.state, "sim_controller", None)
    if not controller:
        raise HTTPException(503, "Simulation controller not connected")
    
    persona_name = payload.get("persona_name", "skeptical_steve")
    controller.persona_name = persona_name
    return {"status": "success", "persona_name": persona_name}

@router.post("/chat")
async def interactive_chat(payload: ChatRequest, request: Request):
    """Direct interactive chat with ReAct loop and command execution."""
    agent = getattr(request.app.state, "llm_agent", None)
    if not agent:
        raise HTTPException(503, "LLM Agent not initialized")
    
    # Session Persistence
    session_id = payload.session_id
    state = getattr(request.app.state, "bms_state", None)
    db = getattr(state, "db", None)
    
    history_ctx = []
    if db:
        if not session_id:
            session_id = str(uuid.uuid4())
            title = "Session " + session_id[:8]
            if len(payload.query) > 5:
                title = payload.query[:30] + ("..." if len(payload.query) > 30 else "")
            await db.create_chat_session(session_id, title)
        else:
            raw_hist = await db.get_chat_history(session_id, limit=20)
            for row in raw_hist:
                history_ctx.append({"role": row["role"], "content": row["content"]})
        
        # Log User Query
        await db.add_chat_message(session_id, str(uuid.uuid4()), "user", payload.query)
        
    # Inject context
    chat_context = {"user_id": "INTERACTIVE_USER", "source": "glass_box_ui"}
    if history_ctx:
        chat_context["chat_history"] = history_ctx[-10:]
    
    response = await agent.chat(
        query=payload.query,
        context=chat_context
    )
    
    if db and session_id and response:
        await db.add_chat_message(session_id, str(uuid.uuid4()), "assistant", response.text)
    
    return {
        "response": response.text if response else "Error: No response generated",
        "confidence": getattr(response, 'confidence', 0.9),
        "tool_calls": getattr(response, 'tool_calls', []),
        "session_id": session_id
    }

@router.get("/chat/sessions")
async def get_chat_sessions(request: Request, limit: int = 50):
    """Get all past chat sessions for the sidebar."""
    state = getattr(request.app.state, "bms_state", None)
    db = getattr(state, "db", None)
    if not db:
        return []
    
    try:
        return await db.get_chat_sessions(limit=limit)
    except Exception as e:
        logger.error(f"Failed to fetch chat sessions: {e}")
        raise HTTPException(500, "Database unavailable")

@router.get("/chat/sessions/{session_id}/history")
async def get_chat_session_history(session_id: str, request: Request):
    """Retrieve history array for a specific chat session."""
    state = getattr(request.app.state, "bms_state", None)
    db = getattr(state, "db", None)
    if not db:
        return []
        
    try:
        return await db.get_chat_history(session_id)
    except Exception as e:
        logger.error(f"Failed to fetch chat history: {e}")
        raise HTTPException(500, "Database unavailable")

# ═══════════════════════════════════════════════════════════════════════════
# INTERACTIVE DEMO MODE (Human-in-the-Loop)
# ═══════════════════════════════════════════════════════════════════════════

class FaultInjectionRequest(BaseModel):
    type: str = Field(..., description="EQUIPMENT_FAULT, WEATHER_EVENT, VIP_OVERRIDE, DATA_CORRUPTION")
    target: Optional[str] = Field(None, description="Equipment ID or zone name")
    parameter: Optional[str] = Field(None, description="e.g. vibration, temperature")
    value: Optional[float] = Field(None, description="Override value")
    duration_hours: int = Field(default=2, description="How long the fault persists in sim-hours")

class AdvisoryResponseRequest(BaseModel):
    action: str = Field(..., description="ACCEPT or REJECT")
    reason: str = Field(default="", description="Operator justification")

class DemoControlRequest(BaseModel):
    action: str = Field(..., description="START, STOP, PAUSE, RESUME, SET_SPEED")
    speed: Optional[int] = Field(None, description="Sim-minutes per real-second tick (1-10000)")

@router.post("/demo/control")
async def control_demo(payload: DemoControlRequest, request: Request):
    """Control the interactive demo lifecycle."""
    from agent_commercial.api.demo_orchestrator import DemoOrchestrator
    
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        # Lazy init
        bms_state = getattr(request.app.state, "bms_state", None)
        llm_agent = getattr(request.app.state, "llm_agent", None)
        demo = DemoOrchestrator(bms_state=bms_state, llm_agent=llm_agent, broadcaster=broadcaster)
        request.app.state.demo_orchestrator = demo
    
    action = payload.action.upper()
    
    if action == "START":
        if payload.speed:
            demo.set_speed(payload.speed)
        return await demo.start()
    elif action == "STOP":
        return await demo.stop()
    elif action == "PAUSE":
        await demo.pause()
        return {"status": "success", "action": "PAUSE"}
    elif action == "RESUME":
        await demo.resume()
        return {"status": "success", "action": "RESUME"}
    elif action == "SET_SPEED":
        demo.set_speed(payload.speed or 10)
        return {"status": "success", "speed": demo.sim_minutes_per_tick}
    else:
        raise HTTPException(400, f"Unknown action: {action}")

@router.get("/demo/status")
async def get_demo_status(request: Request):
    """Get current interactive demo state."""
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        return {"is_running": False, "agent_state": "IDLE", "message": "Demo not initialized"}
    return demo.get_status()

@router.post("/sim/inject")
async def inject_fault(payload: FaultInjectionRequest, request: Request):
    """Inject a manual fault or condition into the running demo."""
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo or not demo.is_running:
        raise HTTPException(503, "Demo not running. Start with POST /demo/control {action: START}")
    
    return await demo.inject_fault(payload.dict())

@router.post("/demo/advisory/{advisory_id}/respond")
async def respond_advisory(advisory_id: str, payload: AdvisoryResponseRequest, request: Request):
    """Human operator responds to a pending advisory (ACCEPT/REJECT)."""
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        raise HTTPException(503, "Demo not initialized")
    
    return await demo.respond_to_advisory(advisory_id, payload.action, payload.reason)

@router.post("/simulation/manual-control")
async def manual_control(payload: Dict[str, Any], request: Request):
    """
    Simulate a physical building action (User as Environment/FM).
    Payload: {"equipment_id": "...", "parameter": "...", "value": ...}
    """
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        raise HTTPException(503, "Demo not initialized")
    
    return await demo.manual_equipment_control(
        payload["equipment_id"], 
        payload["parameter"], 
        payload["value"]
    )

@router.get("/demo/advisories/pending")
async def get_pending_advisories(request: Request):
    """Get all advisories awaiting human response."""
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        return {"pending": [], "count": 0}
    return {"pending": demo.pending_advisories, "count": len(demo.pending_advisories)}

@router.post("/demo/initialize-building")
async def initialize_building(payload: Dict[str, Any], request: Request):
    """Bulk-initialize virtual equipment for the pilot."""
    demo = getattr(request.app.state, "demo_orchestrator", None)
    if not demo:
        # Lazy init
        from agent_commercial.api.demo_orchestrator import DemoOrchestrator
        bms_state = getattr(request.app.state, "bms_state", None)
        llm_agent = getattr(request.app.state, "llm_agent", None)
        demo = DemoOrchestrator(bms_state=bms_state, llm_agent=llm_agent, broadcaster=broadcaster)
        request.app.state.demo_orchestrator = demo
    
    return await demo.initialize_building(payload)

@router.get("/demo/equipment/details")
async def get_equipment_details(request: Request):
    """Get real-time details of all initialized equipment."""
    bms_state = getattr(request.app.state, "bms_state", None)
    if not bms_state:
        raise HTTPException(503, "BMS State not initialized")
    
    snapshot = await bms_state.get_snapshot()
    equipment = await bms_state.get_all_equipment()
    
    details = []
    current_values = snapshot.get("current_values", {})
    for eq in equipment:
        eq_data = eq.to_dict()
        eq_points = {}
        for point_id in eq.data_points:
            if point_id in current_values:
                # Remove equipment_id prefix from point name for cleaner display
                param_name = point_id.replace(f"{eq.equipment_id}_", "")
                eq_points[param_name] = current_values[point_id]
        eq_data["realtime_data"] = eq_points
        details.append(eq_data)
        
    return {"equipment": details, "total": len(details)}
