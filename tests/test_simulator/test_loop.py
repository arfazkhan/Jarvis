"""
Unit tests for loop.py — predict_loop, required_flow_for_load, validate_flow_balance.
No mocks; tests call real functions directly.
"""
from __future__ import annotations

import pytest

from agent_commercial.verifiers.simulator.loop import (
    CP_WATER,
    LoopConfig,
    LoopState,
    predict_loop,
    required_flow_for_load,
    validate_flow_balance,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def default_config() -> LoopConfig:
    return LoopConfig(
        design_flow_lps=120.0,
        design_delta_t_c=5.0,
        design_head_kpa=250.0,
        pump_efficiency=0.75,
        n_pumps=2,
        design_pump_kw=45.0,
    )


def typical_state(flow_fraction: float = 0.8) -> LoopState:
    return LoopState(
        supply_temp_c=7.0,
        return_temp_c=12.0,
        flow_fraction=flow_fraction,
        n_pumps_running=2,
    )


# ── predict_loop ───────────────────────────────────────────────────────────────

def test_q_equals_m_cp_dt():
    """Q = m·Cp·ΔT: heat_removed_kw must match flow * Cp * delta_t / 1000."""
    state = typical_state(flow_fraction=0.8)
    config = default_config()
    result = predict_loop(state, config)

    expected_kw = result.flow_kg_s * CP_WATER * result.delta_t_c / 1000.0
    assert abs(result.heat_removed_kw - expected_kw) < 0.01, (
        f"Q mismatch: result={result.heat_removed_kw:.3f} kW, "
        f"expected={expected_kw:.3f} kW"
    )


def test_predict_loop_delta_t_correct():
    """delta_t_c in result must equal return - supply temperature."""
    state = typical_state()
    result = predict_loop(state, default_config())
    expected_dt = state.return_temp_c - state.supply_temp_c
    assert result.delta_t_c == pytest.approx(expected_dt)


def test_predict_loop_flow_kg_s_from_lps():
    """flow_kg_s must equal flow_lps (since rho=1000, /1000=1 kg per litre)."""
    state = typical_state(flow_fraction=1.0)
    config = default_config()
    result = predict_loop(state, config)
    # 120 LPS * 1000 / 1000 = 120 kg/s
    assert result.flow_kg_s == pytest.approx(120.0)


def test_predict_loop_heat_positive():
    """With warm return and cool supply, heat removed must be > 0."""
    result = predict_loop(typical_state(), default_config())
    assert result.heat_removed_kw > 0.0


def test_pump_cube_law():
    """
    Pump power at 70% flow ≈ P_design * n_pumps * 0.7³.
    State at 70% flow, 2 pumps running.
    """
    config = default_config()
    state = LoopState(
        supply_temp_c=7.0,
        return_temp_c=12.0,
        flow_fraction=0.7,
        n_pumps_running=2,
    )
    result = predict_loop(state, config)
    expected_kw = config.design_pump_kw * 2 * (0.7 ** 3)
    assert abs(result.pumping_power_kw - expected_kw) < 0.01, (
        f"Pump power: expected {expected_kw:.3f} kW, got {result.pumping_power_kw:.3f} kW"
    )


# ── required_flow_for_load ─────────────────────────────────────────────────────

def test_required_flow_increases_with_load():
    """Higher cooling load → more flow required."""
    config = default_config()
    flow_high = required_flow_for_load(2000.0, 5.0, config)
    flow_low = required_flow_for_load(1000.0, 5.0, config)
    assert flow_high > flow_low, (
        f"2000 kW needs more flow ({flow_high:.3f}) than 1000 kW ({flow_low:.3f})"
    )


def test_required_flow_formula():
    """
    required_flow_for_load(500 kW, ΔT=5°C) = 500*1000 / (4186*5) ≈ 23.89 kg/s.
    Expressed as fraction of 120 LPS design flow.
    """
    config = default_config()
    expected_kg_s = (500.0 * 1000.0) / (CP_WATER * 5.0)  # ≈ 23.89 kg/s
    expected_lps = expected_kg_s  # since rho_water=1000, lps = kg/s numerically
    expected_fraction = expected_lps / config.design_flow_lps

    result_fraction = required_flow_for_load(500.0, 5.0, config)
    assert abs(result_fraction - expected_fraction) / expected_fraction < 0.01, (
        f"Expected fraction {expected_fraction:.4f}, got {result_fraction:.4f}"
    )


def test_required_flow_zero_delta_t_returns_one():
    """Zero ΔT → undefined → function returns 1.0 (full flow)."""
    config = default_config()
    assert required_flow_for_load(500.0, 0.0, config) == pytest.approx(1.0)


# ── validate_flow_balance ──────────────────────────────────────────────────────

def test_flow_balance_passes_consistent():
    """
    Consistent Q: flow and temps produce Q close to stated load → passes.
    flow_lps=120, ΔT=5 → Q = 120*(1000/1000)*4186*5/1000 = 2511.6 kW.
    Pass 2511.6 as the stated load.
    """
    config = default_config()
    # Q = 120 kg/s * 4186 * 5 / 1000 = 2511.6 kW
    q_expected = 120.0 * CP_WATER * 5.0 / 1000.0
    is_valid, q_flow, q_stated = validate_flow_balance(
        total_load_kw=q_expected,
        supply_temp_c=7.0,
        return_temp_c=12.0,
        flow_fraction=1.0,
        config=config,
        tolerance=0.05,
    )
    assert is_valid, (
        f"Consistent flow balance should pass: q_flow={q_flow:.1f}, "
        f"q_stated={q_stated:.1f} kW"
    )


def test_flow_balance_fails_inconsistent():
    """
    Inconsistent Q: flow produces ~2511 kW but stated load is 1674 kW (50% less) → fails.
    """
    config = default_config()
    q_actual = 120.0 * CP_WATER * 5.0 / 1000.0  # ≈ 2511 kW
    stated_load = q_actual * 0.5  # 50% discrepancy
    is_valid, q_flow, q_stated = validate_flow_balance(
        total_load_kw=stated_load,
        supply_temp_c=7.0,
        return_temp_c=12.0,
        flow_fraction=1.0,
        config=config,
        tolerance=0.20,
    )
    assert not is_valid, (
        f"50% discrepancy should fail: q_flow={q_flow:.1f}, q_stated={q_stated:.1f} kW"
    )


def test_flow_balance_zero_load_always_passes():
    """Zero stated load is degenerate and always returns valid."""
    config = default_config()
    is_valid, _, _ = validate_flow_balance(
        total_load_kw=0.0,
        supply_temp_c=7.0,
        return_temp_c=12.0,
        flow_fraction=1.0,
        config=config,
    )
    assert is_valid
