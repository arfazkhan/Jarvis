"""Phase-A deterministic analyzers: reading anomaly (L1), trend contradiction (L2),
asset health (L7), compliance (L8). Pure — no DB, no LLM."""
from __future__ import annotations

from arvisx.analyzers import reading_anomaly, trend_alert, asset_health, compliance_report


# ── L1 reading anomaly ──────────────────────────────────────────────────
def test_reading_anomaly_abstains_on_thin_history():
    r = reading_anomaly([24.9, 25.0], 21.7)
    assert r["flagged"] is False and r["reason"] == "insufficient history"


def test_reading_anomaly_flags_battery_dip():
    # the vision example: 30 days around 24.8–25.2, today 21.7 → flag
    hist = [24.9, 25.0, 24.8, 25.1, 25.0, 24.9, 25.2, 24.8]
    r = reading_anomaly(hist, 21.7)
    assert r["flagged"] is True and r["direction"] == "below" and r["z"] <= -3


def test_reading_anomaly_in_band_ok():
    hist = [24.9, 25.0, 24.8, 25.1, 25.0, 24.9]
    assert reading_anomaly(hist, 24.95)["flagged"] is False


def test_reading_anomaly_flat_history_no_explosion():
    # perfectly flat history must NOT make a small move read as huge sigma
    r = reading_anomaly([70.0] * 8, 69.8)
    assert r["flagged"] is False


# ── L2 trend contradiction ──────────────────────────────────────────────
def test_trend_declining_flags():
    t = trend_alert([30, 25, 20, 15])
    assert t["flagged"] and t["direction"] == "declining" and t["change_pct"] == 50


def test_trend_rising_flags():
    assert trend_alert([10, 14, 19, 25])["direction"] == "rising"


def test_trend_stable_no_flag():
    assert trend_alert([20, 21, 20, 20])["flagged"] is False


def test_trend_insufficient():
    assert trend_alert([30, 20])["flagged"] is False


# ── L7 asset health ─────────────────────────────────────────────────────
def test_health_perfect_when_recently_checked_clean():
    h = asset_health(days_since_check=0)
    assert h["score"] == 100 and h["band"] == "good"


def test_health_penalizes_and_bands():
    h = asset_health(critical_issues=1, open_issues=1, days_since_check=0)
    assert h["score"] == 70 and h["band"] == "watch"
    assert any("critical" in r for r in h["reasons"])


def test_health_overdue_and_stale_risk():
    h = asset_health(overdue_ppm=True, days_since_check=None, anomalies=2)
    assert h["band"] == "risk" and h["score"] < 60
    assert any("overdue" in r for r in h["reasons"])
    assert any("no recent check" in r for r in h["reasons"])


def test_health_clamped_at_zero():
    assert asset_health(critical_issues=10)["score"] == 0


# ── L8 compliance ───────────────────────────────────────────────────────
def test_compliance_high_when_overdue():
    rep = compliance_report(
        [{"asset": "MSB", "status": "overdue", "days_remaining": -17, "hours_remaining": None}], [])
    assert rep["compliance_risk"] == "high"
    assert rep["overdue_ppm"][0]["asset"] == "MSB" and rep["overdue_ppm"][0]["days_overdue"] == 17


def test_compliance_medium_due_soon_or_stale():
    rep = compliance_report([{"asset": "DG-1", "status": "due_soon", "days_remaining": 5}], [])
    assert rep["compliance_risk"] == "medium" and "DG-1" in rep["due_soon_ppm"]
    rep2 = compliance_report([], [{"asset": "FIRE-PUMP", "days_since_check": 9}])
    assert rep2["compliance_risk"] == "medium"


def test_compliance_low_when_clean():
    assert compliance_report([{"asset": "X", "status": "ok", "days_remaining": 40}], [])["compliance_risk"] == "low"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print(f"  ok {f.__name__}")
    print(f"PASS — {len(fns)} analyzer tests")
