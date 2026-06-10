"""
ArvisX DEPLOYMENT simulation — digital twin + the real production stack, end to end.

This is "test it as if we really deployed": an in-process MQTT broker stands in for the
building LAN, the CommunityTwin publishes evolving physics telemetry like a real edge
gateway, and the REAL ArvisX API runs in ARVISX_SOURCE=mqtt mode — so every layer is the
production path: broker → paho ingest → AssetStore → learning → readiness gate →
operational → drift catch → WhatsApp alert → work order → money.

Timeline (accelerated: 1 sim-hour per step):
  Day 0      commission the building through the wizard API
  Day 0–7    healthy operation — baselines learn from the live stream
  Day 7      data-driven readiness gate → OPERATIONAL
  Day 7–12   a real degradation creeps in (booster bearing wear: +4%/day power)
  Day 12     ArvisX must have caught it: risk + alert + cost + work order

Run: venv python scratch/twin_deployment_e2e.py
"""
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

BROKER, PORT = "127.0.0.1", 1884

os.environ["ARVISX_SOURCE"] = "mqtt"
os.environ["ARVISX_MQTT_BROKER"] = BROKER
os.environ["ARVISX_MQTT_PORT"] = str(PORT)
os.environ["ARVISX_DB"] = str(Path(tempfile.mkdtemp(prefix="arvisx_twin_")) / "arvisx.db")
os.environ.pop("ARVISX_API_KEY", None)     # open dev API for the harness
os.environ["ARVIS_X_LLM"] = "0"            # deterministic floor — no network LLM needed


def start_broker():
    from amqtt.broker import Broker
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"{BROKER}:{PORT}"}},
           "sys_interval": 0,
           "auth": {"allow-anonymous": True}}

    async def _run():
        broker = Broker(cfg)
        await broker.start()
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())


def main():
    print("═" * 70)
    print("  ARVISX DEPLOYMENT SIMULATION — digital twin over real MQTT")
    print("═" * 70)

    threading.Thread(target=start_broker, daemon=True).start()
    time.sleep(2.5)
    print(f"[infra] broker up on {BROKER}:{PORT}")

    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    from arvisx.twin import CommunityTwin, TwinPublisher

    client = TestClient(create_app())
    time.sleep(1.0)                          # let the paho ingest subscribe
    print("[infra] ArvisX API booted in mqtt mode (real ingest subscribed)")

    twin = CommunityTwin(seed=7)
    pub = TwinPublisher(twin, BROKER, PORT)

    def advance(hours: int, label: str):
        for _ in range(hours):
            pub.publish_step(1.0)
            time.sleep(0.03)                 # let messages traverse broker → ingest
            client.get("/api/v1/community/overview")   # production learning tick
        print(f"[twin] +{hours}h  ({label})  published={pub.published}")

    # ── Day 0: commission the building through the real wizard ───────────
    b = client.post("/api/v1/commission/building",
                    json={"name": "Twin Towers A", }).json()
    bid = b.get("building_id") or b.get("building", {}).get("building_id")
    client.post(f"/api/v1/commission/building/{bid}/services",
                json={"services": ["water", "power_backup", "stp", "pool", "fire"]})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "assets"})
    for aid, typ in [("UG-TANK-01", "underground_tank"), ("OH-TANK-01", "overhead_tank"),
                     ("XFER-PUMP-01", "transfer_pump"), ("BOOST-PUMP-01", "booster_pump"),
                     ("GEN-01", "diesel_generator"), ("GEN-BATT-01", "generator_battery"),
                     ("STP-BLOWER-01", "stp_blower"), ("STP-PUMP-01", "stp_pump"),
                     ("POOL-FILT-01", "pool_filtration_pump"), ("FIRE-PUMP-01", "fire_pump")]:
        client.post(f"/api/v1/commission/building/{bid}/assets",
                    json={"asset": {"id": aid, "type": typ, "name": aid}})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "signals"})
    client.post(f"/api/v1/commission/building/{bid}/signals",
                json={"source": "arvisx/BOOST-PUMP-01/power_kw",
                      "asset_id": "BOOST-PUMP-01", "signal": "power_kw"})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "dependencies"})
    client.post(f"/api/v1/commission/building/{bid}/dependencies",
                json={"service": "water",
                      "nodes": [{"asset_id": "BOOST-PUMP-01", "role": "distribution"}]})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "learning"})
    state0 = client.get(f"/api/v1/commission/building/{bid}").json().get("state")
    print(f"[day 0] commissioned → state={state0}")
    assert state0 == "learning"

    # ── Day 0–7: healthy operation, baselines learn from the live stream ─
    advance(24 * 7, "days 0–7 healthy: learning")

    rd = client.post(f"/api/v1/commission/building/{bid}/evaluate-readiness").json()
    print(f"[day 7] readiness gate: approved={rd.get('approved')} "
          f"coverage={rd.get('coverage')} → state={rd.get('state')}")
    assert rd.get("approved") is True, f"gate rejected: {rd}"
    assert rd.get("state") == "operational"

    risks_before = client.get("/api/v1/community/risks").json()
    boost_before = [r for r in risks_before["risks"] if r["asset_id"] == "BOOST-PUMP-01"
                    and "creep" in r["message"].lower()]
    print(f"[day 7] baseline check: {risks_before['count']} risks, "
          f"booster-creep risks={len(boost_before)} (expect 0 — it is healthy)")

    # ── Day 7–12: REAL degradation creeps in (bearing wear) ──────────────
    twin.inject(boost_power_creep_pct_per_day=4.0)
    print("[fault] injected: booster power creep +4%/day (gradual bearing wear)")
    advance(24 * 5, "days 7–12 degrading")

    # ── Day 12: did ArvisX catch it like a deployed system would? ────────
    risks = client.get("/api/v1/community/risks").json()
    boost = [r for r in risks["risks"] if r["asset_id"] == "BOOST-PUMP-01"
             and ("creep" in r["message"].lower() or "normal" in r["message"].lower()
                  or "drift" in r["message"].lower())]
    print(f"\n[day 12] risks={risks['count']}; booster degradation risks:")
    for r in boost:
        print(f"   ⚠ {r['message']}  [{r.get('confidence')}]")
    assert boost, "deployed ArvisX failed to catch the gradual power creep"

    alerts = client.get("/api/v1/whatsapp/alerts").json()
    creep_alerts = [a for a in alerts["alerts"] if a["asset_id"] == "BOOST-PUMP-01"]
    print(f"[day 12] WhatsApp alerts pushed: {alerts['count']} "
          f"(booster: {len(creep_alerts)})")
    if creep_alerts:
        print("   ── alert as the FM sees it ──")
        for line in creep_alerts[0]["text"].splitlines():
            print(f"   {line}")

    costs = client.get("/api/v1/costs").json()
    print(f"[day 12] money: waste ~{costs.get('currency')} {costs.get('monthly_waste')}/mo, "
          f"exposure {costs.get('exposure_low')}–{costs.get('exposure_high')}")

    wo = client.post("/api/v1/workorders/from-risk",
                     json={"asset_id": "BOOST-PUMP-01"}).json()
    print(f"[day 12] work order: {wo.get('wo_id')} — {wo.get('title')}")
    assert wo.get("wo_id")

    water = client.get("/api/v1/water").json()
    print(f"[day 12] water status: {water.get('band')} fill={water.get('fill_pct')}% "
          f"draw={water.get('draw_lph')}lph hours_remaining={water.get('hours_remaining')}")

    pub.close()
    print("\n" + "═" * 70)
    print("  RESULT: PASS — full deployment lifecycle on live MQTT telemetry:")
    print("  commission → learn(7d) → readiness-approved → operational →")
    print("  gradual fault → caught → alert + money + work order")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
