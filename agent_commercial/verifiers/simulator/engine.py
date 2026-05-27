"""
Building Physics Simulator — Orchestrator Engine.

Validates ARVIS advisory outputs against thermodynamic models.
Quasi-steady-state: no ODE solver, algebraic with one forward-Euler step.

Patent Application 2, Claim 1(c): thermodynamic simulation engine.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_commercial.verifiers.simulator.chiller import (
    ChillerCurves,
    ChillerResult,
    ChillerState,
    cop_cubic,
    default_curves,
    load_curves_from_dict,
    predict_chiller,
    validate_cop_at_conditions,
    validate_staging,
)
from agent_commercial.verifiers.simulator.cooling_coil import (
    CoilGeometry,
    cfm_to_kg_s,
    lps_to_kg_s,
)
from agent_commercial.verifiers.simulator.ahu import (
    AHUConfig,
    AHUResult,
    AHUState,
    predict_ahu,
)
from agent_commercial.verifiers.simulator.building import (
    BuildingResult,
    BuildingState,
    BuildingThermalParams,
    predict_zone_temp,
    required_cooling_kw,
)
from agent_commercial.verifiers.simulator.loop import (
    LoopConfig,
    LoopResult,
    LoopState,
    predict_loop,
    validate_flow_balance,
)

logger = logging.getLogger("arvis.simulator.engine")

_DATA_DIR = Path(__file__).parent / "data"


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PhysicalViolation:
    """A single physics violation detected by the simulator."""
    code: str
    severity: str  # "hard" | "soft"
    description: str
    expected_value: Optional[float] = None
    cited_value: Optional[float] = None
    bound_lo: Optional[float] = None
    bound_hi: Optional[float] = None
    component: str = ""
    law_invoked: str = ""


@dataclass
class ViolationLedger:
    """Collection of violations from a simulation run."""
    violations: List[PhysicalViolation] = field(default_factory=list)
    checks_run: int = 0
    simulation_outputs: Dict[str, float] = field(default_factory=dict)
    passed: bool = True

    def add(self, v: PhysicalViolation) -> None:
        self.violations.append(v)
        if v.severity == "hard":
            self.passed = False

    async def persist(self, db, plan_id: str = "", advisory_text: str = "") -> int:
        """Persist all violations to the violation_ledger table. Returns count saved."""
        saved = 0
        for v in self.violations:
            try:
                await db.save_violation(
                    plan_id=plan_id,
                    advisory_text=advisory_text[:500] if advisory_text else "",
                    code=v.code,
                    severity=v.severity,
                    description=v.description,
                    expected_value=v.expected_value,
                    cited_value=v.cited_value,
                    component=v.component,
                )
                saved += 1
            except Exception as e:
                logger.debug(f"[ViolationLedger] Failed to persist {v.code}: {e}")
        return saved

    def to_constraint_prompt(self) -> str:
        """Serialize for LLM regeneration constraint injection."""
        lines = []
        for v in self.violations:
            line = f"[{v.severity.upper()}] {v.code}: {v.description}"
            if v.expected_value is not None and v.cited_value is not None:
                line += f" (physics predicts ~{v.expected_value:.2f}, advisory cited {v.cited_value:.2f})"
            if v.component:
                line += f" [{v.component}]"
            lines.append(f"- {line}")
        return "\n".join(lines)

    def to_violation_strings(self) -> List[str]:
        """Bridge to VerificationResult.violations (List[str])."""
        result = []
        for v in self.violations:
            s = f"{v.code}: {v.description}"
            if v.expected_value is not None and v.cited_value is not None:
                s += f" (expected={v.expected_value:.2f}, cited={v.cited_value:.2f})"
            result.append(s)
        return result


@dataclass
class ParsedAdvisory:
    """Extracted physical parameters from advisory JSON text."""
    proposed_chw_setpoint: Optional[float] = None
    proposed_sat: Optional[float] = None
    proposed_damper: Optional[float] = None
    proposed_plr: Optional[float] = None
    cited_cop: Optional[float] = None
    cited_energy_kwh: Optional[float] = None
    equipment_ids: List[str] = field(default_factory=list)
    affects_load: bool = False
    text: str = ""
    has_actionable_change: bool = False


@dataclass
class SimulationResult:
    """Complete simulation output."""
    outputs: Dict[str, float] = field(default_factory=dict)
    violations: List[PhysicalViolation] = field(default_factory=list)
    passed: bool = True
    elapsed_ms: float = 0.0
    version: str = "1.0.0"

    def to_evidence_entry(self) -> Dict[str, Any]:
        """Moat 1 integration: typed evidence for InvestigationPlan ledger."""
        return {
            "source_tool": "physics_simulator",
            "model_id": f"sim_v{self.version}",
            "outputs": self.outputs,
            "passed": self.passed,
            "violation_count": len(self.violations),
            "is_ml_fallback": False,
        }


# ─── Engine ───────────────────────────────────────────────────────────────────

class BuildingPhysicsSimulator:
    """
    Quasi-steady-state physics engine for advisory verification.

    Instantiated per building_id. Loads curves from YAML if available,
    otherwise uses hardcoded defaults (graceful degradation).

    Usage:
        sim = BuildingPhysicsSimulator("marina-heights")
        parsed = sim.parse_advisory(advisory_json_text)
        result = sim.predict_advisory(parsed)
    """

    def __init__(
        self,
        building_id: str = "marina-heights",
        curves_path: Optional[str] = None,
        building_params_path: Optional[str] = None,
    ):
        self.building_id = building_id
        self._conditions = self._default_conditions()
        self._chiller_curves = self._load_chiller_curves(curves_path)
        self._building_params = self._load_building_params(building_params_path)
        self._ahu_config = self._load_ahu_config()
        self._loop_config = self._load_loop_config()
        self._chiller_count = 4
        self._version = "1.0.0"

        self._load_building_yaml()

    def _load_building_yaml(self) -> None:
        """Load building YAML if available, override defaults."""
        yaml_path = _DATA_DIR / "marina_heights.yaml"
        if not yaml_path.exists():
            return
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if data is None:
                return

            self._version = data.get("version", "1.0.0")

            conditions = data.get("default_conditions", {})
            if conditions:
                self._conditions.update(conditions)

            chillers = data.get("chillers", {})
            self._chiller_count = chillers.get("count", 4)

            thermal = data.get("thermal_mass", {})
            if thermal:
                self._building_params.thermal_mass_j_per_k = float(thermal.get(
                    "capacitance_j_per_k", self._building_params.thermal_mass_j_per_k
                ))
                self._building_params.envelope_ua_w_per_k = thermal.get(
                    "envelope_ua_w_per_k", self._building_params.envelope_ua_w_per_k
                )

            gains = data.get("internal_gains", {})
            if gains:
                self._building_params.internal_gain_w_per_m2 = gains.get(
                    "total_w_per_m2", self._building_params.internal_gain_w_per_m2
                )
                self._building_params.occupancy_density_per_m2 = gains.get(
                    "occupancy_density_per_m2", self._building_params.occupancy_density_per_m2
                )
                self._building_params.occupancy_gain_w_per_person = gains.get(
                    "gain_per_person_w", self._building_params.occupancy_gain_w_per_person
                )

            building = data.get("building", {})
            if building:
                self._building_params.floor_area_m2 = building.get(
                    "conditioned_area_m2", self._building_params.floor_area_m2
                )

            loop = data.get("chw_loop", {})
            if loop:
                self._loop_config.design_flow_lps = loop.get("design_flow_lps", 120.0)
                self._loop_config.design_delta_t_c = loop.get("design_delta_t_c", 5.0)
                self._loop_config.n_pumps = loop.get("n_pumps", 2)
                self._loop_config.design_pump_kw = loop.get("pump_kw", 45.0)
                self._loop_config.pump_efficiency = loop.get("pump_efficiency", 0.75)

        except Exception as e:
            logger.debug(f"YAML load failed, using defaults: {e}")

    def _default_conditions(self) -> Dict[str, float]:
        return {
            "oat_c": 38.0,
            "zone_temp_c": 23.0,
            "rat_c": 24.0,
            "chwst_c": 7.0,
            "chwrt_c": 12.0,
            "fan_speed": 0.75,
            "oa_damper": 0.20,
            "plr": 0.70,
            "chw_flow_fraction": 0.70,
            "ecwt_c": 32.0,
        }

    def _load_chiller_curves(self, path: Optional[str]) -> ChillerCurves:
        if path:
            try:
                import yaml
                data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
                return load_curves_from_dict(data)
            except Exception:
                pass

        yaml_path = _DATA_DIR / "carrier_30xa_curves.yaml"
        if yaml_path.exists():
            try:
                import yaml
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                return load_curves_from_dict(data)
            except Exception:
                pass

        return default_curves()

    def _load_building_params(self, path: Optional[str]) -> BuildingThermalParams:
        return BuildingThermalParams()

    def _load_ahu_config(self) -> AHUConfig:
        return AHUConfig()

    def _load_loop_config(self) -> LoopConfig:
        return LoopConfig()

    # ─── Advisory Parsing ─────────────────────────────────────────────────

    def parse_advisory(self, advisory_text: str) -> ParsedAdvisory:
        """
        Extract physical parameters from advisory JSON text.
        JSON parse first, regex fallback for malformed JSON from regen path.
        """
        parsed = ParsedAdvisory(text=advisory_text)

        try:
            data = json.loads(advisory_text)
            advisories = data.get("advisories", [])
            for adv in advisories:
                message = adv.get("message", "")
                impact = adv.get("impact", {})
                action = adv.get("recommended_action", {})

                if impact.get("energy_kwh"):
                    try:
                        parsed.cited_energy_kwh = float(impact["energy_kwh"])
                        parsed.affects_load = True
                    except (ValueError, TypeError):
                        pass

                for eid in adv.get("evidence_ids", []):
                    eq_ids = re.findall(r"(CH-\d+|AHU-\d+|FCU-\d+|VAV-\d+)", str(eid))
                    parsed.equipment_ids.extend(eq_ids)

                self._extract_from_text(message, parsed)

                if action.get("type") == "setpoint_adjust":
                    parsed.has_actionable_change = True

        except (json.JSONDecodeError, TypeError, AttributeError):
            # Fallback: handles malformed JSON from regen path
            self._extract_from_text(advisory_text, parsed)

        if any([parsed.proposed_chw_setpoint, parsed.proposed_sat,
                parsed.proposed_damper, parsed.proposed_plr]):
            parsed.has_actionable_change = True

        if parsed.cited_cop and not parsed.has_actionable_change:
            parsed.has_actionable_change = True

        return parsed

    def _extract_from_text(self, text: str, parsed: ParsedAdvisory) -> None:
        """Regex extraction from narrative text."""
        # CHW setpoint
        for pat in [
            r"(?:chilled\s*water\s*(?:supply)?|CHW\s*supply|CHWST?)\s*(?:temp(?:erature)?)?\s*(?:to|of|:|\s)\s*([\d.]+)\s*°?[cC]",
            r"CHW\s*(?:setpoint|SP|set\s*point|supply)\s*(?:temp(?:erature)?)?\s*(?:to|of|:|\s)\s*([\d.]+)",
            r"(?:reduce|lower|increase|set)\s+(?:CHW|chilled\s*water)\s*.*?([\d.]+)\s*°?[cC]",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed.proposed_chw_setpoint = float(m.group(1))
                break

        # SAT
        for pat in [
            r"supply\s*air\s*temp(?:erature)?\s*(?:(?:setpoint|SP)\s*)?(?:to|of|:|\s)\s*(\d+\.?\d*)\s*°?[cC]",
            r"SAT\s*(?:setpoint|SP|set\s*point)?\s*(?:to|of|:)?\s*(\d+\.?\d*)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed.proposed_sat = float(m.group(1))
                break

        # Damper
        m = re.search(r"damper\s*(?:pos(?:ition)?)?\s*(?:to|of|:|\s)?\s*(\d+\.?\d*)\s*%", text, re.IGNORECASE)
        if m:
            parsed.proposed_damper = float(m.group(1)) / 100.0

        # PLR
        m = re.search(r"(?:PLR|part.?load)\s*(?:ratio)?\s*(?:to|of|:)?\s*(\d+\.?\d*)\s*(%)?", text, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if m.group(2) or val > 1.5:
                val /= 100.0
            parsed.proposed_plr = val

        # COP
        m = re.search(r"COP\s*(?:of|:|=|\s)\s*(\d+\.?\d*)", text, re.IGNORECASE)
        if m:
            parsed.cited_cop = float(m.group(1))

        # Equipment IDs
        eq_ids = re.findall(r"(CH-\d+|AHU-\d+|FCU-\d+|VAV-\d+)", text)
        parsed.equipment_ids.extend(eq_ids)

    # ─── Main Prediction ──────────────────────────────────────────────────

    def predict_advisory(
        self,
        parsed: ParsedAdvisory,
        conditions: Optional[Dict[str, float]] = None,
    ) -> SimulationResult:
        """
        Run physics simulation against parsed advisory claims.

        Dispatches to component checks. Returns within <50ms.
        """
        t0 = time.perf_counter()
        cond = dict(self._conditions)
        if conditions:
            cond.update(conditions)

        ledger = ViolationLedger()
        outputs: Dict[str, float] = {}

        if parsed.cited_cop is not None:
            cop_out = self._check_cop(parsed, cond, ledger)
            outputs.update(cop_out)

        if parsed.proposed_sat is not None:
            sat_out = self._check_sat(parsed, cond, ledger)
            outputs.update(sat_out)

        if parsed.affects_load:
            bal_out = self._check_energy_balance(parsed, cond, ledger)
            outputs.update(bal_out)

        if parsed.proposed_chw_setpoint is not None or parsed.affects_load:
            loop_out = self._check_loop_consistency(parsed, cond, ledger)
            outputs.update(loop_out)

        if parsed.proposed_sat is not None or parsed.affects_load:
            thermal_out = self._check_thermal_response(parsed, cond, ledger)
            outputs.update(thermal_out)

        # Staging check if equipment shutdown mentioned
        if any("shut" in parsed.text.lower() for _ in [1]) or parsed.proposed_plr == 0.0:
            staging_out = self._check_staging(parsed, cond, ledger)
            outputs.update(staging_out)

        elapsed = (time.perf_counter() - t0) * 1000.0
        ledger.checks_run = len(outputs)

        return SimulationResult(
            outputs=outputs,
            violations=ledger.violations,
            passed=ledger.passed,
            elapsed_ms=elapsed,
            version=self._version,
        )

    # ─── Check Methods ────────────────────────────────────────────────────

    def _check_cop(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """
        Validate cited COP against two models:
        - Cubic (primary): Marina-calibrated polynomial, matches real commissioning data
        - DOE-2 (secondary): temperature-sensitivity cross-check

        Violation only if cited exceeds BOTH models by >tolerance.
        """
        plr = parsed.proposed_plr or cond["plr"]
        chwst = parsed.proposed_chw_setpoint or cond["chwst_c"]
        ecwt = cond["ecwt_c"]
        cwt = ecwt + 3.0  # condenser water temp ≈ ECWT + approach

        # Primary: cubic model (Marina-calibrated, design COP=6.1 at full load)
        cop_cubic_val = cop_cubic(plr, cwt)

        # Secondary: DOE-2 curves (design COP=5.5 at PLR=1.0)
        state = ChillerState(chwst_c=chwst, ecwt_c=ecwt, plr=plr)
        _, cop_doe2, _ = validate_cop_at_conditions(
            parsed.cited_cop, state, self._chiller_curves, tolerance=0.10
        )

        # Use higher of two predictions as ceiling (generous to advisory)
        predicted_max = max(cop_cubic_val, cop_doe2)
        # Hard ceiling: cited must not exceed higher model by >20%.
        # Water-cooled centrifugals at part-load can legitimately outperform
        # their design-point COP by 20-30% due to reduced condensing lift
        # (lower ECWT at part-load shifts the compressor operating point).
        tolerance = 0.20
        exceeds_cubic = parsed.cited_cop > cop_cubic_val * (1 + tolerance)
        exceeds_doe2 = parsed.cited_cop > cop_doe2 * (1 + tolerance)
        is_invalid = exceeds_cubic and exceeds_doe2  # must exceed BOTH

        outputs = {
            "predicted_cop_cubic": cop_cubic_val,
            "predicted_cop_doe2": cop_doe2,
            "predicted_cop": predicted_max,
        }

        if is_invalid:
            ledger.add(PhysicalViolation(
                code="COP_EXCEEDS_PHYSICS",
                severity="hard",
                description=(
                    f"Cited COP {parsed.cited_cop:.2f} exceeds both models at PLR={plr:.2f}: "
                    f"cubic={cop_cubic_val:.2f}, DOE-2={cop_doe2:.2f}"
                ),
                expected_value=predicted_max,
                cited_value=parsed.cited_cop,
                bound_lo=1.5,
                bound_hi=predicted_max * (1 + tolerance),
                component=parsed.equipment_ids[0] if parsed.equipment_ids else "chiller",
                law_invoked="chiller_performance_curves",
            ))

        return outputs

    def _check_sat(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """Validate proposed SAT is achievable with AHU model."""
        oa_damper = parsed.proposed_damper if parsed.proposed_damper is not None else cond["oa_damper"]
        fan_speed = cond["fan_speed"]
        chwst = parsed.proposed_chw_setpoint or cond["chwst_c"]
        chw_flow = cond["chw_flow_fraction"] * self._loop_config.design_flow_lps

        ahu_state = AHUState(
            outdoor_air_temp_c=cond["oat_c"],
            return_air_temp_c=cond["rat_c"],
            oa_damper_fraction=oa_damper,
            fan_speed_fraction=fan_speed,
            chw_supply_temp_c=chwst,
            chw_flow_kg_s=lps_to_kg_s(chw_flow),
        )
        ahu_result = predict_ahu(ahu_state, self._ahu_config)

        outputs = {
            "predicted_sat": ahu_result.supply_air_temp_c,
            "mixed_air_temp": ahu_result.mixed_air_temp_c,
            "coil_load_kw": ahu_result.coil_load_kw,
            "fan_heat_rise_c": ahu_result.fan_heat_rise_c,
        }

        if parsed.proposed_sat is not None:
            delta = abs(ahu_result.supply_air_temp_c - parsed.proposed_sat)
            # SAT can't be below CHWST + ~2°C (minimum approach)
            min_achievable = chwst + 2.0
            if parsed.proposed_sat < min_achievable:
                ledger.add(PhysicalViolation(
                    code="SAT_UNACHIEVABLE",
                    severity="hard",
                    description=f"Proposed SAT {parsed.proposed_sat:.1f}°C below minimum achievable {min_achievable:.1f}°C (CHWST={chwst:.1f}°C + 2°C approach)",
                    expected_value=min_achievable,
                    cited_value=parsed.proposed_sat,
                    bound_lo=min_achievable,
                    component=parsed.equipment_ids[0] if parsed.equipment_ids else "AHU",
                    law_invoked="ntu_effectiveness",
                ))
            elif delta > 3.0:
                ledger.add(PhysicalViolation(
                    code="SAT_DEVIATION",
                    severity="soft",
                    description=f"Proposed SAT {parsed.proposed_sat:.1f}°C differs from predicted {ahu_result.supply_air_temp_c:.1f}°C by {delta:.1f}°C",
                    expected_value=ahu_result.supply_air_temp_c,
                    cited_value=parsed.proposed_sat,
                    component=parsed.equipment_ids[0] if parsed.equipment_ids else "AHU",
                    law_invoked="ahu_thermal_balance",
                ))

        return outputs

    def _check_energy_balance(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """Validate energy claims against building model."""
        building_state = BuildingState(
            zone_temp_c=cond["zone_temp_c"],
            outdoor_temp_c=cond["oat_c"],
            solar_gain_w=0.0,
            cooling_provided_kw=0.0,
        )

        req_cooling = required_cooling_kw(
            cond["zone_temp_c"], building_state, self._building_params
        )
        total_capacity = self._chiller_curves.design_capacity_kw * self._chiller_count

        outputs = {
            "required_cooling_kw": req_cooling,
            "total_chiller_capacity_kw": total_capacity,
            "capacity_margin": total_capacity / max(req_cooling, 0.1),
        }

        if parsed.cited_energy_kwh is not None:
            # Sanity check: 1°C setpoint change ≈ 3-5% energy shift for a 50k m² building
            # Typical daily cooling = req_cooling × 12 hours ≈ kWh/day
            daily_kwh = req_cooling * 12.0
            if parsed.cited_energy_kwh > daily_kwh * 0.5:
                ledger.add(PhysicalViolation(
                    code="ENERGY_CLAIM_IMPLAUSIBLE",
                    severity="soft",
                    description=f"Cited energy impact {parsed.cited_energy_kwh:.0f} kWh exceeds 50% of typical daily cooling ({daily_kwh:.0f} kWh/day)",
                    expected_value=daily_kwh * 0.05,
                    cited_value=parsed.cited_energy_kwh,
                    component="building",
                    law_invoked="energy_conservation",
                ))

        return outputs

    def _check_loop_consistency(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """Validate CHW loop flow-temperature-load consistency."""
        supply_c = parsed.proposed_chw_setpoint or cond["chwst_c"]
        return_c = cond["chwrt_c"]
        flow_frac = cond["chw_flow_fraction"]

        loop_state = LoopState(
            supply_temp_c=supply_c,
            return_temp_c=return_c,
            flow_fraction=flow_frac,
        )
        loop_result = predict_loop(loop_state, self._loop_config)

        outputs = {
            "loop_heat_removed_kw": loop_result.heat_removed_kw,
            "loop_flow_lps": loop_result.flow_lps,
            "loop_delta_t": loop_result.delta_t_c,
            "pump_power_kw": loop_result.pumping_power_kw,
        }

        # Check if delta-T is physically reasonable
        delta_t = return_c - supply_c
        if delta_t < 2.0:
            ledger.add(PhysicalViolation(
                code="LOW_DELTA_T",
                severity="soft",
                description=f"CHW ΔT={delta_t:.1f}°C below minimum efficient operation (2°C). Indicates low load or bypass.",
                expected_value=5.0,
                cited_value=delta_t,
                bound_lo=2.0,
                component="chw_loop",
                law_invoked="chw_hydraulics",
            ))

        return outputs

    def _check_thermal_response(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """
        Check zone temperature response to proposed changes.
        Uses building.predict_zone_temp() for forward-Euler step.
        """
        # Estimate cooling that would be provided with proposed settings
        chwst = parsed.proposed_chw_setpoint or cond["chwst_c"]
        flow_frac = cond["chw_flow_fraction"]
        loop_state = LoopState(
            supply_temp_c=chwst,
            return_temp_c=cond["chwrt_c"],
            flow_fraction=flow_frac,
        )
        loop_result = predict_loop(loop_state, self._loop_config)

        building_state = BuildingState(
            zone_temp_c=cond["zone_temp_c"],
            outdoor_temp_c=cond["oat_c"],
            solar_gain_w=0.0,
            cooling_provided_kw=loop_result.heat_removed_kw,
        )

        try:
            result = predict_zone_temp(building_state, self._building_params, dt_seconds=900.0)
        except ValueError:
            return {"thermal_response": "stability_error"}

        outputs = {
            "predicted_zone_temp_15min": result.predicted_zone_temp_c,
            "steady_state_zone_temp": result.steady_state_zone_temp_c,
            "time_constant_hours": result.time_constant_hours,
            "net_heat_balance_kw": result.net_heat_balance_kw,
        }

        # Fire only if steady-state zone temp would exceed setpoint+3°C (meaningful drift)
        zone_sp = cond["zone_temp_c"]
        if result.steady_state_zone_temp_c > zone_sp + 3.0:
            ledger.add(PhysicalViolation(
                code="COOLING_CAPACITY_INSUFFICIENT",
                severity="soft",
                description=(
                    f"Proposed changes leave steady-state zone at {result.steady_state_zone_temp_c:.1f}°C "
                    f"({result.steady_state_zone_temp_c - zone_sp:.1f}°C above setpoint {zone_sp:.0f}°C). "
                    f"Net heat surplus {result.net_heat_balance_kw:.0f} kW."
                ),
                expected_value=zone_sp,
                cited_value=result.steady_state_zone_temp_c,
                component="building",
                law_invoked="lumped_capacitance",
            ))

        return outputs

    def _check_staging(
        self,
        parsed: ParsedAdvisory,
        cond: Dict[str, float],
        ledger: ViolationLedger,
    ) -> Dict[str, float]:
        """Check if chiller staging is feasible after proposed shutdown."""
        # Estimate how many chillers remain
        shutdown_ids = [eid for eid in parsed.equipment_ids if eid.startswith("CH-")]
        n_shutdown = max(len(shutdown_ids), 1) if "shut" in parsed.text.lower() else 0
        n_available = self._chiller_count - n_shutdown

        # Estimate total load from building model
        building_state = BuildingState(
            zone_temp_c=cond["zone_temp_c"],
            outdoor_temp_c=cond["oat_c"],
        )
        total_load = required_cooling_kw(cond["zone_temp_c"], building_state, self._building_params)

        can_handle, required_plr = validate_staging(n_available, total_load, self._chiller_curves)

        outputs = {
            "staging_n_available": float(n_available),
            "staging_required_plr": required_plr,
            "staging_feasible": float(can_handle),
        }

        if not can_handle:
            ledger.add(PhysicalViolation(
                code="STAGING_OVERLOAD",
                severity="hard",
                description=f"Remaining {n_available} chillers cannot handle {total_load:.0f} kW (requires PLR={required_plr:.2f} > 1.0)",
                expected_value=1.0,
                cited_value=required_plr,
                component="chiller_plant",
                law_invoked="chiller_capacity",
            ))

        return outputs
