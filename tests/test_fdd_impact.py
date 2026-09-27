"""Phase 4 — avoidable cost, priority scores, closed-loop fix verification, coverage."""
import asyncio
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from agent_commercial.fdd import FDDEngine, Outcome, RULES_BY_ID
from agent_commercial.fdd.coverage import coverage_summary
from agent_commercial.fdd.frame import EquipmentFrame
from agent_commercial.fdd.impact import SiteEconomics, priority_scores
from agent_commercial.semantics import PointRole as R

POLL = 300.0


def _ef(cols, kind="ahu", eq="FAHU-1", periods=300):   # 300 × 5 min ≈ 25 h (≥ 24 h span)
    idx = pd.date_range("2026-07-01", periods=periods, freq="300s")
    df = pd.DataFrame({k.value: (v if hasattr(v, "__len__") else np.full(periods, float(v)))
                       for k, v in cols.items()}, index=idx)
    return EquipmentFrame(eq, kind, df, points_used={c: f"{eq}/{c}" for c in df.columns})


def _fc14(econ=None, **extra):
    cols = {R.SUPPLY_FAN_STATUS: 1.0, R.COOLING_VALVE: 0.0,
            R.COOLING_COIL_ENTERING_TEMP: 44.0, R.COOLING_COIL_LEAVING_TEMP: 40.0, **extra}
    eng = FDDEngine([RULES_BY_ID["FC14"]], poll_seconds=POLL, economics=econ)
    return eng.evaluate(_ef(cols))[0]


def test_passing_valve_cost_from_measured_airflow():
    f = _fc14(SiteEconomics(tariff_per_kwh=0.15, plant_cop=4.0), **{R.SUPPLY_AIRFLOW: 5.0})
    assert f.outcome is Outcome.FAIL
    imp = f.impact
    q_kw = 1.2 * 5.0 * 1.006 * 4.0
    assert imp["status"] == "quantified"
    assert imp["cooling_kwh_thermal"] == pytest.approx(q_kw * imp["fault_hours"], rel=1e-3)
    assert imp["electric_kwh"] == pytest.approx(imp["cooling_kwh_thermal"] / 4.0, rel=1e-3)
    assert imp["cost"] == pytest.approx(imp["electric_kwh"] * 0.15, rel=1e-3)
    assert imp["projected_annual_cost"] > imp["cost"] * 300
    assert f.scores["energy"] is not None and f.scores["health"] is not None
    assert f.scores["priority"] == max(f.scores["energy"], f.scores["health"])


def test_no_airflow_means_no_number():
    f = _fc14(SiteEconomics(tariff_per_kwh=0.15, plant_cop=4.0))
    assert f.impact["status"] == "not_quantifiable"
    assert "airflow" in f.impact["reason"]
    assert "cost" not in f.impact and f.scores["energy"] is None


def test_missing_site_economics_reported_not_assumed():
    f = _fc14(SiteEconomics(), **{R.SUPPLY_AIRFLOW: 5.0})
    assert f.impact["cooling_kwh_thermal"] > 0
    assert "electric_kwh" not in f.impact and "plant_cop not configured" in f.impact["electric_kwh_note"]
    f = _fc14(SiteEconomics(plant_cop=4.0), **{R.SUPPLY_AIRFLOW: 5.0})
    assert f.impact["electric_kwh"] > 0 and f.impact["cost_note"] == "electricity tariff not configured"


def test_unscheduled_runtime_uses_equipments_own_kw():
    eng = FDDEngine([RULES_BY_ID["SCHED-247"]], poll_seconds=POLL,
                    economics=SiteEconomics(tariff_per_kwh=0.2))
    f = eng.evaluate(_ef({R.SUPPLY_FAN_STATUS: 1.0, R.ELECTRIC_POWER: 11.0}, eq="AHU-3"))[0]
    assert f.outcome is Outcome.FAIL
    assert f.impact["electric_kwh"] == pytest.approx(11.0 * f.impact["fault_hours"], rel=1e-3)


def test_scores_follow_the_rule_kind():
    s = priority_scores("VAV-1", 40.0, {"status": "not_applicable"})
    assert s["comfort"] == 4.0 and s["energy"] is None and s["health"] is None and s["priority"] == 4.0
    s = priority_scores("AHU-SIMUL", 10.0, {"projected_annual_cost": 10000.0, "currency": "QAR"})
    assert s["energy"] == 5.0
    assert priority_scores("CHW-4", 10.0, {})["priority"] is None


def test_coverage_names_the_points_that_unlock_rules():
    eng = FDDEngine(poll_seconds=POLL)
    findings = eng.evaluate(_ef({R.SUPPLY_FAN_STATUS: 1.0,
                                 R.SUPPLY_AIR_TEMP: 14 + np.random.default_rng(0).normal(0, .3, 300),
                                 R.SUPPLY_AIR_TEMP_SP: 14.0}, eq="AHU-1"))
    cov = coverage_summary(findings)
    assert 0 < cov["judged_pct"] < 100
    wanted = {p["role"] for p in cov["points_to_map_next"]}
    assert R.COOLING_VALVE.value in wanted or any(R.COOLING_VALVE.value in w for w in wanted)
    assert cov["outcomes"]["pass"] >= 1


# ── closed loop ───────────────────────────────────────────────────────────────

def _seed(db, eq, start, hours, sat_fn):
    rng = np.random.default_rng(1)
    pts = []
    for i in range(int(hours * 12)):
        ts = start + timedelta(minutes=5 * i)
        pts += [{"point_id": f"{eq}/SF_STS", "equipment_id": eq, "value": 1.0, "unit": "", "timestamp": ts},
                {"point_id": f"{eq}/SAT_SP", "equipment_id": eq, "value": 14.0, "unit": "°C", "timestamp": ts},
                {"point_id": f"{eq}/SAT", "equipment_id": eq, "unit": "°C", "timestamp": ts,
                 "value": sat_fn(ts) + float(rng.normal(0, 0.3))}]
    return db.save_data_points_batch(pts)


@pytest.mark.parametrize("after_sat,after_h,expect", [
    (14.0, 30, "verified"),       # repaired: SAT back on setpoint for 30 h
    (21.0, 30, "failed"),         # fault came back
    (14.0, 6, "pending"),         # not enough running time yet
])
def test_fix_verification(tmp_path, after_sat, after_h, expect):
    from agent_commercial.bms_state_engine import BMSStateEngine
    from agent_commercial.database import BMSDatabase
    from agent_commercial.fdd.closed_loop import list_verifications, recheck_pending, register_repair

    async def go():
        db = BMSDatabase(db_path=str(tmp_path / "loop.db"))
        now = datetime.now().replace(second=0, microsecond=0)
        repaired = now - timedelta(hours=after_h)
        await _seed(db, "AHU-7", repaired - timedelta(hours=12), 12, lambda ts: 21.0)   # faulty before
        await _seed(db, "AHU-7", repaired, after_h, lambda ts: after_sat)
        v = await register_repair(db, "AHU-7", "AHU-SATDEV", repaired_at=repaired,
                                  work_order_id="WO-1", hypothesis="CHW valve actuator replaced")
        decided = await recheck_pending(FDDEngine(poll_seconds=POLL), BMSStateEngine(), db)
        rows = await list_verifications(db)
        await db.close()
        return v, decided, rows

    v, decided, rows = asyncio.run(go())
    assert rows[0].status == expect, rows[0].reason
    assert (len(decided) == 1) == (expect != "pending")
    assert rows[0].hypothesis == "CHW valve actuator replaced"


def test_fix_on_unknown_rule_rejected(tmp_path):
    from agent_commercial.database import BMSDatabase
    from agent_commercial.fdd.closed_loop import register_repair

    async def go():
        db = BMSDatabase(db_path=str(tmp_path / "x.db"))
        try:
            await register_repair(db, "AHU-7", "NOT-A-RULE")
        finally:
            await db.close()

    with pytest.raises(ValueError):
        asyncio.run(go())


def test_repair_api_requires_auth_and_records_actor(tmp_path, monkeypatch):
    import os
    os.environ["ARVIS_AUTH_SECRET"] = "regression-secret"
    from fastapi.testclient import TestClient
    import agent_commercial.database as dbmod
    from agent_commercial.api.auth import create_access_token
    from agent_commercial.api.routes import create_api
    from agent_commercial.database import BMSDatabase

    db = BMSDatabase(db_path=str(tmp_path / "api.db"))
    monkeypatch.setattr(dbmod, "get_database", lambda *a, **k: db)
    client = TestClient(create_api())
    body = {"equipment_id": "AHU-7", "rule_id": "FC14", "work_order_id": "WO-9"}
    assert client.post("/api/v1/fdd/repairs", json=body).status_code == 401
    tok = create_access_token({"sub": "tech.ali", "role": "operator"}, expires_delta=timedelta(minutes=5))
    r = client.post("/api/v1/fdd/repairs", json=body, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert "tech.ali" in r.json()["note"]
    listed = client.get("/api/v1/fdd/verifications").json()
    assert listed[0]["work_order_id"] == "WO-9"
