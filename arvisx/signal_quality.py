"""
ArvisX Phase-13 — signal quality (don't let bad sensors become false alarms).

Real CT clamps / level / temp sensors glitch: out-of-range spikes, frozen values,
dropouts, garbage payloads. Untreated, a glitch becomes a false equipment CRITICAL and
the operator loses trust in week one. This layer treats a bad sensor as its OWN finding
("CT clamp reading impossible — sensor fault, not a pump fault") and quarantines the bad
value so it can't trigger a phantom equipment alarm. Ties into the confidence architecture:
a low-quality signal lowers the confidence of anything built on it.

Two integration points:
  - INGEST (AssetStore): a hard gate — impossible/garbage values are quarantined (not stored),
    timestamps tracked for staleness.
  - REPORT (assess_quality_risks): per-signal range / spike-vs-baseline / stuck-vs-baseline
    checks → SENSOR risks, surfaced like any other risk.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import List, Optional, Tuple

from arvisx.models import Asset, Risk, Severity

# Per-signal physical sanity bounds (keyword substring → (lo, hi)). First match wins.
_RANGES: List[Tuple[str, float, float]] = [
    ("level", 0.0, 100.0),
    ("fuel", 0.0, 100.0),
    ("humidity", 0.0, 100.0),
    ("co2", 0.0, 5000.0),
    ("ph", 0.0, 14.0),
    ("battery", 0.0, 80.0),
    ("voltage", 0.0, 80.0),
    ("current_a", 0.0, 2000.0),
    ("power_kw", 0.0, 1000.0),
    ("temp", -40.0, 120.0),
    ("runtime", 0.0, 1e7),
    ("pct", 0.0, 105.0),
    ("turnover", 0.0, 100.0),
    ("pressure", 0.0, 60.0),       # bar — gas/water line pressure
    ("leak", 0.0, 50000.0),        # ppm — gas concentration
    ("_total_m3", 0.0, 1e7),       # cumulative meter index
]
_MAD_K = 1.4826
_SPIKE_SIGMA = 8.0       # far beyond real drift (3σ) → sensor spike, not equipment drift
_STUCK_MIN_SAMPLES = 20  # frozen this long while it should vary → suspect stuck


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def range_for(key: str) -> Optional[Tuple[float, float]]:
    k = key.lower()
    for kw, lo, hi in _RANGES:
        if kw in k:
            return lo, hi
    return None


def check_value(key: str, value) -> Tuple[str, str]:
    """Hard ingest gate: ('good'|'bad', reason). Non-numeric values pass (handled elsewhere)."""
    if value is None:
        return "bad", "null value"
    if _is_num(value):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "bad", "NaN/inf value"
        rng = range_for(key)
        if rng and not (rng[0] <= value <= rng[1]):
            return "bad", f"out of physical range [{rng[0]:g}..{rng[1]:g}] (got {value:g})"
    return "good", ""


# Config/schedule signals that don't vary → exclude from stuck detection.
_NO_STUCK = re.compile(r"capacity|threshold|setpoint|_due|_date|expected_|volume", re.I)


def assess_quality_risks(asset: Asset, baselines=None, now: Optional[datetime] = None) -> List[Risk]:
    """Per-signal sensor-quality findings: out-of-range, spike-vs-baseline, stuck."""
    out: List[Risk] = []
    svc = asset.service
    for k, v in (asset.signals or {}).items():
        if k.startswith("v_") or not _is_num(v):
            continue
        flag, reason = check_value(k, v)
        if flag == "bad":
            out.append(Risk(asset.asset_id, asset.name, svc, Severity.WARNING,
                            f"{asset.name} {k} sensor reading invalid — likely sensor fault",
                            f"{reason}. Value quarantined; verify the sensor/wiring before trusting it.",
                            confidence="Medium", evidence=[f"{k}={v}", reason]))
            continue
        if baselines is None:
            continue
        base = baselines.baseline(asset.asset_id, k)
        if base is None:
            continue
        med, mad, n = base
        # Spike: many-σ beyond a varying baseline, OR a big jump off a dead-flat one.
        spike = ((mad > 1e-9 and abs(v - med) / (_MAD_K * mad) > _SPIKE_SIGMA)
                 or (mad <= 1e-9 and abs(v - med) > max(0.5 * abs(med), 1e-6)))
        if spike:
            out.append(Risk(asset.asset_id, asset.name, svc, Severity.WARNING,
                            f"{asset.name} {k} reading implausible vs history — possible sensor spike",
                            f"{k}={v} is far outside its own learned range — looks like a sensor "
                            "glitch, not real change. Confirm before acting.",
                            confidence="Medium", evidence=[f"{k}={v}", "far outside learned baseline"]))
        elif mad <= 1e-9 and n >= _STUCK_MIN_SAMPLES and not _NO_STUCK.search(k):
            out.append(Risk(asset.asset_id, asset.name, svc, Severity.MAINTENANCE,
                            f"{asset.name} {k} sensor possibly stuck (frozen value)",
                            f"{k} has not changed across {n} readings while it normally varies — the sensor "
                            "may be frozen/disconnected. Verify it reflects reality.",
                            confidence="Low", evidence=[f"{k}={v} unchanged ×{n}"]))
    return out
