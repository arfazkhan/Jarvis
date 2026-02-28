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

from agent_commercial.api.sse_broadcaster import SSEBroadcaster

logger = logging.getLogger("arvis.api.omega")

class ConfigSetupRequest(BaseModel):
    provider: str
    model: str
    api_key: str

class ChatRequest(BaseModel):
    query: str

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
    async def event_generator():
        async for data in broadcaster.subscribe():
            if await request.is_disconnected():
                break
            yield data

    return EventSourceResponse(event_generator())

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
    
    response = await agent.chat(
        query=payload.query,
        context={"user_id": "INTERACTIVE_USER", "source": "glass_box_ui"}
    )
    
    return {
        "response": response.text if response else "Error: No response generated",
        "confidence": getattr(response, 'confidence', 0.9),
        "tool_calls": getattr(response, 'tool_calls', [])
    }
