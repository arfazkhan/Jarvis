"""
Unit tests for ahu.py — mixing_box, fan_power, fan_heat_rise, predict_ahu.
No mocks; tests call real functions directly.
"""
from __future__ import annotations

import pytest

from agent_commercial.verifiers.simulator.ahu import (
    AHUConfig,
    AHUState,
    fan_heat_rise,
    fan_power,
    mixing_box,
    predict_ahu,
)
from agent_commercial.verifiers.simulator.cooling_coil import CP_AIR


# ── mixing_box ─────────────────────────────────────────────────────────────────

def test_mixing_box_full_oa():
    """100% OA → MAT equals outdoor air temperature."""
    result = mixing_box(42.0, 24.0, 1.0)
    assert result == pytest.approx(42.0)


def test_mixing_box_full_ra():
    """0% OA (all recirculation) → MAT equals return air temperature."""
    result = mixing_box(42.0, 24.0, 0.0)
    assert result == pytest.approx(24.0)


def test_mixing_box_mixed():
    """20% OA: MAT = 0.2*40 + 0.8*20 = 8 + 16 = 24°C."""
    result = mixing_box(40.0, 20.0, 0.2)
    assert result == pytest.approx(24.0)


@pytest.mark.parametrize("oat,rat,frac,expected", [
    (30.0, 22.0, 0.5, 26.0),   # 0.5*30 + 0.5*22 = 26
    (35.0, 24.0, 0.25, 26.75), # 0.25*35 + 0.75*24 = 8.75 + 18 = 26.75
])
def test_mixing_box_parametrized(oat, rat, frac, expected):
    assert mixing_box(oat, rat, frac) == pytest.approx(expected)


# ── fan_power ──────────────────────────────────────────────────────────────────

def test_fan_power_cube_law():
    """P = 15 kW × 0.5^2.7 ≈ 2.32 kW (within 1%)."""
    expected = 15.0 * (0.5 ** 2.7)
    result = fan_power(0.5, 15.0)
    assert abs(result - expected) / expected < 0.01, (
        f"Expected {expected:.4f} kW, got {result:.4f} kW"
    )


def test_fan_power_full_speed():
    """At 100% speed, fan power equals design power."""
    assert fan_power(1.0, 15.0) == pytest.approx(15.0)


def test_fan_power_zero_speed():
    """At 0% speed, power is 0."""
    assert fan_power(0.0, 15.0) == pytest.approx(0.0)


@pytest.mark.parametrize("speed,design_kw", [
    (0.8, 20.0),
    (0.6, 10.0),
    (1.0, 5.0),
])
def test_fan_power_always_positive(speed, design_kw):
    assert fan_power(speed, design_kw) >= 0.0


# ── fan_heat_rise ──────────────────────────────────────────────────────────────

def test_fan_heat_rise_formula():
    """ΔT = (5 kW × 1000) / (10.0 kg/s × 1005) ≈ 0.4975°C."""
    expected = (5.0 * 1000.0) / (10.0 * CP_AIR)
    result = fan_heat_rise(5.0, 10.0)
    assert abs(result - expected) < 0.01, (
        f"Expected {expected:.4f}°C, got {result:.4f}°C"
    )


def test_fan_heat_rise_zero_flow():
    """Zero air flow → no temperature rise (avoid divide-by-zero)."""
    assert fan_heat_rise(5.0, 0.0) == pytest.approx(0.0)


def test_fan_heat_rise_zero_power():
    """Zero fan power → zero heat rise."""
    assert fan_heat_rise(0.0, 10.0) == pytest.approx(0.0)


# ── predict_ahu ────────────────────────────────────────────────────────────────

def _make_typical_state() -> AHUState:
    """Typical hot summer day: high OAT, warm return, chilled water supply."""
    return AHUState(
        outdoor_air_temp_c=38.0,
        return_air_temp_c=24.0,
        oa_damper_fraction=0.2,
        fan_speed_fraction=0.9,
        chw_supply_temp_c=7.0,
        chw_flow_kg_s=10.0,
    )


def test_predict_ahu_cools():
    """Supply air temperature must be lower than mixed air temperature."""
    result = predict_ahu(_make_typical_state(), AHUConfig())
    assert result.supply_air_temp_c < result.mixed_air_temp_c, (
        f"SAT={result.supply_air_temp_c:.2f}°C should be < MAT={result.mixed_air_temp_c:.2f}°C"
    )


def test_predict_ahu_sat_positive():
    """Supply air temperature must be above 0°C (not unrealistically cold)."""
    result = predict_ahu(_make_typical_state(), AHUConfig())
    assert result.supply_air_temp_c > 0.0, (
        f"SAT={result.supply_air_temp_c:.2f}°C should be positive"
    )


def test_predict_ahu_mat_is_mixing_box_result():
    """MAT in result must equal mixing_box(oat, rat, oa_fraction)."""
    state = _make_typical_state()
    result = predict_ahu(state, AHUConfig())
    expected_mat = mixing_box(
        state.outdoor_air_temp_c,
        state.return_air_temp_c,
        state.oa_damper_fraction,
    )
    assert result.mixed_air_temp_c == pytest.approx(expected_mat)


def test_predict_ahu_fan_power_positive():
    """Fan power must be positive when fan is running."""
    result = predict_ahu(_make_typical_state(), AHUConfig())
    assert result.fan_power_kw > 0.0


def test_predict_ahu_coil_load_positive():
    """Coil load must be positive (cooling is happening)."""
    result = predict_ahu(_make_typical_state(), AHUConfig())
    assert result.coil_load_kw > 0.0
