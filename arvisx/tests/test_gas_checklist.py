"""Phase 17 — gas service (plant + per-apartment metering/billing) and Phase 17b —
the self-writing daily checklist with pencil-whip detection."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta

from arvisx.checklist import (daily_log, parse_checklist_reply, pending_prompts,
                              verify_reading)
from arvisx.gas_billing import monthly_statement, statement_csv
from arvisx.health import assess_asset
from arvisx.models import Asset, AssetType, ServiceType, Severity
from arvisx.persistence import ArvisxDb
from arvisx.simulator import healthy_community
from arvisx.twin import CommunityTwin


def _db():
    return ArvisxDb(os.path.join(tempfile.mkdtemp(prefix="gas_"), "g.db"), building_id="B")


# ── gas health rules ──────────────────────────────────────────────────────
def test_gas_plant_rules_fire_on_leak_low_bank_and_pressure():
    now = datetime.now()
    leak = Asset("GP", "Gas Plant", AssetType.GAS_PLANT,
                 signals={"leak_ppm": 350.0, "tank_level_pct": 60.0, "line_pressure_bar": 0.5})
    _, risks = assess_asset(leak, now)
    assert any(r.severity == Severity.CRITICAL and "concentration" in r.message for r in risks)

    low = Asset("GP", "Gas Plant", AssetType.GAS_PLANT,
                signals={"leak_ppm": 0.0, "tank_level_pct": 9.0, "line_pressure_bar": 0.5})
    _, risks = assess_asset(low, now)
    assert any("gas bank low" in r.message.lower() for r in risks)

    pr = Asset("GP", "Gas Plant", AssetType.GAS_PLANT,
               signals={"leak_ppm": 0.0, "tank_level_pct": 70.0, "line_pressure_bar": 4.2})
    _, risks = assess_asset(pr, now)
    assert any("pressure" in r.message.lower() for r in risks)

    healthy = Asset("GP", "Gas Plant", AssetType.GAS_PLANT,
                    signals={"leak_ppm": 0.0, "tank_level_pct": 80.0, "line_pressure_bar": 0.5})
    _, risks = assess_asset(healthy, now)
    assert not risks


def test_gas_service_rolls_up():
    from arvisx.health import build_report
    rep = build_report(healthy_community())
    assert any(s.service == ServiceType.GAS for s in rep.services)


# ── twin gas physics ──────────────────────────────────────────────────────
def test_twin_meters_are_monotonic_and_bank_drains():
    twin = CommunityTwin(seed=5)
    start_idx = dict(twin.gas_meters)
    start_bank = twin.gas_level_pct
    for _ in range(24 * 3):
        msgs = twin.step(1.0)
    assert all(twin.gas_meters[k] > start_idx[k] for k in start_idx), "meters must only count up"
    assert twin.gas_level_pct < start_bank, "bank drains as flats cook"
    topics = {t for t, _ in msgs}
    assert any("GAS-PLANT-01/tank_level_pct" in t for t in topics)
    assert sum(1 for t in topics if t.endswith("/meter_total_m3")) == twin.n_apartments


def test_twin_gas_leak_fault_emits():
    twin = CommunityTwin(seed=6)
    twin.inject(gas_leak_ppm=400.0)
    msgs = twin.step(1.0)
    leak = next(p for t, p in msgs if t.endswith("GAS-PLANT-01/leak_ppm"))
    assert float(leak) >= 400.0


# ── signal log + billing ──────────────────────────────────────────────────
def test_signal_log_downsamples_and_queries():
    db = _db()
    t0 = datetime(2026, 6, 1, 8, 0, 0)
    assert db.log_signal("APT-101", "meter_total_m3", 100.0, ts=t0, min_interval_s=600)
    assert not db.log_signal("APT-101", "meter_total_m3", 100.1, ts=t0 + timedelta(seconds=30),
                             min_interval_s=600), "within interval → downsampled away"
    assert db.log_signal("APT-101", "meter_total_m3", 101.0, ts=t0 + timedelta(minutes=20),
                         min_interval_s=600)
    near = db.signal_near("APT-101", "meter_total_m3", t0 + timedelta(minutes=2))
    assert near and near["value"] == 100.0
    assert db.signal_near("APT-101", "meter_total_m3", t0 + timedelta(days=3)) is None


def test_monthly_statement_consumption_flagged_and_csv():
    db = _db()
    base = datetime(2026, 6, 1, 0, 30)
    # APT-101: normal month 100 → 112.5 m³
    db.log_signal("APT-101", "meter_total_m3", 100.0, ts=base, min_interval_s=0)
    db.log_signal("APT-101", "meter_total_m3", 112.5, ts=base + timedelta(days=27), min_interval_s=0)
    # APT-102: index DECREASED → flagged, never billed silently
    db.log_signal("APT-102", "meter_total_m3", 500.0, ts=base, min_interval_s=0)
    db.log_signal("APT-102", "meter_total_m3", 30.0, ts=base + timedelta(days=27), min_interval_s=0)
    stmt = monthly_statement(db, "2026-06")
    by = {r["meter_id"]: r for r in stmt["meters"]}
    assert by["APT-101"]["status"] == "ok" and abs(by["APT-101"]["consumption_m3"] - 12.5) < 1e-6
    assert by["APT-102"]["status"] == "flagged"
    assert stmt["billable_meters"] == 1 and stmt["flagged"] == 1
    csv = statement_csv(stmt)
    assert "APT-101" in csv and "12.5" in csv


# ── checklist: auto-fill + verification + prompts ─────────────────────────
def test_daily_log_autofills_from_telemetry():
    db = _db()
    log = daily_log(healthy_community(), db)
    rec = {a["item_id"]: a for a in log["auto"]}
    assert rec["ugt_level"]["status"] == "recorded" and rec["ugt_level"]["value"] == 78.0
    assert rec["gas_level"]["status"] == "recorded"
    assert log["summary"]["physical_done"] == 0 and log["summary"]["physical_total"] >= 4


def test_verify_reading_matched_mismatch_and_honest_no_data():
    db = _db()
    ts = datetime(2026, 6, 10, 9, 0)
    db.log_signal("UG-TANK-01", "tank_level_pct", 48.0, ts=ts, min_interval_s=0)

    ok = verify_reading(db, "UG-TANK-01", "tank_level_pct", 49.5, ts, unit="%")
    assert ok.verdict == "matched"

    lie = verify_reading(db, "UG-TANK-01", "tank_level_pct", 62.0, ts, unit="%")
    assert lie.verdict == "mismatch" and "does not match" in lie.note

    blind = verify_reading(db, "OH-TANK-01", "tank_level_pct", 70.0, ts, unit="%")
    assert blind.verdict == "no_data", "no telemetry → honest abstain, never assumed"


def test_physical_prompts_and_reply_parse():
    db = _db()
    pend = pending_prompts(db)
    assert len(pend) >= 4 and all("Reply" in p["prompt"] for p in pend)

    parsed = parse_checklist_reply("ok pump_room_visual")
    assert parsed == {"item_id": "pump_room_visual", "status": "ok", "note": ""}
    parsed = parse_checklist_reply("issue gen_room_visual oil leak near base")
    assert parsed["status"] == "issue" and "oil leak" in parsed["note"]
    assert parse_checklist_reply("hello there") is None

    db.save_checklist_response("pump_room_visual", datetime.now().strftime("%Y-%m-%d"), "ok")
    assert "pump_room_visual" not in {p["item_id"] for p in pending_prompts(db)}


# ── API surface ───────────────────────────────────────────────────────────
def _client():
    import tempfile as _tf, os as _os
    _os.environ["ARVISX_DB"] = _os.path.join(_tf.mkdtemp(), "c.db")
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def test_api_gas_billing_and_checklist_endpoints():
    os.environ["ARVISX_BOT_MODE"] = "residential"          # residential-sensor mode (checklist-prompts are sim-bot)
    try:
        c = _client()
        # seed meter history straight into the live db (same file the app opened)
        state = c.app.state.community
        base = datetime(2026, 6, 1, 1, 0)
        state.db.log_signal("APT-101", "meter_total_m3", 10.0, ts=base, min_interval_s=0)
        state.db.log_signal("APT-101", "meter_total_m3", 18.0, ts=base + timedelta(days=20), min_interval_s=0)

        stmt = c.get("/api/v1/gas/billing?month=2026-06").json()
        assert stmt["billable_meters"] == 1
        csv = c.get("/api/v1/gas/billing?month=2026-06&format=csv")
        assert csv.status_code == 200 and "APT-101" in csv.text

        today = c.get("/api/v1/checklist/today").json()
        assert today["summary"]["auto_total"] >= 8

        # pencil-whip detection over the API
        ts = datetime.now().isoformat(timespec="seconds")
        state.db.log_signal("UG-TANK-01", "tank_level_pct", 40.0, min_interval_s=0)
        bad = c.post("/api/v1/checklist/submit-reading",
                     json={"asset_id": "UG-TANK-01", "signal": "tank_level_pct",
                           "value": 75.0, "unit": "%", "claimed_ts": ts, "by": "tech1"}).json()
        assert bad["verdict"] == "mismatch"

        prompts = c.get("/api/v1/whatsapp/checklist-prompts").json()["prompts"]
        assert prompts
        rep = c.post("/api/v1/whatsapp/checklist-reply",
                     json={"text": f"ok {prompts[0]['item_id']}", "by": "tech1"}).json()
        assert rep["recorded"] is True
        log = c.get("/api/v1/checklist/today").json()
        assert log["summary"]["physical_done"] >= 1
        assert log["summary"]["flagged_readings"] >= 1
    finally:
        os.environ.pop("ARVISX_BOT_MODE", None)


def test_api_whatsapp_gas_intent():
    os.environ["ARVISX_BOT_MODE"] = "residential"          # residential-sensor mode (gas answer is sim-bot)
    try:
        c = _client()
        r = c.post("/api/v1/whatsapp/ask", json={"question": "how is the cooking gas?"}).json()
        assert r["intent"] == "gas" and "Gas" in r["text"]
    finally:
        os.environ.pop("ARVISX_BOT_MODE", None)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print(f"  ✅ {f.__name__}")
    print(f"PASS — {len(fns)} gas + checklist tests")
