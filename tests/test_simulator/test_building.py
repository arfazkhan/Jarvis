"""
Unit tests for building.py — predict_zone_temp, required_cooling_kw.
No mocks; tests call real functions directly.

Design constants:
  tau = thermal_mass / envelope_ua = 500e6 / 25000 = 20000 s
  Stability limit = 0.5 * tau = 10000 s
"""
from __future__ import annotations

import pytest

from agent_commercial.verifiers.simulator.building import (
    BuildingResult,
    BuildingState,
    BuildingThermalParams,
    predict_zone_temp,
    required_cooling_kw,
)

# ── Default Marina params ──────────────────────────────────────────────────────

DEFAULT_PARAMS = BuildingThermalParams(
    floor_area_m2=50000.0,
    envelope_ua_w_per_k=25000.0,
    internal_gain_w_per_m2=25.0,
    thermal_mass_j_per_k=500_000_000.0,
)


# ── Stability guard ────────────────────────────────────────────────────────────

def test_stability_guard_triggers():
    """dt >= 0.5*tau (10000 s) must raise ValueError."""
    state = BuildingState(zone_temp_c=23.0, outdoor_temp_c=38.0, cooling_provided_kw=1000.0)
    with pytest.raises(ValueError, match="stability"):
        predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=15000.0)


def test_stability_guard_passes():
    """dt=900 s (well below 10000 s limit) must not raise."""
    state = BuildingState(zone_temp_c=23.0, outdoor_temp_c=38.0, cooling_provided_kw=1000.0)
    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=900.0)
    assert isinstance(result, BuildingResult)


def test_stability_guard_boundary_just_below():
    """dt just below 10000 s (e.g. 9999 s) must not raise."""
    state = BuildingState(zone_temp_c=23.0, outdoor_temp_c=38.0, cooling_provided_kw=1000.0)
    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=9999.0)
    assert isinstance(result, BuildingResult)


def test_stability_guard_at_limit():
    """dt exactly at 0.5*tau (10000 s) must raise."""
    state = BuildingState(zone_temp_c=23.0, outdoor_temp_c=38.0, cooling_provided_kw=1000.0)
    with pytest.raises(ValueError):
        predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=10000.0)


# ── tau formula ────────────────────────────────────────────────────────────────

def test_tau_formula():
    """tau = thermal_mass / envelope_UA must equal ~20000 s for default params."""
    tau = DEFAULT_PARAMS.thermal_mass_j_per_k / DEFAULT_PARAMS.envelope_ua_w_per_k
    assert abs(tau - 20000.0) < 1.0, f"Expected tau=20000 s, got {tau:.1f} s"


def test_time_constant_in_result():
    """Result.time_constant_hours must equal tau/3600 ≈ 5.556 hours."""
    state = BuildingState(zone_temp_c=23.0, outdoor_temp_c=38.0, cooling_provided_kw=1000.0)
    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=900.0)
    expected_hours = 20000.0 / 3600.0
    assert abs(result.time_constant_hours - expected_hours) < 0.01


# ── Zone temperature response ──────────────────────────────────────────────────

def test_zone_heats_without_cooling():
    """OAT=38 > zone=23 with no cooling → zone temperature must increase."""
    state = BuildingState(
        zone_temp_c=23.0,
        outdoor_temp_c=38.0,
        solar_gain_w=0.0,
        cooling_provided_kw=0.0,
    )
    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=900.0)
    assert result.predicted_zone_temp_c > state.zone_temp_c, (
        f"Zone should heat up: {state.zone_temp_c}°C → {result.predicted_zone_temp_c:.3f}°C"
    )


def test_zone_cools_with_excess_cooling():
    """Excessive cooling (much more than required) → zone temperature decreases."""
    state = BuildingState(
        zone_temp_c=23.0,
        outdoor_temp_c=38.0,
        solar_gain_w=0.0,
        cooling_provided_kw=5000.0,  # Far more than Marina needs
    )
    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=900.0)
    assert result.predicted_zone_temp_c < state.zone_temp_c, (
        f"Zone should cool: {state.zone_temp_c}°C → {result.predicted_zone_temp_c:.3f}°C"
    )


def test_steady_state_balanced():
    """
    When cooling exactly matches required, zone_temp change should be < 0.5°C over 900 s.
    required_cooling_kw gives the steady-state Q; use that as cooling input.
    """
    zone_target = 23.0
    state = BuildingState(
        zone_temp_c=zone_target,
        outdoor_temp_c=38.0,
        solar_gain_w=0.0,
        cooling_provided_kw=0.0,  # placeholder; will be filled
    )
    cooling = required_cooling_kw(zone_target, state, DEFAULT_PARAMS)
    state.cooling_provided_kw = cooling

    result = predict_zone_temp(state, DEFAULT_PARAMS, dt_seconds=900.0)
    delta = abs(result.predicted_zone_temp_c - zone_target)
    assert delta < 0.5, (
        f"Balanced cooling: zone changed by {delta:.4f}°C (expected < 0.5°C)"
    )


# ── required_cooling_kw ────────────────────────────────────────────────────────

def test_required_cooling_kw_reasonable():
    """Marina summer conditions: required cooling must be in [500, 5000] kW."""
    state = BuildingState(
        zone_temp_c=23.0,
        outdoor_temp_c=38.0,
        solar_gain_w=0.0,
        cooling_provided_kw=0.0,
    )
    cooling = required_cooling_kw(23.0, state, DEFAULT_PARAMS)
    assert 500.0 <= cooling <= 5000.0, (
        f"Required cooling {cooling:.1f} kW not in expected [500, 5000] range"
    )


def test_required_cooling_kw_higher_oat_needs_more():
    """Higher outdoor temperature → more cooling required."""
    state_hot = BuildingState(zone_temp_c=23.0, outdoor_temp_c=42.0)
    state_cool = BuildingState(zone_temp_c=23.0, outdoor_temp_c=30.0)
    cooling_hot = required_cooling_kw(23.0, state_hot, DEFAULT_PARAMS)
    cooling_cool = required_cooling_kw(23.0, state_cool, DEFAULT_PARAMS)
    assert cooling_hot > cooling_cool, (
        f"Hotter day needs more cooling: {cooling_hot:.1f} vs {cooling_cool:.1f} kW"
    )
