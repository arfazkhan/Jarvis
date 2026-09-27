"""
How much of the building can ARVIS actually judge right now — and what would
unlock more.

Rule-based FDD needs no learning period (the rules are physics, not learned
baselines), so its alerts are not held back behind the statistical
calibrator's 28-day readiness. What limits it is point coverage: this summary
reports the share of applicable rules that could be judged, the sensors that
failed validation, and — most useful during onboarding — which missing points
would unlock the most rules if they were mapped.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable

from agent_commercial.fdd.finding import FaultFinding, Outcome


def coverage_summary(findings: Iterable[FaultFinding]) -> Dict[str, Any]:
    findings = list(findings)
    counts = Counter(f.outcome.value for f in findings)
    judged = counts.get("pass", 0) + counts.get("fail", 0)
    # "Design says not applicable" is a correct answer, not missing coverage.
    design_na = sum(1 for f in findings if f.outcome is Outcome.SKIP and f.reason.startswith("design attribute"))
    considered = len(findings) - design_na
    unlock: Counter = Counter()
    skip_reasons: Counter = Counter()
    per_equipment: Dict[str, Counter] = defaultdict(Counter)
    for f in findings:
        per_equipment[f.equipment_id][f.outcome.value] += 1
        if f.outcome is Outcome.SKIP:
            skip_reasons[f.reason.split(":")[0]] += 1
            for m in f.missing_roles:
                unlock[m] += 1
    failing_sensors = sorted({f"{f.equipment_id}:{r}" for f in findings
                              if f.family == "sensor" and f.outcome is Outcome.FAIL
                              for r in f.invalid_roles})
    return {
        "rules_judged": judged,
        "rules_considered": considered,
        "judged_pct": round(100.0 * judged / considered, 1) if considered else 0.0,
        "outcomes": dict(counts),
        "skip_reasons": dict(skip_reasons.most_common()),
        "points_to_map_next": [{"role": role, "rules_unlocked": n} for role, n in unlock.most_common(10)],
        "sensors_failing_validation": failing_sensors,
        "per_equipment": {eq: dict(c) for eq, c in sorted(per_equipment.items())},
    }
