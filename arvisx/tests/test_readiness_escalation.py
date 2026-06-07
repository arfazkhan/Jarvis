"""Tests for the data-driven ops-readiness gate + the deterministic→agent escalation policy."""
from __future__ import annotations

import asyncio
import os
import tempfile

from arvisx.commissioning import CommissioningManager, CommissioningState
from arvisx.escalation import handle_incident, should_escalate
from arvisx.learning import BaselineStore
from arvisx.models import Risk, ServiceType, Severity
from arvisx.persistence import ArvisxDb
from arvisx.readiness import assess_baseline_readiness
from arvisx.simulator import healthy_community


# ── baseline readiness ────────────────────────────────────────────────────
def test_baseline_not_ready_cold_then_ready_after_learning():
    assets = healthy_community()
    cold = assess_baseline_readiness(assets, BaselineStore())
    assert not cold.ready and cold.coverage == 0.0 and cold.suggested_extra_days > 0

    bl = BaselineStore()
    for _ in range(25):
        bl.learn_from_assets(assets)
    warm = assess_baseline_readiness(assets, bl)
    assert warm.ready and warm.coverage >= 0.8


def test_commissioning_gate_extends_then_approves():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "r.db"), building_id="B")
    mgr = CommissioningManager(db)
    b = mgr.create_building("T")
    mgr.set_services(b.building_id, [ServiceType.WATER.value])
    mgr.transition(b.building_id, "assets")
    mgr.add_asset(b.building_id, {"id": "BOOST-PUMP-01", "type": "booster_pump", "name": "BP"})
    mgr.transition(b.building_id, "signals")
    mgr.add_signal_map(b.building_id, "arvisx/BOOST-PUMP-01/power_kw", "BOOST-PUMP-01", "power_kw")
    mgr.transition(b.building_id, "dependencies")
    mgr.set_dependencies(b.building_id, ServiceType.WATER.value, [{"asset_id": "BOOST-PUMP-01", "role": "primary"}])
    mgr.transition(b.building_id, "learning")

    assets = healthy_community()
    days0 = mgr.get(b.building_id).learning_days

    # Cold baselines → rejected, learning window extended, stays in LEARNING.
    v1 = mgr.evaluate_ops_readiness(b.building_id, assets, BaselineStore())
    assert v1["approved"] is False
    assert mgr.get(b.building_id).learning_days > days0
    assert mgr.get(b.building_id).state == CommissioningState.LEARNING.value

    # Settled baselines → approved, auto-advanced to OPERATIONAL.
    bl = BaselineStore()
    for _ in range(25):
        bl.learn_from_assets(assets)
    v2 = mgr.evaluate_ops_readiness(b.building_id, assets, bl)
    assert v2["approved"] is True
    assert mgr.get(b.building_id).state == CommissioningState.OPERATIONAL.value


# ── escalation policy ─────────────────────────────────────────────────────
def _risk(asset_id, sev, conf, msg="issue", detail=""):
    return Risk(asset_id, asset_id, ServiceType.WATER, sev, msg, detail, confidence=conf)


def test_should_escalate_low_confidence_and_concurrent():
    a = next(x for x in healthy_community() if x.asset_id == "BOOST-PUMP-01")
    low = _risk("BOOST-PUMP-01", Severity.WARNING, "Low")
    esc, why = should_escalate(low, a, [low])
    assert esc and any("unsure" in r for r in why)

    r1 = _risk("BOOST-PUMP-01", Severity.WARNING, "High", "msg a")
    r2 = _risk("BOOST-PUMP-01", Severity.WARNING, "High", "msg b")
    esc2, why2 = should_escalate(r1, a, [r1, r2])
    assert esc2 and any("concurrent" in r for r in why2)


def test_high_confidence_single_risk_does_not_escalate():
    a = next(x for x in healthy_community() if x.asset_id == "GEN-01")
    solo = _risk("GEN-01", Severity.MAINTENANCE, "High", "service due in 30 days")
    esc, why = should_escalate(solo, a, [solo])
    assert not esc and not why


def test_handle_incident_deterministic_without_llm():
    a = next(x for x in healthy_community() if x.asset_id == "FIRE-PUMP-01")
    rk = _risk("FIRE-PUMP-01", Severity.WARNING, "Low", "test overdue", "fire test lapsed")
    out = asyncio.run(handle_incident(a, rk, healthy_community(), [rk], llm=None))
    assert out["route"] == "deterministic" and out["escalated"] is False
    assert out["deterministic"]["root_cause"]              # rules advisory always present
    assert out["escalation_reasons"]                       # policy WOULD escalate, but no LLM


if __name__ == "__main__":
    test_baseline_not_ready_cold_then_ready_after_learning()
    test_commissioning_gate_extends_then_approves()
    test_should_escalate_low_confidence_and_concurrent()
    test_high_confidence_single_risk_does_not_escalate()
    test_handle_incident_deterministic_without_llm()
    print("PASS — readiness gate + escalation policy verified")
