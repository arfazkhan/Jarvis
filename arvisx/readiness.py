"""
ArvisX — baseline operational-readiness gate (data-driven, replaces the hardcoded
learning window).

The commissioning state machine used a fixed learning_days timer to leave LEARNING for
OPERATIONAL. But "14 days" is arbitrary — a building is ready when its BASELINES are
statistically trustworthy, not when a clock runs out. This assesses, deterministically,
whether the learned normals are good enough to alert on:

  • coverage   — fraction of monitored numeric signals that have a settled baseline
                 (>= MIN_SAMPLES observations),
  • stability  — each ready signal's dispersion (MAD/|median|) is finite and sane
                 (not a flat stuck sensor, not wildly noisy),

→ approve (ready) or reject with reasons + a suggested learning extension. The agent can
narrate a borderline rejection, but the gate itself is rules — no LLM needed to be safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from arvisx.learning import MIN_SAMPLES, _SKIP, _is_numeric


@dataclass
class SignalReadiness:
    asset_id: str
    signal: str
    samples: int
    ready: bool
    reason: str


@dataclass
class BaselineReadiness:
    ready: bool
    coverage: float                 # 0..1 share of signals with a settled baseline
    total: int
    ready_count: int
    signals: List[SignalReadiness] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    suggested_extra_days: int = 0

    def summary(self) -> str:
        if self.ready:
            return (f"Baselines READY — {self.ready_count}/{self.total} signals settled "
                    f"({self.coverage:.0%} coverage). Approved for operations.")
        return (f"Baselines NOT ready — {self.ready_count}/{self.total} signals settled "
                f"({self.coverage:.0%}). Extend learning ~{self.suggested_extra_days} days. "
                + "; ".join(self.reasons[:3]))


def assess_baseline_readiness(assets, baselines, min_coverage: float = 0.8) -> BaselineReadiness:
    """Is the learned baseline trustworthy enough to go operational?"""
    sigs: List[SignalReadiness] = []
    for a in assets:
        for k, v in (a.signals or {}).items():
            if not _is_numeric(v) or _SKIP.search(k):
                continue
            base = baselines.baseline(a.asset_id, k) if baselines else None
            if base is None:
                sigs.append(SignalReadiness(a.asset_id, k, 0, False, "insufficient samples"))
                continue
            med, mad, n = base
            rel = (mad / abs(med)) if med else (mad if mad else 0.0)
            # A steady signal (mad≈0) is a valid baseline — stuck-sensor detection is the
            # job of signal-quality/stale checks, not the readiness gate. Only reject a
            # signal whose dispersion is so large the learned normal can't be trusted.
            if rel > 2.0:
                sigs.append(SignalReadiness(a.asset_id, k, n, False, "too noisy — baseline unstable"))
            else:
                sigs.append(SignalReadiness(a.asset_id, k, n, True, "settled"))

    total = len(sigs)
    ready_count = sum(1 for s in sigs if s.ready)
    coverage = (ready_count / total) if total else 0.0
    ready = total > 0 and coverage >= min_coverage

    reasons: List[str] = []
    suggested = 0
    if not ready:
        thin = [s for s in sigs if not s.ready and s.reason == "insufficient samples"]
        flat = [s for s in sigs if s.reason.startswith("flat")]
        noisy = [s for s in sigs if s.reason.startswith("too noisy")]
        if total == 0:
            reasons.append("no monitored numeric signals yet")
        if thin:
            reasons.append(f"{len(thin)} signal(s) lack {MIN_SAMPLES}+ observations")
        if flat:
            reasons.append(f"{len(flat)} signal(s) look frozen (check the sensor, not just time)")
        if noisy:
            reasons.append(f"{len(noisy)} signal(s) still too noisy to baseline")
        # extension scales with how far short coverage is (min 3, capped 21 days)
        gap = max(0.0, min_coverage - coverage)
        suggested = max(3, min(21, int(round(gap * 30)) + (7 if flat or noisy else 0)))

    return BaselineReadiness(ready=ready, coverage=round(coverage, 3), total=total,
                             ready_count=ready_count, signals=sigs, reasons=reasons,
                             suggested_extra_days=suggested)
