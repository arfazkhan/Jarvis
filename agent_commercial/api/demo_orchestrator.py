"""
ARVIS Interactive Demo Orchestrator
====================================

Runs the building simulation autonomously in the background with:
- Ambient thinking broadcasts (SSE) even when idle
- Automatic fault detection and advisory generation
- Human-in-the-loop pause on high-severity events
- Manual fault injection for demos

This replaces the automated OmegaTestRunner for interactive use.
"""

import asyncio
import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum

from agent_commercial.api.sse_broadcaster import SSEBroadcaster

logger = logging.getLogger("arvis.demo")


class AgentState(str, Enum):
    """Visible state of the ARVIS agent for the UI."""
    MONITORING = "MONITORING"      # Background observation, no anomalies
    ANALYZING = "ANALYZING"        # Detected something, running swarm
    INTERVENING = "INTERVENING"    # High-severity advisory, waiting for human
    PAUSED = "PAUSED"              # Simulation paused by user
    IDLE = "IDLE"                  # Not started


class DemoOrchestrator:
    """
    Interactive Demo Engine for ARVIS.
    
    Bridges the BMSStateEngine and BMSLLMAgent for real-time,
    human-in-the-loop building simulation. Runs a background loop
    that progresses simulation time, emits ambient thinking SSE events,
    and pauses when operator intervention is needed.
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        bms_state=None,
        llm_agent=None,
        broadcaster: SSEBroadcaster = None,
    ):
        if self._initialized:
            return
        
        self.bms_state = bms_state
        self.llm_agent = llm_agent
        self.broadcaster = broadcaster or SSEBroadcaster()
        
        # Simulation clock
        self.sim_time: datetime = datetime(2024, 6, 1, 6, 0, 0)  # Start: June 1st, 6 AM
        self.sim_day: int = 1
        self.tick_interval_seconds: float = 1.0  # Real seconds per tick
        self.sim_minutes_per_tick: int = 10       # Sim minutes per tick (adjustable via speed)
        
        # State machine
        self.agent_state: AgentState = AgentState.IDLE
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Start unpaused
        
        # Pending advisories waiting for human action
        self.pending_advisories: List[Dict[str, Any]] = []
        self.advisory_history: List[Dict[str, Any]] = []
        
        # Auto-escalation: if human doesn't respond within this many seconds, resume
        self.intervention_timeout_seconds: float = 120.0  # 2 minutes
        self._intervention_timer: Optional[asyncio.Task] = None
        
        # Injected faults queue
        self._injected_faults: List[Dict[str, Any]] = []
        
        # Ambient thinking counter (cycles between different observations)
        self._ambient_cycle = 0
        
        self._initialized = True
        logger.info("DemoOrchestrator initialized")
    
    # ─────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────────
    
    async def start(self) -> Dict[str, str]:
        """Start the autonomous background loop."""
        if self.is_running:
            return {"status": "error", "message": "Demo already running"}
        
        self.is_running = True
        self.agent_state = AgentState.MONITORING
        self._task = asyncio.create_task(self._run_loop())
        
        await self.broadcaster.broadcast("system", {
            "message": "ARVIS Live Pilot started. Building is now under autonomous monitoring.",
            "sim_time": self.sim_time.isoformat(),
        })
        
        logger.info("Demo loop started")
        return {"status": "success", "message": "Demo started"}

    async def initialize_building(self, config: Dict[str, Any]) -> Dict[str, str]:
        """
        Initialize the virtual building with a set of equipment.
        Format:
        {
            "building_id": "DOHA-TOWER-001",
            "equipment": [
                {"id": "AHU-01", "type": "AHU", "location": "Floor 1, Zone A"},
                {"id": "CH-01", "type": "CHILLER", "location": "Basement, Plant Room"}
            ]
        }
        """
        if not self.bms_state:
            return {"status": "error", "message": "BMS State Engine not available"}

        from agent_commercial.bms_data_model import Equipment, EquipmentType, EquipmentStatus
        
        eq_list = config.get("equipment", [])
        for eq_data in eq_list:
            # Robust EquipmentType mapping (supports name or value)
            eq_type_str = eq_data["type"].upper()
            try:
                e_type = EquipmentType[eq_type_str]
            except KeyError:
                # Fallback to value lookup
                e_type = EquipmentType(eq_data["type"].lower())

            eq = Equipment(
                equipment_id=eq_data["id"],
                name=eq_data.get("name", eq_data["id"]),
                equipment_type=e_type,
                location=eq_data.get("location", config.get("building_id", "Unknown")),
                status=EquipmentStatus.RUNNING
            )
            await self.bms_state.register_equipment(eq)
            
            # Initialize default points for this equipment type
            await self._init_default_points(eq.equipment_id, eq.equipment_type)

        # ⚠️ PRE-WARM DATABASE WITH SYNTHETIC HISTORY FOR UI
        try:
            from agent_commercial.database import get_database
            import random
            from datetime import timedelta
            db = get_database()
            if db:
                conn = await db._get_async_connection()
                today = datetime.now()
                # 1. Seed GSAS Score history
                await conn.execute("DELETE FROM gsas_scores") 
                await conn.execute(
                    "INSERT INTO gsas_scores (building_id, overall_score, certification_level, category_scores, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (config.get("building_id", "DOHA-TOWER-001"), 4.5, "Gold", json.dumps({"energy":4, "water":5, "ieq":4}), today.isoformat())
                )
                await conn.commit()

                # 2. Seed 7 days of Energy Readings
                await conn.execute("DELETE FROM energy_readings") 
                for i in range(7):
                    day_ts = today - timedelta(days=6-i)
                    is_weekend = day_ts.weekday() >= 5
                    base = 8000 if is_weekend else 11000
                    val = base + random.randint(0, 3000)
                    
                    # We will store this as a daily aggregation for simplicity of the UI query
                    await conn.execute(
                        "INSERT INTO energy_readings (meter_id, value, unit, outdoor_temp, occupancy, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        ("MAIN-METER", val, "kWh", 35.0, 0.8, day_ts.isoformat())
                    )
                await conn.commit()
                logger.info("Successfully seeded database with historic energy/GSAS data")
        except Exception as e:
            logger.error(f"Failed to seed history: {e}")

        logger.info(f"Initialized building with {len(eq_list)} equipments")
        return {"status": "success", "count": len(eq_list)}

    async def _init_default_points(self, eq_id: str, eq_type: Any):
        """Register default sensors for a new equipment."""
        from agent_commercial.bms_data_model import EquipmentType
        
        # Default starting values
        pts = []
        if eq_type == EquipmentType.AHU:
            pts = [
                ("SAT", 24.5, "°C"),   # Supply Air Temp
                ("RAT", 26.0, "°C"),   # Return Air Temp
                ("SF_SPEED", 0, "%"),  # Supply Fan Speed
                ("STATUS", 0, "BIN"),  # 0=OFF, 1=ON
            ]
        elif eq_type == EquipmentType.CHILLER:
            pts = [
                ("CHW_ST", 12.0, "°C"), # Chilled Water Supply Temp
                ("CHW_RT", 15.0, "°C"), # Chilled Water Return Temp
                ("VIBRATION", 0.8, "mm/s"),
                ("STATUS", 1, "BIN"),  # ON
                ("KW", 450.0, "kW")
            ]
        elif eq_type == EquipmentType.PUMP:
            pts = [
                ("SPD", 0.0, "%"),      # VFD Speed
                ("STATUS", 0, "BIN"),   # 0=OFF
                ("DP", 0.0, "kPa"),     # Differential Pressure
                ("DISCH_P", 350.0, "kPa"), # Discharge Pressure
                ("VIBRATION", 0.3, "mm/s"),
                ("KW", 0.0, "kW")
            ]
        elif eq_type == EquipmentType.COOLING_TOWER:
            pts = [
                ("FAN_SPD", 0.0, "%"),
                ("STATUS", 0, "BIN"),
                ("CW_RT", 32.0, "°C"),  # Condenser Water Return (From Chiller)
                ("CW_ST", 28.0, "°C"),  # Condenser Water Supply (To Chiller)
                ("WD_TEMP", 25.0, "°C"), # Wet Bulb Temp (Simulated environment)
                ("VIBRATION", 0.5, "mm/s")
            ]
        
        for suffix, val, unit in pts:
            await self.manual_equipment_control(eq_id, suffix, val)
    
    async def stop(self) -> Dict[str, str]:
        """Stop the background loop."""
        if not self.is_running:
            return {"status": "error", "message": "Demo not running"}
        
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        self.agent_state = AgentState.IDLE
        logger.info("Demo loop stopped")
        return {"status": "success", "message": "Demo stopped"}
    
    async def pause(self):
        """Pause the simulation clock."""
        self._pause_event.clear()
        self.agent_state = AgentState.PAUSED
        await self.broadcaster.broadcast("system", {"message": "Simulation paused"})
    
    async def resume(self):
        """Resume the simulation clock."""
        self._pause_event.set()
        self.agent_state = AgentState.MONITORING
        await self.broadcaster.broadcast("system", {"message": "Simulation resumed"})
    
    def set_speed(self, sim_minutes_per_tick: int):
        """Adjust simulation speed (more sim-minutes per real-second tick)."""
        self.sim_minutes_per_tick = max(1, min(sim_minutes_per_tick, 10000))
        logger.info(f"Demo speed set to {self.sim_minutes_per_tick} sim-minutes per tick")

    # ─────────────────────────────────────────────────────────────────────
    # MANUAL EQUIPMENT CONTROL (Simulating 'Physical' Actions)
    # ─────────────────────────────────────────────────────────────────────

    async def manual_equipment_control(self, equipment_id: str, parameter: str, value: Any) -> Dict[str, str]:
        """
        Simulate a user manually changing equipment state (e.g. turning off a chiller).
        In a real deployment, this happens via the BMS. Here, we update our virtual BMS.
        """
        if not self.bms_state:
            return {"status": "error", "message": "BMS State Engine not available"}

        from agent_commercial.bms_data_model import BMSDataPoint, PointType, PointQuality
        point = BMSDataPoint(
            point_id=f"{equipment_id}_{parameter}",
            equipment_id=equipment_id,
            name=f"{equipment_id} {parameter}",
            point_type=PointType.SENSOR if isinstance(value, (int, float)) else PointType.STATUS,
            value=value,
            quality=PointQuality.GOOD,
            timestamp=self.sim_time,
        )
        await self.bms_state.update_point(point)
        
        await self.broadcaster.broadcast("system", {
            "message": f"🔧 Manual Control: {equipment_id}.{parameter} set to {value}",
            "sim_time": self.sim_time.isoformat(),
        })
        
        logger.info(f"Manual Control applied: {equipment_id}.{parameter} = {value}")
        return {"status": "success", "equipment_id": equipment_id, "param": parameter, "value": value}
    
    # ─────────────────────────────────────────────────────────────────────
    # FAULT INJECTION
    # ─────────────────────────────────────────────────────────────────────
    
    async def inject_fault(self, fault: Dict[str, Any]) -> Dict[str, str]:
        """
        Queue a manual fault for the next simulation tick.
        
        fault = {
            "type": "EQUIPMENT_FAULT" | "WEATHER_EVENT" | "VIP_OVERRIDE" | "DATA_CORRUPTION",
            "target": "chiller_01",
            "parameter": "vibration",
            "value": 5.5,
            "duration_hours": 2
        }
        """
        fault["injected_at"] = self.sim_time.isoformat()
        fault["id"] = f"INJ-{int(time.time())}"
        self._injected_faults.append(fault)
        
        await self.broadcaster.broadcast("system", {
            "message": f"⚡ Fault injected: {fault['type']} on {fault.get('target', 'building')}",
            "fault": fault,
        })
        
        logger.info(f"Fault injected: {fault}")
        return {"status": "success", "fault_id": fault["id"]}
    
    # ─────────────────────────────────────────────────────────────────────
    # ADVISORY RESPONSE (Human-in-the-Loop)
    # ─────────────────────────────────────────────────────────────────────
    
    async def respond_to_advisory(self, advisory_id: str, action: str, reason: str = "") -> Dict[str, str]:
        """
        Human operator responds to a pending advisory.
        action: "ACCEPT" or "REJECT"
        """
        target = None
        for adv in self.pending_advisories:
            if adv.get("id") == advisory_id:
                target = adv
                break
        
        if not target:
            return {"status": "error", "message": f"Advisory {advisory_id} not found or already resolved"}
        
        target["human_action"] = action
        target["human_reason"] = reason
        target["resolved_at"] = self.sim_time.isoformat()
        
        # --- ADVISORY-ONLY LOGIC ---
        # If the user ACCEPTS, we simulate the 'Physical Fix' in the virtual building
        if action == "ACCEPT":
            await self._apply_automatic_fix(target)

        self.advisory_history.append(target)
        self.pending_advisories.remove(target)
        
        # Cancel auto-escalation timer
        if self._intervention_timer and not self._intervention_timer.done():
            self._intervention_timer.cancel()
            self._intervention_timer = None
        
        # If no more pending advisories, resume monitoring
        if not self.pending_advisories:
            self.agent_state = AgentState.MONITORING
            self._pause_event.set()
        
        await self.broadcaster.broadcast("swarm_event", {
            "type": "human_response",
            "advisory_id": advisory_id,
            "action": action,
            "reason": reason,
        })
        
        logger.info(f"Advisory {advisory_id} resolved: {action}")
        return {"status": "success", "action": action}
    
    # ─────────────────────────────────────────────────────────────────────
    # MAIN LOOP
    # ─────────────────────────────────────────────────────────────────────
    
    async def _run_loop(self):
        """
        The core autonomous loop. Runs indefinitely:
        1. Progress simulation time
        2. Apply any injected faults
        3. Ambient monitoring (background thinking)
        4. At key hours, run a full swarm cognitive cycle
        5. If high-severity advisory found, pause and wait for human
        """
        KEY_HOURS = {7, 10, 13, 15, 18}  # Hours when swarm does deep analysis
        
        try:
            while self.is_running:
                # Wait if paused
                await self._pause_event.wait()
                
                # 1. Advance simulation clock
                self.sim_time += timedelta(minutes=self.sim_minutes_per_tick)
                current_hour = self.sim_time.hour
                
                # Day boundary
                if self.sim_time.hour == 0 and self.sim_time.minute < self.sim_minutes_per_tick:
                    self.sim_day += 1
                    await self.broadcaster.broadcast("system", {
                        "message": f"☀️ Day {self.sim_day} begins",
                        "sim_time": self.sim_time.isoformat(),
                    })
                
                # 2. Apply injected faults
                await self._apply_injected_faults()
                
                # 3. Simulate Building Physics (Drift, Load, Jitter)
                await self._simulate_physics()
                
                # 4. Emit ambient thinking (every tick)
                await self._emit_ambient_thought()
                
                # 5. At key hours, run deep cognitive cycle
                if current_hour in KEY_HOURS and self.sim_time.minute < self.sim_minutes_per_tick:
                    await self._run_cognitive_cycle()
                
                # 6. Broadcast telemetry snapshot
                await self._broadcast_telemetry()
                
                # Sleep for the real-time tick interval
                await asyncio.sleep(self.tick_interval_seconds)
                
        except asyncio.CancelledError:
            logger.info("Demo loop cancelled")
        except Exception as e:
            logger.error(f"Demo loop error: {e}", exc_info=True)
            self.agent_state = AgentState.IDLE
            self.is_running = False
    
    async def _apply_injected_faults(self):
        """Apply any queued faults to the BMS state engine."""
        if not self._injected_faults or not self.bms_state:
            return
        
        faults_to_remove = []
        for fault in self._injected_faults:
            fault_type = fault.get("type", "")
            
            if fault_type == "EQUIPMENT_FAULT":
                # Update equipment point in state engine
                target = fault.get("target", "")
                param = fault.get("parameter", "vibration")
                value = fault.get("value", 0)
                
                from agent_commercial.bms_data_model import BMSDataPoint, PointType, PointQuality
                point = BMSDataPoint(
                    point_id=f"{target}_{param}",
                    equipment_id=target,
                    name=f"{target} {param}",
                    point_type=PointType.ANALOG_INPUT,
                    value=value,
                    unit="mm/s" if param == "vibration" else "°C",
                    quality=PointQuality.GOOD,
                    timestamp=self.sim_time,
                )
                await self.bms_state.update_point(point)
                logger.info(f"Applied fault: {target}.{param} = {value}")
                
            elif fault_type == "VIP_OVERRIDE":
                # Broadcast VIP event for swarm to detect
                await self.broadcaster.broadcast("thought", {
                    "content": f"[VIP_OVERRIDE_DETECTED] Executive override request for {fault.get('target', 'Zone A')}. "
                               f"Current comfort settings may need adjustment.",
                    "timestamp": self.sim_time.isoformat(),
                })
            
            elif fault_type == "WEATHER_EVENT":
                await self.broadcaster.broadcast("thought", {
                    "content": f"⚠️ Weather alert: Outdoor temperature surging to {fault.get('value', 52)}°C. "
                               f"Heatwave conditions active.",
                    "timestamp": self.sim_time.isoformat(),
                })
            
            # Check if fault has expired
            duration_hours = fault.get("duration_hours", 1)
            injected_at = datetime.fromisoformat(fault["injected_at"])
            if self.sim_time >= injected_at + timedelta(hours=duration_hours):
                faults_to_remove.append(fault)
        
        for f in faults_to_remove:
            self._injected_faults.remove(f)
    
    async def _auto_escalate(self):
        """Auto-resume monitoring if human doesn't respond within timeout."""
        try:
            await asyncio.sleep(self.intervention_timeout_seconds)
            
            # Timeout reached — escalate and resume
            if self.agent_state == AgentState.INTERVENING and self.pending_advisories:
                logger.warning(f"Auto-escalation: {len(self.pending_advisories)} advisories timed out after {self.intervention_timeout_seconds}s")
                
                for adv in self.pending_advisories:
                    adv["human_action"] = "ESCALATED_TIMEOUT"
                    adv["human_reason"] = f"No operator response within {int(self.intervention_timeout_seconds)}s"
                    adv["resolved_at"] = self.sim_time.isoformat()
                    self.advisory_history.append(adv)
                
                self.pending_advisories.clear()
                self.agent_state = AgentState.MONITORING
                self._pause_event.set()
                
                await self.broadcaster.broadcast("swarm_event", {
                    "type": "auto_escalated",
                    "message": f"⏰ No operator response. Advisory auto-escalated and logged. Monitoring resumed.",
                })
        except asyncio.CancelledError:
            pass  # Timer cancelled because human responded in time

    async def _simulate_physics(self):
        """
        Produce realistic sensor behavior for virtual equipment.
        - Temperature drift (Heat gain/loss)
        - Vibration jitter
        - Energy load scaling
        """
        if not self.bms_state:
            return

        snapshot = await self.bms_state.get_snapshot()
        current_hour = self.sim_time.hour
        
        # Simple cyclic outdoor temp (35°C at night, 48°C at peak day)
        import math
        outdoor_temp = 41.5 + 6.5 * math.sin((current_hour - 8/24) * 2 * math.pi)
        await self.manual_equipment_control("BUILDING", "OUTDOOR_TEMP", round(outdoor_temp, 2))

        from agent_commercial.bms_data_model import EquipmentType
        import random

        equipment = await self.bms_state.get_all_equipment()
        for eq in equipment:
            eq_pts = await self.bms_state.get_current_values(eq.data_points)
            status = eq_pts.get(f"{eq.equipment_id}_STATUS", 1)
            
            if eq.equipment_type == EquipmentType.AHU:
                # 🌡️ Temperature Simulation
                current_sat = eq_pts.get(f"{eq.equipment_id}_SAT", 24.0)
                if status == 1:
                    # Cooling ON -> Pull temp down towards 19°C
                    new_sat = current_sat - (current_sat - 19.0) * 0.1
                else:
                    # Cooling OFF -> Temp drifts up towards outdoor temp
                    new_sat = current_sat + (outdoor_temp - current_sat) * 0.05
                
                # Add jitter (±0.1°C)
                new_sat += random.uniform(-0.1, 0.1)
                await self.manual_equipment_control(eq.equipment_id, "SAT", round(new_sat, 2))

            elif eq.equipment_type == EquipmentType.CHILLER:
                # 🚜 Vibration & Energy Simulation
                current_vib = eq_pts.get(f"{eq.equipment_id}_VIBRATION", 0.8)
                if status == 1:
                    # Normal jitter around baseline
                    # Unless a fault was injected (higher value)
                    if current_vib < 2.0:
                        new_vib = 0.82 + random.uniform(-0.05, 0.05)
                    else:
                        # Fault active, keep it high plus jitter
                        new_vib = current_vib + random.uniform(-0.1, 0.1)
                    
                    # Energy scales with outdoor temp load
                    load_factor = (outdoor_temp - 25) / 20.0
                    new_kw = 400.0 * load_factor + random.uniform(-5, 5)
                    await self.manual_equipment_control(eq.equipment_id, "KW", round(new_kw, 1))
                else:
                    new_vib = 0.05 + random.uniform(0, 0.02)
                    await self.manual_equipment_control(eq.equipment_id, "KW", 5.0) # Baseload
                
                await self.manual_equipment_control(eq.equipment_id, "VIBRATION", round(new_vib, 2))

            elif eq.equipment_type == EquipmentType.PUMP:
                # 💦 Pump Physics
                current_spd = eq_pts.get(f"{eq.equipment_id}_SPD", 0.0)
                if status == 1:
                    # Power consumption following pump affinity laws (kW proportional to speed^3)
                    speed_ratio = current_spd / 100.0
                    new_kw = 45.0 * (speed_ratio ** 3) + random.uniform(-0.5, 0.5)
                    # DP proportional to speed^2
                    new_dp = 250.0 * (speed_ratio ** 2) + random.uniform(-2, 2)
                    new_vib = 0.3 + (speed_ratio * 0.4) + random.uniform(-0.02, 0.02)
                    
                    await self.manual_equipment_control(eq.equipment_id, "KW", round(max(1.0, new_kw), 1))
                    await self.manual_equipment_control(eq.equipment_id, "DP", round(max(0.0, new_dp), 1))
                else:
                    new_vib = 0.02 + random.uniform(0, 0.01)
                    await self.manual_equipment_control(eq.equipment_id, "KW", 0.0)
                    await self.manual_equipment_control(eq.equipment_id, "DP", 0.0)
                
                await self.manual_equipment_control(eq.equipment_id, "VIBRATION", round(new_vib, 2))

            elif eq.equipment_type == EquipmentType.COOLING_TOWER:
                # ❄️ Cooling Tower Physics
                fan_spd = eq_pts.get(f"{eq.equipment_id}_FAN_SPD", 0.0)
                wet_bulb = eq_pts.get(f"{eq.equipment_id}_WD_TEMP", 25.0)
                cw_rt = eq_pts.get(f"{eq.equipment_id}_CW_RT", 32.0) # Conditioned by chiller load elsewhere
                
                if status == 1:
                    # Fans ON -> Pull CW_ST towards Wet Bulb + Approach
                    # Effectiveness increases with fan speed
                    approach = 7.0 - (fan_spd / 100.0 * 4.0) 
                    target_st = wet_bulb + approach
                    current_st = eq_pts.get(f"{eq.equipment_id}_CW_ST", 28.0)
                    
                    # Thermal inertia
                    new_st = current_st - (current_st - target_st) * 0.1 + random.uniform(-0.05, 0.05)
                    new_vib = 0.5 + (fan_spd / 100.0 * 1.2) + random.uniform(-0.05, 0.05)
                    
                    await self.manual_equipment_control(eq.equipment_id, "CW_ST", round(new_st, 2))
                else:
                    # Fans OFF -> Supply temp drifts up to return temp
                    current_st = eq_pts.get(f"{eq.equipment_id}_CW_ST", 28.0)
                    new_st = current_st + (cw_rt - current_st) * 0.02 + random.uniform(-0.02, 0.02)
                    new_vib = 0.05 + random.uniform(0, 0.02)
                    await self.manual_equipment_control(eq.equipment_id, "CW_ST", round(new_st, 2))

                await self.manual_equipment_control(eq.equipment_id, "VIBRATION", round(new_vib, 2))

    async def _emit_ambient_thought(self):
        """Emit background monitoring thoughts to show the building is 'thinking'."""
        self._ambient_cycle += 1
        
        # Only emit every few ticks to avoid flooding
        if self._ambient_cycle % 3 != 0:
            return
        
        # Rotate through different types of ambient observations
        observations = [
            f"Monitoring energy baseline. Current hour: {self.sim_time.strftime('%H:%M')}. All systems nominal.",
            f"Scanning occupancy patterns across zones. Day {self.sim_day} profile loading.",
            f"Checking chiller efficiency curves against outdoor conditions.",
            f"Reviewing alarm correlation matrix for cascade risk.",
            f"Ambient comfort check: Zone temperatures within GSAS IEQ thresholds.",
            f"Running predictive maintenance scan on high-runtime equipment.",
        ]
        
        obs_index = (self._ambient_cycle // 3) % len(observations)
        
        await self.broadcaster.broadcast("thought", {
            "content": observations[obs_index],
            "agent_state": self.agent_state.value,
            "sim_time": self.sim_time.isoformat(),
            "sim_day": self.sim_day,
        })
    
    async def _run_cognitive_cycle(self):
        """Run a full swarm cognitive cycle at a key hour."""
        if not self.llm_agent:
            return
        
        self.agent_state = AgentState.ANALYZING
        
        await self.broadcaster.broadcast("swarm_event", {
            "type": "cycle_start",
            "message": f"🧠 Running cognitive analysis for {self.sim_time.strftime('%H:%M')} (Day {self.sim_day})",
            "sim_time": self.sim_time.isoformat(),
        })
        
        try:
            # Build context from current state
            snapshot = {}
            if self.bms_state:
                snapshot = await self.bms_state.get_snapshot()
            
            context = {
                "sim_day": self.sim_day,
                "sim_time": self.sim_time.isoformat(),
                "outdoor_temp": snapshot.get("current_values", {}).get("outdoor_temp", 42.0),
                "source": "demo_orchestrator",
            }
            
            # Run the swarm
            response = await self.llm_agent.chat(
                query="Analyze current building conditions and provide advisories if needed.",
                context=context,
            )
            
            advice_text = response.text if hasattr(response, 'text') else str(response)
            confidence = getattr(response, 'confidence', 0.5)
            
            # Try to parse structured advisories
            advisories = self._parse_advisories(advice_text, confidence)
            
            if advisories:
                # Check severity — if high/critical, pause for human
                high_severity = any(
                    a.get("severity") in ("high", "critical", "terminal")
                    for a in advisories
                )
                
                for adv in advisories:
                    adv["day"] = self.sim_day
                    adv["generated_at"] = self.sim_time.isoformat()
                
                await self.broadcaster.broadcast("swarm_event", {
                    "type": "advisories_generated",
                    "count": len(advisories),
                    "advisories": advisories,
                    "confidence": confidence,
                })
                
                if high_severity:
                    # Pause and wait for human
                    self.pending_advisories.extend(advisories)
                    self.agent_state = AgentState.INTERVENING
                    self._pause_event.clear()
                    
                    await self.broadcaster.broadcast("swarm_event", {
                        "type": "human_intervention_required",
                        "message": f"⚠️ High-severity advisory detected. Awaiting operator response (auto-resumes in {int(self.intervention_timeout_seconds)}s).",
                        "advisories": advisories,
                        "timeout_seconds": self.intervention_timeout_seconds,
                    })
                    logger.info(f"Human intervention required: {len(advisories)} high-severity advisories")
                    
                    # Start auto-escalation timer
                    self._intervention_timer = asyncio.create_task(
                        self._auto_escalate()
                    )
                else:
                    # Low severity — log and continue monitoring
                    self.advisory_history.extend(advisories)
                    self.agent_state = AgentState.MONITORING
            else:
                # No advisories generated — stable conditions
                self.agent_state = AgentState.MONITORING
                await self.broadcaster.broadcast("swarm_event", {
                    "type": "cycle_complete",
                    "message": "Analysis complete. No action required.",
                })
            
        except Exception as e:
            logger.error(f"Cognitive cycle error: {e}", exc_info=True)
            self.agent_state = AgentState.MONITORING
            await self.broadcaster.broadcast("swarm_event", {
                "type": "cycle_error",
                "message": f"Cognitive cycle encountered an error: {str(e)}",
            })
    
    def _parse_advisories(self, raw_text: str, confidence: float) -> List[Dict[str, Any]]:
        """Parse structured advisories from swarm response."""
        advisories = []
        
        try:
            start = raw_text.find('{')
            end = raw_text.rfind('}') + 1
            if start >= 0 and end > start:
                data = json.loads(raw_text[start:end])
                if isinstance(data, dict) and "advisories" in data:
                    return data["advisories"]
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Fallback: wrap narrative in a simple advisory
        if raw_text and len(raw_text.strip()) > 20:
            advisories.append({
                "id": f"DEMO-{self.sim_day}-{int(time.time())}",
                "type": "observation",
                "severity": "low",
                "message": raw_text[:500],
                "confidence": confidence,
            })
        
        return advisories
    
    async def _broadcast_telemetry(self):
        """Broadcast a lightweight telemetry snapshot for the UI dashboard."""
        snapshot = {}
        if self.bms_state:
            try:
                snapshot = await self.bms_state.get_snapshot()
            except Exception:
                pass
        
        await self.broadcaster.broadcast("telemetry", {
            "sim_time": self.sim_time.isoformat(),
            "sim_day": self.sim_day,
            "agent_state": self.agent_state.value,
            "equipment_count": snapshot.get("equipment_count", 0),
            "active_alarms": snapshot.get("active_alarm_count", 0),
            "pending_advisories": len(self.pending_advisories),
        })
    
    # ─────────────────────────────────────────────────────────────────────
    # STATUS
    # ─────────────────────────────────────────────────────────────────────
    
    def get_status(self) -> Dict[str, Any]:
        """Get current demo state for API responses."""
        return {
            "is_running": self.is_running,
            "agent_state": self.agent_state.value,
            "sim_time": self.sim_time.isoformat(),
            "sim_day": self.sim_day,
            "speed": self.sim_minutes_per_tick,
            "pending_advisories": len(self.pending_advisories),
            "total_advisories": len(self.advisory_history),
            "active_faults": len(self._injected_faults),
            "architecture": "ADVISORY-ONLY",
        }

    async def _apply_automatic_fix(self, advisory: Dict[str, Any]):
        """
        Simulate the physical action taken by the FM after accepting an advisory.
        In production, ARVIS does not do this. 
        In the Interactive Pilot, we must update the Virtual Building state.
        """
        if not self.bms_state: return

        # Simple logic: reset common fault points
        msg = advisory.get("message", "").lower()
        
        # Example: 'Chiller 01 vibration' -> reset vibration to 1.0
        if "vibration" in msg:
            await self.manual_equipment_control("chiller_01", "vibration", 1.2)
        elif "energy" in msg or "scheduling" in msg:
            # Simulate energy savings by reducing simulated load
            await self.broadcaster.broadcast("system", {"message": "✅ Physical Action: Building schedule optimized by FM."})
        elif "sensor" in msg:
             await self.broadcaster.broadcast("system", {"message": "✅ Physical Action: Sensor recalibrated by FM."})
