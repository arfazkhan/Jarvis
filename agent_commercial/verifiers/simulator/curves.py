"""
Polynomial curve evaluation utilities for DOE-2 performance models.
"""
from __future__ import annotations

from typing import Sequence


def biquadratic(x: float, y: float, coeffs: Sequence[float]) -> float:
    """
    DOE-2 bi-quadratic: f(x,y) = c0 + c1*x + c2*x² + c3*y + c4*y² + c5*x*y

    Used for CAP-FT and EIR-FT chiller curves where x=CHWST, y=ECWT.
    Returns dimensionless multiplier (≈1.0 at design conditions).
    """
    c = coeffs
    return c[0] + c[1] * x + c[2] * x * x + c[3] * y + c[4] * y * y + c[5] * x * y


def cubic(x: float, coeffs: Sequence[float]) -> float:
    """
    DOE-2 cubic polynomial: f(x) = c0 + c1*x + c2*x² + c3*x³

    Used for EIR-FPLR (part-load ratio) curves.
    """
    c = coeffs
    return c[0] + c[1] * x + c[2] * x * x + c[3] * x * x * x


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))
