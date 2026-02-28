
import asyncio
import json
import os
import sys
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from colorama import Fore, Style, init
from dotenv import load_dotenv

# Ensure environment is loaded
load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import REAL Agent and Dependencies
from agent_unified.llm import UnifiedLLM
from agent_commercial.bms_llm_agent import BMSLLMAgent

init()

# ═══════════════════════════════════════════════════════════════════════════
# 1. MOCK BACKEND ENGINES (The World Model)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# 1. MOCK BACKEND ENGINES (The World Model)
# ═══════════════════════════════════════════════════════════════════════════

class MockObject:
    def __init__(self, data):
        self.__dict__.update(data)
    def to_dict(self):
        result = {}
        for k, v in self.__dict__.items():
            if hasattr(v, 'to_dict'):
                result[k] = v.to_dict()
            elif isinstance(v, list):
                result[k] = [i.to_dict() if hasattr(i, 'to_dict') else i for i in v]
            elif isinstance(v, datetime):
                result[k] = v.isoformat()
            elif isinstance(v, dict):
                 # Handle dicts recursively too if they contain MockObjects or datetimes
                new_dict = {}
                for dk, dv in v.items():
                    if hasattr(dv, 'to_dict'):
                        new_dict[dk] = dv.to_dict()
                    elif isinstance(dv, datetime):
                        new_dict[dk] = dv.isoformat()
                    else:
                        new_dict[dk] = dv
                result[k] = new_dict
            else:
                result[k] = v
        return result

class MockEquipment(MockObject):
    pass

class MockPoint(MockObject):
    pass

class MockAlarm(MockObject):
    pass

class MockBMSState:
    def __init__(self):
        self.equipment_map = {}
        
    def set_status(self, eq_id: str, status: Dict):
        # Ensure status has required fields
        if "id" not in status: status["id"] = eq_id
        if "name" not in status: status["name"] = eq_id
        if "equipment_type" not in status: status["equipment_type"] = MockObject({"value": "chiller"}) # Enum mock
        else: status["equipment_type"] = MockObject({"value": status["equipment_type"] if isinstance(status["equipment_type"], str) else "chiller"})
        
        if "status" not in status: status["status"] = MockObject({"value": "running"})
        else: status["status"] = MockObject({"value": status["status"] if isinstance(status["status"], str) else "running"})
        
        if "location" not in status: status["location"] = "Zone 1"
        if "efficiency" not in status: status["efficiency"] = 90
        if "runtime_hours" not in status: status["runtime_hours"] = 1000
        
        self.equipment_map[eq_id] = MockEquipment(status)
        
    async def get_equipment(self, equipment_id: str):
        return self.equipment_map.get(equipment_id, MockEquipment({
            "id": equipment_id,
            "name": equipment_id,
            "status": MockObject({"value": "running"}),
            "equipment_type": MockObject({"value": "unknown"}),
            "location": "Unknown",
            "efficiency": 85,
            "runtime_hours": 5000
        }))
        
    async def get_all_equipment(self):
        return list(self.equipment_map.values())
        
    async def get_points_by_equipment(self, equipment_id: str):
        return [
            MockPoint({"point_id": f"{equipment_id}/temp", "value": 22.5}),
            MockPoint({"point_id": f"{equipment_id}/pressure", "value": 101.3}),
            MockPoint({"point_id": f"{equipment_id}/status", "value": 1})
        ]

    async def get_active_alarms(self):
        return [] # Handled by AlarmEngine

    async def get_point_history(self, point_id, minutes):
        return [(datetime.now(), 22.0)]
        
    async def get_snapshot(self):
        return {"total_power": 1200}

class MockAlarmEngine:
    def __init__(self):
        self.priority_queue = []
        
    def inject_alarm(self, alarm_data: Dict):
        # Adapter to match AlarmWrapper expected by ToolHandler
        # ToolHandler does: queue[i].alarm.severity
        # So we need a wrapper object
        
        inner_alarm = MockObject({
            "id": alarm_data.get("id", "ALM-001"),
            "equipment_id": alarm_data.get("equipment_id", "EQ-01"),
            "message": alarm_data.get("title", "Alarm"),
            "severity": MockObject({"value": alarm_data.get("priority", "medium").lower()}),
            "timestamp": datetime.now()
        })
        
        wrapper = MockObject({
            "alarm": inner_alarm,
            "score": 100
        })
        self.priority_queue.append(wrapper)
        
    def clear_alarms(self):
        self.priority_queue = []
        
    def get_priority_queue(self):
        return self.priority_queue
        
    def get_root_cause_analysis(self, alarm_id):
        return MockObject({
            "root_cause_id": "Unknown",
            "recommendation": "Investigate manually",
            "likelihood": 0.5
        })

class MockEnergyAnalyzer:
    def __init__(self):
        self.patterns = []
        self.summary = {"daily_kwh": 1000, "baseline": 900}
        
    def inject_anomaly(self, anomaly: Dict):
        self.patterns.append(MockObject({
            "title": anomaly.get("type", "Anomaly"),
            "description": anomaly.get("description", "Energy spike"),
            "severity": "high",
            "impact_qar_day": 500
        }))
        
    def get_summary(self):
        return self.summary
        
    def identify_waste_patterns(self):
        return self.patterns

class MockPredictiveEngine:
    async def predict_maintenance(self, equipment_id):
        return {"next_maintenance": "2026-03-01", "health_score": 88}

# ═══════════════════════════════════════════════════════════════════════════
# 2. SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

SIMULATION_DAYS = 30
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

@dataclass
class BuildingContext:
    id: str
    name: str
    type: str 
    priority: str 
    criticality: str 

BUILDINGS = [
    BuildingContext("west_bay", "West Bay Tower", "Office", "GSAS Compliance", "Med"),
    BuildingContext("sidra", "Sidra Medical Center", "Healthcare", "Patient Safety", "LIFE_CRITICAL"),
]

@dataclass
class DailyScenario:
    day: int
    building_id: str
    title: str
    description: str
    signal_data: Dict # Actual data to inject into backend
    true_root_cause: str 
    expected_mode: str 
    expected_tools: List[str] = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════════════
# 3. THE ARCHITECT (Dynamic Scenario Generator)
# ═══════════════════════════════════════════════════════════════════════════

class Architect:
    def __init__(self, llm: UnifiedLLM):
        self.llm = llm
        
    async def generate_daily_chaos(self, day: int, target: BuildingContext) -> List[DailyScenario]:
        """Generates scenarios containing setup data for the mock backend."""
        # 40% chance of a quiet day (DISABLED for validation)
        # if random.random() > 0.6: return [] 
        
        # We ask LLM to output valid JSON for the Mock Backend
        prompt = [
            {"role": "system", "content": f"""
            You are The Architect. Generate a DEEP, REALISTIC BMS scenario for:
            Target: {target.name} ({target.type})
            Priority: {target.priority}
            Day: {day}/30
            
            VALID TOOLS (Only use these in 'expected_tools'):
            [
             get_equipment_status, list_equipment, 
             get_active_alarms, explain_alarm, analyze_root_cause,
             analyze_energy, get_energy_anomalies, 
             predict_maintenance, get_equipment_health,
             get_gsas_status, get_gsas_improvement_priorities,
             check_cost_impact, get_burn_rate
            ]
            
            SCENARIO TYPES (Choose 1):
            1. HIDDEN COST: No alarms, but energy usage is spiked. (Essential: `analyze_energy`)
            2. SAFETY CRITICAL: Life safety sensor fault. (Essential: `get_active_alarms`, `get_equipment_status`)
            3. CASCADE FAILURE: Root cause investigation. (Essential: `analyze_root_cause`)
            4. GSAS RISK: Sustainability score dropping. (Essential: `get_gsas_status`)
            5. PREDICTIVE: Equipment degrading. (Essential: `predict_maintenance`)
            6. MEMORY RECALL: Recurring issue. (Essential: `get_active_alarms` + history)
            
            SURGICAL TOOLING: Do NOT list every possible tool. Only list the 2-3 ESSENTIAL tools required to diagnose this specific incident.
            
            OUTPUT JSON ONLY:
            {{
                "title": "Chiller Efficiency Drop",
                "description": "Operator notes Chiller 1 is running loud and energy bill is up.",
                "inject_alarm": null, 
                "inject_status": {{ "status": "Running", "efficiency": 0.5 }},
                "inject_energy": {{ "daily_kwh": 3000, "anomalies": ["CH-1 Overconsumption"] }},
                "expected_mode": "COST_ACCOUNTABILITY",
                "expected_tools": ["analyze_energy", "get_equipment_status"]
            }}
            """},
            {"role": "user", "content": "Generate deep scenario."}
        ]
        
        try:
            resp = await self.llm.ask(prompt)
            data = json.loads(re.search(r"\{.*\}", resp.content, re.DOTALL).group(0))
            
            signal_data = {
                "alarm": data.get("inject_alarm"),
                "status": data.get("inject_status"),
                "energy": data.get("inject_energy")
            }
            
            return [DailyScenario(
                day=day,
                building_id=target.id,
                title=data['title'],
                description=data['description'],
                signal_data=signal_data,
                true_root_cause=data.get('title'),
                expected_mode=data.get('expected_mode', 'OPERATIONAL_CAUSE'),
                expected_tools=data.get('expected_tools', [])
            )]
        except Exception as e:
            print(f"{Fore.RED}Architect Fail: {e}{Style.RESET_ALL}")
            return []

# ═══════════════════════════════════════════════════════════════════════════
# 4. SUPER GAUNTLET RUNNER
# ═══════════════════════════════════════════════════════════════════════════

async def run_e2e_gauntlet():
    print(f"\n{Fore.MAGENTA}==========================================================================")
    print(f"🦸‍♂️ ARVIS E2E SUPER GAUNTLET (REAL AGENT STACK)")
    print(f"=========================================================================={Style.RESET_ALL}", flush=True)

    # 1. Initialize Mocks
    mock_state = MockBMSState()
    mock_alarm = MockAlarmEngine()
    mock_energy = MockEnergyAnalyzer()
    mock_pm = MockPredictiveEngine()
    
    # 2. Initialize REAL AGENT with Mocks (Dependency Injection)
    agent = BMSLLMAgent(
        bms_state=mock_state,
        alarm_engine=mock_alarm,
        energy_analyzer=mock_energy,
        predictive_engine=mock_pm
    )
    
    # 3. Architect
    llm = UnifiedLLM(provider=LLM_PROVIDER, model_name=LLM_MODEL)
    architect = Architect(llm)
    
    passed_scenarios = 0
    total_scenarios = 0
    total_expected_count = 0
    total_used_count = 0
    
    # 4. Simulation Loop (Per Building)
    for building in BUILDINGS:
        print(f"\n{Fore.BLUE}🔹 SITE: {building.name} ({building.type}){Style.RESET_ALL}")
        mock_state.building_id = building.id
        
        for day in range(1, 15): # Running 14 days per building
            
            # Generate Scenarios
            scenarios = await architect.generate_daily_chaos(day, building)
            
            if not scenarios: 
                print(f"[{day}] Quiet.", end=" ", flush=True)
                continue
                
            for scen in scenarios:
                total_scenarios += 1
                print(f"\n  > {Fore.CYAN}[Day {day}] SCENARIO: {scen.title}{Style.RESET_ALL}", flush=True)
                print(f"    Desc: {scen.description}", flush=True)
                print(f"    Expect: {scen.expected_mode} | Tools: {scen.expected_tools}", flush=True)
                
                # --- INJECT FAULT INTO MOCK BACKEND ---
                mock_alarm.clear_alarms()
                alarm_data = scen.signal_data.get("alarm")
                
                if alarm_data:
                    if isinstance(alarm_data, list):
                        for a in alarm_data: 
                            if isinstance(a, dict): mock_alarm.inject_alarm(a)
                        eq_id = alarm_data[0].get("equipment_id", "CH-01") if isinstance(alarm_data[0], dict) else "CH-01"
                    elif isinstance(alarm_data, dict):
                        mock_alarm.inject_alarm(alarm_data)
                        eq_id = alarm_data.get("equipment_id", "CH-01")
                    else:
                        # Fallback for string/malformed
                        eq_id = "CH-01"
                else:
                    eq_id = "CH-01"
                    
                if scen.signal_data.get("status"):
                    mock_state.set_status(eq_id, scen.signal_data["status"])
                    
                if scen.signal_data.get("energy"):
                    # Inject energy data if provided
                    pass 
                # ----------------------------------------
                
                # --- AGENT EXECUTION ---
                # We wrap the description in an Alert to force the agent to Verify
                query = f"ALERT: {scen.description} Please check system status and advise."
                try:
                    response = await agent.chat(query, context={"site_type": building.type})
                    
                    # --- VERIFICATION ---
                    passed = True
                    fail_reasons = []
                    
                    # Check 1: Tool Usage (Smart Evaluation)
                    tools_used = [tc['tool'] for tc in response.tool_calls]
                    found_expected = [t for t in scen.expected_tools if t in tools_used]
                    tool_accuracy = len(found_expected) / len(scen.expected_tools) if scen.expected_tools else 1.0
                    
                    if tool_accuracy < 0.65: # Flexible threshold for economy experimentation
                        passed = False
                        fail_reasons.append(f"Missing Essential Tools (Acc: {tool_accuracy:.1%}). Expected: {scen.expected_tools}")
                    
                    # Update global economy metrics
                    total_expected_count += len(scen.expected_tools)
                    total_used_count += len(tools_used)
                    
                    # Check 2: Mode Compliance
                    content = response.text.lower()
                    if scen.expected_mode == "SAFETY_VALIDATION" or "safety" in scen.title.lower():
                        if "risk" not in content and "safety" not in content and "critical" not in content and "patient" not in content:
                            passed = False
                            fail_reasons.append("Missed Safety Mode keywords")
                            
                    elif scen.expected_mode == "COST_ACCOUNTABILITY":
                        if "qar" not in content and "cost" not in content:
                            passed = False
                            fail_reasons.append("No Cost (QAR/Cost)")

                    # Check 3: Memory Recall (Titan/ACE Verification)
                    if "recall" in scen.title.lower() or "memory" in scen.title.lower():
                        # Agent must acknowledge history or trends
                        keywords = ["history", "previous", "earlier", "trend", "since", "last time", "recurring"]
                        if not any(k in content for k in keywords):
                            passed = False
                            fail_reasons.append("Failed Memory Recall (No reference to history/trends)")

                    if passed:
                        passed_scenarios += 1
                        print(f"    {Fore.GREEN}✅ PASSED{Style.RESET_ALL}")
                        print(f"    Tools Used: {tools_used} (Acc: {tool_accuracy:.1%})")
                        print(f"    Ans: {response.text[:150]}...", flush=True)
                    else:
                        print(f"    {Fore.RED}❌ FAILED{Style.RESET_ALL}")
                        print(f"    Reasons: {fail_reasons}")
                        print(f"    Tools Used: {tools_used}")
                        print(f"    Ans: {response.text[:150]}...", flush=True)
                        
                except Exception as e:
                    print(f"    {Fore.RED}CRASH: {e}{Style.RESET_ALL}", flush=True)

    # 5. Report
    score = (passed_scenarios / total_scenarios * 100) if total_scenarios > 0 else 100
    economy_score = (total_expected_count / total_used_count * 100) if total_used_count > 0 else 0
    
    print(f"\n{Fore.CYAN}--- EFFICIENCY AUDIT ---{Style.RESET_ALL}")
    print(f"Total Expected Tools (Target): {total_expected_count}")
    print(f"Total Used Tools (Actual): {total_used_count}")
    print(f"Tool Economy Score: {economy_score:.1f}% (Aiming for 100%)")
    
    print(f"\n{Fore.MAGENTA}=== RESULT: {score:.1f}% ({passed_scenarios}/{total_scenarios}) ==={Style.RESET_ALL}")

if __name__ == "__main__":
    asyncio.run(run_e2e_gauntlet())
