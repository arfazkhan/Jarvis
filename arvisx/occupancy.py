"""
ArvisX Phase-5b — virtual occupancy + ghost-floor detection.

Residential port of commercial ARVIS's VirtualOccupancySensor / find_ghost_spaces.
With cheap CO2 + motion sensors (PIR), estimate whether an area is occupied, then flag
GHOST operation — empty space still being conditioned/lit → energy waste.

Honest like the rest of ArvisX: CO2 lags and motion has blind spots, so the estimate
carries a CONFIDENCE and says 'likely empty — verify', and ABSTAINS (UNKNOWN) when
neither sensor is present rather than guessing a space is empty.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from arvisx.models import (
    GhostAlert, OccupancyLevel, Risk, ServiceType, Severity, Zone,
)

_AMBIENT_CO2 = 420.0     # outdoor baseline ppm


def estimate_occupancy(co2_ppm: Optional[float], motion_events_15m: Optional[float],
                       light_on: Optional[bool] = None) -> Tuple[OccupancyLevel, float]:
    """Combine CO2 + motion (+ light) → occupancy level + confidence (0..1).
    Returns UNKNOWN with 0 confidence when neither primary sensor is available."""
    have_co2 = isinstance(co2_ppm, (int, float))
    have_motion = isinstance(motion_events_15m, (int, float))
    if not have_co2 and not have_motion:
        return OccupancyLevel.UNKNOWN, 0.0

    score = 0.0   # >0 → occupied evidence, <0 → empty evidence
    conf = 0.0
    if have_motion:
        if motion_events_15m >= 3:
            score += 2; conf += 0.45            # motion = strong occupied signal
        elif motion_events_15m >= 1:
            score += 1; conf += 0.3
        else:
            score -= 1.5; conf += 0.5           # no motion (PIR) → strong empty evidence
    if have_co2:
        rise = co2_ppm - _AMBIENT_CO2
        if rise > 250:
            score += 2; conf += 0.4             # people breathing → occupied
        elif rise > 80:
            score += 1; conf += 0.25
        else:
            score -= 1.5; conf += 0.35          # near-ambient → empty evidence
    if light_on is False:
        score -= 0.5; conf += 0.05

    conf = min(conf, 0.95)
    if score >= 1.5:
        return OccupancyLevel.OCCUPIED, conf
    if score <= -1.5:
        return OccupancyLevel.EMPTY, conf
    return OccupancyLevel.LIKELY_EMPTY if score < 0 else OccupancyLevel.OCCUPIED, max(conf * 0.7, 0.3)


def detect_ghost(zone: Zone, now: Optional[datetime] = None) -> Optional[GhostAlert]:
    """Ghost = conditioning active + area (likely) empty with enough confidence."""
    s = zone.signals or {}
    conditioning = bool(s.get("ac_on")) or bool(s.get("light_on")) or zone.always_on
    if not conditioning:
        return None
    level, conf = estimate_occupancy(s.get("co2_ppm"), s.get("motion_events_15m"), s.get("light_on"))
    if level in (OccupancyLevel.EMPTY, OccupancyLevel.LIKELY_EMPTY) and conf >= 0.5:
        waste_kw = zone.conditioned_load_kw
        waste_qar_day = round(waste_kw * 24.0 * zone.tariff_qar_per_kwh, 1)
        return GhostAlert(
            zone_id=zone.zone_id, zone_name=zone.name, occupancy=level, confidence=round(conf, 2),
            waste_kw=waste_kw, waste_qar_per_day=waste_qar_day,
            note=f"{zone.name} is {level.value} (conf {conf:.0%}) but conditioning is on — "
                 f"~{waste_kw:.1f}kW / ~QAR {waste_qar_day:.0f}/day wasted.",
        )
    return None


def assess_zones(zones: List[Zone], now: Optional[datetime] = None) -> Tuple[float, List[Risk], List[GhostAlert]]:
    """Energy-service health + ghost risks across all zones. Returns
    (energy_score, risks, alerts). No zones → perfect score, no risks."""
    now = now or datetime.now()
    alerts: List[GhostAlert] = []
    risks: List[Risk] = []
    for z in zones or []:
        g = detect_ghost(z, now)
        if g is None:
            continue
        alerts.append(g)
        sev = Severity.WARNING if g.waste_qar_per_day >= 20 else Severity.MAINTENANCE
        band = "High" if g.confidence >= 0.75 else "Medium" if g.confidence >= 0.6 else "Low"
        risks.append(Risk(
            asset_id=z.zone_id, asset_name=z.name, service=ServiceType.ENERGY, severity=sev,
            message=f"{z.name}: energy waste — empty but conditioned",
            detail=g.note + " Apply an occupancy-based setback / schedule.",
            confidence=band,
            evidence=[f"{g.occupancy.value} (occupancy {g.confidence:.0%})",
                      "conditioning active", f"~QAR {g.waste_qar_per_day:.0f}/day wasted"],
        ))
    score = max(0.0, 100.0 - 18.0 * len(alerts))
    return round(score, 1), risks, alerts
