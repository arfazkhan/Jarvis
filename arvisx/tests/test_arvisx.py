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
    import tempfile, os as _os
    _os.environ["ARVISX_DB"] = _os.path.join(tempfile.mkdtemp(), "c.db")   # isolated per client
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def test_api_overview_and_risks():
    c = _client()
    ov = c.get("/api/v1/community/overview").json()
    assert len(ov["services"]) == 6                          # + energy (Phase 5b)
    assert {s["service"] for s in ov["services"]} == {"water", "power_backup", "pool", "stp", "fire", "energy"}
    rk = c.get("/api/v1/community/risks").json()
    assert rk["count"] == 6                                  # 4 asset + 2 ghost


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
    assert c.get("/api/v1/community/risks").json()["count"] == 0      # assets + zones all healthy
    assert c.post("/api/v1/scenario/prd").json()["scenario"] == "prd"
    assert c.get("/api/v1/community/risks").json()["count"] == 6      # 4 asset + 2 ghost


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


# ── Phase 3: work orders ─────────────────────────────────────────────────
def test_workorders_open_from_risks():
    from arvisx.workorders import WorkOrderStore, sync_workorders
    store = WorkOrderStore()
    c = sync_workorders(inject_prd_scenario(), store)
    assert c["opened"] == 4                       # one per PRD risk
    wos = store.all()
    # priority derived from severity; advisory cause attached.
    booster = next(w for w in wos if w.asset_id == "BOOST-PUMP-01")
    assert booster.priority.value == "P2"         # warning
    assert "wear" in booster.cause.lower()
    assert booster.recommended_action
    gen = next(w for w in wos if w.asset_id == "GEN-01")
    assert gen.priority.value == "P3"             # maintenance


def test_workorders_dedup_and_autoclose():
    from arvisx.workorders import WorkOrderStore, sync_workorders
    store = WorkOrderStore()
    sync_workorders(inject_prd_scenario(), store)
    c2 = sync_workorders(inject_prd_scenario(), store)     # same risks again
    assert c2["opened"] == 0 and c2["refreshed"] == 4      # dedup — no new tickets
    assert len(store.all()) == 4
    # risks clear → tickets auto-close
    c3 = sync_workorders(healthy_community(), store)
    assert c3["auto_closed"] == 4
    assert all(w.status.value == "done" for w in store.all())


def test_workorders_reopen_on_recurrence():
    from arvisx.workorders import WorkOrderStore, sync_workorders
    store = WorkOrderStore()
    sync_workorders(inject_prd_scenario(), store)
    sync_workorders(healthy_community(), store)            # auto-closed
    c = sync_workorders(inject_prd_scenario(), store)      # same problems return
    assert c["reopened"] == 4 and c["opened"] == 0         # same WOs reopened, not duplicated
    assert len(store.all()) == 4


def test_api_workorders():
    c = _client()
    lst = c.get("/api/v1/workorders").json()
    assert lst["count"] == 6                       # 4 asset + 2 ghost (energy)
    assert any(w["service"] == "energy" for w in lst["work_orders"])   # ghost → ticket
    wid = lst["work_orders"][0]["wo_id"]
    # status transition
    upd = c.post(f"/api/v1/workorders/{wid}/status/in_progress").json()
    assert upd["status"] == "in_progress"
    assert c.post(f"/api/v1/workorders/{wid}/status/bogus").status_code == 400
    assert c.get("/api/v1/workorders/NOPE").status_code == 404


# ── Phase 4: pattern learning + drift ────────────────────────────────────
def _feed(store, asset_id, signal, values):
    for v in values:
        store.observe(asset_id, signal, v)


def test_drift_cold_start_abstains():
    from arvisx.learning import BaselineStore
    b = BaselineStore()
    _feed(b, "P1", "power_kw", [5.0] * 5)          # < MIN_SAMPLES
    assert b.drift_z("P1", "power_kw") is None       # not enough history → abstain


def test_drift_stable_no_fire():
    from arvisx.learning import BaselineStore, DRIFT_Z
    b = BaselineStore()
    _feed(b, "P1", "power_kw", [5.0 + (i % 3 - 1) * 0.1 for i in range(40)])  # ~5 ± noise
    z = b.drift_z("P1", "power_kw")
    assert z is not None and abs(z) < DRIFT_Z


def test_drift_sustained_fires():
    from arvisx.learning import BaselineStore, DRIFT_Z
    b = BaselineStore()
    _feed(b, "P1", "power_kw", [5.0 + (i % 3 - 1) * 0.1 for i in range(35)])  # learned normal ~5
    _feed(b, "P1", "power_kw", [7.5] * 5)                                     # sustained rise
    z = b.drift_z("P1", "power_kw")
    assert z is not None and z >= DRIFT_Z            # drifting ABOVE its own normal


def test_drift_single_spike_does_not_fire():
    from arvisx.learning import BaselineStore, DRIFT_Z
    b = BaselineStore()
    _feed(b, "P1", "power_kw", [5.0 + (i % 3 - 1) * 0.1 for i in range(34)])
    _feed(b, "P1", "power_kw", [20.0])               # one spike, latest
    z = b.drift_z("P1", "power_kw")                  # recent-window median resists a spike
    assert z is None or abs(z) < DRIFT_Z


def test_drift_skips_cumulative_runtime():
    from arvisx.learning import BaselineStore
    b = BaselineStore()
    _feed(b, "P1", "runtime_hours", list(range(40)))   # monotonic — excluded
    assert b.drift_z("P1", "runtime_hours") is None


def test_drift_flows_into_report():
    from arvisx.learning import BaselineStore
    from arvisx.models import Asset, AssetType
    b = BaselineStore()
    a = Asset("XFER-PUMP-01", "Transfer Pump 1", AssetType.TRANSFER_PUMP,
              signals={"power_kw": 9.0}, next_maintenance_due=None)
    # learn a normal ~5kW, then the asset now reads ~9kW sustained
    _feed(b, "XFER-PUMP-01", "power_kw", [5.0 + (i % 3 - 1) * 0.1 for i in range(35)])
    _feed(b, "XFER-PUMP-01", "power_kw", [9.0] * 5)
    rep = build_report([a], baselines=b)
    assert any("drifting from its learned normal" in r.message for r in rep.risks)


# ── Phase 5a: PM virtual sensors ─────────────────────────────────────────
def _mk(asset_type, **signals):
    from arvisx.models import Asset
    return Asset("VS-01", "VS Pump", asset_type, signals=signals)


def test_vsensor_short_cycling_and_duty():
    from arvisx.virtual_sensors import derive_all
    from arvisx.models import AssetType
    a = _mk(AssetType.BOOSTER_PUMP, starts_today=144, runtime_today_hours=23.0, power_kw=3.0)
    readings, risks = derive_all(a)
    assert a.signals["v_cycling_per_hour"] == 6.0           # 144/24
    assert a.signals["v_duty_cycle"] == 0.96
    msgs = " ".join(r.message.lower() for r in risks)
    assert "short-cycling" in msgs and "near-continuously" in msgs


def test_vsensor_powercreep_abstains_without_history():
    from arvisx.virtual_sensors import derive_all
    from arvisx.models import AssetType
    a = _mk(AssetType.BOOSTER_PUMP, power_kw=3.0)
    readings, risks = derive_all(a, baselines=None)         # no learned normal
    assert "v_power_creep_sigma" not in a.signals           # abstains, no fabrication
    assert all("power creep" not in r.message.lower() for r in risks)


def test_vsensor_dry_run_detected():
    from arvisx.virtual_sensors import derive_all
    from arvisx.learning import BaselineStore
    from arvisx.models import AssetType
    b = BaselineStore()
    for _ in range(30):
        b.observe("VS-01", "power_kw", 3.0)                 # learned normal ~3kW
    a = _mk(AssetType.BOOSTER_PUMP, power_kw=1.0)           # now pulling ~1/3 → dry-run
    _, risks = derive_all(a, baselines=b)
    assert any("dry-run" in r.message.lower() for r in risks)


def test_degradation_demo_catches_wear_from_power_alone():
    from arvisx.degradation import run_demo
    asset, baselines, series = run_demo()
    rep = build_report([asset], baselines=baselines, virtual=True)
    creep = [r for r in rep.risks if "power creep" in r.message.lower()]
    assert len(creep) == 1                                  # caught
    # and NOT duplicated by generic drift on power_kw
    assert not any("power_kw drifting" in r.message for r in rep.risks)


def test_vsensor_abstains_with_no_relevant_signals():
    from arvisx.virtual_sensors import derive_all
    from arvisx.models import AssetType
    a = _mk(AssetType.FIRE_PANEL, active_faults=0)          # no power/runtime/starts
    readings, risks = derive_all(a)
    assert readings == [] and risks == []


# ── Phase 5b: ghost-floor / occupancy virtual sensors ────────────────────
def test_occupancy_levels():
    from arvisx.occupancy import estimate_occupancy
    from arvisx.models import OccupancyLevel
    lvl, c = estimate_occupancy(co2_ppm=900, motion_events_15m=6)
    assert lvl == OccupancyLevel.OCCUPIED and c > 0.5
    lvl, c = estimate_occupancy(co2_ppm=430, motion_events_15m=0)
    assert lvl == OccupancyLevel.EMPTY and c > 0.5
    # neither sensor → abstain
    lvl, c = estimate_occupancy(co2_ppm=None, motion_events_15m=None)
    assert lvl == OccupancyLevel.UNKNOWN and c == 0.0


def test_ghost_fires_only_when_empty_and_conditioned():
    from arvisx.occupancy import detect_ghost
    from arvisx.models import Zone, ZoneKind
    empty_on = Zone("Z1", "Clubhouse", ZoneKind.AMENITY,
                    {"co2_ppm": 430, "motion_events_15m": 0, "ac_on": True}, conditioned_load_kw=8.0)
    g = detect_ghost(empty_on)
    assert g is not None and g.waste_kw == 8.0 and g.waste_qar_per_day > 0
    # occupied → no ghost
    occ = Zone("Z2", "Gym", ZoneKind.AMENITY,
               {"co2_ppm": 900, "motion_events_15m": 6, "ac_on": True}, conditioned_load_kw=6.0)
    assert detect_ghost(occ) is None
    # empty but conditioning OFF → no waste, no ghost
    empty_off = Zone("Z3", "Hall", ZoneKind.AMENITY,
                     {"co2_ppm": 430, "motion_events_15m": 0, "ac_on": False}, conditioned_load_kw=5.0)
    assert detect_ghost(empty_off) is None


def test_energy_tile_and_ghost_risks_in_report():
    from arvisx.simulator import community_zones
    rep = build_report(inject_prd_scenario(), zones=community_zones("prd"))
    energy = [s for s in rep.services if s.service.value == "energy"]
    assert len(energy) == 1 and energy[0].band.value != "Healthy"
    ghosts = [r for r in rep.risks if r.service.value == "energy"]
    assert len(ghosts) == 2                                  # clubhouse + parking
    # healthy zones → no ghost, energy tile healthy
    rep2 = build_report(inject_prd_scenario(), zones=community_zones("healthy"))
    assert [r for r in rep2.risks if r.service.value == "energy"] == []
    assert [s for s in rep2.services if s.service.value == "energy"][0].band.value == "Healthy"


# ── Phase 6: environmental sensing + sensor fusion ───────────────────────
def _ac(**signals):
    from arvisx.models import Asset, AssetType
    return Asset("AC-1", "Conf Room AC", AssetType.AC_UNIT, signals=signals)


def test_fusion_cooling_fault_confidence_scales():
    from arvisx.fusion import assess_fusion
    # 2 modalities (electrical + thermal) → Medium
    _, f2 = assess_fusion([_ac(current_a=7.0, room_temp_c=29.0, room_setpoint_c=23.0)])
    assert len(f2) == 1 and f2[0].confidence_band == "Medium"
    assert set(f2[0].modalities) == {"electrical", "thermal"}
    # + presence + runtime → High
    _, f4 = assess_fusion([_ac(current_a=7.0, room_temp_c=29.0, room_setpoint_c=23.0,
                               motion_events_15m=4, runtime_today_hours=2.0)])
    assert f4[0].confidence_band == "High" and len(f4[0].modalities) >= 3
    assert "cooling effectiveness" in f4[0].conclusion.lower()


def test_fusion_no_fire_when_cooling_ok():
    from arvisx.fusion import assess_fusion
    _, f = assess_fusion([_ac(current_a=7.0, room_temp_c=23.5, room_setpoint_c=23.0)])
    assert f == []                                  # reaching setpoint → not a fault


def test_fusion_single_weak_signal_is_low():
    from arvisx.fusion import assess_fusion
    from arvisx.models import Asset, AssetType
    tank = Asset("T1", "Tank", AssetType.UNDERGROUND_TANK, signals={"humidity_pct": 92.0})
    _, f = assess_fusion([tank])
    assert len(f) == 1 and f[0].confidence_band == "Low"     # one modality → low, 'confirm'


def test_fusion_pump_stress_thermal():
    from arvisx.fusion import assess_fusion
    from arvisx.models import Asset, AssetType
    pump = Asset("P1", "STP Pump", AssetType.STP_PUMP, signals={"current_a": 12.0, "room_temp_c": 50.0})
    _, f = assess_fusion([pump])
    stress = [x for x in f if "stress" in x.conclusion.lower()]
    assert stress and stress[0].confidence_band == "Medium"
    assert "thermal" in stress[0].modalities and "electrical" in stress[0].modalities


def test_fusion_flows_into_report():
    a = _ac(current_a=7.0, room_temp_c=30.0, room_setpoint_c=23.0, motion_events_15m=5)
    rep = build_report([a], fusion=True)
    assert any("cooling effectiveness" in r.message.lower() for r in rep.risks)
    assert any("High confidence" in r.detail for r in rep.risks)


# ── Reasoning layer: cross-asset correlation + NL Q&A ────────────────────
class _FakeJsonLLM:
    def __init__(self, payload): self._p = payload
    async def ask_json(self, **kwargs): return self._p


def _flagged():
    """Two assets, two active risks, for correlation."""
    rep = build_report(inject_prd_scenario())
    return inject_prd_scenario(), rep.risks


def test_correlate_independent_when_few_risks():
    from arvisx.reasoning import correlate
    a = healthy_community()
    one = [build_report(inject_prd_scenario()).risks[0]]
    out = asyncio.run(correlate(a, one, llm=None))
    assert out.independent and out.common_cause is None


def test_correlate_no_llm_graceful():
    from arvisx.reasoning import correlate
    assets, risks = _flagged()
    out = asyncio.run(correlate(assets, risks, llm=object()))   # llm present but ARVIS_X_LLM unset
    assert out.source == "deterministic" and out.independent


def test_correlate_links_real_assets_and_drops_hallucinated():
    from arvisx.reasoning import correlate
    assets, risks = _flagged()
    real_id = risks[0].asset_id
    fake = _FakeJsonLLM({"common_cause": "Upstream power event", "independent": False,
                         "linked_assets": [real_id, "GHOST-ASSET-999"], "confidence": 0.8,
                         "rationale": "both lost power"})
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        out = asyncio.run(correlate(assets, risks, llm=fake))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert out.common_cause == "Upstream power event"
    assert real_id in out.linked_assets and "GHOST-ASSET-999" not in out.linked_assets  # evidence-bind
    assert out.source == "llm"


def test_correlate_common_cause_without_valid_links_demoted():
    from arvisx.reasoning import correlate
    assets, risks = _flagged()
    fake = _FakeJsonLLM({"common_cause": "Cosmic rays", "independent": False,
                         "linked_assets": ["NOPE-1", "NOPE-2"], "confidence": 0.9})
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        out = asyncio.run(correlate(assets, risks, llm=fake))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert out.common_cause is None and out.independent   # ungrounded → demoted


def test_ask_grounds_and_filters_citations():
    from arvisx.reasoning import ask
    assets, risks = _flagged()
    real_id = risks[0].asset_id
    fake = _FakeJsonLLM({"answer": "The booster pump runtime is high.",
                         "cited": [real_id, "FAKE-1"], "confidence": 0.6})
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        out = asyncio.run(ask("why is water flagged?", assets, risks, llm=fake))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert real_id in out.cited and "FAKE-1" not in out.cited
    assert out.confidence == "Medium"


def test_api_reason_endpoints_graceful():
    c = _client()
    corr = c.post("/api/v1/reason/correlate").json()      # no ARVIS_X_LLM → deterministic
    assert "independent" in corr
    a = c.post("/api/v1/ask", json={"question": "status?"}).json()
    assert "answer" in a
    assert c.post("/api/v1/ask", json={}).status_code == 400


# ── Phase 7: persistence + skillbook + outcome feedback ──────────────────
def _tmpdb():
    import tempfile, os as _os
    from arvisx.persistence import ArvisxDb
    return ArvisxDb(path=_os.path.join(tempfile.mkdtemp(), "t.db"), building_id="test")


def test_baseline_warmstart_persists():
    from arvisx.learning import BaselineStore
    db = _tmpdb()
    b1 = BaselineStore()
    _feed(b1, "P1", "power_kw", [5.0 + (i % 3 - 1) * 0.1 for i in range(35)] + [7.5] * 5)
    z_before = b1.drift_z("P1", "power_kw")
    b1.save_to(db)
    # fresh store, warm-started from disk → drift still detected (learning survived restart)
    b2 = BaselineStore()
    assert b2.drift_z("P1", "power_kw") is None              # empty before load
    b2.load_from(db)
    z_after = b2.drift_z("P1", "power_kw")
    assert z_after is not None and abs(z_after - z_before) < 0.01


def test_event_history_logged():
    db = _tmpdb()
    db.log_event("GEN-01", "Generator 1", "power_backup", "critical", "fault", "active fault")
    h = db.history("GEN-01")
    assert len(h) == 1 and h[0]["message"] == "fault"


def test_skillbook_record_and_recall():
    from arvisx.skillbook import Skillbook
    from arvisx.models import Asset, AssetType, Risk, ServiceType, Severity
    sb = Skillbook(_tmpdb())
    a = Asset("BP-1", "Booster Pump 1", AssetType.BOOSTER_PUMP)
    r = Risk("BP-1", "Booster Pump 1", ServiceType.WATER, Severity.WARNING,
             "Booster Pump 1 power creep (3.4σ above its own normal)", "")
    assert sb.recall(a, r) is None                            # nothing learned yet
    sb.record(a, r, "Bearing wear", "Inspect bearings")
    s = sb.recall(a, r)
    assert s and s["cause"] == "Bearing wear" and s["confirmed"] == 0


def test_outcome_feedback_confirms_skill():
    from arvisx.skillbook import Skillbook
    from arvisx.models import Asset, AssetType, Risk, ServiceType, Severity
    sb = Skillbook(_tmpdb())
    a = Asset("BP-9", "Booster Pump 9", AssetType.BOOSTER_PUMP)
    r = Risk("BP-9", "Booster Pump 9", ServiceType.WATER, Severity.WARNING,
             "Booster Pump 9 power creep (5.0σ above its own normal)", "")
    sb.record_confirmed(a.asset_type.value, "power creep (#σ above its own normal)",
                        "Worn bearing — replaced", "Replace bearing")
    note = sb.recall_note(a, r)
    assert note and "CONFIRMED" in note and "Worn bearing" in note   # institutional memory recalled


def test_workorder_close_teaches_and_persists():
    from arvisx.workorders import WorkOrderStore, sync_workorders
    from arvisx.skillbook import Skillbook
    db = _tmpdb(); sb = Skillbook(db); store = WorkOrderStore()
    sync_workorders(inject_prd_scenario(), store, db=db, skillbook=sb)
    booster = next(w for w in store.all() if w.asset_id == "BOOST-PUMP-01")
    store.close_with_cause(booster.wo_id, "Worn impeller confirmed", "Replace impeller", skillbook=sb)
    # event history + a confirmed skill now exist
    assert any(e["asset_id"] == "BOOST-PUMP-01" for e in db.history())
    confirmed = [s for s in sb.all() if s["confirmed"]]
    assert confirmed and confirmed[0]["cause"] == "Worn impeller confirmed"
    # WO persistence round-trips
    store.save_to(db)
    store2 = WorkOrderStore(); store2.load_from(db)
    assert any(w.cause == "Worn impeller confirmed" for w in store2.all())


def test_api_memory_endpoints():
    import tempfile, os as _os
    _os.environ["ARVISX_DB"] = _os.path.join(tempfile.mkdtemp(), "api.db")
    try:
        c = _client()
        c.get("/api/v1/workorders")                          # triggers sync → events + skills
        wid = c.get("/api/v1/workorders").json()["work_orders"][0]["wo_id"]
        closed = c.post(f"/api/v1/workorders/{wid}/close", json={"actual_cause": "Bearing failure"}).json()
        assert closed["status"] == "done" and "Bearing failure" in closed["cause"]
        assert c.post(f"/api/v1/workorders/{wid}/close", json={}).status_code == 400
        skills = c.get("/api/v1/skillbook").json()["skills"]
        assert any(s["confirmed"] for s in skills)
        # asset history populated
        hist = c.get("/api/v1/asset/BOOST-PUMP-01/history").json()
        assert len(hist["events"]) >= 1
    finally:
        _os.environ.pop("ARVISX_DB", None)


# ── Phase 8: outcome framing + readiness + confidence ────────────────────
def test_community_readiness_headline():
    rep = build_report(inject_prd_scenario())
    assert 0 < rep.readiness <= 100
    assert rep.readiness_band in ("Healthy", "Attention Required", "Critical")
    # healthy community → ~100
    assert build_report(healthy_community()).readiness >= 99


def test_service_outcome_labels():
    rep = build_report(inject_prd_scenario())
    labels = {s.service.value: s.outcome for s in rep.services}
    assert labels["water"] == "Water Availability"
    assert labels["power_backup"] == "Backup Readiness"
    assert labels["fire"] == "Fire Readiness"
    assert labels["stp"] == "STP Compliance"


def test_every_risk_carries_confidence_and_evidence():
    rep = build_report(inject_prd_scenario())
    assert rep.risks
    for r in rep.risks:
        assert r.confidence in ("Low", "Medium", "High")
        assert r.evidence and isinstance(r.evidence, list)


def test_confidence_scales_with_evidence_sources():
    from arvisx.fusion import assess_fusion
    from arvisx.models import Asset, AssetType
    # fusion cooling fault with 3+ modalities → High; single-signal threshold → Low
    a = Asset("AC-9", "AC", AssetType.AC_UNIT,
              signals={"current_a": 7.0, "room_temp_c": 30.0, "room_setpoint_c": 23.0,
                       "motion_events_15m": 5, "runtime_today_hours": 2.0})
    frisks, _ = assess_fusion([a])
    assert frisks and frisks[0].confidence == "High" and len(frisks[0].evidence) >= 3
    # a plain tank-low threshold risk → Low (one source)
    from arvisx.health import assess_asset
    from datetime import datetime
    tank = Asset("T9", "Tank", AssetType.OVERHEAD_TANK, signals={"tank_level_pct": 10.0})
    _, risks = assess_asset(tank, datetime.now())
    assert any(r.confidence == "Low" for r in risks)


# ── Phase 9: Water Availability Engine ───────────────────────────────────
def test_water_healthy():
    from arvisx.water import assess_water
    w = assess_water(inject_prd_scenario())          # tanks 78%/64%, pumps ok
    assert w.score >= 80 and w.band == "Healthy"
    assert w.can_refill and w.hours_remaining and w.hours_remaining > 12
    assert not any(r.severity.value == "critical" for r in w.risks)


def test_water_shortage_blocked_refill():
    from arvisx.water import assess_water
    from arvisx.models import Asset, AssetType
    short = [Asset("UG-TANK-01", "UG Tank", AssetType.UNDERGROUND_TANK,
                   signals={"tank_level_pct": 8, "tank_capacity_l": 50000}),
             Asset("XFER-PUMP-01", "Transfer Pump", AssetType.TRANSFER_PUMP, signals={"fault": True})]
    w = assess_water(short)
    assert w.band == "Critical" and w.can_refill is False
    assert w.hours_remaining is not None and w.hours_remaining < 12
    assert any("refill blocked" in r.message.lower() for r in w.risks)


def test_water_draw_from_meter_signal():
    from arvisx.water import assess_water
    from arvisx.models import Asset, AssetType
    a = [Asset("OH-TANK-01", "OH", AssetType.OVERHEAD_TANK,
               signals={"tank_level_pct": 50, "tank_capacity_l": 20000, "draw_lph": 2000})]
    w = assess_water(a)                              # 10000 L / 2000 = 5h
    assert abs(w.hours_remaining - 5.0) < 0.1 and w.draw_lph == 2000.0


def test_water_flows_into_report():
    from arvisx.models import Asset, AssetType
    short = [Asset("UG-TANK-01", "UG Tank", AssetType.UNDERGROUND_TANK,
                   signals={"tank_level_pct": 6, "tank_capacity_l": 50000}),
             Asset("XFER-PUMP-01", "Transfer Pump", AssetType.TRANSFER_PUMP, signals={"fault": True})]
    rep = build_report(short, water=True)
    assert any("water availability" in r.message.lower() for r in rep.risks)


# ── Phase 10: Asset Dependency Graph ─────────────────────────────────────
def test_impact_redundancy_reasoning():
    from arvisx.topology import impact_analysis
    rep = build_report(inject_prd_scenario())
    cascades = {c.asset_id: c for c in impact_analysis(inject_prd_scenario(), rep.risks)}
    # Fire pump = single suppression → major/critical, no standby
    fp = cascades["FIRE-PUMP-01"]
    assert fp.impact in ("major", "critical") and fp.redundancy == "single"
    # Booster pump = parallel distribution → only partial (redundancy absorbs)
    bp = cascades["BOOST-PUMP-01"]
    assert bp.impact == "partial" and bp.redundancy == "parallel"
    assert fp.readiness_delta > bp.readiness_delta   # essential single hits readiness harder


def test_service_graph_shape():
    from arvisx.topology import service_graph
    g = service_graph()
    roles = {n["role"] for n in g["water"]}
    assert {"source", "transfer", "storage", "distribution"} <= roles


def test_api_water_topology_impact():
    c = _client()
    w = c.get("/api/v1/water").json()
    assert "score" in w and "hours_remaining" in w and "forecast" in w
    g = c.get("/api/v1/topology").json()["graph"]
    assert "water" in g and "fire" in g
    imp = c.post("/api/v1/scenario/prd") and c.get("/api/v1/impact").json()["impacts"]
    assert isinstance(imp, list) and any(i["service"] == "fire" for i in imp)


# ── Phase 11a: commissioning (per-building config + gated state machine) ──
def test_commissioning_full_flow():
    from arvisx.commissioning import CommissioningManager, CommissioningState
    m = CommissioningManager(_tmpdb())
    b = m.create_building("Marina Residences")
    assert b.state == "draft" and b.building_id.startswith("BLD-")
    m.set_services(b.building_id, ["water", "power_backup"])
    m.transition(b.building_id, "assets")
    m.add_asset(b.building_id, {"id": "OHT-A", "type": "overhead_tank", "name": "Overhead Tank A"})
    m.add_asset(b.building_id, {"id": "XFER-A", "type": "transfer_pump", "name": "Transfer Pump A"})
    m.transition(b.building_id, "signals")
    m.add_signal_map(b.building_id, "arvisx/OHT-A/level", "OHT-A", "tank_level_pct")
    m.transition(b.building_id, "dependencies")
    m.set_dependencies(b.building_id, "water",
                       [{"asset_id": "XFER-A", "role": "transfer", "redundancy": "single"}])
    m.transition(b.building_id, "learning")
    final = m.transition(b.building_id, "operational", force=True)   # skip the 14-day wait in test
    assert final.state == "operational"
    # persisted + reloads identically
    again = m.get(b.building_id)
    assert again.state == "operational" and len(again.assets) == 2 and again.dependencies["water"]


def test_commissioning_gates_block_skips():
    from arvisx.commissioning import CommissioningManager, CommissioningError
    m = CommissioningManager(_tmpdb())
    b = m.create_building("X")
    # can't enter ASSETS without a service
    import pytest
    with pytest.raises(CommissioningError):
        m.transition(b.building_id, "assets")
    # can't jump straight to operational
    m.set_services(b.building_id, ["water"])
    with pytest.raises(CommissioningError):
        m.transition(b.building_id, "operational")
    # signal to a non-existent asset rejected
    m.transition(b.building_id, "assets")
    with pytest.raises(CommissioningError):
        m.add_signal_map(b.building_id, "s", "NOPE", "x")


def test_api_commissioning_wizard():
    c = _client()
    b = c.post("/api/v1/commission/building", json={"name": "Tower 5"}).json()
    bid = b["building_id"]
    assert c.post(f"/api/v1/commission/building/{bid}/services", json={"services": ["water"]}).json()["services"] == ["water"]
    assert c.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "assets"}).json()["state"] == "assets"
    c.post(f"/api/v1/commission/building/{bid}/assets", json={"asset": {"id": "T1", "type": "overhead_tank", "name": "T1"}})
    # gated: can't go operational mid-flow
    assert c.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "operational"}).status_code == 400
    assert any(x["building_id"] == bid for x in c.get("/api/v1/commission/buildings").json()["buildings"])
    assert c.get(f"/api/v1/commission/building/NOPE").status_code == 404


# ── Phase 11b: templates, learning gate, validation, discovery assist ────
def test_apply_template_loads_assets_and_deps():
    from arvisx.commissioning import CommissioningManager
    m = CommissioningManager(_tmpdb())
    b = m.create_building("T")
    b = m.apply_template(b.building_id, "water")
    ids = {a["id"] for a in b.assets}
    assert {"UGT-01", "XFER-A", "OHT-A", "BOOST-01"} <= ids        # standard water assets loaded
    assert "water" in b.services and b.dependencies["water"]        # + dependency graph
    assert any(a["type"] == "underground_tank" for a in b.assets)


def test_learning_gate_blocks_premature_golive():
    from arvisx.commissioning import CommissioningManager, CommissioningError
    from datetime import datetime, timedelta
    m = CommissioningManager(_tmpdb())
    b = m.create_building("L"); m.apply_template(b.building_id, "water")
    m.set_services(b.building_id, ["water"])
    for s in ("assets", "signals"):
        if s == "signals":
            m.add_signal_map(b.building_id, "arvisx/UGT-01/level", "UGT-01", "tank_level_pct")
        m.transition(b.building_id, s)
    m.transition(b.building_id, "dependencies")
    m.transition(b.building_id, "learning")          # learning_started_at set
    import pytest
    with pytest.raises(CommissioningError):          # day 0 → still learning → blocked
        m.transition(b.building_id, "operational")
    prog = m.learning_progress(b.building_id)
    assert prog["in_learning"] and not prog["ready"] and prog["days_total"] == 14
    # force override OR elapsed time goes live
    m.transition(b.building_id, "operational", force=True)
    assert m.get(b.building_id).state == "operational"


def test_validation_loop_records_answer():
    from arvisx.commissioning import CommissioningManager
    m = CommissioningManager(_tmpdb())
    b = m.create_building("V")
    m.add_validation(b.building_id, "PUMP-A", "runtime_today_hours", 12.0,
                     "Pump A ran 12h yesterday — is this normal?")
    vid = m.get(b.building_id).validations[0]["id"]
    m.answer_validation(b.building_id, vid, is_normal=False)
    v = m.get(b.building_id).validations[0]
    assert v["answer"] == "abnormal"


def test_discovery_assist_suggests_from_topics():
    from arvisx.discovery_assist import suggest_from_topics
    s = suggest_from_topics(["arvisx/UGT-01/tank_level_pct", "arvisx/XFER-A/current_a",
                             "arvisx/GEN-01/fuel_level_pct", "junk/x"])
    by_id = {a["id"]: a for a in s["assets"]}
    assert by_id["UGT-01"]["type"] == "underground_tank"
    assert by_id["XFER-A"]["type"] == "transfer_pump"
    assert by_id["GEN-01"]["type"] == "diesel_generator"
    assert any(m["signal"] == "tank_level_pct" for m in s["signal_maps"])
    assert "junk/x" in s["unmapped_topics"]


def test_api_11b_template_and_discover():
    c = _client()
    b = c.post("/api/v1/commission/building", json={"name": "Z"}).json()
    bid = b["building_id"]
    t = c.post(f"/api/v1/commission/building/{bid}/apply-template", json={"service": "water"}).json()
    assert len(t["assets"]) >= 4 and "water" in t["services"]
    sug = c.post("/api/v1/commission/discover", json={"topics": ["arvisx/OHT-A/tank_level_pct"]}).json()
    assert sug["assets"][0]["id"] == "OHT-A"


# ── Phase 12: agentic investigation + proactive monitor ──────────────────
class _SeqLLM:
    """Scripted multi-turn LLM for the agent loop (pops one response per ask_json)."""
    def __init__(self, responses): self._q = list(responses)
    async def ask_json(self, **kwargs):
        return self._q.pop(0) if self._q else {"final": {"root_cause": "out of script", "confidence": 0.3}}


def _risk_for(asset_id):
    assets = inject_prd_scenario()
    rep = build_report(assets)
    return assets, rep.risks, next(r for r in rep.risks if r.asset_id == asset_id)


def test_agent_multistep_tool_use():
    from arvisx.agent import investigate
    from arvisx.learning import BaselineStore
    assets, risks, risk = _risk_for("BOOST-PUMP-01")
    a = next(x for x in assets if x.asset_id == "BOOST-PUMP-01")
    fake = _SeqLLM([
        {"thought": "history?", "tool": "get_fault_history", "args": {"asset_id": "BOOST-PUMP-01"}},
        {"thought": "impact?", "tool": "check_dependency_impact", "args": {"asset_id": "BOOST-PUMP-01"}},
        {"thought": "conclude", "final": {"root_cause": "Bearing wear at high duty",
         "recommended_action": "Inspect bearings", "confidence": 0.6, "evidence": ["water partial impact"]}},
    ])
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        inv = asyncio.run(investigate(a, risk, assets, risks, llm=fake, db=_tmpdb(), baselines=BaselineStore()))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert inv.source == "agent" and inv.confirmed is False
    assert inv.root_cause == "Bearing wear at high duty"
    tools = {s["tool"] for s in inv.steps}
    assert "get_fault_history" in tools and "check_dependency_impact" in tools   # it gathered evidence itself


def test_agent_no_llm_falls_back_to_rules():
    from arvisx.agent import investigate
    assets, risks, risk = _risk_for("BOOST-PUMP-01")
    a = next(x for x in assets if x.asset_id == "BOOST-PUMP-01")
    inv = asyncio.run(investigate(a, risk, assets, risks, llm=None))
    assert inv.source == "rules" and inv.steps == [] and "wear" in inv.root_cause.lower()


def test_agent_budget_grounds_out():
    from arvisx.agent import investigate
    from arvisx.learning import BaselineStore
    assets, risks, risk = _risk_for("BOOST-PUMP-01")
    a = next(x for x in assets if x.asset_id == "BOOST-PUMP-01")
    fake = _SeqLLM([{"tool": "get_asset_state", "args": {"asset_id": "BOOST-PUMP-01"}}] * 10)  # never finalizes
    os.environ["ARVIS_X_LLM"] = "1"
    try:
        inv = asyncio.run(investigate(a, risk, assets, risks, llm=fake, db=_tmpdb(),
                                      baselines=BaselineStore(), max_steps=3))
    finally:
        os.environ.pop("ARVIS_X_LLM", None)
    assert len(inv.steps) == 3 and "rules" in inv.source     # budget hit → grounded out, trace kept


def test_monitor_prioritizes_caps_and_tiers():
    from arvisx.agent import monitor
    assets, risks, _ = _risk_for("BOOST-PUMP-01")
    invs = asyncio.run(monitor(assets, risks, llm=None, max_investigations=2))   # no LLM → rules
    assert len(invs) == 2 and all(i.source == "rules" for i in invs)
    # critical risk ranks first
    from arvisx.models import Asset, AssetType, Risk, ServiceType, Severity
    crit_assets = assets + [Asset("GEN-01b", "Gen X", AssetType.DIESEL_GENERATOR, signals={"fault": True})]
    crit = [Risk("GEN-01b", "Gen X", ServiceType.POWER_BACKUP, Severity.CRITICAL, "Gen X fault", "")] + risks
    invs2 = asyncio.run(monitor(crit_assets, crit, llm=None, max_investigations=1))
    assert invs2[0].asset_id == "GEN-01b"                    # critical investigated first


def test_api_investigate_and_monitor():
    c = _client()
    m = c.post("/api/v1/monitor", json={"max_investigations": 2}).json()
    assert m["investigated"] >= 1 and "investigations" in m
    inv = c.post("/api/v1/investigate/BOOST-PUMP-01").json()
    assert inv.get("asset_id") == "BOOST-PUMP-01"
    assert c.post("/api/v1/investigate/NOPE").status_code == 404


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
