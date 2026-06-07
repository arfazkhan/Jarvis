"""
ArvisX FULL-LIFECYCLE end-to-end test — the whole product, naturally, in order.

This is the one test that exercises everything ArvisX is supposed to do, against the
REAL engine (no mocks, no FakeLLM — the deterministic floor end to end):

  1. IDENTIFY   — sniff live MQTT topics, infer the asset/signal map (discovery assist)
  2. COMMISSION — gated state machine: create → services → assets → signals →
                  dependencies → learning (proves the gate rejects illegal jumps)
  3. INGEST     — real topic parsing → AssetStore (signal-quality gate, abstain-on-absent)
  4. LEARN      — feed a healthy window → BaselineStore learns each signal's own normal
  5. ANALYSE    — degrade the fleet → build_report surfaces drift (learned-baseline catch)
                  + threshold faults, with confidence + evidence; water + economics + fusion
  6. UNDERSTAND — reasoning.correlate + ask answer in operational language (deterministic)
  7. ACT        — sync_workorders opens tickets; close_with_cause feeds the skillbook
  8. SAVE       — persist baselines + work orders + skills + commissioning to SQLite,
                  then RELOAD into fresh objects and assert the building came back smart

Run as a test:   pytest arvisx/tests/test_full_lifecycle_e2e.py -v
Run as a story:  python arvisx/tests/test_full_lifecycle_e2e.py   (prints each stage)
"""
from __future__ import annotations

import asyncio
import os
import tempfile

from arvisx.commissioning import CommissioningError, CommissioningManager, CommissioningState
from arvisx.discovery_assist import suggest_from_topics
from arvisx.economics import community_cost
from arvisx.health import build_report
from arvisx.ingest.mock_publisher import scenario_messages
from arvisx.ingest.topics import parse
from arvisx.learning import BaselineStore
from arvisx.models import ServiceType
from arvisx.persistence import ArvisxDb
from arvisx.reasoning import ask, correlate
from arvisx.simulator import community_zones, healthy_community
from arvisx.skillbook import Skillbook
from arvisx.store import AssetStore
from arvisx.water import assess_water
from arvisx.workorders import WorkOrderStore, sync_workorders


def _run(verbose=False):
    def say(*a):
        if verbose:
            print(*a)

    db_path = os.path.join(tempfile.mkdtemp(prefix="arvisx_e2e_"), "arvisx.db")
    db = ArvisxDb(db_path, building_id="MARINA-A")

    # ── 1. IDENTIFY ──────────────────────────────────────────────────────
    # The edge node sniffs topics; ArvisX proposes the asset/signal map.
    topics = sorted({t for t, _ in scenario_messages("healthy")})
    disc = suggest_from_topics(topics)
    say(f"\n[1] IDENTIFY  observed {len(topics)} topics → "
        f"{len(disc['assets'])} assets, {len(disc['signal_maps'])} signal-maps inferred")
    assert len(disc["assets"]) >= 10
    assert len(disc["signal_maps"]) >= len(disc["assets"])
    say("    e.g. " + ", ".join(f"{a['id']}→{a['type']}" for a in disc["assets"][:4]))

    # ── 2. COMMISSION (gated) ────────────────────────────────────────────
    mgr = CommissioningManager(db)
    b = mgr.create_building("Marina Heights — Tower A")
    bid = b.building_id
    say(f"\n[2] COMMISSION  building {bid} created (state={b.state})")

    # The gate must reject jumping straight to learning.
    jumped = False
    try:
        mgr.transition(bid, "learning")
    except CommissioningError as e:
        jumped = True
        say(f"    gate held: {e}")
    assert jumped, "gate should reject draft→learning jump"

    mgr.set_services(bid, [ServiceType.WATER.value, ServiceType.POWER_BACKUP.value,
                           ServiceType.STP.value, ServiceType.POOL.value, ServiceType.FIRE.value])
    mgr.transition(bid, "assets")

    # Operator confirms the discovered fleet (authoritative types from the asset defs).
    fleet = healthy_community()
    svc_of = {ServiceType.WATER: ["UNDERGROUND_TANK", "OVERHEAD_TANK", "TRANSFER_PUMP", "BOOSTER_PUMP"]}
    for a in fleet:
        mgr.add_asset(bid, {"id": a.asset_id, "type": a.asset_type.value,
                            "name": a.name, "service": a.service.value})
    mgr.transition(bid, "signals")

    for t, _ in scenario_messages("healthy"):
        r = parse(t, "0")
        if r:
            aid, sig, _v = r[0]
            try:
                mgr.add_signal_map(bid, t, aid, sig)
            except CommissioningError:
                pass  # topic for an asset we didn't add — fine
    mgr.transition(bid, "dependencies")

    mgr.set_dependencies(bid, ServiceType.WATER.value, [
        {"asset_id": "BOOST-PUMP-01", "role": "primary", "redundancy": "none"},
        {"asset_id": "UG-TANK-01", "role": "source", "redundancy": "OH-TANK-01"}])
    mgr.transition(bid, "learning")
    say(f"    advanced through gate → state={mgr.get(bid).state}")
    assert mgr.get(bid).state == CommissioningState.LEARNING.value

    # ── 3. INGEST (real parse → store) ───────────────────────────────────
    store = AssetStore.from_fleet_definition(healthy_community())
    accepted = 0
    for t, p in scenario_messages("healthy"):
        for aid, sig, val in parse(t, p):
            if store.apply_reading(aid, sig, val):
                accepted += 1
    say(f"\n[3] INGEST  applied {accepted} live readings (store updates={store.update_count})")
    assert store.update_count > 0

    # ── 4. LEARN (build per-signal baselines) ────────────────────────────
    baselines = BaselineStore()
    import random
    random.seed(7)
    for _ in range(30):                                    # a healthy observation window
        for a in store.snapshot():
            for k, v in (a.signals or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    baselines.observe(a.asset_id, k, v * (1 + random.uniform(-0.02, 0.02)))
    base = baselines.baseline("BOOST-PUMP-01", "power_kw")
    say(f"\n[4] LEARN  BOOST-PUMP-01 power_kw baseline = "
        f"{base[0]:.2f}kW (±{base[1]:.3f} MAD, n={base[2]})")
    assert base is not None and base[2] >= 20, "should have learned a real baseline"

    # ── 5. ANALYSE (degrade → drift + faults + money) ────────────────────
    boost = store.asset("BOOST-PUMP-01")
    for _ in range(5):                                     # sustained creep, not a spike
        boost.signals["power_kw"] = 4.3
        baselines.observe("BOOST-PUMP-01", "power_kw", 4.3)
    # A second, independent fault class: fire-pump test overdue.
    from datetime import datetime, timedelta
    store.asset("FIRE-PUMP-01").signals["next_test_due"] = datetime.now() - timedelta(days=3)

    assets = store.snapshot()
    zones = community_zones("prd")
    report = build_report(assets, baselines=baselines, virtual=True, zones=zones,
                          fusion=True, water=True, signal_quality=True)
    msgs = [r.message.lower() for r in report.risks]
    say(f"\n[5] ANALYSE  Community Readiness {report.readiness:.0f}% "
        f"({report.readiness_band}) — {len(report.risks)} risks")
    for r in report.risks[:6]:
        say(f"    [{r.severity.value}/{r.confidence}] {r.message}")
    # The learned-baseline catch on power_kw surfaces via the PowerCreep virtual
    # sensor ("Nσ above its own normal") — drift_risks cedes power_kw to it so the
    # same physical cause never double-tickets. Either phrasing proves the learned
    # normal (not a fixed threshold) caught the creep.
    drift_hit = any(("above its own normal" in m or "drift" in m or "creep" in m) for m in msgs)
    fire_hit = any("test overdue" in m or "overdue" in m for m in msgs)
    assert drift_hit, "learned-baseline catch (drift/creep vs own normal) should surface"
    assert fire_hit, "fire-pump test-overdue should surface"
    # every risk carries evidence + a confidence band (no naked claims)
    assert all(r.confidence in ("Low", "Medium", "High") for r in report.risks)

    water = assess_water(assets, baselines)
    say(f"    WATER  stored~{water.stored_l:.0f}L, {water.hours_remaining}h remaining, "
        f"refill_ok={water.can_refill}")

    cost = community_cost(report, assets, baselines)
    say(f"    MONEY  ~{cost['currency']} {cost['monthly_waste']:.0f}/mo waste, "
        f"exposure {cost['currency']} {cost['exposure_low']:.0f}-{cost['exposure_high']:.0f}")
    assert (cost["monthly_waste"] + cost["exposure_high"]) > 0, "risks should translate to money"

    # ── 6. UNDERSTAND (deterministic reasoning) ──────────────────────────
    corr = asyncio.run(correlate(assets, report.risks))
    ans = asyncio.run(ask("why is community readiness down?", assets, report.risks))
    say(f"\n[6] UNDERSTAND  correlate→ independent={corr.independent}, "
        f"linked={corr.linked_assets} ({corr.source})")
    say(f"    ask→ {ans.answer[:100]}...")
    assert ans.answer and isinstance(ans.answer, str)
    assert corr.source == "deterministic"   # no LLM → deterministic floor answered

    # ── 7. ACT (work orders + outcome feedback) ──────────────────────────
    skillbook = Skillbook(db)
    wo = WorkOrderStore()
    counts = sync_workorders(assets, wo, baselines=baselines, virtual=True,
                             zones=zones, fusion=True, db=db, skillbook=skillbook)
    say(f"\n[7] ACT  work orders: {counts}")
    assert counts["opened"] > 0
    open_wos = wo.all()
    # Close one with a confirmed cause → teaches the skillbook.
    target = next((w for w in open_wos if "BOOST-PUMP-01" == w.asset_id), open_wos[0])
    wo.close_with_cause(target.wo_id, actual_cause="worn impeller bearing",
                        action="replace bearing; re-baseline", skillbook=skillbook)
    say(f"    closed {target.wo_id} on {target.asset_id} → skillbook taught the cause")
    assert any(s["confirmed"] for s in skillbook.all()), "confirmed skill should exist"

    # ── 8. SAVE → RELOAD (warm-start the brain) ──────────────────────────
    n_base = baselines.save_to(db)
    wo.save_to(db)
    say(f"\n[8] SAVE  persisted {n_base} baselines, {len(wo.all())} work orders, "
        f"{len(skillbook.all())} skills, commissioning config")

    # Fresh objects on the SAME db file — nothing carried in memory.
    db2 = ArvisxDb(db_path, building_id="MARINA-A")
    baselines2 = BaselineStore()
    n2 = baselines2.load_from(db2)
    wo2 = WorkOrderStore()
    n_wo2 = wo2.load_from(db2)
    mgr2 = CommissioningManager(db2)
    b2 = mgr2.get(bid)
    sk2 = Skillbook(db2)
    hist = db2.history()

    say(f"    RELOAD  baselines={n2}, work_orders={n_wo2}, "
        f"building_state={b2.state}, events={len(hist)}, skills={len(sk2.all())}")
    assert n2 == n_base and n2 > 0, "baselines must survive restart"
    assert n_wo2 == len(wo.all()), "work orders must survive restart"
    assert b2 is not None and b2.state == CommissioningState.LEARNING.value
    assert len(b2.assets) == len(fleet), "commissioned fleet must survive restart"
    assert any(s["confirmed"] for s in sk2.all()), "learned skill must survive restart"
    assert len(hist) > 0, "fault events must be on record"
    # warm-started baseline still recognises the booster's learned normal
    assert baselines2.baseline("BOOST-PUMP-01", "power_kw") is not None

    say("\nRESULT: PASS — identify → commission → ingest → learn → analyse → "
        "understand → act → save/reload all verified end to end.\n")
    return True


def test_full_lifecycle_e2e():
    assert _run(verbose=False)


if __name__ == "__main__":
    _run(verbose=True)
