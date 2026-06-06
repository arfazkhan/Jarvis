"""
ArvisX Phase-5a — PM virtual sensors.

A virtual sensor DERIVES a preventive-maintenance indicator that has no dedicated
hardware, from the cheap signals residential gear already exposes (power draw,
on/off starts, runtime). One power clamp → many PM indicators. Same pattern as the
commercial VirtualOccupancySensor: combine available signals → a derived value WITH
a confidence, and ABSTAIN when inputs are missing (never fabricate).

Derived signals are written back into asset.signals as `v_*` so the existing health,
drift (Phase 4) and advisory layers consume them like real sensors. History-dependent
sensors (power-creep, dry-run) read the Phase-4 BaselineStore for the learned normal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from arvisx.models import Asset, AssetType, Risk, Severity

logger = logging.getLogger("arvisx.vsensors")

_PUMPS = {AssetType.TRANSFER_PUMP, AssetType.BOOSTER_PUMP,
          AssetType.POOL_FILTRATION_PUMP, AssetType.STP_PUMP}


@dataclass
class VirtualReading:
    key: str            # v_* signal written back into the asset
    value: float
    unit: str
    confidence: float   # 0..1
    note: str


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class VirtualSensor:
    key = "v_base"
    def applies(self, asset: Asset) -> bool: return False
    def evaluate(self, asset: Asset, baselines, now) -> Tuple[Optional[VirtualReading], Optional[Risk]]:
        return None, None
    def _risk(self, asset, sev, msg, detail) -> Risk:
        return Risk(asset.asset_id, asset.name, asset.service, sev, msg, detail)


class ShortCycling(VirtualSensor):
    """Starts-per-hour from on/off counts → contactor wear / pressure-tank fault /
    oversizing. From `starts_today` (no extra hardware beyond a run signal)."""
    key = "v_cycling_per_hour"
    THRESH = 4.0
    def applies(self, asset): return asset.asset_type in _PUMPS
    def evaluate(self, asset, baselines, now):
        starts = _num((asset.signals or {}).get("starts_today"))
        if starts is None:
            return None, None
        rate = round(starts / 24.0, 2)
        reading = VirtualReading(self.key, rate, "starts/h", 0.8,
                                 "derived from start counts")
        risk = None
        if rate > self.THRESH:
            risk = self._risk(asset, Severity.WARNING,
                              f"{asset.name} short-cycling ({rate:.1f} starts/h)",
                              "Frequent starts wear contactors/motors — check pressure-tank precharge, "
                              "pressure-switch differential, or pump oversizing.")
        return reading, risk


class DutyCycle(VirtualSensor):
    """Run-fraction of the day → over-use / demand mismatch / undersizing.
    From `runtime_today_hours`."""
    key = "v_duty_cycle"
    THRESH = 0.9
    def applies(self, asset): return asset.asset_type in _PUMPS or asset.asset_type == AssetType.STP_BLOWER
    def evaluate(self, asset, baselines, now):
        rt = _num((asset.signals or {}).get("runtime_today_hours"))
        if rt is None:
            return None, None
        duty = round(min(rt / 24.0, 1.0), 2)
        reading = VirtualReading(self.key, duty, "fraction", 0.85, "runtime/24h")
        risk = None
        if duty > self.THRESH:
            risk = self._risk(asset, Severity.WARNING,
                              f"{asset.name} running near-continuously ({duty*100:.0f}% duty)",
                              "Sustained near-100% duty points to undersizing, a stuck call, or rising "
                              "demand/leak — accelerates wear.")
        return reading, risk


class PowerCreep(VirtualSensor):
    """Power drifting ABOVE the asset's learned normal at similar duty → rising
    friction: bearing wear, fouling, impeller damage. Reads the Phase-4 baseline."""
    key = "v_power_creep_sigma"
    def applies(self, asset): return asset.asset_type in _PUMPS or asset.asset_type == AssetType.STP_BLOWER
    def evaluate(self, asset, baselines, now):
        if baselines is None or _num((asset.signals or {}).get("power_kw")) is None:
            return None, None
        z = baselines.drift_z(asset.asset_id, "power_kw")
        if z is None:
            return None, None   # not enough history → abstain
        reading = VirtualReading(self.key, round(z, 2), "sigma", 0.7,
                                 "power vs learned baseline")
        risk = None
        if z >= 3.0:
            risk = self._risk(asset, Severity.WARNING,
                              f"{asset.name} power creep ({z:.1f}σ above its own normal)",
                              "Drawing more power for the same duty — early mechanical wear "
                              "(bearings/impeller) or fouling. Trend it and inspect before failure.")
        return reading, risk


class DryRunRisk(VirtualSensor):
    """Power far BELOW the learned running load while the unit is on → loss of prime /
    running dry / closed suction. Reads the Phase-4 baseline."""
    key = "v_dry_run_risk"
    def applies(self, asset): return asset.asset_type in _PUMPS
    def evaluate(self, asset, baselines, now):
        p = _num((asset.signals or {}).get("power_kw"))
        if p is None or baselines is None:
            return None, None
        base = baselines.baseline(asset.asset_id, "power_kw")
        if base is None:
            return None, None
        med, _mad, _n = base
        if med <= 0 or p <= 0:
            return None, None
        ratio = p / med
        risk = None
        flagged = ratio < 0.5   # running but pulling <50% of normal load
        reading = VirtualReading(self.key, round(1.0 - ratio, 2), "score", 0.65,
                                 f"power {p:.1f} vs normal {med:.1f}kW")
        if flagged:
            risk = self._risk(asset, Severity.WARNING,
                              f"{asset.name} possible dry-run / loss of prime",
                              f"Running but drawing {ratio*100:.0f}% of normal load — air-bound, lost prime, "
                              "or closed suction. Risk of seal/bearing damage. Check suction + prime.")
        return reading, risk


class PoolTurnover(VirtualSensor):
    """Pool water turnovers/day from filtration runtime × flow ÷ volume → water-quality
    proxy. Needs `flow_lpm` + `pool_volume_l` (commissioned), else abstains."""
    key = "v_turnovers_per_day"
    MIN_TURNOVERS = 1.0
    def applies(self, asset): return asset.asset_type == AssetType.POOL_FILTRATION_PUMP
    def evaluate(self, asset, baselines, now):
        s = asset.signals or {}
        rt = _num(s.get("runtime_today_hours")); flow = _num(s.get("flow_lpm")); vol = _num(s.get("pool_volume_l"))
        if rt is None or not flow or not vol:
            return None, None
        turns = round((rt * 60.0 * flow) / vol, 2)
        reading = VirtualReading(self.key, turns, "turnovers/day", 0.75, "runtime×flow/volume")
        risk = None
        if turns < self.MIN_TURNOVERS:
            risk = self._risk(asset, Severity.WARNING,
                              f"{asset.name} pool turnover below code ({turns:.1f}/day)",
                              "Insufficient water turnover risks water quality — increase filtration runtime "
                              "or check flow restriction.")
        return reading, risk


_SENSORS: List[VirtualSensor] = [
    ShortCycling(), DutyCycle(), PowerCreep(), DryRunRisk(), PoolTurnover(),
]


def derive_all(asset: Asset, baselines=None, now: Optional[datetime] = None) -> Tuple[List[VirtualReading], List[Risk]]:
    """Run every applicable virtual sensor: write v_* signals into the asset and
    collect PM risks. Abstaining sensors contribute nothing (no fabrication)."""
    now = now or datetime.now()
    readings: List[VirtualReading] = []
    risks: List[Risk] = []
    for vs in _SENSORS:
        if not vs.applies(asset):
            continue
        reading, risk = vs.evaluate(asset, baselines, now)
        if reading is not None:
            asset.signals[reading.key] = reading.value
            readings.append(reading)
        if risk is not None:
            risks.append(risk)
    return readings, risks
