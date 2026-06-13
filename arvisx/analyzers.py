"""
ArvisX Agentic Phase-A — deterministic analyzers (NO LLM).

The "no human would notice this from a checklist" wins, computed from the entries the
checklist already captures. Pure functions over already-fetched data so they're instant,
free, hermetically testable, and un-hallucinatable. The LLM agents (Phase C) reason OVER
these signals; they don't replace them.

  L1 Inspection Assistant — a reading vs the item's OWN history (robust band) → flag.
  L2 Supervisor          — missing items + trend contradictions on a submitted run.
  L7 Asset Health Score  — 0..100 per asset from issues / anomalies / PPM / staleness.
  L8 Compliance          — overdue PPM + assets gone stale (un-checked).

Same robust-z discipline as learning.py: a flat history can't manufacture huge sigma
(MAD floored relative to the value), and we ABSTAIN below a minimum history.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

_MAD_K = 1.4826
_REL_FLOOR = 0.01
_ABS_FLOOR = 1e-6
_Z = 3.0


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── L1: reading anomaly vs the item's own history ─────────────────────────
def reading_anomaly(history: List[float], latest: float, min_history: int = 5) -> Dict[str, Any]:
    """history = prior numeric readings for one item; latest = today's. Flags when latest
    is ≥3 robust-σ off the item's own learned band. Abstains under min_history."""
    hist = [h for h in (history or []) if _num(h) is not None]
    lat = _num(latest)
    if lat is None:
        return {"flagged": False, "reason": "non-numeric", "n": len(hist)}
    if len(hist) < min_history:
        return {"flagged": False, "reason": "insufficient history", "n": len(hist)}
    med = statistics.median(hist)
    mad = statistics.median([abs(x - med) for x in hist])
    scale = max(_MAD_K * mad, abs(med) * _REL_FLOOR, _ABS_FLOOR)
    z = (lat - med) / scale
    return {"flagged": abs(z) >= _Z, "z": round(z, 1), "median": round(med, 2),
            "low": round(med - _Z * scale, 2), "high": round(med + _Z * scale, 2),
            "latest": lat, "n": len(hist),
            "direction": "below" if z < 0 else "above"}


# ── L2: trend contradiction (e.g. "Normal" but steadily declining) ────────
def trend_alert(values: List[float], window: int = 4, min_change_pct: float = 0.10) -> Dict[str, Any]:
    """values chronological (oldest→newest). Flags a strong monotonic run over the last
    `window` readings (the 30/25/20/15 case) so a contradicting label gets verified."""
    vals = [_num(v) for v in (values or [])]
    vals = [v for v in vals if v is not None]
    if len(vals) < window:
        return {"flagged": False, "reason": "insufficient history"}
    recent = vals[-window:]
    dec = all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))
    inc = all(recent[i] < recent[i + 1] for i in range(len(recent) - 1))
    if not (dec or inc):
        return {"flagged": False}
    base = abs(recent[0]) or 1.0
    change_pct = abs(recent[-1] - recent[0]) / base
    if change_pct < min_change_pct:
        return {"flagged": False}
    return {"flagged": True, "direction": "declining" if dec else "rising",
            "from": recent[0], "to": recent[-1], "change_pct": round(change_pct * 100, 0)}


# ── L7: asset health score (0..100) ───────────────────────────────────────
def asset_health(*, open_issues: int = 0, critical_issues: int = 0, anomalies: int = 0,
                 overdue_ppm: bool = False, days_since_check: Optional[int] = None) -> Dict[str, Any]:
    """Deterministic score + reasons. Penalties are additive and clamped. No history /
    never checked → treated as stale (a real gap, not 'healthy by default')."""
    score = 100.0
    reasons: List[str] = []
    if critical_issues:
        score -= 30 * critical_issues; reasons.append(f"{critical_issues} critical issue(s)")
    other = max(0, open_issues - critical_issues)
    if other:
        score -= 10 * other; reasons.append(f"{other} open issue(s)")
    if anomalies:
        score -= 8 * anomalies; reasons.append(f"{anomalies} reading anomaly(ies)")
    if overdue_ppm:
        score -= 20; reasons.append("PPM overdue")
    if days_since_check is None:
        score -= 15; reasons.append("no recent check on record")
    elif days_since_check > 3:
        score -= 12; reasons.append(f"not checked in {days_since_check} days")
    score = max(0.0, min(100.0, round(score)))
    band = "good" if score >= 85 else ("watch" if score >= 60 else "risk")
    return {"score": score, "band": band, "reasons": reasons}


# ── L8: compliance ────────────────────────────────────────────────────────
def compliance_report(ppm_statuses: List[Dict[str, Any]], stale_assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """ppm_statuses = ppm_status() dicts; stale_assets = [{asset, days_since_check}].
    Summarizes the audit risk: overdue PPM + assets gone too long without a check."""
    overdue = [{"asset": s["asset"], "days_overdue": (-s["days_remaining"]) if s.get("days_remaining") is not None and s["days_remaining"] < 0 else None,
                "hours_over": (-s["hours_remaining"]) if s.get("hours_remaining") is not None and s["hours_remaining"] < 0 else None}
               for s in ppm_statuses if s.get("status") == "overdue"]
    due_soon = [s["asset"] for s in ppm_statuses if s.get("status") == "due_soon"]
    risk = "high" if overdue else ("medium" if (due_soon or stale_assets) else "low")
    return {"compliance_risk": risk, "overdue_ppm": overdue, "due_soon_ppm": due_soon,
            "stale_assets": stale_assets}
