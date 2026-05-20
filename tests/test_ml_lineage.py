"""
WS-M7.1 — ML Lineage Tests
===========================

Assert Evidence dataclass has correct ML lineage fields.
Assert from_tool_result() populates them correctly from _ml_lineage.
Assert fallback evidence gets is_ml_fallback=True and freshness=UNKNOWN.
"""

import pytest
from arvis_core.evidence import Evidence, EvidenceLedger, FreshnessStatus


# ── Evidence ML lineage fields ────────────────────────────────────────────────

def test_evidence_has_ml_lineage_fields():
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(Evidence)}
    required = {"is_ml_fallback", "model_id", "model_version", "algorithm",
                "confidence_bounds", "drift_score", "training_window"}
    missing = required - field_names
    assert not missing, f"Evidence missing fields: {missing}"


def test_evidence_ml_defaults():
    ev = Evidence(source_tool="test", raw_payload={})
    assert ev.is_ml_fallback is False
    assert ev.model_id is None
    assert ev.model_version is None
    assert ev.confidence_bounds is None
    assert ev.drift_score is None
    assert ev.training_window is None


# ── from_tool_result: fallback detection ─────────────────────────────────────

def test_from_tool_result_detects_fallback_flag():
    result = {
        "fallback": True,
        "ml_status": "unavailable",
        "confidence": None,
        "reason": "VAE not loaded",
    }
    ev = Evidence.from_tool_result("detect_equipment_faults", result)
    assert ev.is_ml_fallback is True
    assert ev.freshness == FreshnessStatus.UNKNOWN
    assert "ML FALLBACK" in ev.summary
    assert "VAE not loaded" in ev.summary


def test_from_tool_result_detects_ml_status_unavailable():
    result = {"ml_status": "unavailable", "reason": "pgmpy missing"}
    ev = Evidence.from_tool_result("analyze_root_cause", result)
    assert ev.is_ml_fallback is True


def test_from_tool_result_extracts_lineage_on_success():
    result = {
        "forecast": [100.0, 110.0],
        "_ml_lineage": {
            "model_id": "energy_forecaster",
            "model_version": "v20260510",
            "algorithm": "prophet+lightgbm",
            "confidence_bounds": {"lower": 90.0, "upper": 120.0},
            "drift_score": 0.04,
            "training_window": "2026-04-01T00:00:00",
        },
    }
    ev = Evidence.from_tool_result("forecast_energy", result)
    assert ev.is_ml_fallback is False
    assert ev.model_id == "energy_forecaster"
    assert ev.model_version == "v20260510"
    assert ev.algorithm == "prophet+lightgbm"
    assert ev.confidence_bounds == {"lower": 90.0, "upper": 120.0}
    assert ev.drift_score == 0.04
    assert ev.freshness == FreshnessStatus.LIVE


def test_from_tool_result_normal_has_live_freshness():
    ev = Evidence.from_tool_result("get_equipment_status", {"cop": 4.2, "status": "ok"})
    assert ev.freshness == FreshnessStatus.LIVE
    assert ev.is_ml_fallback is False


# ── to_synthesis_context ML tags ─────────────────────────────────────────────

def test_synthesis_context_shows_ml_fallback_tag():
    ledger = EvidenceLedger()
    ev = Evidence.from_tool_result("detect_equipment_faults", {
        "fallback": True, "ml_status": "unavailable", "reason": "VAE not loaded"
    })
    ledger.add(ev)
    ctx = ledger.to_synthesis_context()
    assert "[ML_FALLBACK]" in ctx


def test_synthesis_context_shows_ml_model_tag():
    ledger = EvidenceLedger()
    ev = Evidence.from_tool_result("forecast_energy", {
        "forecast": [100.0],
        "_ml_lineage": {
            "model_id": "energy_forecaster",
            "model_version": "v1",
            "drift_score": 0.05,
        }
    })
    ledger.add(ev)
    ctx = ledger.to_synthesis_context()
    assert "[ML: energy_forecaster" in ctx


def test_synthesis_context_strips_ml_lineage_from_data():
    ledger = EvidenceLedger()
    ev = Evidence.from_tool_result("forecast_energy", {
        "forecast": [100.0],
        "_ml_lineage": {"model_id": "energy_forecaster", "algorithm": "lgbm"},
    })
    ledger.add(ev)
    ctx = ledger.to_synthesis_context()
    assert "_ml_lineage" not in ctx
