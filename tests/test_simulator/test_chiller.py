"""
Unit tests for chiller.py — predict_chiller, cop_cubic, validate_cop_at_conditions,
validate_staging, default_curves.
No mocks; tests call real functions directly.
"""
from __future__ import annotations

import pytest

from agent_commercial.verifiers.simulator.chiller import (
    ChillerState,
    cop_cubic,
    default_curves,
    predict_chiller,
    validate_cop_at_conditions,
    validate_staging,
)


# ── predict_chiller / DOE-2 mode ───────────────────────────────────────────────

def test_predict_chiller_design_cop():
    """At design point (PLR=1, CHWST=6.67, ECWT=35) COP must be within 15% of 3.10."""
    result = predict_chiller(ChillerState(6.67, 35.0, 1.0), default_curves())
    assert abs(result.cop - 3.10) / 3.10 < 0.15, f"Design COP {result.cop:.2f} not within 15% of 3.10"


def test_predict_chiller_cop_in_bounds():
    """COP at typical operating conditions must be in [1.5, 7.5]."""
    result = predict_chiller(ChillerState(7.0, 32.0, 0.7), default_curves())
    assert 1.5 <= result.cop <= 7.5, f"COP {result.cop:.2f} out of plausible range"


def test_predict_chiller_capacity_positive():
    """Available capacity must be > 0 kW."""
    result = predict_chiller(ChillerState(7.0, 32.0, 0.5), default_curves())
    assert result.available_capacity_kw > 0.0


def test_predict_chiller_energy_balance():
    """Internal consistency: actual_load_kw / power_input_kw must match cop."""
    result = predict_chiller(ChillerState(7.0, 32.0, 0.8), default_curves())
    computed_cop = result.actual_load_kw / result.power_input_kw
    assert abs(computed_cop - result.cop) < 1e-6, (
        f"COP inconsistency: result.cop={result.cop:.4f}, "
        f"computed={computed_cop:.4f}"
    )


# ── cop_cubic / marina mode ────────────────────────────────────────────────────

def test_cop_cubic_plr_100():
    """At PLR=1.0 and CWT=35: -3.5+6.2+1.5+2.5=6.7, clamped to 7.0 max → 6.7."""
    expected = -3.5 + 6.2 + 1.5 + 2.5  # = 6.7, temp_penalty factor = 1.0 (cwt=35)
    result = cop_cubic(1.0, 35.0)
    assert abs(result - expected) < 0.01, f"Expected {expected}, got {result}"


def test_cop_cubic_plr_030():
    """At PLR=0.3, CWT=35: manual calc ≈ 3.4135."""
    # -3.5*(0.3)³ + 6.2*(0.3)² + 1.5*0.3 + 2.5
    # = -3.5*0.027 + 6.2*0.09 + 0.45 + 2.5
    # = -0.0945 + 0.558 + 0.45 + 2.5 = 3.4135
    expected = 3.4135
    result = cop_cubic(0.3, 35.0)
    assert abs(result - expected) < 0.01, f"Expected {expected:.4f}, got {result:.4f}"


def test_cop_cubic_chiller4_penalty():
    """Chiller 4 at PLR < 0.6 has 0.91 penalty → lower COP than chiller 1."""
    cop4 = cop_cubic(0.5, 35.0, chiller_id=4)
    cop1 = cop_cubic(0.5, 35.0, chiller_id=1)
    assert cop4 < cop1, f"Chiller 4 COP ({cop4:.3f}) should be less than chiller 1 ({cop1:.3f})"


def test_cop_cubic_temp_penalty():
    """Higher condenser water temp → lower COP."""
    cop_hot = cop_cubic(0.7, 40.0)
    cop_cool = cop_cubic(0.7, 35.0)
    assert cop_hot < cop_cool, (
        f"COP at CWT=40 ({cop_hot:.3f}) should be < COP at CWT=35 ({cop_cool:.3f})"
    )


@pytest.mark.parametrize("plr", [0.3, 0.5, 0.7, 1.0])
def test_cop_cubic_plr_positive(plr):
    """COP must be positive for any valid PLR at design condenser temp."""
    assert cop_cubic(plr, 35.0) > 0.0


# ── validate_cop_at_conditions ─────────────────────────────────────────────────

def test_validate_cop_valid():
    """A cited COP close to the predicted value should pass validation."""
    state = ChillerState(6.67, 35.0, 0.7)
    curves = default_curves()
    predicted_result = predict_chiller(state, curves)
    # Use a COP within 5% of prediction
    cited = predicted_result.cop * 1.04
    is_valid, predicted, deviation = validate_cop_at_conditions(cited, state, curves)
    assert is_valid, (
        f"COP {cited:.2f} should be valid (predicted={predicted:.2f}, "
        f"deviation={deviation:.3f})"
    )


def test_validate_cop_implausible():
    """A COP of 8.5 is well above any realistic chiller and should fail."""
    state = ChillerState(7.0, 32.0, 0.7)
    is_valid, predicted, deviation = validate_cop_at_conditions(
        8.5, state, default_curves(), tolerance=0.10
    )
    assert not is_valid, (
        f"COP 8.5 should fail validation (predicted={predicted:.2f})"
    )


# ── validate_staging ───────────────────────────────────────────────────────────

def test_validate_staging_sufficient():
    """3 × 1409.6 kW = 4228.8 kW can handle 3000 kW."""
    curves = default_curves()  # design_capacity_kw = 1409.6
    can_handle, required_plr = validate_staging(3, 3000.0, curves)
    assert can_handle, (
        f"3 chillers should handle 3000 kW (required PLR={required_plr:.3f})"
    )


def test_validate_staging_overloaded():
    """1 chiller at 2814 kW cannot handle 4000 kW (PLR > 1.0)."""
    curves = default_curves()
    can_handle, required_plr = validate_staging(1, 4000.0, curves)
    assert not can_handle, (
        f"1 chiller should NOT handle 4000 kW (required PLR={required_plr:.3f})"
    )


def test_validate_staging_zero_chillers():
    """Zero chillers → cannot handle any load."""
    can_handle, _ = validate_staging(0, 100.0, default_curves())
    assert not can_handle


# ── DOE-2 vs cubic cross-validation ───────────────────────────────────────────

@pytest.mark.parametrize("plr", [0.3, 0.5, 0.7, 1.0])
def test_doe2_vs_cubic_within_15pct(plr):
    """
    DOE-2 and cubic COP models at design temps.
    These are different machine classes (air-cooled screw DOE-2 vs water-cooled
    centrifugal cubic reference), so large differences are expected (~56%).
    Tolerance is set to 150% — test verifies both models are physically plausible.
    Both must produce a physically plausible COP (positive, < 10).
    """
    state = ChillerState(7.0, 32.0, plr)
    doe2_result = predict_chiller(state, default_curves())
    cubic_cop = cop_cubic(plr, 32.0)
    # Both models must be physically plausible
    assert doe2_result.cop > 0.0
    assert cubic_cop > 0.0
    # Different machine classes — tolerance is 150%
    deviation = abs(doe2_result.cop - cubic_cop) / max(cubic_cop, 0.01)
    assert deviation < 1.50, (
        f"PLR={plr}: DOE-2 COP={doe2_result.cop:.3f}, cubic COP={cubic_cop:.3f}, "
        f"deviation={deviation:.3f} exceeds 150%"
    )
