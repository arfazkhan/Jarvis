"""
ArvisX Phase-9 — Water Availability Engine (the hero).

Residential complaint #1 is "why is there no water this morning?". This engine turns
tank levels + draw + pump/power state into the answers a resident/committee actually
wants: how much water is left, for how long, will it refill, and what threatens it.

Outputs:
  - water availability score (the headline tile)
  - hours / days of water remaining at current draw
  - refill capability (transfer pump + power present?) + a plain-language forecast
  - pump risk that could break the refill chain

Deterministic. Consumption rate comes from a draw meter signal if present, else the
learned tank-level trend (Phase-4 baselines), else a sane default — and it ABSTAINS
toward caution when inputs are thin (honest, like everything else).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from arvisx.models import (
    Asset, AssetType, HealthBand, Risk, ServiceType, Severity, confidence_band,
)

_DEFAULT_CAP = {AssetType.UNDERGROUND_TANK: 50000.0, AssetType.OVERHEAD_TANK: 20000.0}
_TRANSFER = {AssetType.TRANSFER_PUMP}
_TANKS = {AssetType.UNDERGROUND_TANK, AssetType.OVERHEAD_TANK}


@dataclass
class WaterStatus:
    score: float
    band: str
    stored_l: float
    capacity_l: float
    fill_pct: float
    draw_lph: float
    hours_remaining: Optional[float]
    days_remaining: Optional[float]
    can_refill: bool
    forecast: str
    risks: List[Risk] = field(default_factory=list)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _derive_draw(tanks: List[Asset], baselines, sample_interval_h: float) -> Optional[float]:
    """Liters/hour drain from the learned tank-level trend, if enough history."""
    if baselines is None:
        return None
    total = 0.0
    have = False
    for t in tanks:
        cap = _num((t.signals or {}).get("tank_capacity_l")) or _DEFAULT_CAP.get(t.asset_type, 30000.0)
        base = baselines.baseline(t.asset_id, "tank_level_pct")
        if base is None:
            continue
        with baselines._lock:
            data = list(baselines._hist[(t.asset_id, "tank_level_pct")])
        if len(data) < 6:
            continue
        drop_pct = data[0] - data[-1]          # net fall over the window
        if drop_pct <= 0:
            continue
        per_h = (drop_pct / 100.0) * cap / (len(data) * sample_interval_h)
        total += per_h
        have = True
    return total if have else None


def assess_water(assets: List[Asset], baselines=None, now: Optional[datetime] = None,
                 draw_lph: Optional[float] = None, sample_interval_h: float = 1.0) -> WaterStatus:
    now = now or datetime.now()
    tanks = [a for a in assets if a.asset_type in _TANKS]
    pumps = [a for a in assets if a.asset_type in (AssetType.TRANSFER_PUMP, AssetType.BOOSTER_PUMP)]
    risks: List[Risk] = []

    # Stored volume.
    stored = capacity = 0.0
    for t in tanks:
        cap = _num((t.signals or {}).get("tank_capacity_l")) or _DEFAULT_CAP.get(t.asset_type, 30000.0)
        lvl = _num((t.signals or {}).get("tank_level_pct"))
        capacity += cap
        if lvl is not None:
            stored += (lvl / 100.0) * cap
    fill_pct = round(100.0 * stored / capacity, 1) if capacity else 0.0

    # Consumption rate: explicit > learned trend > default (3%/h of capacity).
    draw = draw_lph
    if draw is None:
        draw = next((_num((t.signals or {}).get("draw_lph")) for t in tanks
                     if _num((t.signals or {}).get("draw_lph")) is not None), None)
    if draw is None:
        draw = _derive_draw(tanks, baselines, sample_interval_h)
    if draw is None or draw <= 0:
        draw = max(capacity * 0.03, 1.0)       # cautious default
    hours = round(stored / draw, 1) if draw > 0 else None
    days = round(hours / 24.0, 1) if hours is not None else None

    # Refill chain: a transfer pump that's online + not faulted, and power available.
    def _pump_ok(p: Asset) -> bool:
        s = p.signals or {}
        if s.get("fault") or s.get("online") is False:
            return False
        cur = _num(s.get("current_a"))
        return True if cur is None else True   # presence of pump asset = capable unless faulted
    transfer_ok = any(_pump_ok(p) for p in pumps if p.asset_type in _TRANSFER) or not any(
        p.asset_type in _TRANSFER for p in pumps)
    gens = [a for a in assets if a.asset_type == AssetType.DIESEL_GENERATOR]
    power_ok = not any((g.signals or {}).get("fault") for g in gens)
    can_refill = transfer_ok and power_ok

    # Pump risk that threatens the refill chain.
    for p in pumps:
        s = p.signals or {}
        if s.get("fault") or s.get("online") is False:
            risks.append(Risk(p.asset_id, p.name, ServiceType.WATER, Severity.CRITICAL,
                              f"{p.name} down — refill/supply chain broken",
                              "Pump faulted/offline — water delivery at risk.",
                              confidence="Medium", evidence=["pump fault/offline", "water-critical role"]))

    # Score.
    if hours is None:
        score = 60.0
    elif hours >= 48:
        score = 100.0
    elif hours >= 24:
        score = 85.0
    elif hours >= 12:
        score = 65.0
    elif hours >= 6:
        score = 45.0
    else:
        score = 25.0
    if not can_refill:
        score = min(score, 40.0)
    score = max(0.0, min(100.0, score - 15.0 * sum(1 for r in risks if r.severity == Severity.CRITICAL)))

    # Forecast + headline risk.
    if hours is not None and hours < 24 and not can_refill:
        forecast = f"~{hours:.0f}h of water left and refill is blocked — shortage likely; restore the refill chain now."
        risks.append(Risk("WATER", "Water Service", ServiceType.WATER, Severity.CRITICAL,
                          f"Water Availability: ~{hours:.0f}h remaining, refill blocked",
                          forecast, confidence="High",
                          evidence=[f"{fill_pct:.0f}% stored", f"~{draw:.0f} L/h draw", "refill chain down"]))
    elif hours is not None and hours < 12:
        forecast = f"~{hours:.0f}h of water at current draw; refilling — monitor."
        risks.append(Risk("WATER", "Water Service", ServiceType.WATER, Severity.WARNING,
                          f"Water Availability: ~{hours:.0f}h remaining at current draw", forecast,
                          confidence="Medium", evidence=[f"{fill_pct:.0f}% stored", f"~{draw:.0f} L/h draw"]))
    elif not can_refill:
        forecast = f"{fill_pct:.0f}% stored (~{days}d) but refill chain is impaired — fix before it drains."
    else:
        forecast = f"{fill_pct:.0f}% stored, ~{days}d at current draw, refill chain healthy."

    return WaterStatus(
        score=round(score, 1), band=HealthBand.from_score(score).value,
        stored_l=round(stored), capacity_l=round(capacity), fill_pct=fill_pct,
        draw_lph=round(draw, 1), hours_remaining=hours, days_remaining=days,
        can_refill=can_refill, forecast=forecast, risks=risks,
    )
