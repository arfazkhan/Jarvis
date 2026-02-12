import asyncio
import json
import os
import sys
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from colorama import Fore, Style, init
from dotenv import load_dotenv

# Ensure environment is loaded
load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_unified.llm import UnifiedLLM

# Initialize Colorama
init()

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SIMULATION_DAYS = 30
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

@dataclass
class BuildingContext:
    name: str
    type: str # Office, Heritage, Retail, Healthcare, Industrial
    baseline_energy_kwh: float
    tariff_rate: float # QAR/kWh
    sensitivity: str
    location: str # West Bay, Souq, Lusail, Sidra, Industrial

BUILDINGS = {
    "west_bay": BuildingContext("West Bay Tower", "Office", 15000, 0.32, "Compliance & Cost", "West Bay"),
    "souq": BuildingContext("Souq Waqif Heritage Hotel", "Heritage", 4000, 0.32, "Comfort vs Heritage", "Souq Waqif"),
    "lusail": BuildingContext("Lusail Marina Mall", "Retail", 25000, 0.45, "Unintentional Ops", "Lusail"),
    "sidra": BuildingContext("Sidra Medical Center", "Healthcare", 35000, 0.32, "Safety Critical", "Education City"),
    "industrial": BuildingContext("Logistics Warehouse 4", "Industrial", 8000, 0.22, "Asset Health", "Industrial Area"),
}

@dataclass
class DailySimData:
    day: int
    outdoor_temp_c: float
    dust_level_pm25: float # 0-500
    occupancy_pct: float
    events: List[str] = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════════════
# SIMULATOR ENGINE (QATAR CLIMATE)
# ═══════════════════════════════════════════════════════════════════════════

class QatarBuildingSimulator:
    def __init__(self, context: BuildingContext):
        self.ctx = context
        self.current_faults = []
        self.cumulative_cost_impact = 0.0
        
    def generate_day(self, day: int) -> Dict[str, Any]:
        # weather
        base_temp = 38.0 + (5.0 * (day % 10) / 10) # 38-43C cycle
        if day == 15: base_temp = 48.0 # Heat Spike
        
        dust = 50
        if "Industrial" in self.ctx.location: dust = 150
        if day == 29: dust = 400 # Sandstorm
        
        # Scenarios injection based on building profile
        scenario = None
        
        # 1. WEST BAY: Bill Shock & Compliance
        if self.ctx.name == "West Bay Tower":
            if day == 2:
                scenario = {
                    "id": "bill_shock",
                    "signal": "AHU-22 Override ON (24h) - Peak Tariff Active",
                    "impact_kwh": 3000,
                    "user_query": "Why was the electricity bill higher this week?"
                }
            elif day == 9:
                 scenario = {
                    "id": "control_conflict",
                    "signal": "Zone 4: Reheat Valve 100% AND Cooling Valve 100%",
                    "impact_kwh": 1200,
                    "user_query": "Everything is 'efficient' equipment, why is usage up?"
                }
            elif day == 28:
                scenario = {
                    "id": "compliance",
                    "signal": "EUI Projection +4.2% > GSAS Limit",
                    "impact_kwh": 0,
                    "user_query": "Are we still GSAS compliant after this spike?"
                }

        # 2. SOUQ WAQIF: Trade-offs & Paradox
        elif self.ctx.name == "Souq Waqif Heritage Hotel":
            if day == 12:
                scenario = {
                    "id": "systems_paradox",
                    "signal": "Room 104 Damper Stuck Closed -> AHU VFD at 98%",
                    "impact_kwh": 800,
                    "user_query": "We're paying more but guests complain it's hot."
                }
            elif day == 26:
                scenario = {
                    "id": "tradeoff",
                    "signal": "Night Setback Disabled to maintain 21C insulation loss",
                    "impact_kwh": 450,
                    "user_query": "We only adjusted comfort slightly, why the cost jump?"
                }

        # 3. LUSAIL MALL: Unintentional & Invisible
        elif self.ctx.name == "Lusail Marina Mall":
            if day == 5:
                scenario = {
                    "id": "unintentional",
                    "signal": "Lighting Schedule shift +2h (Cleaners Logged In)",
                    "impact_kwh": 1500,
                    "user_query": "We didn't change anything settings-wise. Why costs up?"
                }
            elif day == 10:
                scenario = {
                    "id": "invisible_fault",
                    "signal": "Temp Sensor Chiller Return drifted +3C (Self-correcting)",
                    "impact_kwh": 2200,
                    "user_query": "Why did energy spike on Tuesday only?"
                }

        # 4. SIDRA MEDICAL: False Savings & Plain English
        elif self.ctx.name == "Sidra Medical Center":
            if day == 17:
                scenario = {
                    "id": "false_savings",
                    "signal": "Chiller-01 kW reading = 0.0 (Status: RUNNING)",
                    "impact_kwh": -5000, # Fake drop
                    "user_query": "Energy dropped 40% — great job!"
                }
            elif day == 30:
                scenario = {
                    "id": "plain_english",
                    "signal": "Complex VAV hunting oscillation on Floor 3",
                    "impact_kwh": 300,
                    "user_query": "Explain this VAV issue like I'm not an engineer."
                }

        # 5. INDUSTRIAL WAREHOUSE: Silent Degradation
        elif self.ctx.name == "Logistics Warehouse 4":
            if day == 22:
                scenario = {
                    "id": "silent_degradation",
                    "signal": "AHU Filter dP rising slowly (+20% vs baseline) over 3 weeks",
                    "impact_kwh": 900,
                    "user_query": "Why are we spending more even though nothing is broken?"
                }

        # Calculation
        kwh = self.ctx.baseline_energy_kwh * (1 + (base_temp - 24)/100)
        cost = kwh * self.ctx.tariff_rate
        
        if scenario:
            kwh += scenario["impact_kwh"]
            cost += (scenario["impact_kwh"] * self.ctx.tariff_rate)

        return {
            "day": day,
            "temp": base_temp,
            "dust": dust,
            "kwh": kwh,
            "cost": cost,
            "scenario": scenario
        }

# ═══════════════════════════════════════════════════════════════════════════
# VERIFICATION LOGIC
# ═══════════════════════════════════════════════════════════════════════════

def verify_explanation(scenario_id: str, response: Dict[str, Any], ctx: BuildingContext) -> bool:
    explanation = response.get("explanation", "").lower()
    rec_fix = response.get("recommended_fix", "").lower()
    cost = response.get("cost_impact", "0")
    
    # Check 1: Must identify specific entity (Attribution)
    if "aggregate" in explanation or "multiple factors" in explanation:
         return False # Failed "No Fluff" rule
         
    # Check 2: Scenario Specifics
    if scenario_id == "bill_shock":
        # Relaxed: Needs "override" and cost/peak implication
        return "override" in explanation and ("peak" in explanation or "cost" in explanation or "bill" in explanation)
        
    elif scenario_id == "control_conflict":
        # Relaxed: Needs "fighting", "conflict", "simultaneous", or "both"
        return any(x in explanation for x in ["fighting", "conflict", "simultaneous", "both on", "opposing"])
        
    elif scenario_id == "unintentional":
        return "cleaners" in explanation or "cleaning" in explanation or "schedule" in explanation
        
    elif scenario_id == "invisible_fault":
        return "drift" in explanation or "sensor" in explanation or "calibration" in explanation
        
    elif scenario_id == "systems_paradox":
        return "damper" in explanation and ("stuck" in explanation or "closed" in explanation or "failure" in explanation)
        
    elif scenario_id == "false_savings":
        # CRITICAL: Must reject for Hospital
        if ctx.name == "Sidra Medical Center":
            return ("fault" in explanation or "error" in explanation) and ("not real" in explanation or "false" in explanation or "safety" in explanation)
        return "fault" in explanation or "error" in explanation
        
    elif scenario_id == "silent_degradation":
        return "filter" in explanation and ("clog" in explanation or "dust" in explanation or "dirty" in explanation)
        
    elif scenario_id == "tradeoff":
        return "insulation" in explanation or "setback" in explanation or "comfort" in explanation
        
    elif scenario_id == "compliance":
        return ("compliant" in explanation or "limit" in explanation) and ("risk" in explanation or "breach" in explanation or "fail" in explanation)
        
    elif scenario_id == "plain_english":
        # Check against jargon
        features = ["oscillation", "hunting", "pid", "derivative"]
        for f in features:
            if f in explanation: return False
        return True
        
    return False

# ═══════════════════════════════════════════════════════════════════════════
# MAIN GAUNTLET
# ═══════════════════════════════════════════════════════════════════════════

async def run_qatar_gauntlet():
    print(f"\n{Fore.CYAN}=======================================================")
    print(f"🧠 ARVIS GAUNTLET: EXPLAINABILITY (QATAR OPERATIONS) 🇶🇦")
    print(f"======================================================={Style.RESET_ALL}")

    llm = UnifiedLLM(provider=LLM_PROVIDER, model_name=LLM_MODEL)
    print(f"[UnifiedLLM] Agent Ready: {LLM_PROVIDER}:{LLM_MODEL}")

    simulators = {k: QatarBuildingSimulator(v) for k, v in BUILDINGS.items()}
    results = {k: 0 for k in BUILDINGS.keys()}
    total_scenarios = 0

    for day in range(1, SIMULATION_DAYS + 1):
        print(f"\n[{Fore.YELLOW}Day {day}{Style.RESET_ALL} / {SIMULATION_DAYS}] Simulation Tick...")
        
        for b_id, sim in simulators.items():
            data = sim.generate_day(day)
            
            if data["scenario"]:
                scen = data["scenario"]
                total_scenarios += 1
                print(f"  > {Fore.MAGENTA}{sim.ctx.name}{Style.RESET_ALL}: {scen['user_query']}")
                
                # Construct Prompt
                prompt_messages = [
                    {"role": "system", "content": f"""
                    You are ARVIS (Qatar Ops). Explain root causes in PLAIN ENGLISH.
                    Context: {sim.ctx.name} ({sim.ctx.type}). Location: {sim.ctx.location}.
                    Tariff: {sim.ctx.tariff_rate} QAR/kWh.
                    
                    RULES:
                    1. Name the specific machine/person.
                    2. State cost in QAR.
                    3. No jargon ("Hunting", "PID"). Use "Fighting", "Stuck".
                    4. If data is unrealistic (0kW), REJECT IT.
                    
                    OUTPUT JSON:
                    {{
                      "explanation": "...",
                      "evidence": ["..."],
                      "cost_impact": "X QAR",
                      "confidence": 0.0-1.0,
                      "recommended_fix": "..."
                    }}
                    """},
                    {"role": "user", "content": f"""
                    Query: "{scen['user_query']}"
                    
                    Data Stream:
                    - Outdoor Temp: {data['temp']}°C
                    - Dust: {data['dust']} PM2.5
                    - Energy: {data['kwh']} kWh (Today)
                    - Signal Trace: {scen['signal']}
                    """}
                ]
                
                try:
                    response_obj = await llm.ask(prompt_messages)
                    response_text = response_obj.content
                    print(f"    Raw Response: {response_text[:100]}...") # Debug log
                    
                    # Robust JSON Extraction
                    try:
                        import re
                        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
                        if json_match:
                             response = json.loads(json_match.group(0))
                        else:
                             response = json.loads(response_text)
                    except json.JSONDecodeError:
                        print(f"    {Fore.RED}JSON FAIL{Style.RESET_ALL}: Could not parse response.")
                        continue

                    passed = verify_explanation(scen['id'], response, sim.ctx)
                    
                    if passed:
                        results[b_id] += 1
                        print(f"    {Fore.GREEN}✅ PASSED{Style.RESET_ALL}: {response['explanation'][:80]}...")
                    else:
                        print(f"    {Fore.RED}❌ FAILED{Style.RESET_ALL}: {response['explanation']}")
                        print(f"      Expected keywords for {scen['id']} not found.")
                        
                except Exception as e:
                    print(f"    {Fore.RED}ERROR{Style.RESET_ALL}: {e}")
                    
    # Final Score
    print(f"\n{Fore.CYAN}=== QATAR OPERATIONS REPORT ==={Style.RESET_ALL}")
    GRAND_TOTAL = 0
    GRAND_PASSED = 0
    
    for b_id, score in results.items():
        # Each building has specific count of scenarios
        # West Bay: 3, Souq: 2, Lusail: 2, Sidra: 2, Industrial: 1 = Total 10
        total_for_b = 2 # default approx
        if b_id == "west_bay": total_for_b = 3
        elif b_id == "industrial": total_for_b = 1
        
        print(f"{BUILDINGS[b_id].name}: {score}/{total_for_b} Scenarios Explained")
        GRAND_PASSED += score
    
    print(f"\nOVERALL EXPLAINABILITY: {GRAND_PASSED}/{total_scenarios} ({(GRAND_PASSED/total_scenarios)*100}%)")

if __name__ == "__main__":
    asyncio.run(run_qatar_gauntlet())
