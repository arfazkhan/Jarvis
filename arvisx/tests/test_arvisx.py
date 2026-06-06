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
    assert lst["count"] == 4
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
