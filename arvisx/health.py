"""
ArvisX Phase-0 intelligence layer (deterministic, no LLM).

Converts each asset's operational footprint into:
  - a per-asset health score + alerts (rule-based),
  - preventive-maintenance / operational RISKS,
  - a service-level roll-up (Water / Power / Pool / STP / Fire),
  - a community report (the MVP dashboard).

Deterministic on purpose: Phase 0 proves the residential model + health + PM end to
end with zero hardware and zero LLM. Phase 1 layers grounded RCA (arvis_core) on top.
The honest-when-unknown principle still holds: missing signals don't fabricate health.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from arvisx.models import (
    Asset, AssetType, AssetHealth, CommunityReport, HealthBand, Risk,
    ServiceHealth, ServiceType, Severity, ASSET_SERVICE,
)


def _days_until(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if dt is None:
        return None
    return (dt - now).days


# ── Per-asset health: rule-based score (0..100) + alerts + risks ─────────
def assess_asset(asset: Asset, now: datetime) -> Tuple[AssetHealth, List[Risk]]:
    score = 100.0
    alerts: List[str] = []
    risks: List[Risk] = []
    s = asset.signals or {}

    def _risk(sev: Severity, msg: str, detail: str = ""):
        risks.append(Risk(asset.asset_id, asset.name, asset.service, sev, msg, detail))

    # Offline / no data → can't assert health (abstain, don't fabricate).
    if not asset.online:
        score = min(score, 35.0)
        alerts.append("Asset offline — no live signal")
        _risk(Severity.WARNING, f"{asset.name} offline — no operational signal",
              "Data collection lost; health cannot be confirmed.")

    # Active fault flag on any asset.
    if s.get("fault"):
        score = min(score, 30.0)
        alerts.append("Active fault reported")
        _risk(Severity.CRITICAL, f"{asset.name} reporting an active fault",
              str(s.get("fault_detail", "Device fault signal active.")))

    # Runtime-over-threshold (PM): wear indicator.
    if asset.runtime_threshold_hours and asset.runtime_hours > asset.runtime_threshold_hours:
        score -= 25.0
        over = asset.runtime_hours - asset.runtime_threshold_hours
        alerts.append(f"Runtime {asset.runtime_hours:.0f}h over {asset.runtime_threshold_hours:.0f}h threshold")
        _risk(Severity.WARNING, f"{asset.name} runtime above threshold",
              f"{asset.runtime_hours:.0f}h vs {asset.runtime_threshold_hours:.0f}h limit (+{over:.0f}h).")

    # Service due / overdue (PM).
    d = _days_until(asset.next_maintenance_due, now)
    if d is not None:
        if d < 0:
            score -= 30.0
            alerts.append(f"Maintenance overdue {abs(d)}d")
            _risk(Severity.WARNING, f"{asset.name} maintenance overdue",
                  f"Service was due {abs(d)} day(s) ago.")
        elif d <= 14:
            score -= 8.0
            alerts.append(f"Service due in {d}d")
            _risk(Severity.MAINTENANCE, f"{asset.name} service due in {d} days",
                  "Schedule preventive maintenance.")

    # ── Asset-type-specific operational rules ────────────────────────────
    at = asset.asset_type
    if at in (AssetType.UNDERGROUND_TANK, AssetType.OVERHEAD_TANK):
        lvl = s.get("tank_level_pct")
        if isinstance(lvl, (int, float)):
            if lvl < 15:
                score = min(score, 40.0); alerts.append(f"Tank level critically low ({lvl:.0f}%)")
                _risk(Severity.CRITICAL, f"{asset.name} level critically low", f"{lvl:.0f}% — supply at risk.")
            elif lvl < 30:
                score -= 15.0; alerts.append(f"Tank level low ({lvl:.0f}%)")
                _risk(Severity.WARNING, f"{asset.name} level low", f"{lvl:.0f}%.")

    if at == AssetType.DIESEL_GENERATOR:
        fuel = s.get("fuel_level_pct")
        if isinstance(fuel, (int, float)):
            if fuel < 20:
                score = min(score, 35.0); alerts.append(f"Fuel low ({fuel:.0f}%)")
                _risk(Severity.CRITICAL, f"{asset.name} fuel low — backup at risk", f"{fuel:.0f}% fuel.")
            elif fuel < 40:
                score -= 12.0; alerts.append(f"Fuel below comfortable reserve ({fuel:.0f}%)")

    if at == AssetType.GENERATOR_BATTERY:
        v = s.get("battery_voltage")
        if isinstance(v, (int, float)) and v < 12.2:
            score -= 20.0; alerts.append(f"Battery weak ({v:.1f}V)")
            _risk(Severity.WARNING, f"{asset.name} battery weak", f"{v:.1f}V — generator may fail to start.")

    if at == AssetType.POOL_FILTRATION_PUMP:
        rt_today = s.get("runtime_today_hours")
        exp = s.get("expected_runtime_hours", 8.0)
        if isinstance(rt_today, (int, float)) and rt_today < 0.6 * exp:
            score -= 20.0; alerts.append(f"Filtration runtime below normal ({rt_today:.1f}h vs ~{exp:.0f}h)")
            _risk(Severity.WARNING, f"{asset.name} filtration runtime below normal",
                  f"{rt_today:.1f}h today vs expected ~{exp:.0f}h — water quality risk.")

    if at == AssetType.STP_BLOWER:
        rt_today = s.get("runtime_today_hours")
        if isinstance(rt_today, (int, float)) and rt_today < 1.0:
            score = min(score, 45.0); alerts.append("Blower inactivity detected")
            _risk(Severity.CRITICAL, f"{asset.name} inactivity detected",
                  f"{rt_today:.1f}h today — aeration loss risks STP process failure.")

    if at == AssetType.FIRE_PUMP:
        d_test = _days_until(s.get("next_test_due"), now)
        if d_test is not None and d_test < 0:
            score -= 25.0; alerts.append(f"Test overdue {abs(d_test)}d")
            _risk(Severity.WARNING, f"{asset.name} test overdue",
                  f"Mandatory test was due {abs(d_test)} day(s) ago — fire readiness unverified.")

    if at == AssetType.FIRE_PANEL and s.get("active_faults", 0):
        n = s["active_faults"]
        score -= 10.0 * min(n, 3)
        alerts.append(f"{n} active panel fault(s)")
        _risk(Severity.WARNING, f"{asset.name} reporting {n} active fault(s)",
              "Fire-system faults present (supplementary view — verify on the certified panel).")

    score = max(0.0, min(100.0, score))
    status = ("Fault" if s.get("fault") else "Offline" if not asset.online else
              alerts[0] if alerts else "Normal")
    health = AssetHealth(
        asset_id=asset.asset_id, name=asset.name, asset_type=at, status=status,
        score=round(score, 1), band=HealthBand.from_score(score),
        runtime_hours=asset.runtime_hours, last_maintenance=asset.last_maintenance,
        next_maintenance_due=asset.next_maintenance_due, alerts=alerts,
    )
    return health, risks


# Highest open-risk severity on a service decides its tile band. The product
# promise is "what needs attention before residents are affected", so a tile must
# turn yellow/red when there's an OPEN action on it — not only when a numeric score
# crosses a line. Score is kept as a secondary detail.
_SEV_BAND = {
    Severity.CRITICAL: HealthBand.CRITICAL,
    Severity.WARNING: HealthBand.ATTENTION,
    Severity.MAINTENANCE: HealthBand.ATTENTION,
    Severity.INFO: HealthBand.HEALTHY,
}
_BAND_RANK = {HealthBand.HEALTHY: 0, HealthBand.ATTENTION: 1, HealthBand.CRITICAL: 2}


# ── Service roll-up: worst-weighted score + risk-driven band ─────────────
def roll_up_services(asset_healths: List[AssetHealth], risks: List[Risk]) -> List[ServiceHealth]:
    by_service: Dict[ServiceType, List[AssetHealth]] = {st: [] for st in ServiceType}
    for h in asset_healths:
        by_service[ASSET_SERVICE[h.asset_type]].append(h)
    risks_by_service: Dict[ServiceType, List[Risk]] = {st: [] for st in ServiceType}
    for r in risks:
        risks_by_service[r.service].append(r)

    out: List[ServiceHealth] = []
    for st in ServiceType:
        members = by_service[st]
        if not members:
            continue
        # Score = mean tilted toward the WORST asset (weakest-link readiness).
        worst = min(members, key=lambda h: h.score)
        mean = sum(h.score for h in members) / len(members)
        svc_score = round(0.6 * worst.score + 0.4 * mean, 1)
        # Band = worst of (score band, highest open-risk severity band).
        band = HealthBand.from_score(svc_score)
        for r in risks_by_service[st]:
            rb = _SEV_BAND[r.severity]
            if _BAND_RANK[rb] > _BAND_RANK[band]:
                band = rb
        out.append(ServiceHealth(
            service=st, score=svc_score, band=band,
            contributing_assets=len(members),
            worst_asset=worst.name if (worst.score < 80 or risks_by_service[st]) else None,
        ))
    return out


_SEV_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.MAINTENANCE: 2, Severity.INFO: 3}


def build_report(assets: List[Asset], now: Optional[datetime] = None) -> CommunityReport:
    now = now or datetime.now()
    healths: List[AssetHealth] = []
    risks: List[Risk] = []
    for a in assets:
        h, r = assess_asset(a, now)
        healths.append(h)
        risks.extend(r)
    risks.sort(key=lambda r: _SEV_ORDER.get(r.severity, 9))
    services = roll_up_services(healths, risks)
    return CommunityReport(generated_at=now, services=services, risks=risks, assets=healths)
