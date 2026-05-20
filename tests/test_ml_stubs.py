"""
WS-M7.1 — ML Stub Tests
========================

Assert NO ML handler returns a numeric confidence value in fallback mode.
All 6 handlers must return structured ML_UNAVAILABLE envelopes.
"""

import asyncio
import pytest


class _EmptyInstance:
    """Instance with no engines attached — forces all handlers to fallback path."""
    predictive_engine = None
    world_model = None
    knowledge_base = None


@pytest.fixture
def handler():
    from agent_commercial.tools.handlers.ml import MLHandlerMixin
    class _H(MLHandlerMixin):
        predictive_engine = None
        world_model = None
        knowledge_base = None
    return _H()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Individual handler stubs ──────────────────────────────────────────────────

def test_forecast_energy_fallback_no_numeric_confidence(handler):
    result = _run(handler._handle_forecast_energy({"forecast_hours": 24}))
    assert result.get("fallback") is True, "Must set fallback=True"
    assert result.get("ml_status") == "unavailable"
    conf = result.get("confidence")
    assert conf is None or not isinstance(conf, (int, float)) or conf is None, \
        f"Fallback must not have numeric confidence, got {conf}"


def test_detect_equipment_faults_fallback_no_numeric_confidence(handler):
    result = _run(handler._handle_detect_equipment_faults({"equipment_id": "CH-01"}))
    assert result.get("fallback") is True
    assert result.get("ml_status") == "unavailable"
    assert result.get("confidence") is None
    assert result.get("status") == "unknown", "Status must be 'unknown' not 'normal'"
    assert result.get("faults_detected") == []


def test_analyze_root_cause_fallback_no_probability(handler):
    result = _run(handler._handle_analyze_root_cause({"alarm_ids": ["ALM-001"]}))
    assert result.get("fallback") is True
    assert result.get("root_causes") == [], "Must not fabricate root causes"
    # Old stub had: root_causes: [{"cause":"Unknown","probability":0.5}]
    for rc in result.get("root_causes", []):
        assert "probability" not in rc, f"Root cause must not have probability: {rc}"


def test_simulate_with_uncertainty_fallback(handler):
    result = _run(handler._handle_simulate_with_uncertainty({
        "current_value": 22.0,
        "proposed_value": 24.0,
    }))
    assert result.get("fallback") is True
    assert result.get("confidence") is None


def test_find_similar_skills_fallback(handler):
    result = _run(handler._handle_find_similar_skills({"query": "chiller fault diagnosis"}))
    # May succeed via SemanticSkillMatcher — only check if fallback
    if result.get("fallback"):
        assert result.get("ml_status") == "unavailable"
        assert result.get("confidence") is None


def test_benchmark_building_ml_fallback(handler):
    result = _run(handler._handle_benchmark_building_ml({"building_id": "BLD-01"}))
    if result.get("fallback"):
        assert result.get("ml_status") == "unavailable"
        assert result.get("confidence") is None


# ── Cross-check: no handler emits numeric confidence in fallback ──────────────

ALL_FALLBACK_RESULTS = []


def test_all_fallbacks_structured(handler):
    """All fallback dicts must have fallback=True and confidence=None."""
    cases = [
        handler._handle_forecast_energy({}),
        handler._handle_detect_equipment_faults({"equipment_id": "CH-01"}),
        handler._handle_analyze_root_cause({"alarm_ids": ["A1"]}),
        handler._handle_simulate_with_uncertainty({"current_value": 1, "proposed_value": 2}),
        handler._handle_find_similar_skills({"query": "test"}),
        handler._handle_benchmark_building_ml({}),
    ]
    for coro in cases:
        result = _run(coro)
        if result.get("fallback"):
            conf = result.get("confidence")
            assert not isinstance(conf, (int, float)) or conf is None, \
                f"Handler {result} returned numeric confidence in fallback mode: {conf}"
