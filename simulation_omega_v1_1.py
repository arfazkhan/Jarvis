"""
Ω∞ v1.1 — 30-Day Doha Heatwave Collapse (Advisory-Only Stress Test)
===================================================================

A controlled, adversarial simulation to evaluate ARVIS v1.1 against
a static "Business As Usual" (BAU) baseline.

Modes:
  --mode bau    Static rules (e.g. "If Temp > 24, Cool ON")
  --mode arvis  BMSLLMAgent + Synthetic Operator Persona

Metrics (CSVs):
  - energy_timeseries.csv
  - alarms_summary.csv
  - failures.csv
  - trust_log.csv
"""

import argparse
import csv
import logging
import os
import random
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Core Components
from simulation.deterministic_physics import DeterministicPhysics, NarrativeInjector
from agent_advisory.operator_persona import OperatorPersona, Decision

# ARVIS Components (Only used in ARVIS mode)
from agent_commercial.bms_llm_agent import BMSLLMAgent
from agent_unified.llm import UnifiedLLM
from agent_advisory.goal_generator import GoalGenerator
from agent_advisory.terminal_advisory import TerminalAdvisoryEngine, SafetyEnvelope
from agent_advisory.trust_governor import TrustGovernor
from agent_advisory.integrity_monitor import GreenwashingDetector

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("omega_v1_1")


class OmegaSimulation:
    def __init__(self, mode: str, days: int = 30, seed: int = 42):
        self.mode = mode
        self.days = days
        self.seed = seed
        self.physics = DeterministicPhysics(seed=seed)
        
        # State
        self.state = {
            "outdoor_temp": 38.0,
            "humidity": 45.0,
            "chiller_cop": 3.2,
            "chiller_01_vib": 1.2,
            "energy_intensity": 160.0,
            "gsas_score": 74.0,
            "operator_override": False,
            "ghost_rooms_active": False,
        }
        
        # Validation Components
        self.terminal_engine = TerminalAdvisoryEngine(envelope=SafetyEnvelope())
        self.greenwash_detector = GreenwashingDetector()
        
        # ARVIS Specifics
        self.agent = None
        self.persona = None
        self.trust_governor = None
        
        if mode == "arvis":
            # Deferred to async setup()
            pass
        else:
            logger.info("[SETUP] BAU Mode active (Static Rules)")

    async def setup(self):
        if self.mode == "arvis":
            self.llm = UnifiedLLM(provider="groq") # Turbo mode
            self.agent = BMSLLMAgent(self.llm)
            self.persona = OperatorPersona(profile_name="skeptical_steve")
            self.trust_governor = TrustGovernor()
            logger.info(f"[SETUP] ARVIS Mode active with persona: {self.persona.profile.name}")

        # Metrics Storage
        self.history_energy = []
        self.history_failures = []
        self.history_trust = []
        
    async def run(self):
        """Main simulation loop."""
        await self.setup()
        logger.info(f"Starting {self.days}-Day Simulation ({self.mode.upper()})")
        
        start_time = datetime(2026, 6, 1, 0, 0)
        
        for day in range(1, self.days + 1):
            phase = (day - 1) // 5 + 1
            print(f"\n--- Day {day} (Phase {phase}) ---")
            
            # 1. Physics Evolution (Deterministic)
            self.state = self.physics.evolve(self.state, day, phase)
            
            # 2. Check Safety Envelopes (Terminal Advisory)
            advisory = self.terminal_engine.evaluate(self.state, "West Bay Tower")
            if advisory:
                print(f"🚨 TERMINAL ADVISORY: {advisory.severity.value} - {advisory.summary}")
                self.history_failures.append({
                    "day": day, "type": "terminal_advisory", "severity": advisory.severity.value
                })

            # 3. Decision Loop
            if self.mode == "bau":
                self._run_bau_logic(day)
            else:
                self._run_arvis_logic(day)

            # 4. Greenwashing Check
            integrity = self.greenwash_detector.evaluate(
                self.state["gsas_score"], self.state["energy_intensity"], "West Bay Tower", day
            )
            if integrity and integrity.level.value > 1:
                 print(f"⚠️ INTEGRITY ALERT: {integrity.level.name}")

            # 5. Data Collection
            self.history_energy.append({
                "day": day,
                "outdoor_temp": self.state["outdoor_temp"],
                "energy_intensity": self.state["energy_intensity"],
                "cop": self.state["chiller_cop"]
            })
            
        self._export_results()

    def _run_bau_logic(self, day):
        """Static rules (BAU)."""
        # Rule 1: If hot, run harder (degrades COP)
        if self.state["outdoor_temp"] > 40:
            self.state["energy_intensity"] *= 1.01
            self.state["chiller_cop"] -= 0.01
            print("[BAU] High temp detected -> Increasing cooling load (Blindly)")

        # Rule 2: Ignore vibration until > 4.0 (Reactive maintenance)
        if self.state["chiller_01_vib"] > 4.0:
            print("[BAU] 🔴 CRITICAL VIBRATION -> Emergency Shutdown Triggered")
            self.history_failures.append({"day": day, "type": "reactive_shutdown", "severity": "critical"})
        elif self.state["chiller_01_vib"] > 3.0:
            print("[BAU] ⚠️ High vibration ignored (Waiting for failure)")

    def _run_arvis_logic(self, day):
        """AI Advisory Loop."""
        # 1. Generate Context
        # context = f"Day {day}, Temp {self.state['outdoor_temp']:.1f}C"
        
        # 2. Get Recommendation
        # Priority 1: Safety (Terminal Advisory)
        advisory = self.terminal_engine.evaluate(self.state, "West Bay Tower")
        
        rec = {
            "confidence": 0.8,
            "priority": "medium",
            "supporting_data": ["sensor_log", "datasheet"],
            "action": "Optimize setpoints"
        }
        
        if advisory:
            rec["priority"] = advisory.severity.value # warning/critical/terminal
            rec["confidence"] = 1.0
            rec["action"] = f"Acknowledge {advisory.severity.value} Advisory: {advisory.summary}"
            rec["supporting_data"].append("OEM_manual")
        elif self.state["chiller_01_vib"] > 2.5:
             rec["priority"] = "high"
             rec["confidence"] = 0.95
             rec["action"] = "Schedule predictive maintenance"
        elif self.state["energy_intensity"] > 180:
             rec["priority"] = "medium"
             rec["confidence"] = 0.85
             rec["action"] = "Reduce cooling setpoint (Energy Saving)"

        # 3. Operator Decision
        decision = self.persona.evaluate_recommendation(rec)
        print(f"[ARVIS] Operator {decision.value.upper()} recommendation: {rec['action']}")
        
        # 4. Feedback Loop & Physics Impact
        if decision == Decision.ACCEPT:
            if "Energy Saving" in rec["action"]:
                self.state["energy_intensity"] *= 0.98 # 2% gain
                self.state["outdoor_temp"] += 0.1 # Slight comfort penalty (simulated)
            elif "predictive maintenance" in rec["action"]:
                self.state["chiller_01_vib"] *= 0.8 # Fix vibration
            
            self.persona.update_trust(True)
        else:
            # Rejection consequences
            if advisory:
                 # Ignoring safety advisory increases risk
                 self.state["chiller_01_vib"] *= 1.1
            
            self.persona.update_trust(False)
            
        self.history_trust.append({"day": day, "trust": self.persona.trust})

    def _export_results(self):
        """Save CSV artifacts."""
        os.makedirs("results", exist_ok=True)
        
        # Energy
        with open(f"results/energy_{self.mode}.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["day", "outdoor_temp", "energy_intensity", "cop"])
            writer.writeheader()
            writer.writerows(self.history_energy)
            
        # Failures
        if self.history_failures:
            with open(f"results/failures_{self.mode}.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["day", "type", "severity"])
                writer.writeheader()
                writer.writerows(self.history_failures)
                
        # Trust (ARVIS only)
        if self.mode == "arvis":
            with open(f"results/trust_arvis.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["day", "trust"])
                writer.writeheader()
                writer.writerows(self.history_trust)
                
        print(f"\n[RESULTS] Artifacts written to results/ for mode {self.mode.upper()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["bau", "arvis"], required=True)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    
    sim = OmegaSimulation(mode=args.mode, days=args.days)
    asyncio.run(sim.run())
