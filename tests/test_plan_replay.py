"""
Plan Replay Tests
=================

Save an InvestigationPlan → load it → verify all fields round-trip correctly.
No LLM calls.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


def build_rich_plan():
    """Build a plan with tasks, evidence, spans, budget usage, and tool cache."""
    from arvis_core.plan import InvestigationPlan, Budget, TaskStatus, PlanStatus
    from arvis_core.evidence import Evidence

    plan = InvestigationPlan(
        query="Why is AHU-01 consuming more energy than expected?",
        budget=Budget(max_tool_calls=12, max_cost_usd=0.30),
    )

    # Add tasks
    t1 = plan.add_task("Get equipment status", tool_hint="get_equipment_status", expected_outcome="status dict")
    t2 = plan.add_task("Analyze energy anomalies", tool_hint="get_energy_anomalies", expected_outcome="anomaly list")

    # Simulate execution
    t1.mark_active()
    ev1 = Evidence.from_tool_result(
        "get_equipment_status",
        {"equipment_id": "AHU-01", "status": "running", "cop": 3.8},
        node_name="Energy_Agent",
        task_id=t1.id,
    )
    plan.evidence.add(ev1)
    t1.mark_complete(ev1.id)

    t2.mark_active()
    ev2 = Evidence.from_tool_result(
        "get_energy_anomalies",
        {"anomalies": [{"zone": "office_3", "delta_kwh": 45.2}], "_ml_lineage": {"model_id": "anomaly_v2", "drift_score": 0.12}},
        node_name="Energy_Agent",
        task_id=t2.id,
    )
    plan.evidence.add(ev2)
    t2.mark_complete(ev2.id)

    # Budget usage
    plan.budget.record_tool_call(tokens_used=500, cost_usd=0.002)
    plan.budget.record_tool_call(tokens_used=800, cost_usd=0.004)

    # Register call sigs
    sig1 = "get_equipment_status:{equipment_id:AHU-01}"
    sig2 = "get_energy_anomalies:{}"
    plan.register_call(sig1)
    plan.register_call(sig2)
    plan.cache_tool_result(sig1, {"equipment_id": "AHU-01", "cop": 3.8})
    plan.cache_tool_result(sig2, {"anomalies": []})

    # Record spans
    plan.record_span(
        task_id=t1.id,
        node_name="Energy_Agent",
        action="tool_call:get_equipment_status",
        tool_name="get_equipment_status",
        tool_args={"equipment_id": "AHU-01"},
        evidence_id=ev1.id,
        duration_ms=142.3,
    )
    plan.record_span(
        task_id=t2.id,
        node_name="Energy_Agent",
        action="tool_call:get_energy_anomalies",
        tool_name="get_energy_anomalies",
        tool_args={},
        evidence_id=ev2.id,
        duration_ms=89.1,
    )

    return plan, ev1, ev2


def test_plan_save_and_load_roundtrip():
    """Full save→load preserves plan identity and structure."""
    from arvis_core.plan import TaskStatus, PlanStatus

    plan, ev1, ev2 = build_rich_plan()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        plan.save(tmp_path)
        assert tmp_path.exists(), "save() must create the file"

        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert loaded.id == plan.id
    assert loaded.query == plan.query
    assert loaded.status == plan.status


def test_plan_tasks_roundtrip():
    from arvis_core.plan import TaskStatus
    plan, ev1, ev2 = build_rich_plan()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        plan.save(tmp_path)
        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert len(loaded.tasks) == 2
    assert loaded.tasks[0].status == TaskStatus.COMPLETE
    assert loaded.tasks[1].status == TaskStatus.COMPLETE
    assert loaded.tasks[0].goal == "Get equipment status"
    assert ev1.id in loaded.tasks[0].evidence_ids


def test_plan_evidence_roundtrip():
    plan, ev1, ev2 = build_rich_plan()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        plan.save(tmp_path)
        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert len(loaded.evidence) == 2
    loaded_ev1 = loaded.evidence.get(ev1.id)
    assert loaded_ev1 is not None
    assert loaded_ev1.source_tool == "get_equipment_status"
    assert loaded_ev1.node_name == "Energy_Agent"

    loaded_ev2 = loaded.evidence.get(ev2.id)
    assert loaded_ev2 is not None
    assert loaded_ev2.model_id == "anomaly_v2"
    assert loaded_ev2.drift_score == pytest.approx(0.12)


def test_plan_budget_roundtrip():
    plan, _, _ = build_rich_plan()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        plan.save(tmp_path)
        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert loaded.budget.max_tool_calls == 12
    assert loaded.budget.max_cost_usd == pytest.approx(0.30)
    assert loaded.budget.used_tool_calls == 2
    assert loaded.budget.used_cost_usd == pytest.approx(0.006)


def test_plan_audit_trail_roundtrip():
    plan, ev1, ev2 = build_rich_plan()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        plan.save(tmp_path)
        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert len(loaded.audit_trail) == 2
    span = loaded.audit_trail[0]
    assert span.tool_name == "get_equipment_status"
    assert span.evidence_id == ev1.id
    assert span.duration_ms == pytest.approx(142.3)


def test_plan_call_sigs_and_cache_roundtrip():
    plan, _, _ = build_rich_plan()
    sig1 = "get_equipment_status:{equipment_id:AHU-01}"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        plan.save(tmp_path)
        loaded = type(plan).load(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert loaded.is_duplicate_call(sig1)
    cached = loaded.get_cached_tool_result(sig1)
    assert cached == {"equipment_id": "AHU-01", "cop": 3.8}


def test_plan_persist_dict_schema_version():
    """to_persist_dict includes _schema_version=1."""
    plan, _, _ = build_rich_plan()
    d = plan.to_persist_dict()
    assert d.get("_schema_version") == 1


def test_plan_to_json_still_works():
    """to_json() (display) still works after adding persistence methods."""
    plan, _, _ = build_rich_plan()
    raw = plan.to_json()
    parsed = json.loads(raw)
    assert "id" in parsed
    assert "tasks" in parsed
    assert "evidence_count" in parsed
    assert parsed["evidence_count"] == 2


def test_evidence_from_dict_roundtrip():
    """Evidence.to_dict() → from_dict() preserves all fields."""
    from arvis_core.evidence import Evidence, FreshnessStatus

    ev = Evidence(
        source_tool="forecast_energy",
        raw_payload={"kwh": 1234},
        node_name="ML_Node",
        is_ml_fallback=False,
        model_id="energy_forecaster_v2",
        model_version="2.1.0",
        drift_score=0.15,
        algorithm="prophet+lgbm",
        training_window="30d",
        confidence_bounds={"lower": 1100.0, "upper": 1350.0},
        freshness=FreshnessStatus.LIVE,
        summary="Energy forecast result",
    )

    d = ev.to_dict()
    ev2 = Evidence.from_dict(d)

    assert ev2.id == ev.id
    assert ev2.source_tool == ev.source_tool
    assert ev2.model_id == ev.model_id
    assert ev2.model_version == ev.model_version
    assert ev2.drift_score == pytest.approx(0.15)
    assert ev2.algorithm == ev.algorithm
    assert ev2.training_window == ev.training_window
    assert ev2.confidence_bounds == ev.confidence_bounds
    assert ev2.freshness == FreshnessStatus.LIVE
    assert ev2.is_ml_fallback is False
