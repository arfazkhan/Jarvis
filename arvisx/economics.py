"""
ArvisX Phase-15 — economic layer ("what is this costing us?").

Committees understand money faster than readiness scores. This translates risks into
QAR: energy WASTE (running inefficiently → extra kWh × tariff) and failure EXPOSURE
(deferred maintenance / wear → a repair-cost range + service-disruption). Deterministic
and honest — estimates are clearly labelled, given as ranges, grounded in the learned
baseline when available, and abstain when the inputs aren't there.

Config: ARVISX_TARIFF (currency/kWh, default 0.11 ≈ Kahramaa residential), ARVISX_CURRENCY
(default QAR). Multi-currency so it works in India (₹) or the Gulf (QAR).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from arvisx.models import Asset, AssetType, CommunityReport, Risk, Severity

TARIFF = float(os.environ.get("ARVISX_TARIFF", "0.11"))     # currency per kWh
CURRENCY = os.environ.get("ARVISX_CURRENCY", "QAR")

# Nominal running power (kW) when no live power signal exists.
_NOMINAL_KW = {
    AssetType.BOOSTER_PUMP: 3.0, AssetType.TRANSFER_PUMP: 5.0, AssetType.POOL_FILTRATION_PUMP: 2.0,
    AssetType.STP_BLOWER: 7.5, AssetType.STP_PUMP: 3.0, AssetType.AC_UNIT: 4.0, AssetType.FCU: 1.5,
}
# Failure / major-repair cost ranges (one-time, currency) by equipment class.
_FAILURE_COST = {
    AssetType.DIESEL_GENERATOR: (8000, 25000), AssetType.GENERATOR_BATTERY: (300, 900),
    AssetType.BOOSTER_PUMP: (1500, 5000), AssetType.TRANSFER_PUMP: (1500, 5000),
    AssetType.POOL_FILTRATION_PUMP: (1200, 4000), AssetType.STP_BLOWER: (3000, 9000),
    AssetType.STP_PUMP: (1500, 5000), AssetType.FIRE_PUMP: (3000, 10000),
    AssetType.UNDERGROUND_TANK: (2000, 8000), AssetType.OVERHEAD_TANK: (2000, 8000),
}
_DEFAULT_FAILURE = (1000, 5000)
_WATER_DISRUPTION = (1500, 4000)   # tanker supply + resident impact if water actually runs out

_WASTE_KW = re.compile(r"power creep|drift|near-continuous|duty|ghost|energy waste|above threshold|cooling effectiveness", re.I)
_FAILURE_KW = re.compile(r"overdue|service due|fault|wear|stress|weak|dry-run|stuck|inactivity|below baseline|below normal|capacity|test overdue|down", re.I)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@dataclass
class CostEstimate:
    kind: str                    # "energy_waste" | "failure_exposure" | "none"
    monthly_waste: float = 0.0   # recurring currency/month
    exposure_low: float = 0.0    # one-time potential cost range
    exposure_high: float = 0.0
    currency: str = CURRENCY
    basis: str = ""


def estimate(risk: Risk, asset: Optional[Asset], baselines=None) -> CostEstimate:
    msg = (risk.message + " " + risk.detail).lower()

    # ── Energy waste (recurring) ─────────────────────────────────────────
    if asset is not None and _WASTE_KW.search(msg):
        s = asset.signals or {}
        power = _num(s.get("power_kw")) or _NOMINAL_KW.get(asset.asset_type, 0.0)
        duty_h = _num(s.get("runtime_today_hours")) or 8.0
        extra_kw = None
        if baselines is not None and _num(s.get("power_kw")) is not None:
            base = baselines.baseline(asset.asset_id, "power_kw")
            if base:
                extra_kw = max(0.0, _num(s.get("power_kw")) - base[0])   # grounded extra over learned normal
        if extra_kw is None or extra_kw <= 0:
            extra_kw = power * 0.15                                      # estimate: ~15% inefficiency
        if power > 0 and extra_kw > 0:
            monthly = round(extra_kw * duty_h * 30.0 * TARIFF, 0)
            return CostEstimate("energy_waste", monthly_waste=monthly, currency=CURRENCY,
                                basis=f"~{extra_kw:.1f}kW extra × {duty_h:.0f}h/day × 30 × {TARIFF}/kWh")

    # ── Failure exposure (one-time potential) ────────────────────────────
    if _FAILURE_KW.search(msg) or risk.severity in (Severity.CRITICAL, Severity.WARNING):
        lo, hi = (_FAILURE_COST.get(asset.asset_type, _DEFAULT_FAILURE) if asset else _DEFAULT_FAILURE)
        basis = "estimated major-repair range for this equipment class"
        if "water" in msg and ("refill" in msg or "remaining" in msg or "supply" in msg):
            lo += _WATER_DISRUPTION[0]; hi += _WATER_DISRUPTION[1]
            basis += " + water tanker/disruption"
        return CostEstimate("failure_exposure", exposure_low=float(lo), exposure_high=float(hi),
                            currency=CURRENCY, basis=basis)

    return CostEstimate("none")


def money_line(est: CostEstimate) -> str:
    """One-line money summary for an alert/advisory."""
    if est.kind == "energy_waste" and est.monthly_waste > 0:
        return f"💸 Est. energy waste: ~{est.currency} {est.monthly_waste:,.0f}/month"
    if est.kind == "failure_exposure":
        return f"💸 Potential failure cost: {est.currency} {est.exposure_low:,.0f}–{est.exposure_high:,.0f}"
    return ""


def community_cost(report: CommunityReport, assets: List[Asset], baselines=None) -> dict:
    """'What is this costing us?' — total recurring waste + total exposure across active risks."""
    by_id = {a.asset_id: a for a in assets}
    monthly = 0.0
    exp_lo = exp_hi = 0.0
    items = []
    seen = set()
    for r in report.risks:
        key = (r.asset_id, r.message[:24])
        if key in seen:
            continue
        seen.add(key)
        est = estimate(r, by_id.get(r.asset_id), baselines)
        if est.kind == "none":
            continue
        monthly += est.monthly_waste
        exp_lo += est.exposure_low
        exp_hi += est.exposure_high
        items.append({"asset": r.asset_name, "issue": r.message, "kind": est.kind,
                      "monthly_waste": est.monthly_waste, "exposure_low": est.exposure_low,
                      "exposure_high": est.exposure_high, "basis": est.basis})
    return {"currency": CURRENCY, "monthly_waste": round(monthly, 0),
            "exposure_low": round(exp_lo, 0), "exposure_high": round(exp_hi, 0),
            "items": items}


def community_cost_message(report: CommunityReport, assets: List[Asset], baselines=None) -> str:
    c = community_cost(report, assets, baselines)
    if not c["items"]:
        return "✅ No measurable cost impact from current operations."
    L = [f"*What this is costing you*", ""]
    if c["monthly_waste"] > 0:
        L.append(f"💸 Ongoing waste: ~{c['currency']} {c['monthly_waste']:,.0f}/month")
    if c["exposure_high"] > 0:
        L.append(f"⚠️ At-risk (deferred maintenance): {c['currency']} {c['exposure_low']:,.0f}–{c['exposure_high']:,.0f}")
    L.append("")
    L.append("Top contributors:")
    for it in sorted(c["items"], key=lambda x: x["monthly_waste"] + x["exposure_high"], reverse=True)[:4]:
        amt = (f"~{c['currency']} {it['monthly_waste']:,.0f}/mo" if it["kind"] == "energy_waste"
               else f"{c['currency']} {it['exposure_low']:,.0f}–{it['exposure_high']:,.0f}")
        L.append(f"• {it['asset']}: {amt}")
    return "\n".join(L)
