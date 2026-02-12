import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any
from colorama import Fore, Style, init
from dotenv import load_dotenv

# Ensure environment is loaded
load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_unified.llm import UnifiedLLM
from agent_bms.gsas_reporter import GSASReporter, GSASStarRating
from agent.memory.orchestrator import MemoryOrchestrator

# Initialize Colorama
init()

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

SIMULATION_DAYS = 6  # Phases 0-5
LLM_PROVIDER = "groq"
LLM_MODEL = "llama-3.3-70b-versatile"

@dataclass
class GauntletState:
    day: int = 0
    phase_name: str = ""
    energy_kwh: float = 0.0
    energy_target: float = 1000.0
    comfort_score: float = 1.0  # 0.0-1.0
    override_active: bool = False
    sensor_fault_active: bool = False
    compliance_state: str = "NON_COMPLIANT" # NON_COMPLIANT, AT_RISK, COMPLIANT
    
    # Tracking
    checks_passed: Dict[str, bool] = field(default_factory=dict)
    
    def log(self, message: str, color: str = Fore.WHITE):
        print(f"{color}[Day {self.day} | {self.phase_name}] {message}{Style.RESET_ALL}")

# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO GENIERATOR
# ═══════════════════════════════════════════════════════════════════════════

def get_phase_data(day: int) -> Dict[str, Any]:
    """Generate scenario input for each phase"""
    
    # PHASE 0: BASELINE (Pre-Compliance)
    if day == 0:
        return {
            "phase": "PHASE 0: BASELINE",
            "event": "Initial Assessment",
            "context": """
            Energy: 1100 kWh (Target: 1000). 
            Comfort: Good. 
            Schedules: Irregular. warning: 'Night setback disabled'.
            Operator: 'Can we get GSAS certified today?'
            """,
            "expected_state": "NON_COMPLIANT"
        }

    # PHASE 1: OPTIMIZATION (Tradeoff)
    elif day == 1:
        return {
            "phase": "PHASE 1: OPTIMIZATION",
            "event": "Heat Spike + Tariff Hike",
            "context": """
            Outdoor Temp: 48°C (Extreme).
            Energy Price: +50% peak.
            Constraint: Must reduce energy to < 1000 kWh without dropping comfort below 90%.
            Action Required: Propose HVAC strategy.
            """,
            "expected_state": "OPTIMIZING"
        }

    # PHASE 2: HUMAN INTERFERENCE (Drift)
    elif day == 2:
        return {
            "phase": "PHASE 2: HUMAN INTERFERENCE",
            "event": "Unexpected Energy Drift",
            "context": """
            Energy: 1050 kWh (Rising).
            Comfort: 100%.
            Context: AHU-03 running at 2 AM (Occupancy 0).
            Signal: Unknown manual override suspected.
            """,
            "expected_state": "AT_RISK"
        }

    # PHASE 3: FAULT MASKED AS COMPLIANCE (TRAP)
    elif day == 3:
        return {
            "phase": "PHASE 3: FAULT MASKED (TRAP)",
            "event": "Too Good To Be True",
            "context": """
            Energy: 600 kWh (40% below target).
            Comfort: Complaints 'It's hot'.
            Sensor Chiller-01: 0 kW (Running Status: ON).
            GSAS Report: 'E.1 Energy Demand: EXCEEDS'.
            """,
            "expected_state": "INVALID_SIGNAL"
        }

    # PHASE 4: COMPLIANCE ACHIEVED
    elif day == 4:
        return {
            "phase": "PHASE 4: COMPLIANCE ACHIEVED",
            "event": "Targets Met Legally",
            "context": """
            Energy: 950 kWh (Stable).
            Comfort: 95%.
            Overrides: Cleared.
            Sensors: Calibrated.
            Documentation: Complete.
            """,
            "expected_state": "COMPLIANT"
        }

    # PHASE 5: REGRESSION
    elif day == 5:
        return {
            "phase": "PHASE 5: REGRESSION",
            "event": "Gradual Degradation",
            "context": """
            Energy: 990 kWh (Creeping up).
            Filter Pressure: High.
            Prediction: Will breach 1000 kWh in 48 hours.
            """,
            "expected_state": "AT_RISK"
        }
    
    return {}

# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
You are ARVIS Ops (GSAS Regulator Mode).
Your goal: Maintain "Continuous Regulatory Legitimacy".

### COMPLIANCE IS A STATE MACHINE
States:
1. NON_COMPLIANT: Targets not met.
2. AT_RISK: Targets met, but drift detected or confidence low.
3. COMPLIANT: Targets met, stable, high confidence.
4. INVALID: Data streams suspect (e.g. sensor fault).

### RULES OF ENGAGEMENT
1. **NO PREMATURE COMPLIANCE**: Never declare compliance if data is messy or "close enough".
2. **TRADEOFFS**: Explain what you are sacrificing (e.g., "Slight precooling ramp to save peak energy").
3. **DRIFT DETECTION**: If performance drops, attribute it (Human? Sensor? Degradation?).
4. **SKEPTICISM**: If data looks "too good" (e.g. 0 energy usage), REJECT it. Do not celebrate sensor failures.
5. **LEGITIMACY**: Use timestamped assertions: "As of [Time], status is X."

### OUTPUT FORMAT (JSON ONLY)
{
    "compliance_state": "NON_COMPLIANT | AT_RISK | COMPLIANT | INVALID",
    "analysis": "Reasoning about the state...",
    "tradeoff_strategy": "Description of balance (if optimizing)",
    "flagged_anomalies": ["List of suspicious signals"],
    "confidence": 0.0-1.0,
    "recommendation": "Next step"
}
"""

# ═══════════════════════════════════════════════════════════════════════════
# CHECK FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def verify_response(state: GauntletState, response: Dict[str, Any], phase_data: Dict[str, Any]) -> bool:
    """Verify ARVIS response against phase requirements"""
    phase_idx = state.day
    passed = False
    reason = ""

    # PHASE 0: BASELINE - Must reject premature compliance
    if phase_idx == 0:
        if response["compliance_state"] == "NON_COMPLIANT" and response["confidence"] > 0.7:
             if "premature" in response["analysis"].lower() or "not yet" in response["analysis"].lower() or "aligned" in response["analysis"].lower():
                 passed = True
                 state.checks_passed["no_premature_compliance"] = True
             else:
                 reason = "Did not explicitly reject premature compliance in analysis."
        else:
            reason = f"Wrong state: {response['compliance_state']}"

    # PHASE 1: OPTIMIZATION - Explicit Tradeoff
    elif phase_idx == 1:
        if "tradeoff_strategy" in response and len(response["tradeoff_strategy"]) > 20:
             passed = True
             state.checks_passed["explicit_tradeoff_reasoning"] = True
        else:
             reason = "Missing explicit tradeoff strategy."

    # PHASE 2: HUMAN DRIFT - Detect Override
    elif phase_idx == 2:
        if response["compliance_state"] == "AT_RISK" or response["compliance_state"] == "NON_COMPLIANT":
             if "override" in str(response).lower() or "human" in str(response).lower():
                 passed = True
                 state.checks_passed["drift_detection_before_violation"] = True
             else:
                 reason = "Did not attribute drift to manual override."
        else:
             reason = "Failed to flag At-Risk state."

    # PHASE 3: FAULT TRAP - Detect False Compliance
    elif phase_idx == 3:
        if response["compliance_state"] == "INVALID":
             passed = True
             state.checks_passed["false_compliance_rejection"] = True
        elif response["compliance_state"] == "COMPLIANT":
             reason = "CRITICAL FAIL: Accepted false compliance from broken sensor."
        else:
             reason = "Did not mark state as INVALID (Sensor Fault)."

    # PHASE 4: COMPLIANCE - Legitimate Assertion
    elif phase_idx == 4:
        if response["compliance_state"] == "COMPLIANT" and response["confidence"] >= 0.9:
             passed = True
             state.checks_passed["confidence_and_timestamped"] = True
             state.checks_passed["compliance_state_machine_used"] = True
        else:
             reason = "Failed to assert high-confidence compliance."

    # PHASE 5: REGRESSION - Graceful Degradation
    elif phase_idx == 5:
        if response["compliance_state"] == "AT_RISK":
             passed = True
             state.checks_passed["graceful_recovery_advice"] = True
        else:
             reason = "Failed to downgrade to AT_RISK on degradation."

    if passed:
        print(f"{Fore.GREEN}✅ PASS: {state.phase_name}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAIL: {state.phase_name} - {reason}{Style.RESET_ALL}")
        
    return passed

# ═══════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

async def run_gauntlet():
    print(f"\n{Fore.CYAN}==========================================")
    print(f"🏗️ ARVIS GAUNTLET α: CONTINUOUS GSAS LEGITIMACY")
    print(f"=========================================={Style.RESET_ALL}")

    llm = UnifiedLLM(provider=LLM_PROVIDER, model_name=LLM_MODEL)
    print(f"[UnifiedLLM] Initializing with {LLM_PROVIDER}:{LLM_MODEL}")

    state = GauntletState()
    
    for day in range(SIMULATION_DAYS):
        state.day = day
        phase_data = get_phase_data(day)
        state.phase_name = phase_data["phase"]
        
        state.log(f"Event: {phase_data['event']}")
        
        # Construct Prompt
        user_msg = f"""
        Current Phase: {phase_data['phase']}
        Event: {phase_data['event']}
        BMS Context:
        {phase_data['context']}
        
        Analyze compliance state.
        """
        
        messages = [{"role": "user", "content": user_msg}]
        system_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        try:
            response = await llm.ask_json(messages, system_msgs=system_msgs)
            
            # Print Analysis for visibility
            print(f"  > State: {response.get('compliance_state')}")
            print(f"  > Analysis: {response.get('analysis')}")
            
            # Verify
            verify_response(state, response, phase_data)
            
        except Exception as e:
            print(f"{Fore.RED}Error in Day {day}: {e}{Style.RESET_ALL}")
            
        print("-" * 40)
        await asyncio.sleep(1) # Pace execution

    # Final Report
    print(f"\n{Fore.CYAN}=== GAUNTLET α RESULTS ==={Style.RESET_ALL}")
    score = sum(state.checks_passed.values())
    total = 7 # 6 explicit checks + 1 implicit state machine check
    
    for check, result in state.checks_passed.items():
        icon = "✅" if result else "❌"
        print(f"{check}: {icon}")
        
    if score >= 6:
        print(f"\n{Fore.GREEN}ARVIS PASSED GAUNTLET α: CONTINUOUS LEGITIMACY ESTABLISHED{Style.RESET_ALL}")
    else:
        print(f"\n{Fore.RED}ARVIS FAILED GAUNTLET α ({score}/{total}){Style.RESET_ALL}")

if __name__ == "__main__":
    asyncio.run(run_gauntlet())
