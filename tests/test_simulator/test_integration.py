"""
Integration tests for BuildingPhysicsSimulator + PhysicsVerifier.

End-to-end flow: parse_advisory → predict_advisory → SimulationResult.
No mocks — all tests run against production code.

Input format note: parse_advisory() extracts physical parameters via:
  1. ARVIS JSON path: processes advisories[].message via regex
  2. Regex fallback: applied to raw text when JSON is malformed

Plain JSON dicts with fields like {"cited_cop": 8.5} are NOT parsed by the
field-extraction path — only narrative text (or advisories[].message strings)
feed the regex extractor. All test inputs use narrative text accordingly.
"""
from __future__ import annotations

import json
import time

import pytest

from agent_commercial.verifiers.simulator import BuildingPhysicsSimulator, ViolationLedger
from agent_commercial.verifiers.simulator.engine import PhysicalViolation, SimulationResult
from agent_commercial.verifiers import PhysicsVerifier


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sim() -> BuildingPhysicsSimulator:
    return BuildingPhysicsSimulator("marina-heights")


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_valid_advisory_passes(sim: BuildingPhysicsSimulator) -> None:
    """
    COP=2.9 at PLR=0.7, SAT=14°C, CHW setpoint 7°C should pass without
    any hard violations. Air-cooled screw (DOE-2) model at PLR=0.7 gives ~2.9,
    so 2.9 is well within tolerance.
    """
    text = (
        "Reduce chilled water supply to 7.0C. "
        "Set supply air temperature setpoint to 14.0C. "
        "Chiller PLR of 0.70. COP of 2.9 at PLR 0.70."
    )
    parsed = sim.parse_advisory(text)
    result = sim.predict_advisory(parsed)

    hard_violations = [v for v in result.violations if v.severity == "hard"]
    assert hard_violations == [], (
        f"Expected no hard violations for valid advisory; got: "
        f"{[v.code + ': ' + v.description for v in hard_violations]}"
    )
    assert result.passed is True


def test_implausible_cop_fails(sim: BuildingPhysicsSimulator) -> None:
    """
    COP=8.5 at PLR=0.7 exceeds both cubic (~5.39) and DOE-2 models by >10%.
    A COP_EXCEEDS_PHYSICS hard violation must be raised.
    """
    # Narrative text — the regex extracts COP and PLR from prose
    text = "Operate chiller at PLR 0.70. COP of 8.5 is achievable at current conditions."
    parsed = sim.parse_advisory(text)

    assert parsed.cited_cop == pytest.approx(8.5), (
        f"Parser must extract cited_cop=8.5, got: {parsed.cited_cop}"
    )
    assert parsed.proposed_plr == pytest.approx(0.70), (
        f"Parser must extract proposed_plr=0.70, got: {parsed.proposed_plr}"
    )

    result = sim.predict_advisory(parsed)

    cop_violations = [
        v for v in result.violations
        if "COP" in v.code or "COP" in v.description.upper()
    ]
    assert not result.passed or len(cop_violations) > 0, (
        "Expected COP violation for cited COP=8.5 at PLR=0.7"
    )
    assert len(cop_violations) > 0, (
        f"No COP violation found; all violations: {[v.code for v in result.violations]}"
    )


def test_unachievable_sat_fails(sim: BuildingPhysicsSimulator) -> None:
    """
    SAT=3.0°C is below CHWST(7°C)+2°C=9°C minimum approach limit.
    SAT_UNACHIEVABLE hard violation must be raised.
    """
    text = "Set supply air temperature setpoint to 3.0C."
    parsed = sim.parse_advisory(text)

    assert parsed.proposed_sat == pytest.approx(3.0), (
        f"Parser must extract proposed_sat=3.0, got: {parsed.proposed_sat}"
    )

    result = sim.predict_advisory(parsed)

    sat_violations = [
        v for v in result.violations
        if "SAT" in v.code or "SAT" in v.description.upper()
    ]
    assert not result.passed or len(sat_violations) > 0, (
        "Expected SAT violation for proposed SAT=3.0°C"
    )
    assert len(sat_violations) > 0, (
        f"No SAT violation found; all violations: {[v.code for v in result.violations]}"
    )
    # Must be a hard violation since 3°C < CHWST+2=9°C (minimum achievable)
    hard_sat = [v for v in sat_violations if v.severity == "hard"]
    assert len(hard_sat) > 0, (
        f"SAT violation present but not 'hard'; severities: {[v.severity for v in sat_violations]}"
    )


def test_no_actionable_change_skips_simulation(sim: BuildingPhysicsSimulator) -> None:
    """
    Purely informational advisory (no setpoints, no COP claim, no PLR).
    has_actionable_change must be False and no violations expected.
    """
    # Plain informational text — no numeric setpoint claims, no COP
    text = "Building energy consumption report for Q2. All systems nominal."
    parsed = sim.parse_advisory(text)

    # No actionable parameters extracted means has_actionable_change == False
    assert parsed.has_actionable_change is False, (
        f"Expected has_actionable_change=False for informational text, "
        f"got parsed fields: chw={parsed.proposed_chw_setpoint}, "
        f"sat={parsed.proposed_sat}, plr={parsed.proposed_plr}, cop={parsed.cited_cop}"
    )

    # Running predict_advisory on a non-actionable advisory should still
    # produce a result without hard violations
    result = sim.predict_advisory(parsed)
    hard_violations = [v for v in result.violations if v.severity == "hard"]
    assert hard_violations == [], (
        f"No hard violations expected for informational advisory; got: {hard_violations}"
    )


def test_evidence_entry_structure(sim: BuildingPhysicsSimulator) -> None:
    """
    to_evidence_entry() must return a dict with required moat-integration keys.
    """
    text = (
        "Reduce chilled water supply to 7.0C. "
        "Set supply air temperature setpoint to 14.0C. "
        "Chiller PLR of 0.70. COP of 2.9 at PLR 0.70."
    )
    parsed = sim.parse_advisory(text)
    result = sim.predict_advisory(parsed)
    entry = result.to_evidence_entry()

    assert isinstance(entry, dict), "to_evidence_entry() must return a dict"
    assert entry.get("source_tool") == "physics_simulator", (
        f"Expected source_tool='physics_simulator', got: {entry.get('source_tool')}"
    )
    assert entry.get("is_ml_fallback") is False, (
        f"Expected is_ml_fallback=False, got: {entry.get('is_ml_fallback')}"
    )
    assert "passed" in entry, "Evidence entry must contain 'passed' key"
    assert isinstance(entry["passed"], bool), "'passed' must be a bool"


def test_simulator_unavailable_graceful() -> None:
    """
    PhysicsVerifier with an unknown building slug should fall back to
    bounds-only mode and not raise during verify_advisory_text().
    """
    verifier = PhysicsVerifier("nonexistent-building-slug-xyz")
    advisory = "Recommend increasing chilled water setpoint. Current zone temp 24°C."
    try:
        result = verifier.verify_advisory_text(advisory)
    except Exception as exc:
        pytest.fail(
            f"verify_advisory_text() raised an exception for unknown building: {exc}"
        )
    # Result must be a VerificationResult with the expected attributes
    assert hasattr(result, "passed"), "VerificationResult must have 'passed'"
    assert hasattr(result, "violations"), "VerificationResult must have 'violations'"
    assert hasattr(result, "checks_run"), "VerificationResult must have 'checks_run'"


def test_physics_verifier_wires_simulator() -> None:
    """
    PhysicsVerifier("marina-heights") must surface simulator violations
    (COP_EXCEEDS_PHYSICS) in its violations list for an implausible COP claim.
    """
    verifier = PhysicsVerifier("marina-heights")
    # COP 8.5 — bounds check allows up to 7.5 so that fires too,
    # and the simulator fires COP_EXCEEDS_PHYSICS via predict_advisory
    text = "Recommend reducing CHW setpoint. COP 8.5 is achievable at current conditions."
    result = verifier.verify_advisory_text(text)

    assert len(result.violations) > 0, (
        "Expected at least one violation for implausible COP=8.5 advisory"
    )
    # At least one violation should mention COP
    cop_related = [v for v in result.violations if "COP" in v.upper() or "cop" in v.lower()]
    assert len(cop_related) > 0, (
        f"Expected a COP-related violation string; got: {result.violations}"
    )


def test_checks_run_nonzero_with_simulator() -> None:
    """
    verify_advisory_text() with a valid actionable advisory must report
    checks_run > 0 (simulator adds output keys to the count).
    """
    verifier = PhysicsVerifier("marina-heights")
    text = (
        "Reduce chilled water supply to 7.0C. "
        "Set supply air temperature setpoint to 14.0C. "
        "PLR of 0.70. COP of 2.9 at PLR 0.70."
    )
    result = verifier.verify_advisory_text(text)
    assert result.checks_run > 0, (
        f"Expected checks_run > 0 for actionable advisory; got {result.checks_run}"
    )


def test_performance_under_50ms(sim: BuildingPhysicsSimulator) -> None:
    """
    predict_advisory on a simple advisory must complete in < 50ms.
    Uses high-resolution perf_counter for wall-clock measurement.
    """
    text = "Reduce chilled water supply to 7.0C. PLR of 0.70. COP of 2.9 at PLR 0.70."
    parsed = sim.parse_advisory(text)

    t0 = time.perf_counter()
    result = sim.predict_advisory(parsed)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 50.0, (
        f"predict_advisory took {elapsed_ms:.1f}ms, must be < 50ms"
    )
    # Also verify the internal elapsed_ms field is populated
    assert result.elapsed_ms >= 0.0


def test_staging_advisory_passes_3_chillers(sim: BuildingPhysicsSimulator) -> None:
    """
    CH-04 bearing fault shutdown with 3 remaining chillers — staging must pass
    because 3 × 2814 kW = 8442 kW capacity is well above any reasonable building load.

    Advisory text includes 'shut' to trigger the staging check code path in
    predict_advisory() (line: `if any("shut" in parsed.text.lower() ...)`).
    """
    # Narrative text triggers both equipment ID regex (CH-04) and 'shut' keyword
    text = (
        "CH-04 bearing fault detected. Recommend shut down of CH-04 immediately. "
        "PLR of 0.71 on remaining chillers."
    )
    parsed = sim.parse_advisory(text)

    # Verify the parser found CH-04 and 'shut' is in the advisory text
    assert "CH-04" in parsed.equipment_ids or "CH-04" in parsed.text, (
        "CH-04 must be identifiable in the parsed advisory"
    )
    assert "shut" in parsed.text.lower(), (
        "Advisory text must contain 'shut' to trigger staging check"
    )

    result = sim.predict_advisory(parsed)

    staging_violations = [
        v for v in result.violations if v.code == "STAGING_OVERLOAD"
    ]
    assert staging_violations == [], (
        f"Expected no STAGING_OVERLOAD for 3 chillers + reasonable load; "
        f"got: {[v.description for v in staging_violations]}"
    )
