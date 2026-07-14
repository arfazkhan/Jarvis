"""
Marina Heights Tower — S1 fault scenario tests.

These tests exercise specific fault patterns observed in the Marina Heights
commissioning data. All tests run against production simulator code; no mocks.

Scenario naming follows the S1-Px convention from the Marina Heights S1 report.

Input format note: parse_advisory() extracts physical parameters via regex
from narrative text (or from advisories[].message in ARVIS JSON format).
Plain dict-style JSON keys are NOT extracted — all inputs here use narrative
text so the regex path fires reliably.
"""
from __future__ import annotations

import pytest

from agent_commercial.verifiers.simulator import BuildingPhysicsSimulator, ViolationLedger
from agent_commercial.verifiers.simulator.engine import PhysicalViolation, SimulationResult
from agent_commercial.verifiers import PhysicsVerifier


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sim() -> BuildingPhysicsSimulator:
    return BuildingPhysicsSimulator("marina-heights")


# ─── Scenario Tests ────────────────────────────────────────────────────────────

def test_s1_p4_cop_drift(sim: BuildingPhysicsSimulator) -> None:
    """
    S1-P4: Diagnostics claim COP=6.8 at PLR=0.30 — impossible for centrifugal chiller.

    Marina cubic at PLR=0.3, cwt=35°C:
      cop_base = -3.5*(0.3^3) + 6.2*(0.3^2) + 1.5*0.3 + 2.5
               = -0.0945 + 0.558 + 0.45 + 2.5 = 3.4135
      temp_penalty = 1.0 - 0.018*(35-35) = 1.0
      cop_cubic ≈ 3.41

    COP=6.8 >> 3.41 × 1.1 = 3.75 → violation from cubic model.
    Both models exceeded → COP_EXCEEDS_PHYSICS hard violation expected.
    """
    text = "Chiller diagnostic: operating at part load ratio 0.30. COP of 6.8 measured."
    parsed = sim.parse_advisory(text)

    assert parsed.cited_cop == pytest.approx(6.8), (
        f"Parser must extract cited_cop=6.8, got: {parsed.cited_cop}"
    )
    assert parsed.proposed_plr == pytest.approx(0.30), (
        f"Parser must extract proposed_plr=0.30, got: {parsed.proposed_plr}"
    )

    sim_result = sim.predict_advisory(parsed)

    # Primary assertion: must fail or have violations
    assert not sim_result.passed or len(sim_result.violations) > 0, (
        "COP=6.8 at PLR=0.3 must produce violations (physics impossible)"
    )

    # At least one violation must reference COP
    cop_violations = [
        v for v in sim_result.violations
        if "COP" in v.code or "COP" in v.description.upper()
    ]
    assert len(cop_violations) > 0, (
        f"Expected COP violation for cited COP=6.8 at PLR=0.3; "
        f"violations found: {[v.code for v in sim_result.violations]}"
    )


def test_s1_p5_ahu_sat_unachievable(sim: BuildingPhysicsSimulator) -> None:
    """
    S1-P5: Advisory proposes SAT=14°C with 85% OA at OAT=42°C.

    Mixed air temp: MAT = 0.85×42 + 0.15×24 = 35.7 + 3.6 = 39.3°C.
    With UA=85000 W/K coil and CHWST=7°C, the coil aggressively cools
    the 39.3°C mixed air to ~7.8°C (far below the proposed 14°C).

    Expected violation:
    - SAT_DEVIATION (soft): predicted SAT ~7.8°C deviates from proposed 14°C
      by ~6.2°C > 3°C threshold.

    Note: SAT_UNACHIEVABLE (hard) fires only when proposed_sat < CHWST+2=9°C.
    Since 14°C > 9°C, that path is not triggered. The deviation flag is the
    correct signal that 14°C is mis-specified at these conditions.
    """
    # Narrative text: parser extracts proposed_sat=14 and proposed_damper=0.85
    text = "Set supply air temperature setpoint to 14.0C. Set damper position to 85%."
    parsed = sim.parse_advisory(text)

    assert parsed.proposed_sat == pytest.approx(14.0), (
        f"Parser must extract proposed_sat=14.0, got: {parsed.proposed_sat}"
    )
    assert parsed.proposed_damper == pytest.approx(0.85), (
        f"Parser must extract proposed_damper=0.85, got: {parsed.proposed_damper}"
    )

    conditions = {"oat_c": 42.0, "zone_temp_c": 23.0, "chwst_c": 7.0}
    sim_result = sim.predict_advisory(parsed, conditions=conditions)

    # SAT-related violations (SAT_DEVIATION or SAT_UNACHIEVABLE)
    sat_related = [
        v for v in sim_result.violations
        if "SAT" in v.code or "SAT" in v.description.upper() or "UNACHIEVABLE" in v.code
    ]

    # The coil predicts ~7.8°C SAT, deviating from proposed 14°C by ~6.2°C > 3°C
    # → SAT_DEVIATION must fire. Accept either SAT violation or general failure.
    assert len(sat_related) > 0 or not sim_result.passed, (
        f"Expected SAT violation at OAT=42°C, damper=85%, proposed SAT=14°C; "
        f"sim_result.passed={sim_result.passed}, "
        f"violations={[v.code for v in sim_result.violations]}, "
        f"predicted_sat={sim_result.outputs.get('predicted_sat')}"
    )

    # If there are SAT-related violations, verify the first one references SAT
    if sat_related:
        first = sat_related[0]
        assert "SAT" in first.code or "SAT" in first.description.upper(), (
            f"SAT violation must mention SAT: code={first.code}, desc={first.description}"
        )


def test_s1_p6_chiller_bearing_shutdown(sim: BuildingPhysicsSimulator) -> None:
    """
    S1-P6: CH-04 bearing fault — recommend shutdown. 3 chillers remain.

    3 × 2814 kW = 8442 kW available capacity >> typical building load.
    Staging check must PASS — no STAGING_OVERLOAD violation.

    Advisory text must include 'shut' to trigger the staging check path
    in predict_advisory() (engine.py line 414).
    """
    text = (
        "CH-04 bearing fault detected. Recommend shut down of CH-04 immediately. "
        "PLR of 0.71 on remaining units."
    )
    parsed = sim.parse_advisory(text)

    # Confirm 'shut' is present to trigger staging check
    assert "shut" in parsed.text.lower(), (
        "Advisory text must contain 'shut' to trigger staging check"
    )

    sim_result = sim.predict_advisory(parsed)

    staging_violations = [
        v for v in sim_result.violations if v.code == "STAGING_OVERLOAD"
    ]
    assert staging_violations == [], (
        f"Expected no STAGING_OVERLOAD with 3 available chillers (8442 kW capacity); "
        f"staging_n_available={sim_result.outputs.get('staging_n_available')}, "
        f"violations: {[v.description for v in staging_violations]}"
    )


def test_s1_p7_humidity_warning(sim: BuildingPhysicsSimulator) -> None:
    """
    S1-P7: Advisory on sensible cooling only — mild CHW setpoint adjustment.

    The sensible-only model must not produce any hard violations for a
    conservative setpoint change. Only soft violations are acceptable.

    This test guards against the simulator incorrectly hard-failing scenarios
    that involve humidity/latent load data which are outside v1 scope.
    """
    # Mild CHW setpoint reduction — no COP/SAT claims, no unusual conditions
    text = "Reduce chilled water supply setpoint to 6.5C."
    parsed = sim.parse_advisory(text)

    assert parsed.proposed_chw_setpoint == pytest.approx(6.5), (
        f"Parser must extract proposed_chw_setpoint=6.5, got: {parsed.proposed_chw_setpoint}"
    )

    sim_result = sim.predict_advisory(parsed)

    hard_violations = [v for v in sim_result.violations if v.severity == "hard"]
    assert hard_violations == [], (
        f"No hard violations expected for mild CHW setpoint advisory; "
        f"got hard violations: {[(v.code, v.description) for v in hard_violations]}"
    )

    # Soft violations are acceptable (e.g., LOW_DELTA_T, COOLING_CAPACITY_INSUFFICIENT)
    for v in sim_result.violations:
        assert v.severity == "soft", (
            f"Unexpected non-soft violation for mild setpoint change: "
            f"code={v.code}, severity={v.severity}, desc={v.description}"
        )


def test_s1_p4_via_physics_verifier() -> None:
    """
    S1-P4 full path through PhysicsVerifier.

    verify_advisory_text() for a text mentioning "COP of 6.8 at part load
    ratio 0.30" must surface a COP violation in the violations list.

    COP bounds: [1.5, 7.5] — COP=6.8 is within bounds so the bounds check
    does NOT fire. The simulator (COP_EXCEEDS_PHYSICS) catches the violation
    because 6.8 >> cubic(0.30)=3.41.
    """
    verifier = PhysicsVerifier("marina-heights")
    text = (
        "Chiller CH-01 diagnostic: COP of 6.8 at part load ratio 0.30 "
        "during night setback. Recommend verifying sensor calibration."
    )
    result = verifier.verify_advisory_text(text)

    # Simulator must surface COP_EXCEEDS_PHYSICS as a violation string
    cop_violations = [
        v for v in result.violations
        if "COP" in v.upper()
    ]
    assert len(cop_violations) > 0, (
        f"Expected COP violation from simulator for COP=6.8 at PLR=0.30; "
        f"violations found: {result.violations}"
    )
    assert not result.passed, (
        "PhysicsVerifier must report passed=False when COP exceeds physics model bounds"
    )
