"""
ArvisX regression tests — Phase 0 (health/PM/sim) → Phase 1a (advisory) → 1b (API).

Runs under pytest, OR standalone:  python -m arvisx.tests.test_arvisx
LLM tests use a FakeLLM (no Bedrock/creds needed) so the suite is hermetic & offline.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

from arvisx.advisory import _evidence_ledger, _llm_differential, investigate_asset
from arvisx.health import assess_asset, build_report
from arvisx.models import AssetType, Severity
from arvisx.simulator import healthy_community, inject_prd_scenario


# ── Phase 0: health, PM, service roll-up, simulator ──────────────────────
def test_healthy_all_green():
    rep = build_report(healthy_community())
    assert len(rep.assets) == 12
    assert rep.risks == []
    assert all(s.band.value == "Healthy" for s in rep.services)


def test_prd_scenario_risks():
    rep = build_report(inject_prd_scenario())
    sev = [r.severity for r in rep.risks]
    assert len(rep.risks) == 4
    assert sev.count(Severity.WARNING) == 3      # booster, pool, fire-pump
    assert sev.count(Severity.MAINTENANCE) == 1  # generator service-due
    # Risks sorted critical→…: no critical in this scenario, warnings first.
    assert rep.risks[0].severity == Severity.WARNING


def test_service_bands_risk_driven():
    """A service with any open action flags Attention (the product promise);
    a service with no open risk stays Healthy."""
    rep = build_report(inject_prd_scenario())
    bands = {s.service.value: s.band.value for s in rep.services}
    assert bands["power_backup"] == "Attention Required"   # only a maintenance item, still flagged
    assert bands["water"] == "Attention Required"
    assert bands["pool"] == "Attention Required"
    assert bands["fire"] == "Attention Required"
    assert bands["stp"] == "Healthy"                        # no open risk


def test_simulator_deterministic_ids():
    ids = {a.asset_id for a in healthy_community()}
    assert {"BOOST-PUMP-01", "GEN-01", "STP-BLOWER-01", "POOL-FILT-01", "FIRE-PUMP-01"} <= ids


def test_missing_data_does_not_fabricate_health():
    """Offline asset can't be asserted healthy (no fabrication)."""
    assets = healthy_community()
    a = next(x for x in assets if x.asset_id == "GEN-01")
    a.online = False
    h, risks = assess_asset(a, datetime.now())
    assert h.score <= 35
    assert any("offline" in r.message.lower() for r in risks)


# ── Phase 1a: grounded advisory (rules floor) ────────────────────────────
def _advise(asset_id: str, scenario=None):
    assets = scenario or inject_prd_scenario()
    a = next(x for x in assets if x.asset_id == asset_id)
    _, risks = assess_asset(a, datetime.now())
    return asyncio.run(investigate_asset(a, risks, llm=None)), a, risks


def test_rules_floor_grounded():
    adv, _, _ = _advise("BOOST-PUMP-01")
    assert adv.source == "rules"
    assert adv.confirmed is False                 # never confirmed without inspection
    assert "wear" in adv.root_cause.lower()
    assert adv.recommended_action


def test_fire_pump_is_supplementary():
    adv, _, _ = _advise("FIRE-PUMP-01")
    # Honest: lapsed test = UNVERIFIED, not 'failed'; defer to certified vendor.
    assert "unverified" in adv.root_cause.lower()
    assert "vendor" in adv.recommended_action.lower() or "certified" in adv.recommended_action.lower()
    assert adv.confirmed is False


# ── Phase 1a: LLM differential + evidence-bind gate (FakeLLM, hermetic) ──
class _FakeLLM:
    def __init__(self, hyps):
        self._hyps = hyps

    async def ask_json(self, **kwargs):
        return {"hypotheses": self._hyps}


def test_evidence_bind_drops_hallucinated_citation():
    assets = inject_prd_scenario()
    a = next(x for x in assets if x.asset_id == "BOOST-PUMP-01")
    _, risks = assess_asset(a, datetime.now())
    ledger = _evidence_ledger(a, risks)
    fake = _FakeLLM([
        {"label": "Worn impeller", "probability": 0.7,
         "supporting_evidence_ids": list(ledger)[:1]},          # valid → kept
        {"label": "Fabricated cause", "probability": 0.9,
         "supporting_evidence_ids": ["sig:NONEXISTENT"]},        # invalid → dropped
    ])
    hyps = asyncio.run(_llm_differential(a, risks, ledger, fake))
    labels = [h.label for h in hyps]
    assert "Worn impeller" in labels
    assert "Fabricated cause" not in labels                      # anti-hallucination


def test_llm_merge_sets_source_and_leader():
    assets = inject_prd_scenario()
    a = next(x for x in assets if x.asset_id == "POOL-FILT-01")
    _, risks = assess_asset(a, datetime.now())
    ledger = _evidence_ledger(a, risks)
    fake = _FakeLLM([
        {"label": "Clogged filter cutting flow", "probability": 0.7,
         "supporting_evidence_ids": list(ledger)[:2],
         "discriminating_test": "Check filter ΔP", "recommended_action": "Backwash/clean filter"},
        {"label": "Timer fault", "probability": 0.3,
         "supporting_evidence_ids": list(ledger)[:1]},
    ])
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        adv = asyncio.run(investigate_asset(a, risks, llm=fake))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert adv.source == "llm+rules"
    assert adv.root_cause == "Clogged filter cutting flow"       # leading hypothesis wins
    assert adv.confirmed is False
    assert len(adv.hypotheses) == 2


# ── Phase 1b: dashboard API ──────────────────────────────────────────────
def _client():
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def test_api_overview_and_risks():
    c = _client()
    ov = c.get("/api/v1/community/overview").json()
    assert len(ov["services"]) == 5
    assert {s["service"] for s in ov["services"]} == {"water", "power_backup", "pool", "stp", "fire"}
    rk = c.get("/api/v1/community/risks").json()
    assert rk["count"] == 4


def test_api_assets_and_advisory():
    c = _client()
    assets = c.get("/api/v1/community/assets").json()
    assert assets["count"] == 12
    adv = c.get("/api/v1/asset/BOOST-PUMP-01/advisory").json()
    assert adv["confirmed"] is False
    assert adv["source"] == "rules"          # no ARVIS_X_LLM → rules floor
    bad = c.get("/api/v1/asset/NOPE/advisory")
    assert bad.status_code == 404


def test_api_scenario_toggle():
    c = _client()
    assert c.post("/api/v1/scenario/healthy").json()["scenario"] == "healthy"
    assert c.get("/api/v1/community/risks").json()["count"] == 0
    assert c.post("/api/v1/scenario/prd").json()["scenario"] == "prd"
    assert c.get("/api/v1/community/risks").json()["count"] == 4


# ── Phase 2: MQTT ingest (pure — no broker) ──────────────────────────────
def test_topic_parse_coercion():
    from arvisx.ingest.topics import parse
    assert parse("arvisx/GEN-01/fuel_level_pct", "18.5") == [("GEN-01", "fuel_level_pct", 18.5)]
    assert parse("arvisx/GEN-01/fault", "true") == [("GEN-01", "fault", True)]
    assert parse("arvisx/GEN-01/runtime_hours", "910") == [("GEN-01", "runtime_hours", 910)]
    # ISO datetime signal
    r = parse("arvisx/FIRE-PUMP-01/next_test_due", "2026-06-01T00:00:00")
    assert r[0][0] == "FIRE-PUMP-01" and isinstance(r[0][2], datetime)
    # out-of-prefix and malformed → []
    assert parse("other/X/y", "1") == []
    assert parse("arvisx", "") == []
    # JSON-object payload on the asset topic → multiple readings
    multi = parse("arvisx/GEN-01", '{"fuel_level_pct": 30, "fault": false}')
    assert ("GEN-01", "fuel_level_pct", 30) in multi and ("GEN-01", "fault", False) in multi


def test_store_apply_reading():
    from arvisx.store import AssetStore
    store = AssetStore.from_fleet_definition(healthy_community())
    assert store.apply_reading("BOOST-PUMP-01", "runtime_hours", 8600) is True
    assert store.apply_reading("BOOST-PUMP-01", "power_kw", 4.2) is True
    assert store.apply_reading("GHOST-99", "x", 1) is False        # unknown asset rejected
    a = store.asset("BOOST-PUMP-01")
    assert a.runtime_hours == 8600 and a.signals["power_kw"] == 4.2


def test_mqtt_loopback_drives_risks():
    """Full ingest path with NO broker: mock publisher messages → handle_message →
    store → build_report. PRD telemetry (booster runtime, pool runtime, fire test)
    must surface as risks on a healthy-seeded fleet."""
    from arvisx.store import AssetStore
    from arvisx.ingest.mqtt_adapter import handle_message
    from arvisx.ingest.mock_publisher import scenario_messages
    store = AssetStore.from_fleet_definition(healthy_community())
    assert build_report(store.snapshot()).risks == []              # healthy before ingest
    for topic, payload in scenario_messages("prd"):
        handle_message(store, topic, payload)
    assert store.update_count > 0
    rep = build_report(store.snapshot())
    msgs = " ".join(r.message.lower() for r in rep.risks)
    assert "runtime above threshold" in msgs        # booster runtime telemetry
    assert "below normal" in msgs                    # pool filtration telemetry
    assert "test overdue" in msgs                    # fire pump iso-date telemetry


# ── standalone runner ────────────────────────────────────────────────────
def _main() -> int:
    fns = [g for n, g in sorted(globals().items()) if n.startswith("test_") and callable(g)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e!r}")
    print(f"\n{passed}/{len(fns)} passed")
    return 0 if passed == len(fns) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
