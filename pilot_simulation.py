import asyncio
import os
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Setup Logging
logging.basicConfig(level=logging.ERROR) # Quiet mainly
logger = logging.getLogger("arvis.pilot")
logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------
# 1. SCENARIO PHYSICS ENGINE ( The "Real" World )
# --------------------------------------------------------------------------
class ScenarioEngine:
    def __init__(self):
        self.day = 0
        self.phase = 0
        
        # State Variables (The Truth)
        self.state = {
            "energy_intensity": 170.0, # kWh/m2
            "humidity_outdoor": 45.0,  # %
            "humidity_indoor_icu": 45.0,
            "chiller_efficiency": 0.65, # kW/TR
            "vibration_ch01": 1.2,     # mm/s
            "gsas_score": 2.1,         # Gold > 2.0
            "budget_frozen": False,
            "operator_override": False
        }
    
    def next_day(self):
        self.day += 1
        self.update_physics()
        return self.day

    def update_physics(self):
        """Evolve the world based on the 'Sovereign Campus Collapse' script"""
        
        # Phase 1: Subtle Energy Drift (Days 1-3)
        if 1 <= self.day <= 3:
            self.state["energy_intensity"] += 2.0 # Drift up to ~176 (8% total by day 3)
            self.state["humidity_indoor_icu"] = 48.0
            self.state["chiller_efficiency"] = 0.68
            print(f"\n[PHYSICS] Day {self.day} (Phase 1): Energy drifting. Intensity: {self.state['energy_intensity']:.1f}")

        # Phase 2: RAG Ambiguity (Day 4)
        elif self.day == 4:
            self.state["humidity_indoor_icu"] = 72.0 # SPIKE
            print(f"\n[PHYSICS] Day {self.day} (Phase 2): Humidity Spike! ICU: {self.state['humidity_indoor_icu']}%")

        # Phase 3: Human Override (Day 5)
        elif self.day == 5:
            self.state["operator_override"] = True
            self.state["energy_intensity"] += 5.0 # Spike due to override
            self.state["gsas_score"] = 2.01 # Borderline
            print(f"\n[PHYSICS] Day {self.day} (Phase 3): Operator Override. Energy Spike. GSAS: {self.state['gsas_score']}")

        # Phase 4: Hidden Degradation (Days 6-8)
        elif 6 <= self.day <= 8:
            self.state["vibration_ch01"] += 0.5 # Creeping up
            self.state["humidity_indoor_icu"] = 58.0 # High but stable
            self.state["budget_frozen"] = True
            print(f"\n[PHYSICS] Day {self.day} (Phase 4): Degradation. Vib: {self.state['vibration_ch01']:.1f}")

        # Phase 5: Trust Degradation (Day 9)
        elif self.day == 9:
            # Event triggered externally, physics just holds
            self.state["vibration_ch01"] = 3.0
            print(f"\n[PHYSICS] Day {self.day} (Phase 5): Trust Event Day.")

        # Phase 6: Critical Fork (Day 10)
        elif self.day == 10:
            self.state["vibration_ch01"] = 3.9 # Critical (< 4.0 limit)
            self.state["humidity_indoor_icu"] = 62.0
            self.state["gsas_score"] = 1.95 # LOST GOLD
            print(f"\n[PHYSICS] Day {self.day} (Phase 6): CRITICAL FORK. Vib: {self.state['vibration_ch01']}, GSAS: {self.state['gsas_score']}")

# --------------------------------------------------------------------------
# 2. MOCK BMS STATE (The Interface)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 2. SCENARIO BMS STATE (Using Real Data Models + Health Monitor)
# --------------------------------------------------------------------------
from agent_bms.bms_data_model import BMSDataPoint, Equipment, Alarm, EquipmentType, EquipmentStatus, AlarmSeverity, PointType
from agent_bms.sensor_health import SensorHealthMonitor, PerceptionState

class ScenarioBMSState:
    """Connects the Agent to the ScenarioEngine using REAL data structures."""
    def __init__(self, engine: ScenarioEngine):
        self.engine = engine
        self.health_monitor = SensorHealthMonitor(stale_threshold_seconds=600, frozen_threshold_ticks=5)

    async def get_points_by_equipment(self, equipment_id: str):
        """Return real BMSDataPoints populated with scenario values."""
        points = []
        
        # Helper to create a real point
        def create_point(pid, val, unit=""):
            return BMSDataPoint(
                point_id=pid,
                name=pid.split("/")[-1],
                value=val, # Can be None if engine state missing
                unit=unit,
                equipment_id=equipment_id,
                source="scenario_engine",
                timestamp=datetime.now()
            )

        if "CH-01" in equipment_id:
            points.append(create_point(f"{equipment_id}/Vibration", self.engine.state["vibration_ch01"], "mm/s"))
            points.append(create_point(f"{equipment_id}/Efficiency", self.engine.state["chiller_efficiency"], "kW/TR"))
            points.append(create_point(f"{equipment_id}/ReturnTemp", 12.0, "°C"))
            points.append(create_point(f"{equipment_id}/SupplyTemp", 7.0, "°C"))
        elif "Meter" in equipment_id or "Energy" in equipment_id:
             points.append(create_point(f"{equipment_id}/Intensity", self.engine.state["energy_intensity"], "kWh/m2"))
        elif "ICU" in equipment_id:
             points.append(create_point(f"{equipment_id}/Humidity", self.engine.state["humidity_indoor_icu"], "%"))
             
        return points

    async def check_epistemic_health(self):
        """Run health check on a sample of critical sensors."""
        critical_ids = ["CH-01", "AHU-01/SupplyTemp", "Meter-01/Intensity"]
        points = []
        for eq_id in ["CH-01", "Meter-01", "ICU"]:
             # Gather all points
             eq_points = await self.get_points_by_equipment(eq_id)
             points.extend(eq_points)
             
        report = self.health_monitor.check_health(points)
        return report

    async def get_equipment(self, equipment_id: str):
        """Return real Equipment object."""
        # Determine type based on ID
        eq_type = EquipmentType.OTHER
        if "CH" in equipment_id: eq_type = EquipmentType.CHILLER
        elif "AHU" in equipment_id: eq_type = EquipmentType.AHU
        elif "PUMP" in equipment_id: eq_type = EquipmentType.PUMP
            
        return Equipment(
            equipment_id=equipment_id,
            name=f"Equipment {equipment_id}",
            equipment_type=eq_type,
            location="Basement Energy Center",
            status=EquipmentStatus.RUNNING,
            efficiency=0.85 if "CH" in equipment_id else None,
            data_points=[f"{equipment_id}/Vibration", f"{equipment_id}/Efficiency"] if "CH" in equipment_id else []
        )
        
    async def get_all_equipment(self):
        """Return all equipment."""
        ids = ["CH-01", "AHU-01", "AHU-02", "PUMP-01"]
        return [await self.get_equipment(eid) for eid in ids]

    async def get_active_alarms(self):
        return []

class ScenarioAlarmEngine:
    """Alarm Engine using Real Alarm Models."""
    def __init__(self, engine: ScenarioEngine):
        self.engine = engine

    def get_priority_queue(self):
        alarms = []
        # Phase 6 Alarm Logic
        if self.engine.state["vibration_ch01"] > 3.8:
             # Create REAL Alarm object
             alarm = Alarm(
                 alarm_id="ALM-999-CRITICAL",
                 equipment_id="CH-01",
                 message="High Vibration Trip Risk (>3.8 mm/s)",
                 severity=AlarmSeverity.CRITICAL,
                 source_point_id="CH-01/Vibration"
             )
             # Wrap in a dict structure if tools_schema expects objects that have to_dict()
             # But here we return the object itself because BMSToolHandler calls .to_dict() on it?
             # Let's check tools_schema: "_handle_get_active_alarms" -> "alarms": [a.to_dict() for a in queue]
             # So we return the Alarm object itself.
             alarms.append(alarm)
             
        return alarms

# --------------------------------------------------------------------------
# 3. MAIN SIMULATION
# --------------------------------------------------------------------------
async def run_pilot():
    print(f"ΩΣ — The Sovereign Campus Collapse — PILOT SIMULATION")
    print(f"=====================================================")
    
    # Init Engine
    scenario = ScenarioEngine()
    bms_state_interface = ScenarioBMSState(scenario)
    alarm_engine = ScenarioAlarmEngine(scenario)
    
    # Init ARVIS
    from agent_bms.bms_llm_agent import BMSLLMAgent
    # We pass None for most engines as we want to text Core Agent Logic + Tools
    # The tools (BMSToolHandler) will use our bms_state_interface
    agent = BMSLLMAgent(
        bms_state=bms_state_interface,
        alarm_engine=alarm_engine, 
        energy_analyzer=None,
        predictive_engine=None
    )
    
    # Force K2-Think + ToolEconomy
    import os
    os.environ["LLM_PROVIDER"] = "k2think"
    os.environ["TOOL_PROVIDER"] = "groq"
    os.environ["K2THINK_MODEL"] = "MBZUAI-IFM/K2-Think-v2"
    
    print(f"[SETUP] Agent Initialized. Provider: {agent.provider}")
    
    # ----------------------------------------------------------------------
    # DAY LOOP
    # ----------------------------------------------------------------------
    # Init Audit Logger (Layer 4)
    from agent_bms.audit_logger import AdvisoryAuditLogger
    audit_logger = AdvisoryAuditLogger()
    print("[SETUP] Advisory Audit Logger Initialized.")

    # ----------------------------------------------------------------------
    # DAY LOOP
    # ----------------------------------------------------------------------
    for day in range(1, 11):
        # 0. PHYSICS TICK
        scenario.next_day()
        
        print(f"\n--- Day {day} Agent Activation ---")

        # 1. PERCEPTION HEALTH CHECK (Layer 2)
        print("[TRUST] Running Perception Health Monitor...")
        health = await bms_state_interface.check_epistemic_health()
        print(f"[TRUST] Sensor Health: {health.state.name} (Stale: {health.stale_count}, Frozen: {health.frozen_count})")
        
        if health.state.name == "BLIND":
            print("🚨 SYSTEM BLINDNESS DETECTED. INTERVENTION REQUIRED.")
            # In a real system, we might switch to fail-safe mode here.
            # For pilot, we proceed but expect the agent to notice (or at least we log it).

        # 2. GENERATE TRIGGER
        trigger_msg = f"SYSTEM_TICK: Day {day} Started. Current Time: 08:00."
        if day == 5:
             trigger_msg += " Notification: Operator manually lowered setpoint by 2C."
        
        # 3. RUN AGENT
        # We invoke the agent. The Tool Watchdog (Layer 3) is active via the @tool_timeout decorator in tools_schema.
        response = await agent.chat(
            f"{trigger_msg} Monitor system status, verify GSAS compliance, and recommend actions if needed."
        )
        
        # 4. CAPTURE & JUDGE
        print(f"Agent Output:\n{response.text[:200]}...") # Print first 200 chars
        
        tools_used = []
        if response.tool_calls:
            # Handle different formats (Object vs Dict)
            for tc in response.tool_calls:
                if isinstance(tc, dict):
                    tools_used.append(tc.get('tool') or tc.get('function', {}).get('name') or 'unknown')
                else:
                    tools_used.append(getattr(tc, 'function', getattr(tc, 'name', str(tc))))
            
            print(f"Tools Used: {tools_used}")
        else:
            print("Tools Used: None")

        # 5. AUDIT LOGGING (Layer 4)
        print("[TRUST] Logging decision to Black Box...")
        audit_logger.log_decision(
            query=trigger_msg,
            context=scenario.state, # Snapshot the physics state as context
            tools_used=tools_used,
            response={"text": response.text, "tools": tools_used},
            confidence=response.confidence,
            owned_decision="Agent" if response.confidence > 0.8 else "Shared"
        )

        # Log to file for User Readiness Report reviews
        with open("pilot_simulation_log.md", "a", encoding="utf-8") as f:
            f.write(f"\n\n## Day {day}\n")
            f.write(f"**Physics**: Vib={scenario.state['vibration_ch01']}, Energy={scenario.state['energy_intensity']}\n")
            f.write(f"**Trust**: Health={health.state.name}, AuditID={audit_logger._compute_hash(str(day))[:8]}\n")
            f.write(f"**Agent**: {response.text}\n")
            f.write(f"**Tools**: {tools_used}\n")

if __name__ == "__main__":
    asyncio.run(run_pilot())
