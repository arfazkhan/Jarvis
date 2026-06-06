"""
ArvisX degradation simulator — the "catch a failure from one wire" demo.

Models a pump's slow mechanical decline and emits ONLY the cheap raw signal it would
publish in real life (power_kw, and on/off starts). The PM virtual sensors + Phase-4
drift then reconstruct the failure (power-creep, rising cycling) from that one signal —
no vibration/flow/pressure hardware. Proves condition-based PM from minimal sensing.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from arvisx.learning import BaselineStore
from arvisx.models import Asset, AssetType


def bearing_wear_series(nominal_kw: float = 3.0, healthy_days: int = 30,
                        decline_days: int = 10, seed: int = 7) -> List[float]:
    """Daily power readings: stable at nominal, then a gradual rise as bearings wear
    (more friction → more power for the same duty)."""
    rng = random.Random(seed)
    out = [nominal_kw + rng.gauss(0, 0.05) for _ in range(healthy_days)]
    for i in range(1, decline_days + 1):
        creep = nominal_kw * (0.10 * i / decline_days)   # up to +10% over the decline
        out.append(nominal_kw + creep + rng.gauss(0, 0.05))
    return out


def run_demo() -> Tuple[Asset, BaselineStore, List[float]]:
    """Feed a wearing pump's power history into the baseline; return the asset (set to
    its latest, degraded reading) + the baseline so virtual sensors/drift can judge it."""
    series = bearing_wear_series()
    b = BaselineStore()
    for p in series:
        b.observe("BOOST-PUMP-01", "power_kw", p)
    asset = Asset("BOOST-PUMP-01", "Booster Pump 1", AssetType.BOOSTER_PUMP,
                  signals={"power_kw": series[-1], "starts_today": 24,
                           "runtime_today_hours": 10.0})
    return asset, b, series


if __name__ == "__main__":
    from arvisx.health import build_report
    asset, baselines, series = run_demo()
    print(f"power history: healthy ~{series[0]:.2f}kW → latest {series[-1]:.2f}kW "
          f"(+{(series[-1]/series[0]-1)*100:.0f}%)")
    rep = build_report([asset], baselines=baselines, virtual=True)
    print(f"derived v_* signals: { {k: v for k, v in asset.signals.items() if k.startswith('v_')} }")
    print("PM risks caught from the power signal alone:")
    for r in rep.risks:
        print(f"  • {r.severity.value:>8}  {r.message}")
