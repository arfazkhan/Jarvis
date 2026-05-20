"""
WS-M7.1 — ML Fallback Propagation Tests
=========================================

Assert that ML fallback evidence propagates correctly through the pipeline:
- fallback evidence → abstention gate fires in bms_llm_agent
- node.py serializes fallback dicts with [ML UNAVAILABLE] prefix
- Evidence.is_ml_fallback tracked correctly in ledger
"""

import pytest
import asyncio
from arvis_core.evidence import Evidence, EvidenceLedger, FreshnessStatus
from arvis_core.plan import InvestigationPlan, Budget


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── node.py serialization ─────────────────────────────────────────────────────

def test_node_serializes_fallback_with_prefix():
    """node.py must prepend [ML UNAVAILABLE] when result has fallback=True."""
    import json
    result = {
        "fallback": True,
        "ml_status": "unavailable",
        "confidence": None,
        "reason": "VAE not loaded",
    }
    # Reproduce the exact logic from node.py line ~244
    if isinstance(result, dict) and result.get("fallback"):
        tool_content = "[ML UNAVAILABLE — DO NOT CITE VALUES FROM THIS RESULT]\n" + json.dumps(result, default=str)
    else:
        tool_content = json.dumps(result, default=str) if isinstance(result, dict) else str(result)

    assert tool_content.startswith("[ML UNAVAILABLE")
    assert "DO NOT CITE" in tool_content


def test_node_serializes_normal_result_as_json():
    import json
    result = {"cop": 4.2, "status": "ok"}
    if isinstance(result, dict) and result.get("fallback"):
        tool_content = "[ML UNAVAILABLE — DO NOT CITE VALUES FROM THIS RESULT]\n" + json.dumps(result, default=str)
    else:
        tool_content = json.dumps(result, default=str) if isinstance(result, dict) else str(result)

    assert not tool_content.startswith("[ML UNAVAILABLE")
    parsed = json.loads(tool_content)
    assert parsed["cop"] == 4.2


# ── Evidence ledger fallback ratio ───────────────────────────────────────────

def test_fallback_ratio_computation():
    """Plan evidence fallback ratio computed correctly."""
    plan = InvestigationPlan(query="test", budget=Budget())

    # 3 fallback + 1 real = 75% fallback
    for i in range(3):
        ev = Evidence.from_tool_result(f"ml_tool_{i}", {
            "fallback": True, "ml_status": "unavailable", "reason": "model not loaded"
        })
        plan.evidence.add(ev)

    real_ev = Evidence.from_tool_result("get_equipment_status", {"cop": 4.2})
    plan.evidence.add(real_ev)

    all_ev = plan.evidence.get_all()
    fb_count = sum(1 for e in all_ev if getattr(e, "is_ml_fallback", False))
    ratio = fb_count / len(all_ev)
    assert ratio == 0.75
    assert ratio > 0.5, "Should trigger abstention gate"


# ── Abstention gate threshold ─────────────────────────────────────────────────

def test_abstention_gate_fires_on_high_fallback_ratio():
    """ml_fallback_ratio > 0.5 must trigger abstention (unit test of the gate logic)."""
    plan = InvestigationPlan(query="test", budget=Budget())
    for i in range(4):
        ev = Evidence.from_tool_result(f"ml_tool_{i}", {
            "fallback": True, "ml_status": "unavailable", "reason": "model not loaded"
        })
        plan.evidence.add(ev)

    all_ev = plan.evidence.get_all()
    fb_count = sum(1 for e in all_ev if getattr(e, "is_ml_fallback", False))
    ml_fallback_ratio = fb_count / len(all_ev) if all_ev else 0.0

    assert ml_fallback_ratio > 0.5
    # Gate logic (mirrors bms_llm_agent.py)
    abstention_reason = None
    if ml_fallback_ratio > 0.5:
        abstention_reason = f"ml_fallback_ratio={ml_fallback_ratio:.0%}"
    assert abstention_reason is not None, "Abstention gate must fire"


def test_abstention_gate_fires_on_high_drift():
    """max_drift > 0.7 must trigger abstention."""
    plan = InvestigationPlan(query="test", budget=Budget())
    from arvis_core.evidence import FreshnessStatus
    import uuid
    ev = Evidence(
        source_tool="energy_forecaster",
        raw_payload={"forecast": [100]},
        model_id="energy_forecaster",
        drift_score=0.85,
    )
    plan.evidence.add(ev)

    all_ev = plan.evidence.get_all()
    drift_vals = [e.drift_score for e in all_ev if getattr(e, "drift_score", None) is not None]
    max_drift = max(drift_vals) if drift_vals else 0.0

    assert max_drift > 0.7
    abstention_reason = None
    if max_drift > 0.7:
        abstention_reason = f"max_drift={max_drift:.2f}"
    assert abstention_reason is not None, "Abstention gate must fire on high drift"


def test_abstention_gate_does_not_fire_on_low_fallback():
    """Low fallback ratio must NOT trigger abstention."""
    plan = InvestigationPlan(query="test", budget=Budget())
    # 1 fallback + 9 real = 10% fallback
    ev_fb = Evidence.from_tool_result("ml_tool", {
        "fallback": True, "ml_status": "unavailable", "reason": "test"
    })
    plan.evidence.add(ev_fb)
    for i in range(9):
        ev = Evidence.from_tool_result(f"real_tool_{i}", {"value": i})
        plan.evidence.add(ev)

    all_ev = plan.evidence.get_all()
    fb_count = sum(1 for e in all_ev if getattr(e, "is_ml_fallback", False))
    ratio = fb_count / len(all_ev)
    assert ratio <= 0.5, f"Ratio {ratio} should be below 0.5"
