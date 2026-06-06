"""
ArvisX Phase-6 — environmental sensing + sensor FUSION.

Single sensors are boring; the value is COMBINING them. A CT clamp says a unit is
running; a temp sensor says the room isn't cooling; presence says it's occupied —
together they say COOLING FAULT with high confidence. This is the commercial
"independent corroborating sources" idea applied to cheap physical sensors:

  confidence = number of INDEPENDENT modalities that agree
    1 modality  → Low   (single signal — flag + 'confirm')
    2 modalities → Medium
    3+ modalities → High

Modalities: ELECTRICAL (CT/power), THERMAL (temp), HUMIDITY, PRESENCE, RUNTIME.
Each fusion finding rides the existing risk → advisory → work-order pipeline, and
abstains honestly when only one weak signal is present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from arvisx.models import Asset, AssetType, Risk, Severity

_PUMPS = {AssetType.TRANSFER_PUMP, AssetType.BOOSTER_PUMP,
          AssetType.POOL_FILTRATION_PUMP, AssetType.STP_PUMP}
_COOLING = {AssetType.AC_UNIT, AssetType.FCU}


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _running(asset: Asset) -> Optional[bool]:
    """Run-state from electrical signal (CT amps or power). None if no electrical sensor."""
    s = asset.signals or {}
    cur = _num(s.get("current_a"))
    if cur is not None:
        return cur > 0.5
    p = _num(s.get("power_kw"))
    if p is not None:
        return p > 0.05
    return None


_BAND = {1: "Low", 2: "Medium", 3: "High", 4: "High", 5: "High"}


@dataclass
class FusionFinding:
    asset_id: str
    asset_name: str
    conclusion: str
    action: str
    severity: Severity
    confidence_band: str
    modalities: List[str] = field(default_factory=list)   # independent sources that agreed
    evidence: List[str] = field(default_factory=list)


def _finding(asset, conclusion, action, severity, corrob: List[Tuple[str, str]]) -> FusionFinding:
    mods = sorted({m for m, _ in corrob})
    return FusionFinding(
        asset_id=asset.asset_id, asset_name=asset.name, conclusion=conclusion, action=action,
        severity=severity, confidence_band=_BAND.get(len(mods), "High"),
        modalities=mods, evidence=[f for _, f in corrob],
    )


# ── Fusion rules ─────────────────────────────────────────────────────────
def _cooling_fault(asset: Asset, baselines, now) -> Optional[FusionFinding]:
    """AC running + room not reaching setpoint (+ occupied) → cooling effectiveness
    declining, WITHOUT talking to the AC."""
    if asset.asset_type not in _COOLING:
        return None
    s = asset.signals or {}
    run = _running(asset)
    rt = _num(s.get("room_temp_c")); sp = _num(s.get("room_setpoint_c"))
    if run is not True or rt is None or sp is None:
        return None
    gap = rt - sp
    if gap < 3.0:
        return None   # cooling OK
    corrob = [("electrical", f"unit running ({s.get('current_a', s.get('power_kw'))})"),
              ("thermal", f"room {rt:.0f}°C vs setpoint {sp:.0f}°C (+{gap:.0f})")]
    occ = _num(s.get("motion_events_15m"))
    if occ is not None and occ >= 1:
        corrob.append(("presence", "occupied"))
    if _num(s.get("runtime_today_hours")):
        corrob.append(("runtime", f"running {s['runtime_today_hours']}h today"))
    return _finding(
        asset, "Cooling effectiveness declining — running but not reaching setpoint",
        "Check refrigerant charge, coil fouling, and airflow/filter — likely low charge or dirty coil.",
        Severity.WARNING, corrob)


def _pump_stress(asset: Asset, baselines, now) -> Optional[FusionFinding]:
    """Pump running + high current/power-creep + hot pump room → mechanical stress."""
    if asset.asset_type not in _PUMPS:
        return None
    s = asset.signals or {}
    if _running(asset) is not True:
        return None
    corrob: List[Tuple[str, str]] = [("electrical", "pump running")]
    # electrical degradation: power creep vs baseline
    hot = _num(s.get("room_temp_c"))
    creep = baselines.drift_z(asset.asset_id, "power_kw") if baselines is not None else None
    elec_stress = creep is not None and creep >= 3.0
    if elec_stress:
        corrob.append(("electrical", f"power {creep:.1f}σ above normal"))
    thermal = hot is not None and hot >= 45.0
    if thermal:
        corrob.append(("thermal", f"pump room {hot:.0f}°C (hot)"))
    if not (elec_stress or thermal):
        return None   # just running normally — no stress signal
    return _finding(
        asset, "Pump stress — elevated load and/or thermal stress while running",
        "Inspect bearings/seals + suction; check ventilation of the pump room and motor temperature.",
        Severity.WARNING, corrob)


def _room_overheat(asset: Asset, baselines, now) -> Optional[FusionFinding]:
    """Equipment running + very hot room → motor/equipment overheating (e.g. STP blower)."""
    s = asset.signals or {}
    hot = _num(s.get("room_temp_c"))
    if hot is None or hot < 45.0:
        return None
    corrob = [("thermal", f"room {hot:.0f}°C")]
    if _running(asset) is True:
        corrob.append(("electrical", "equipment running"))
    sev = Severity.CRITICAL if hot >= 55.0 else Severity.WARNING
    return _finding(
        asset, f"{asset.name} room overheating ({hot:.0f}°C) — equipment thermal risk",
        "Check ventilation/exhaust fan, ambient load, and motor temperature; risk of thermal trip/damage.",
        sev, corrob)


def _humidity_leak(asset: Asset, baselines, now) -> Optional[FusionFinding]:
    """Sudden high humidity in a dry equipment room → leak / overflow / burst (early)."""
    s = asset.signals or {}
    h = _num(s.get("humidity_pct"))
    if h is None or h < 80.0:
        return None
    corrob = [("humidity", f"room humidity {h:.0f}%")]
    return _finding(
        asset, f"{asset.name} room humidity spike ({h:.0f}%) — possible leak / overflow",
        "Inspect for water ingress, pipe/valve leak, or tank overflow before it spreads.",
        Severity.WARNING, corrob)


_RULES = [_cooling_fault, _pump_stress, _room_overheat, _humidity_leak]


def assess_fusion(assets: List[Asset], baselines=None, now: Optional[datetime] = None
                  ) -> Tuple[List[Risk], List[FusionFinding]]:
    """Run all fusion rules across assets → risks (confidence-banded) + findings."""
    now = now or datetime.now()
    risks: List[Risk] = []
    findings: List[FusionFinding] = []
    for a in assets:
        for rule in _RULES:
            f = rule(a, baselines, now)
            if f is None:
                continue
            findings.append(f)
            risks.append(Risk(
                asset_id=f.asset_id, asset_name=f.asset_name, service=a.service,
                severity=f.severity, message=f"{f.asset_name}: {f.conclusion}",
                detail=(f"[{f.confidence_band} confidence — {len(f.modalities)} independent signals: "
                        f"{', '.join(f.modalities)}] " + " · ".join(f.evidence) + f". {f.action}"),
            ))
    return risks, findings


def _demo():
    """Show the fusion 'magic': cheap sensors combined → confident conclusions."""
    ac = Asset("AC-CONF", "Conference Room AC", AssetType.AC_UNIT,
               signals={"current_a": 7.0, "room_temp_c": 29.0, "room_setpoint_c": 23.0,
                        "motion_events_15m": 4, "runtime_today_hours": 2.0})
    pump = Asset("STP-PUMP-01", "STP Pump 1", AssetType.STP_PUMP,
                 signals={"current_a": 12.0, "room_temp_c": 50.0})
    blower = Asset("STP-BLOWER-01", "STP Blower 1", AssetType.STP_BLOWER,
                   signals={"current_a": 9.0, "room_temp_c": 56.0})
    tank = Asset("UG-TANK-01", "Underground Tank 1", AssetType.UNDERGROUND_TANK,
                 signals={"humidity_pct": 92.0})
    _risks, findings = assess_fusion([ac, pump, blower, tank])
    print("ArvisX sensor fusion — cheap sensors combined:\n")
    for f in findings:
        print(f"  • [{f.confidence_band}] {f.conclusion}")
        print(f"      {len(f.modalities)} independent signals ({', '.join(f.modalities)}): "
              f"{' · '.join(f.evidence)}")
        print(f"      → {f.action}\n")


if __name__ == "__main__":
    _demo()
