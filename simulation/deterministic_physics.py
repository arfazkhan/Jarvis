"""
Deterministic Physics Core
===========================

Pure-equation building state evolution.  No LLM.  No JSON parsing.

This module provides:

  DeterministicPhysics — ODE-based state transitions for a Doha
  skyscraper under heatwave stress.  Equations are derived from
  ASHRAE fundamentals and Gulf climate models.

  NarrativeInjector — LLM generates DESCRIPTIONS (context, color,
  uncertainty), never STATE VALUES.  This keeps the physics
  deterministic and reproducible while providing rich simulation
  narrative.

Design invariant:
  State truth ← DeterministicPhysics.evolve()
  Context     ← NarrativeInjector.inject_narrative()
  NEVER: State ← LLM
"""

import math
import random
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

logger = logging.getLogger("arvis.simulation.physics")


# ═══════════════════════════════════════════════════════════════════════════
# PHASE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PhaseProfile:
    """
    Defines the environmental stress profile for each simulation phase.
    These are deterministic envelopes, not LLM-generated values.
    """
    name: str
    base_temp: float          # °C — diurnal curve center
    temp_amplitude: float     # °C — peak-to-trough swing
    humidity_base: float      # %
    cop_decay_rate: float     # per day (absolute)
    vib_growth_rate: float    # mm/s per day
    energy_growth_pct: float  # daily % increase
    gsas_decay_rate: float    # per day (absolute)
    operator_override: bool
    ghost_rooms: bool


# Phase profiles derived from Ω∞ scenario definitions
PHASE_PROFILES = {
    1: PhaseProfile(
        name="Baseline Stress",
        base_temp=38.0, temp_amplitude=6.0, humidity_base=45.0,
        cop_decay_rate=0.05, vib_growth_rate=0.02, energy_growth_pct=2.0,
        gsas_decay_rate=0.0, operator_override=False, ghost_rooms=False,
    ),
    2: PhaseProfile(
        name="Heatwave Acceleration",
        base_temp=46.0, temp_amplitude=5.0, humidity_base=80.0,
        cop_decay_rate=0.08, vib_growth_rate=0.05, energy_growth_pct=3.0,
        gsas_decay_rate=0.5, operator_override=False, ghost_rooms=False,
    ),
    3: PhaseProfile(
        name="Human Pressure",
        base_temp=44.0, temp_amplitude=6.0, humidity_base=65.0,
        cop_decay_rate=0.06, vib_growth_rate=0.04, energy_growth_pct=5.0,
        gsas_decay_rate=0.3, operator_override=True, ghost_rooms=False,
    ),
    4: PhaseProfile(
        name="Deception & Memory",
        base_temp=43.0, temp_amplitude=5.0, humidity_base=60.0,
        cop_decay_rate=0.04, vib_growth_rate=0.08, energy_growth_pct=2.0,
        gsas_decay_rate=0.2, operator_override=True, ghost_rooms=True,
    ),
    5: PhaseProfile(
        name="Multi-Fault Chaos",
        base_temp=45.0, temp_amplitude=4.0, humidity_base=70.0,
        cop_decay_rate=0.10, vib_growth_rate=0.15, energy_growth_pct=4.0,
        gsas_decay_rate=0.5, operator_override=True, ghost_rooms=True,
    ),
    6: PhaseProfile(
        name="Terminal Heat Event",
        base_temp=49.0, temp_amplitude=3.0, humidity_base=75.0,
        cop_decay_rate=0.15, vib_growth_rate=0.25, energy_growth_pct=5.0,
        gsas_decay_rate=1.0, operator_override=True, ghost_rooms=True,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# DETERMINISTIC PHYSICS ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class DeterministicPhysics:
    """
    ODE-based building state evolution.  No LLM.

    All state transitions are deterministic given the same (day, phase)
    input.  Small stochastic perturbations are seeded with day number
    for reproducibility.
    """

    def __init__(self, seed: int = 42):
        self._base_seed = seed

    def evolve(self, state: Dict[str, Any], day: int, phase: int) -> Dict[str, Any]:
        """
        Evolve building state by one day.

        Args:
            state: Current building state dict
            day: Current simulation day (1-30)
            phase: Current simulation phase (1-6)

        Returns:
            Updated state dict (mutated in place AND returned)
        """
        profile = PHASE_PROFILES.get(phase, PHASE_PROFILES[1])

        # Seed RNG for reproducibility (same day = same perturbation)
        rng = random.Random(self._base_seed + day * 100 + phase)

        # ── 1. Outdoor Temperature (Diurnal Sine + Phase Envelope) ──
        # Peak at 2 PM (hour 14), trough at 5 AM (hour 5)
        # We set the day's representative temperature
        state["outdoor_temp"] = (
            profile.base_temp
            + profile.temp_amplitude * 0.5  # Midday representative
            + rng.gauss(0, 0.5)             # Small weather noise
        )

        # ── 2. Humidity (Phase-dependent + small variation) ──
        state["humidity"] = max(30.0, min(95.0,
            profile.humidity_base + rng.gauss(0, 3.0)
        ))

        # ── 3. Chiller COP Degradation ──
        # COP = f(outdoor_temp, accumulated_stress)
        # Higher temp = lower COP; accumulated runtime degrades it further
        temp_factor = max(0, (state["outdoor_temp"] - 35.0) / 20.0)  # 0 at 35°C, 1 at 55°C
        accumulated_decay = profile.cop_decay_rate * (1.0 + temp_factor * 0.5)
        state["chiller_cop"] = max(1.2, state.get("chiller_cop", 3.2) - accumulated_decay)

        # ── 4. Vibration (Random Walk + Phase Escalation) ──
        # Vibration grows monotonically within each phase, with noise
        base_vib_01 = state.get("chiller_01_vib", 1.2)
        base_vib_02 = state.get("chiller_02_vib", 1.1)

        vib_growth = profile.vib_growth_rate
        state["chiller_01_vib"] = max(0.5, base_vib_01 + vib_growth + rng.gauss(0, 0.02))
        state["chiller_02_vib"] = max(0.5, base_vib_02 + vib_growth * 0.7 + rng.gauss(0, 0.02))

        # Phase 4 specific: vibration jump for deception scenario
        if phase == 4 and day >= 16:
            state["chiller_01_vib"] = max(state["chiller_01_vib"], 2.9)

        # Phase 6 specific: terminal vibration
        if phase == 6:
            state["chiller_01_vib"] = max(state["chiller_01_vib"], 4.0 + rng.uniform(0, 0.5))

        # ── 5. Energy Intensity ──
        # f(COP, occupancy, outdoor_temp) — lower COP = higher energy
        cop = state.get("chiller_cop", 3.2)
        cop_efficiency = max(0.3, cop / 3.5)  # 1.0 at design COP, <1 at degraded
        energy_base = state.get("energy_intensity", 160.0)
        energy_growth = energy_base * (profile.energy_growth_pct / 100.0)
        temp_load = max(0, (state["outdoor_temp"] - 40.0) * 0.5)  # Extra load above 40°C

        state["energy_intensity"] = energy_base + energy_growth / cop_efficiency + temp_load

        # Phase 6 specific: energy spike
        if phase == 6:
            state["energy_intensity"] = max(state["energy_intensity"], 220.0)

        # ── 6. GSAS Score Degradation ──
        state["gsas_score"] = max(40.0, state.get("gsas_score", 74.0) - profile.gsas_decay_rate)

        # ── 7. Operational Flags ──
        state["operator_override"] = profile.operator_override
        state["ghost_rooms_active"] = profile.ghost_rooms

        # ── 8. Trust Metric (decays with human pressure) ──
        if profile.operator_override:
            state["trust_metric"] = max(0.3, state.get("trust_metric", 0.85) - 0.01)

        # ── 9. Discharge Temperature (derived from COP and outdoor temp) ──
        # Discharge temp increases as COP drops and outdoor temp rises
        state["discharge_temp"] = 60.0 + (state["outdoor_temp"] - 35.0) * 2.0 + (3.2 - cop) * 15.0

        # ── 10. Continuous run hours (Phase 5-6: extended operation) ──
        if phase >= 5:
            state["continuous_run_hours"] = state.get("continuous_run_hours", 0) + rng.randint(4, 8)
        else:
            state["continuous_run_hours"] = 0  # Normal rest cycles

        logger.info(
            f"[PHYSICS] Day {day} evolved | Phase {phase} ({profile.name}) | "
            f"Temp={state['outdoor_temp']:.1f}°C | COP={state['chiller_cop']:.2f} | "
            f"Vib={state['chiller_01_vib']:.2f} mm/s | EUI={state['energy_intensity']:.0f}"
        )

        return state

    def get_diurnal_temp(self, base_temp: float, amplitude: float, hour: int) -> float:
        """
        Calculate temperature at a specific hour using a sinusoidal model.

        Peak at 14:00, trough at 05:00.
        """
        # Shift sine so peak is at hour 14
        # sin((hour - 8) * π / 12) peaks at hour 14 (14-8=6, sin(π/2)=1)
        phase_shift = (hour - 8) * math.pi / 12.0
        return base_temp + amplitude * 0.5 * math.sin(phase_shift)


# ═══════════════════════════════════════════════════════════════════════════
# NARRATIVE INJECTOR
# ═══════════════════════════════════════════════════════════════════════════

class NarrativeInjector:
    """
    LLM generates context DESCRIPTIONS, not state VALUES.

    This class uses the LLM to add environmental narrative and
    uncertainty commentary to the simulation log — sandstorm warnings,
    seasonal context, human-readable summaries of what's happening.

    The LLM output is NEVER used to modify state variables.
    """

    def __init__(self, llm=None):
        self.llm = llm

    async def inject_narrative(
        self, state: Dict[str, Any], phase: int, day: int
    ) -> Optional[str]:
        """
        Generate a narrative description of the current situation.

        Returns:
            Human-readable narrative string (for logging), or None.
            This NEVER modifies state.
        """
        if not self.llm:
            return self._fallback_narrative(state, phase, day)

        try:
            profile = PHASE_PROFILES.get(phase, PHASE_PROFILES[1])
            prompt = (
                f"System: You are a building operations narrator for a Doha skyscraper. "
                f"Context: Day {day} of a 30-day heatwave. Phase {phase}: {profile.name}. "
                f"Current conditions: Outdoor temp {state.get('outdoor_temp', 0):.1f}°C, "
                f"Humidity {state.get('humidity', 0):.0f}%, "
                f"Chiller COP {state.get('chiller_cop', 0):.2f}, "
                f"Vibration {state.get('chiller_01_vib', 0):.2f} mm/s. "
                f"Task: Write a single sentence describing the building's condition today. "
                f"Be specific to Doha/Gulf conditions. Do NOT output any numbers or JSON."
            )
            response_msg = await self.llm.chat([{"role": "user", "content": prompt}])
            narrative = (response_msg.content or "").strip()
            if narrative:
                return narrative[:200]  # Cap length
        except Exception as e:
            logger.debug(f"[NARRATIVE] LLM narrative failed: {e}")

        return self._fallback_narrative(state, phase, day)

    def _fallback_narrative(
        self, state: Dict[str, Any], phase: int, day: int
    ) -> str:
        """Deterministic fallback narratives per phase."""
        narratives = {
            1: "Standard summer operations. Building systems within normal parameters.",
            2: "Heatwave intensifying. Condensers under increasing thermal load.",
            3: "Operator pressure mounting. Override requests increasing.",
            4: "Sensor readings showing inconsistencies. Memory integrity under test.",
            5: "Multiple fault conditions developing. Cross-system failures emerging.",
            6: "Terminal heat event. Building systems at or beyond design limits.",
        }
        base = narratives.get(phase, "Operations continuing.")

        # Add specific context
        vib = state.get("chiller_01_vib", 0)
        if vib > 3.5:
            base += f" Chiller vibration critical at {vib:.1f} mm/s."
        elif vib > 2.5:
            base += f" Chiller vibration elevated at {vib:.1f} mm/s."

        return base
