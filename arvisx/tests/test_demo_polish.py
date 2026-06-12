"""Polish fixes surfaced by the live WhatsApp demo: greeting/fix intents, issue
overflow, false 'stuck sensor' suppression, twin cold-start runtime backfill."""
from __future__ import annotations

from datetime import datetime

from arvisx.messaging import answer, route_intent
from arvisx.models import (Asset, AssetType, CommunityReport, Risk, ServiceHealth,
                           ServiceType, Severity, HealthBand)
from arvisx.signal_quality import assess_quality_risks
from arvisx.twin import CommunityTwin


# ── intents ───────────────────────────────────────────────────────────────
def test_greeting_routes_to_status_not_unknown():
    for g in ["hi", "Hello", "hey", "good morning", "Salam"]:
        assert route_intent(g) == "status", g


def test_fix_intent():
    for q in ["how to fix", "what should I do", "how do we repair it", "next step"]:
        assert route_intent(q) == "fix", q


def _report(n_risks):
    risks = []
    sev = [Severity.CRITICAL, Severity.WARNING, Severity.MAINTENANCE]
    for i in range(n_risks):
        risks.append(Risk(f"A{i}", f"Asset {i}", ServiceType.WATER, sev[i % 3],
                          f"issue {i}", f"do action {i}", confidence="Low"))
    svc = [ServiceHealth(ServiceType.WATER, "Water", 80.0, HealthBand.ATTENTION, [])]
    return CommunityReport(generated_at=datetime.now(), readiness=80.0,
                           readiness_band="Attention Required", services=svc,
                           risks=risks, assets=[])


def test_issues_overflow_shows_remaining_count():
    res = answer("any issues?", _report(15))
    assert "15 active issue" in res["text"]
    assert "and 5 more" in res["text"]          # 15 − top 10
    # critical ranked above maintenance — first listed line is a critical one
    assert "🚨" in res["text"].split("\n")[1]


def test_fix_answer_lists_actions():
    res = answer("how to fix", _report(6))
    assert res["intent"] == "fix"
    assert "What to do" in res["text"] and "→ do action" in res["text"]
    assert "create work order" in res["text"].lower()


# ── false 'stuck sensor' suppression ──────────────────────────────────────
def _baselines_flat(asset_id, signal, value, n=30):
    from arvisx.learning import BaselineStore
    bl = BaselineStore()
    for _ in range(n):
        bl.observe(asset_id, signal, value)
    return bl


def test_off_pump_reading_zero_is_not_stuck():
    bl = _baselines_flat("XFER-PUMP-01", "power_kw", 0.0)
    a = Asset("XFER-PUMP-01", "Transfer Pump 1", AssetType.TRANSFER_PUMP, signals={"power_kw": 0.0})
    risks = assess_quality_risks(a, bl)
    assert not any("stuck" in r.message.lower() for r in risks), "0 kW = pump OFF, not a stuck sensor"


def test_starts_today_counter_not_flagged_stuck():
    bl = _baselines_flat("BOOST-PUMP-01", "starts_today", 22.0)
    a = Asset("BOOST-PUMP-01", "Booster Pump 1", AssetType.BOOSTER_PUMP, signals={"starts_today": 22})
    risks = assess_quality_risks(a, bl)
    assert not any("stuck" in r.message.lower() for r in risks), "starts_today is a counter"


# ── twin cold-start backfill ──────────────────────────────────────────────
def test_twin_midday_spawn_backfills_runtime():
    twin = CommunityTwin(start=datetime(2026, 6, 1, 13, 0), seed=3)   # spawn at 1 PM
    assert twin.pool_runtime_today > 0, "pool ran 06:00–13:00 already — must be backfilled"
    assert twin.stp_runtime_today > 0, "STP aeration accumulated by 1 PM"


def test_twin_midnight_spawn_zero_runtime():
    twin = CommunityTwin(start=datetime(2026, 6, 1, 0, 5), seed=3)
    assert twin.pool_runtime_today == 0.0, "pool schedule hasn't started at 00:05"


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print(f"  ✅ {f.__name__}")
    print(f"PASS — {len(fns)} demo-polish tests")
