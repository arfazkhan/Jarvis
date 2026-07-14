"""
Unit tests for curves.py — biquadratic, cubic, clamp.
No mocks; tests call real functions directly.
"""
from __future__ import annotations

import math

import pytest

from agent_commercial.verifiers.simulator.curves import biquadratic, clamp, cubic

# ── Coefficient sets mirroring chiller.py defaults ────────────────────────────

_DEFAULT_CAP_FT = [1.020000, 0.020000, 0.0, -0.005000, 0.0, 0.0]
_DEFAULT_EIR_FT = [0.430000, -0.010000, 0.0, 0.020000, 0.0, 0.0]
_DEFAULT_EIR_FPLR = [2.785324, -3.167667, 1.348787, 0.038704]


# ── biquadratic ────────────────────────────────────────────────────────────────

def test_biquadratic_design_point():
    """CAP-FT must equal 1.0 at design (CHWST=7°C, ECWT=32°C)."""
    # 1.02 + 0.02*7 + 0 + (-0.005)*32 + 0 + 0 = 1.02 + 0.14 - 0.16 = 1.0
    result = biquadratic(7.0, 32.0, _DEFAULT_CAP_FT)
    assert abs(result - 1.0) < 1e-6, f"Expected 1.0, got {result}"


def test_biquadratic_constant():
    """All-zero sensitivity coeffs → constant c0 regardless of x,y."""
    coeffs = [5.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert biquadratic(0.0, 0.0, coeffs) == pytest.approx(5.0)
    assert biquadratic(100.0, 200.0, coeffs) == pytest.approx(5.0)
    assert biquadratic(-50.0, 50.0, coeffs) == pytest.approx(5.0)


def test_eir_ft_design_point():
    """EIR-FT must equal 1.0 at design conditions."""
    # 0.43 + (-0.01)*7 + 0 + 0.02*32 + 0 + 0 = 0.43 - 0.07 + 0.64 = 1.0
    result = biquadratic(7.0, 32.0, _DEFAULT_EIR_FT)
    assert abs(result - 1.0) < 1e-6, f"Expected 1.0, got {result}"


def test_biquadratic_chwst_sensitivity():
    """Higher CHWST (8°C vs 7°C) increases CAP-FT modifier (more available capacity)."""
    cap_7 = biquadratic(7.0, 32.0, _DEFAULT_CAP_FT)
    cap_8 = biquadratic(8.0, 32.0, _DEFAULT_CAP_FT)
    assert cap_8 > cap_7, (
        f"cap_ft at CHWST=8 ({cap_8:.4f}) should exceed cap_ft at CHWST=7 ({cap_7:.4f})"
    )


# ── cubic ──────────────────────────────────────────────────────────────────────

def test_cubic_design():
    """EIR-FPLR at PLR=1.0 should be close to 1.0 (within 0.05)."""
    result = cubic(1.0, _DEFAULT_EIR_FPLR)
    assert abs(result - 1.0) < 0.05, f"Expected ~1.0, got {result}"


def test_cubic_zero_arg():
    """cubic(0, coeffs) returns c0."""
    coeffs = [3.14, -1.0, 0.5, -0.1]
    assert cubic(0.0, coeffs) == pytest.approx(3.14)


@pytest.mark.parametrize("x,coeffs,expected", [
    (0.0, [1.0, 0.0, 0.0, 0.0], 1.0),
    (1.0, [1.0, 1.0, 1.0, 1.0], 4.0),   # 1 + 1 + 1 + 1
    (2.0, [0.0, 0.0, 0.0, 1.0], 8.0),   # 0 + 0 + 0 + 8
])
def test_cubic_parametrized(x, coeffs, expected):
    assert cubic(x, coeffs) == pytest.approx(expected)


# ── clamp ──────────────────────────────────────────────────────────────────────

def test_clamp_within():
    assert clamp(5.0, 0.0, 10.0) == 5.0


def test_clamp_below():
    assert clamp(-1.0, 0.0, 10.0) == 0.0


def test_clamp_above():
    assert clamp(11.0, 0.0, 10.0) == 10.0


@pytest.mark.parametrize("value,lo,hi,expected", [
    (0.0, 0.0, 1.0, 0.0),
    (1.0, 0.0, 1.0, 1.0),
    (0.5, 0.0, 1.0, 0.5),
    (-99.0, -10.0, 10.0, -10.0),
    (99.0, -10.0, 10.0, 10.0),
])
def test_clamp_parametrized(value, lo, hi, expected):
    assert clamp(value, lo, hi) == expected
