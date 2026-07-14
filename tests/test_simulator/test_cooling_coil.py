"""
Unit tests for cooling_coil.py — effectiveness_crossflow_unmixed, predict_coil,
cfm_to_kg_s, lps_to_kg_s.
No mocks; tests call real functions directly.
"""
from __future__ import annotations

import math

import pytest

from agent_commercial.verifiers.simulator.cooling_coil import (
    CP_AIR,
    CP_WATER,
    CoilGeometry,
    CoilState,
    cfm_to_kg_s,
    effectiveness_crossflow_unmixed,
    lps_to_kg_s,
    predict_coil,
)


# ── effectiveness_crossflow_unmixed ────────────────────────────────────────────

def test_effectiveness_ntu_zero():
    """NTU=0 → no heat transfer → effectiveness=0."""
    assert effectiveness_crossflow_unmixed(0.0, 0.5) == 0.0


def test_effectiveness_ntu_large():
    """Large NTU → effectiveness approaches 1.0 (must exceed 0.9)."""
    eps = effectiveness_crossflow_unmixed(10.0, 0.5)
    assert eps > 0.9, f"Large-NTU effectiveness={eps:.4f} should be > 0.9"


def test_effectiveness_c_ratio_zero():
    """c_ratio=0 (one fluid infinite capacity) → ε = 1 - exp(-NTU)."""
    ntu = 2.0
    expected = 1.0 - math.exp(-ntu)  # ≈ 0.8647
    result = effectiveness_crossflow_unmixed(ntu, 0.0)
    assert abs(result - expected) < 1e-6, f"Expected {expected:.6f}, got {result:.6f}"


@pytest.mark.parametrize("ntu,c_ratio", [
    (1.0, 0.5),
    (2.0, 1.0),
    (3.0, 0.8),
])
def test_effectiveness_in_unit_interval(ntu, c_ratio):
    """Effectiveness must always be in [0, 1]."""
    eps = effectiveness_crossflow_unmixed(ntu, c_ratio)
    assert 0.0 <= eps <= 1.0, f"NTU={ntu}, Cr={c_ratio}: eps={eps:.4f} out of [0,1]"


# ── unit conversions ───────────────────────────────────────────────────────────

def test_cfm_to_kg_s_unit():
    """1000 CFM should yield ≈ 0.578 kg/s (using 0.000472 m³/s per CFM and rho=1.225)."""
    # 1000 * 0.000472 * 1.225 = 0.5782 kg/s
    expected = 1000.0 * 0.000472 * 1.225
    result = cfm_to_kg_s(1000.0)
    assert abs(result - expected) / expected < 0.01, (
        f"Expected {expected:.4f} kg/s, got {result:.4f} kg/s"
    )


def test_lps_to_kg_s_unit():
    """10 L/s of water (rho=1000) → 10.0 kg/s."""
    result = lps_to_kg_s(10.0)
    assert abs(result - 10.0) < 1e-6, f"Expected 10.0 kg/s, got {result}"


# ── predict_coil ───────────────────────────────────────────────────────────────

def _make_typical_state() -> CoilState:
    """Typical AHU coil state: 20000 CFM air, 10 LPS chilled water."""
    return CoilState(
        air_entering_temp_c=28.0,
        air_flow_kg_s=cfm_to_kg_s(20000.0),
        water_entering_temp_c=7.0,
        water_flow_kg_s=lps_to_kg_s(10.0),
    )


def test_predict_coil_cools_air():
    """Leaving air must be cooler than entering air."""
    result = predict_coil(_make_typical_state(), CoilGeometry())
    assert result.air_leaving_temp_c < 28.0, (
        f"Air not cooled: leaving={result.air_leaving_temp_c:.2f}°C, entering=28°C"
    )


def test_predict_coil_positive_load():
    """sensible_load_kw (heat_transfer_kw) must be > 0."""
    result = predict_coil(_make_typical_state(), CoilGeometry())
    assert result.heat_transfer_kw > 0.0, (
        f"heat_transfer_kw should be positive, got {result.heat_transfer_kw}"
    )


def test_predict_coil_energy_conservation():
    """
    Q_air = m_air * Cp_air * (T_in - T_out) should match heat_transfer_kw within 5%.
    The coil function reports Q in kW; verify via air side calculation.
    """
    state = _make_typical_state()
    result = predict_coil(state, CoilGeometry())

    q_air_w = state.air_flow_kg_s * CP_AIR * (
        state.air_entering_temp_c - result.air_leaving_temp_c
    )
    q_reported_w = result.heat_transfer_kw * 1000.0
    deviation = abs(q_air_w - q_reported_w) / max(q_reported_w, 1.0)
    assert deviation < 0.05, (
        f"Energy conservation error: Q_air={q_air_w:.1f}W, "
        f"Q_reported={q_reported_w:.1f}W, deviation={deviation:.3f}"
    )


def test_predict_coil_latent_flag():
    """v1 model is sensible-only; latent_included must be False."""
    result = predict_coil(_make_typical_state(), CoilGeometry())
    assert result.latent_included is False


def test_predict_coil_zero_flow_returns_no_transfer():
    """Zero air flow → no heat transfer, air temp unchanged."""
    state = CoilState(
        air_entering_temp_c=28.0,
        air_flow_kg_s=0.0,
        water_entering_temp_c=7.0,
        water_flow_kg_s=10.0,
    )
    result = predict_coil(state, CoilGeometry())
    assert result.heat_transfer_kw == 0.0
    assert result.air_leaving_temp_c == pytest.approx(28.0)
