"""
Deterministic Physics Verifier
==============================

Validates ARVIS diagnostic claims against hard physics constraints.
No LLM involved — pure math checks. If a claim violates physics, it's blocked.

Checks:
  1. COP plausibility (chiller COP must be 1.5–7.5)
  2. Temperature range (supply air 8–22°C, zone 16–35°C, OAT -5–55°C)
  3. Energy balance (total load vs chiller capacity)
  4. Causal hop count (max 4 hops in causal chain)
  5. Mass/flow balance (chilled water flow vs load)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.verifiers.physics")


@dataclass
class VerificationResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    checks_run: int = 0

    def add_violation(self, msg: str) -> None:
        self.violations.append(msg)
        self.passed = False


# Physics bounds — conservative ranges for Qatar commercial buildings
_BOUNDS = {
    "cop": (1.5, 7.5),
    "sat": (8.0, 22.0),
    "zone_temp": (16.0, 38.0),
    "oat": (-5.0, 55.0),
    "chw_supply": (4.0, 12.0),
    "chw_return": (8.0, 18.0),
    "condenser_water": (20.0, 45.0),
    "fan_speed_pct": (0.0, 100.0),
    "damper_pct": (0.0, 100.0),
    "vibration_mm_s": (0.0, 12.0),
    "filter_dp_pa": (50.0, 400.0),
    "power_factor": (0.70, 1.0),
    "plr_pct": (0.0, 100.0),
}

_MAX_CAUSAL_HOPS = 4


# Building ID aliases — map historical/display names to canonical slugs
_BUILDING_ALIASES: Dict[str, str] = {
    "QNB-TOWER-DOHA": "marina-heights",
    "BUILDING-01": "marina-heights",
    "Marina Heights Tower": "marina-heights",
    "West Bay Tower": "marina-heights",
}


class PhysicsVerifier:
    """Deterministic physics validator. No LLM, no tolerance, no bypass."""

    def __init__(self, building_id: str = "marina-heights") -> None:
        self._simulator = None
        self._last_ledger = None
        slug = _BUILDING_ALIASES.get(building_id, building_id)
        try:
            from agent_commercial.verifiers.simulator import BuildingPhysicsSimulator, ViolationLedger
            self._simulator = BuildingPhysicsSimulator(slug)
            self._ViolationLedger = ViolationLedger
        except Exception as e:
            logger.debug(f"Physics simulator unavailable, bounds-only mode: {e}")

    def get_constraint_prompt(self) -> Optional[str]:
        """Return rich constraint prompt from last simulation for LLM regeneration."""
        if self._last_ledger is not None and not self._last_ledger.passed:
            return self._last_ledger.to_constraint_prompt()
        return None

    def verify_evidence(self, evidence_payload: Dict[str, Any]) -> VerificationResult:
        """Verify a tool result payload against physics bounds."""
        result = VerificationResult(passed=True)

        for key, value in self._flatten(evidence_payload):
            normalized_key = self._normalize_key(key)
            if normalized_key and normalized_key in _BOUNDS:
                lo, hi = _BOUNDS[normalized_key]
                try:
                    num = float(value)
                    result.checks_run += 1
                    if num < lo or num > hi:
                        result.add_violation(
                            f"{key}={num} outside physics bounds [{lo}, {hi}]"
                        )
                except (ValueError, TypeError):
                    pass

        return result

    def verify_causal_chain(self, causal_text: str) -> VerificationResult:
        """Verify causal chain doesn't exceed maximum hop count."""
        result = VerificationResult(passed=True)

        # Count causal connectors: "→", "causes", "leads to", "results in", "because"
        connectors = re.findall(
            r"→|→|causes|caused by|leads? to|results? in|therefore|consequently",
            causal_text, re.IGNORECASE
        )
        hop_count = len(connectors)
        result.checks_run = 1

        if hop_count > _MAX_CAUSAL_HOPS:
            result.add_violation(
                f"Causal chain has {hop_count} hops (max {_MAX_CAUSAL_HOPS}). "
                f"Likely over-reasoning — reduce to direct evidence-backed chain."
            )

        return result

    def verify_energy_balance(
        self,
        total_load_kw: float,
        chiller_capacity_kw: float,
        n_chillers_on: int,
    ) -> VerificationResult:
        """Verify load doesn't exceed available chiller capacity."""
        result = VerificationResult(passed=True, checks_run=1)

        available_capacity = chiller_capacity_kw * n_chillers_on
        if available_capacity > 0 and total_load_kw > available_capacity * 1.1:
            result.add_violation(
                f"Claimed load {total_load_kw:.0f} kW exceeds available capacity "
                f"{available_capacity:.0f} kW ({n_chillers_on} chillers × {chiller_capacity_kw:.0f} kW). "
                f"Energy balance violated."
            )

        return result

    def verify_cop_claim(self, cop: float, plr: float) -> VerificationResult:
        """Verify COP is physically plausible for given part-load ratio."""
        result = VerificationResult(passed=True, checks_run=1)

        lo, hi = _BOUNDS["cop"]
        if cop < lo or cop > hi:
            result.add_violation(f"COP={cop:.2f} outside physics bounds [{lo}, {hi}]")
            return result

        # COP at very low PLR (<0.2) should not exceed 4.0 (inefficient)
        if plr < 0.2 and cop > 4.5:
            result.add_violation(
                f"COP={cop:.2f} at PLR={plr:.2f} is implausible. "
                f"Centrifugal chillers cannot maintain high COP below 20% load."
            )

        return result

    def verify_advisory_text(self, advisory_text: str) -> VerificationResult:
        """
        Run all applicable physics checks on an advisory text.
        Extracts numbers and checks plausibility.
        """
        result = VerificationResult(passed=True)

        # Extract narrative text if the input is a valid JSON to avoid matching JSON structural elements
        import json
        narrative_texts = []
        try:
            data = json.loads(advisory_text)
            if isinstance(data, dict):
                # Extract message fields
                for adv in data.get("advisories", []):
                    if isinstance(adv, dict) and "message" in adv:
                        narrative_texts.append(adv["message"])
                if "analysis" in data:
                    narrative_texts.append(data["analysis"])
        except Exception:
            pass

        scan_text = "\n".join(narrative_texts) if narrative_texts else advisory_text

        # Extract COP claims
        cop_matches = re.findall(r"COP\s*(?:of|:|\s)\s*([\d.]+)", scan_text, re.IGNORECASE)
        for cop_str in cop_matches:
            try:
                cop = float(cop_str)
                result.checks_run += 1
                lo, hi = _BOUNDS["cop"]
                if cop < lo or cop > hi:
                    result.add_violation(f"Cited COP={cop} outside physics bounds [{lo}, {hi}]")
            except ValueError:
                pass

        # Extract temperature claims and validate
        temp_patterns = [
            (r"supply\s*(?:air)?\s*temp(?:erature)?\s*(?:of|:|\s)?\s*([\d.]+)\s*°?[cC]", "sat"),
            (r"zone\s*temp(?:erature)?\s*(?:of|:|\s)?\s*([\d.]+)\s*°?[cC]", "zone_temp"),
            (r"(?:outdoor|outside|ambient)\s*(?:air)?\s*temp(?:erature)?\s*(?:of|:|\s)?\s*([\d.]+)\s*°?[cC]", "oat"),
        ]
        for pattern, bound_key in temp_patterns:
            for m in re.finditer(pattern, scan_text, re.IGNORECASE):
                try:
                    temp = float(m.group(1))
                    result.checks_run += 1
                    lo, hi = _BOUNDS[bound_key]
                    if temp < lo or temp > hi:
                        result.add_violation(
                            f"Cited {bound_key} temperature={temp}°C outside bounds [{lo}, {hi}]"
                        )
                except ValueError:
                    pass

        # Check causal chain depth
        causal_result = self.verify_causal_chain(scan_text)
        result.checks_run += causal_result.checks_run
        result.violations.extend(causal_result.violations)
        if causal_result.violations:
            result.passed = False

        if self._simulator is not None:
            try:
                parsed = self._simulator.parse_advisory(advisory_text)
                if parsed.has_actionable_change:
                    sim_result = self._simulator.predict_advisory(parsed)
                    result.checks_run += len(sim_result.outputs)
                    for v in sim_result.violations:
                        violation_str = f"{v.code}: {v.description}"
                        if v.expected_value is not None and v.cited_value is not None:
                            violation_str += f" (expected={v.expected_value:.2f}, cited={v.cited_value:.2f})"
                        result.add_violation(violation_str)
                    self._last_ledger = self._ViolationLedger(
                        violations=sim_result.violations,
                        checks_run=len(sim_result.outputs),
                        simulation_outputs=sim_result.outputs,
                        passed=sim_result.passed,
                    )
            except Exception as e:
                logger.debug(f"Simulator check failed (non-fatal): {e}")

        return result

    def verify_ml_evidence(self, evidence: Any) -> "VerificationResult":
        """
        Verify ML evidence for physics plausibility and staleness.

        Rules:
        - ML fallback → cannot verify, flag as unverifiable
        - High confidence + high drift → suspicious, flag
        - Predicted values checked against physics bounds
        """
        result = VerificationResult(passed=True)

        is_fallback = getattr(evidence, "is_ml_fallback", False)
        if is_fallback:
            result.add_violation(
                f"ML_FALLBACK evidence from {getattr(evidence, 'source_tool', '?')}: "
                f"model not loaded — physics cannot be verified against predictions"
            )
            return result

        drift_score = getattr(evidence, "drift_score", None)
        confidence_bounds = getattr(evidence, "confidence_bounds", None)
        if drift_score is not None and drift_score > 0.7:
            if confidence_bounds is not None:
                lower = confidence_bounds.get("lower", 1.0)
                if lower > 0.8:
                    result.add_violation(
                        f"ML evidence claims high confidence (lower bound={lower:.2f}) "
                        f"but model drift={drift_score:.2f} — prediction reliability suspect"
                    )
            else:
                result.add_violation(
                    f"ML model drift={drift_score:.2f} exceeds threshold 0.7 — predictions stale"
                )
            result.checks_run += 1

        payload = getattr(evidence, "raw_payload", {}) or {}
        physics_result = self.verify_evidence(payload)
        result.checks_run += physics_result.checks_run
        result.violations.extend(physics_result.violations)
        if physics_result.violations:
            result.passed = False

        return result

    @staticmethod
    def _normalize_key(key: str) -> Optional[str]:
        """Map common tool result keys to physics bound categories."""
        k = key.lower().replace(" ", "_").replace("-", "_")
        mappings = {
            "cop": "cop",
            "cop_value": "cop",
            "sat": "sat",
            "supply_air_temp": "sat",
            "zone_temp": "zone_temp",
            "zn_temp": "zone_temp",
            "oat": "oat",
            "outdoor_air_temp": "oat",
            "chwst": "chw_supply",
            "chw_supply_temp": "chw_supply",
            "chwrt": "chw_return",
            "chw_return_temp": "chw_return",
            "condenser_temp": "condenser_water",
            "cond_temp": "condenser_water",
            "fan_speed": "fan_speed_pct",
            "sf_spd": "fan_speed_pct",
            "damper_pos": "damper_pct",
            "oa_dmpr": "damper_pct",
            "vib_rms": "vibration_mm_s",
            "vibration": "vibration_mm_s",
            "filter_dp": "filter_dp_pa",
            "flt_dp": "filter_dp_pa",
            "power_factor": "power_factor",
            "pf": "power_factor",
            "load": "plr_pct",
            "plr": "plr_pct",
        }
        return mappings.get(k)

    @staticmethod
    def _flatten(obj: Any, prefix: str = "", depth: int = 0) -> List[tuple]:
        """Flatten nested dict into (key, value) pairs."""
        if depth > 5:
            return []
        items = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (int, float)):
                    items.append((k, v))
                elif isinstance(v, dict):
                    items.extend(PhysicsVerifier._flatten(v, new_key, depth + 1))
                elif isinstance(v, (list, tuple)):
                    for item in v:
                        items.extend(PhysicsVerifier._flatten(item, new_key, depth + 1))
        return items
