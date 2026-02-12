import asyncio
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load env vars first!
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("arvis_e2e")

from agent_unified.llm import UnifiedLLM
from agent_unified.agents.manus import ARVISManus
from agent_unified.tools.bms import BMSToolkit
from agent_unified.schema import Message

# ═══════════════════════════════════════════════════════════
# 1. SIMULATED BUILDING ENGINE
# ═══════════════════════════════════════════════════════════

class SimulatedBMS:
    def __init__(self):
        self.alarms = [
            {"id": "ALM-101", "priority": "critical", "message": "Chiller-01 High Pressure Trip", "status": "active"},
            {"id": "ALM-102", "priority": "low", "message": "Filter Replacement Due AHU-05", "status": "active"}
        ]
        self.equipment = {
            "AHU-01": {"id": "AHU-01", "name": "Main Office AHU", "status": "running", "type": "ahu", "location": "Roof"},
            "CH-01": {"id": "CH-01", "name": "Primary Chiller", "status": "fault", "type": "chiller", "location": "Basement"}
        }
        self.points = {
            "AHU-01": [{"id": "p1", "name": "Supply Temp", "value": 22.5, "unit": "C"}, {"id": "p2", "name": "Return Temp", "value": 24.1, "unit": "C"}]
        }
        
    # --- Interface for Equipment Tool ---
    def get_equipment(self, eq_id): 
        # Return object with attributes as expected by tool
        data = self.equipment.get(eq_id)
        if not data: return None
        class EqObj: pass
        obj = EqObj()
        for k,v in data.items(): setattr(obj, k, v)
        # Fix for type/status mismatch in tool (tool expects object or string, let's make it robust)
        obj.equipment_id = data["id"]
        obj.eq_type = data["type"]
        return obj

    def get_points_by_equipment(self, eq_id):
        raw = self.points.get(eq_id, [])
        res = []
        for p in raw:
            class Pt: pass
            obj = Pt(); obj.point_id=p["id"]; obj.name=p["name"]; obj.value=p["value"]; obj.unit=p["unit"]
            res.append(obj)
        return res
        
    def get_all_equipment(self):
        res = []
        for k, v in self.equipment.items():
            class Eq: pass
            obj = Eq(); obj.equipment_id=v["id"]; obj.eq_type=v["type"]; obj.status=v["status"]
            res.append(obj)
        return res

    # --- Interface for Alarms Tool ---
    def get_active_alarms(self, priority_filter=None):
        res = []
        for a in self.alarms:
            if priority_filter and priority_filter != a["priority"]: continue
            if a["status"] != "active": continue
            class Alm: pass
            obj = Alm(); 
            obj.to_dict = lambda a=a: a # Capture 'a' in closure
            res.append(obj)
        return res
        
    def acknowledge_alarm(self, alarm_id, user, note):
        print(f"   [SIM-INTERNAL] acknowledge_alarm called for {alarm_id} by {user}")
        for a in self.alarms:
            if a["id"] == alarm_id:
                a["status"] = "acknowledged"
                a["note"] = note
                logger.info(f"[SIM] Alarm {alarm_id} ACKNOWLEDGED by {user}: {note}")
                return True
        return False

    # --- Interface for Energy Tool ---
    def analyze(self, period="today"):
        return {
            "period": period,
            "consumption": "1,250 kWh",
            "trend": "+5% vs average",
            "peak_load": "450 kW at 14:00"
        }
        
    def detect_anomalies(self):
        return ["High after-hours usage in Zone B", "Chiller short-cycling detected"]

# ═══════════════════════════════════════════════════════════
# 2. TEST SCENARIOS
# ═══════════════════════════════════════════════════════════

async def run_scenario(name, user_input, agent):
    print(f"\n⚡ SYSTEM TEST: {name}")
    print(f"👤 User: \"{user_input}\"")
    
    agent.memory.clear()
    agent.memory.add_message(Message.user_message(user_input))
    
    # Run Agent Loop (Think -> Act -> Observe -> Think -> Reponse)
    steps = 0
    max_steps = 5
    final_response = ""
    
    while steps < max_steps:
        print(f"   🤖 Agent Thinking... (Step {steps+1})")
        has_tools = await agent.step() # Think
        print(f"   [DEBUG] think() returned {has_tools}")
        print(f"   [DEBUG] agent.tool_calls: {agent.tool_calls}")
        if agent.tool_calls:
            print(f"   🛠️  Tools Selected: {[tc.function.name for tc in agent.tool_calls]}")
            result = await agent.act()   # Act
            print(f"   📊 Tool Result: {str(result)[:100]}...")
            steps += 1
        elif has_tools is True: 
            # Tool calls present but maybe handled differently in some agent versions?
            # Unified agent returns True if tool calls generated
            result = await agent.act()
            steps += 1
        else:
            # Final response
            last_msg = agent.memory.messages[-1]
            if last_msg.role == "assistant" and last_msg.content:
                final_response = last_msg.content
                break
            else:
                # Agent didn't generate content?
                break
                
    print(f"💬 Agent: \"{final_response}\"")
    return final_response

async def main():
    print("🚀 Initializing End-to-End Simulation Environment...")
    
    # 1. Setup Simulation
    sim = SimulatedBMS()
    
    # 2. Setup Agent
    # Note: We rely on the real LLM (hybrid) initialized internally
    agent = await ARVISManus.create(
        bms_state=sim,
        alarm_engine=sim,
        energy_analyzer=sim,
        skillbook=None
    )
    
    # 3. Scenario 1: Critical Alarm Management
    resp1 = await run_scenario(
        "SCENARIO 1: Critical Alarm Handling",
        "Check for any critical alarms and acknowledge the first one with note 'Maintenance notified'",
        agent
    )
    
    # Debug State
    print("\n--- SIM STATE ---")
    print(sim.alarms)
    print("-----------------")
    
    ack_alarm = next((a for a in sim.alarms if a["id"] == "ALM-101"), None)
    if ack_alarm and ack_alarm["status"] == "acknowledged":
        print("✅ SUCCESS: Critical alarm was acknowledged in simulation.")
    else:
        print(f"❌ FAILURE: Alarm status is {ack_alarm['status'] if ack_alarm else 'Missing'}")

    # 4. Scenario 2: Equipment Diagnostics
    # Context: User investigating specific breakdown
    resp2 = await run_scenario(
        "SCENARIO 2: Equipment Diagnostics",
        "What is the status of AHU-01? Give me its temperature readings.",
        agent
    )
    if "22.5" in str(resp2) or "Supply Temp" in str(resp2):
        print("✅ SUCCESS: Retrieved equipment live data.")
    else:
        print("⚠️ WARNING: Data might be missing from response.")

    # 5. Scenario 3: Sustainability Insight
    # Context: High level management query
    resp3 = await run_scenario(
        "SCENARIO 3: Energy Analysis",
        "Analyze typical energy usage today and tell me if we are wasting power.",
        agent
    )
    if "1,250" in str(resp3) or "Zone B" in str(resp3):
        print("✅ SUCCESS: Energy report generated.")
    else:
        print("❌ FAILURE: Energy data missing.")
        
    print("\n🏁 E2E Simulation Cycle Complete.")

if __name__ == "__main__":
    asyncio.run(main())
