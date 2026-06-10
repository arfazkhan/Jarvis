"""
ArvisX ADVERSARIAL deployment test — hostile conditions, not a happy path.

Real deployments are ugly: garbage on the broker, sensors that spike and lie, several
things degrading at once, processes restarting mid-incident. This run attacks the
production path (broker → paho ingest → store → learning → gate → alerts) with all of
it and asserts ArvisX behaves like the product we claim:

  1  GARBAGE BARRAGE   malformed topics, unknown devices, out-of-range/junk payloads,
                       duplicates — must be rejected/quarantined, never crash, never
                       invent an asset.
  2  TRANSIENT SPIKE   a one-tick power glitch — must NOT leave a standing fault
                       (anti-false-alarm: drift judges a sustained window, not a blip).
  3  TRIPLE FAULT      power creep + tank leak + battery decay SIMULTANEOUSLY —
                       all three must be caught independently.
  4  ANTI-FATIGUE      polling alerts twice must not re-push the same alert.
  5  RESTART MID-INCIDENT  kill the app, boot a fresh one on the same DB — baselines,
                       work orders, commissioning state survive; the creep is
                       re-flagged within 3 ticks (warm start, no re-learning).

Run: venv python scratch/twin_adversarial_e2e.py
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

BROKER, PORT = "127.0.0.1", 1885
os.environ["ARVISX_SOURCE"] = "mqtt"
os.environ["ARVISX_MQTT_BROKER"] = BROKER
os.environ["ARVISX_MQTT_PORT"] = str(PORT)
DB = str(Path(tempfile.mkdtemp(prefix="arvisx_adv_")) / "arvisx.db")
os.environ["ARVISX_DB"] = DB
os.environ.pop("ARVISX_API_KEY", None)
os.environ["ARVIS_X_LLM"] = "0"

CHECKS = []


def check(name, ok, note=""):
    CHECKS.append((name, ok))
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {note}" if note else ""))
    return ok


def start_broker():
    from amqtt.broker import Broker
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"{BROKER}:{PORT}"}},
           "sys_interval": 0, "auth": {"allow-anonymous": True}}

    async def _run():
        await Broker(cfg).start()
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())


def commission(client):
    b = client.post("/api/v1/commission/building", json={"name": "Adversarial Towers"}).json()
    bid = b["building_id"]
    client.post(f"/api/v1/commission/building/{bid}/services",
                json={"services": ["water", "power_backup", "stp", "pool", "fire"]})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "assets"})
    for aid, typ in [("UG-TANK-01", "underground_tank"), ("OH-TANK-01", "overhead_tank"),
                     ("XFER-PUMP-01", "transfer_pump"), ("BOOST-PUMP-01", "booster_pump"),
                     ("GEN-01", "diesel_generator"), ("GEN-BATT-01", "generator_battery"),
                     ("STP-BLOWER-01", "stp_blower"), ("POOL-FILT-01", "pool_filtration_pump"),
                     ("FIRE-PUMP-01", "fire_pump")]:
        client.post(f"/api/v1/commission/building/{bid}/assets",
                    json={"asset": {"id": aid, "type": typ, "name": aid}})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "signals"})
    client.post(f"/api/v1/commission/building/{bid}/signals",
                json={"source": "arvisx/BOOST-PUMP-01/power_kw",
                      "asset_id": "BOOST-PUMP-01", "signal": "power_kw"})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "dependencies"})
    client.post(f"/api/v1/commission/building/{bid}/dependencies",
                json={"service": "water", "nodes": [{"asset_id": "BOOST-PUMP-01", "role": "distribution"}]})
    client.post(f"/api/v1/commission/building/{bid}/transition", json={"state": "learning"})
    return bid


def main():
    print("═" * 70)
    print("  ARVISX ADVERSARIAL DEPLOYMENT TEST")
    print("═" * 70)
    threading.Thread(target=start_broker, daemon=True).start()
    time.sleep(2.5)

    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    from arvisx.twin import CommunityTwin, TwinPublisher

    client = TestClient(create_app())
    time.sleep(1.0)
    twin = CommunityTwin(seed=23)
    pub = TwinPublisher(twin, BROKER, PORT)

    def advance(hours, tick_sleep=0.03):
        for _ in range(hours):
            pub.publish_step(1.0)
            time.sleep(tick_sleep)
            client.get("/api/v1/community/overview")

    bid = commission(client)
    print(f"[setup] commissioned {bid} → learning")

    # ── learn 7 healthy days, pass the gate ──────────────────────────────
    advance(24 * 7)
    rd = client.post(f"/api/v1/commission/building/{bid}/evaluate-readiness").json()
    check("readiness gate approves after real learning", rd.get("approved") is True,
          f"coverage={rd.get('coverage')}")

    risks0 = client.get("/api/v1/community/risks").json()["risks"]
    check("negative control: no creep/battery/leak risks while healthy",
          not [r for r in risks0 if any(k in r["message"].lower()
               for k in ("creep", "battery weak", "drift"))],
          f"{len(risks0)} baseline risks (maintenance/schedule only)")

    # ── 1) GARBAGE BARRAGE ───────────────────────────────────────────────
    print("\n[attack 1] garbage barrage on the broker")
    raw = pub.client
    garbage = [
        ("arvisx/HACKER-99/power_kw", "3.2"),                  # unknown device
        ("arvisx//", "{}"),                                    # malformed topic
        ("noise", "hello"),                                    # off-prefix
        ("arvisx/OH-TANK-01/tank_level_pct", "250.0"),         # out of range
        ("arvisx/GEN-BATT-01/battery_voltage", "999"),         # absurd voltage
        ("arvisx/BOOST-PUMP-01/power_kw", "not_a_number"),     # junk payload
        ("arvisx/BOOST-PUMP-01/power_kw", "nan"),              # NaN
    ]
    for t, p in garbage * 3:                                   # repeated + duplicates
        raw.publish(t, p, qos=1)
    time.sleep(1.5)
    advance(2)

    assets = client.get("/api/v1/community/assets").json()
    ids = {a["asset_id"] for a in assets["assets"]}
    check("unknown device NOT invented as an asset", "HACKER-99" not in ids)
    sq = client.get("/api/v1/signal-quality").json()
    quar = sq.get("quarantined", [])
    check("out-of-range readings quarantined (not stored)",
          any(q["signal"] == "tank_level_pct" and float(q["value"]) == 250.0 for q in quar)
          and any(q["signal"] == "battery_voltage" for q in quar),
          f"{len(quar)} quarantined")
    ov = client.get("/api/v1/community/overview")
    check("engine alive and serving after barrage", ov.status_code == 200,
          f"readiness={ov.json().get('community_readiness')}")

    # ── 2) TRANSIENT SPIKE (must not become a standing fault) ───────────
    print("\n[attack 2] one-tick power spike, then recovery")
    raw.publish("arvisx/BOOST-PUMP-01/power_kw", "9.4", qos=1)   # in-range glitch
    time.sleep(0.5)
    client.get("/api/v1/community/overview")
    advance(12)                                                   # half a day of normal
    risks = client.get("/api/v1/community/risks").json()["risks"]
    standing = [r for r in risks if r["asset_id"] == "BOOST-PUMP-01"
                and any(k in r["message"].lower() for k in ("creep", "drift", "normal"))]
    check("transient spike does NOT leave a standing fault", not standing,
          "drift judges a sustained window, not a blip")

    # ── 3) TRIPLE OVERLAPPING FAULT ──────────────────────────────────────
    print("\n[attack 3] simultaneous: power creep + tank leak + battery decay")
    water_before = client.get("/api/v1/water").json()
    twin.inject(boost_power_creep_pct_per_day=5.0,
                oh_tank_leak_lph=1500.0,
                gen_battery_decay_v_per_day=0.22)
    advance(24 * 5)

    risks = client.get("/api/v1/community/risks").json()["risks"]
    msgs = [r["message"].lower() for r in risks]
    check("fault 1/3 caught: booster power creep",
          any("creep" in m or "above its own normal" in m for m in msgs))
    check("fault 2/3 caught: generator battery weak",
          any("battery weak" in m for m in msgs),
          f"battery now ~{twin.gen_battery_v:.2f}V")
    water_after = client.get("/api/v1/water").json()
    hb, ha = water_before.get("hours_remaining"), water_after.get("hours_remaining")
    check("fault 3/3 visible: leak shrinks water autonomy",
          (hb is not None and ha is not None and ha < hb * 0.85),
          f"hours_remaining {hb} → {ha}")

    # ── 4) ANTI-FATIGUE: alert dedup across polls ────────────────────────
    print("\n[attack 4] alert fatigue probe")
    a1 = client.get("/api/v1/whatsapp/alerts").json()
    a2 = client.get("/api/v1/whatsapp/alerts").json()
    sigs1 = {a["signature"] for a in a1["alerts"]}
    sigs2 = {a["signature"] for a in a2["alerts"]}
    check("second poll does not re-push the same alerts", not (sigs1 & sigs2),
          f"first={len(sigs1)} pushed, repeat={len(sigs1 & sigs2)}")

    wo = client.post("/api/v1/workorders/from-risk", json={"asset_id": "BOOST-PUMP-01"}).json()
    check("work order created from the creep risk", bool(wo.get("wo_id")), wo.get("wo_id", ""))

    # ── 5) RESTART MID-INCIDENT (warm start) ─────────────────────────────
    print("\n[attack 5] process restart mid-incident (same DB)")
    client2 = TestClient(create_app())       # fresh app, same ARVISX_DB
    time.sleep(1.0)
    for _ in range(3):                       # only 3 ticks — far below MIN_SAMPLES=20
        pub.publish_step(1.0)
        time.sleep(0.05)
        client2.get("/api/v1/community/overview")

    b2 = client2.get(f"/api/v1/commission/building/{bid}").json()
    check("commissioning state survives restart", b2.get("state") == "operational",
          f"state={b2.get('state')}")
    wos = client2.get("/api/v1/workorders").json()
    check("work orders survive restart",
          any(w["wo_id"] == wo.get("wo_id") for w in wos.get("work_orders", [])),
          f"{wos.get('count')} WOs")
    risks2 = client2.get("/api/v1/community/risks").json()["risks"]
    check("creep re-flagged within 3 ticks (warm baselines, no re-learning)",
          any("creep" in r["message"].lower() or "above its own normal" in r["message"].lower()
              for r in risks2 if r["asset_id"] == "BOOST-PUMP-01"))

    pub.close()
    failed = [n for n, ok in CHECKS if not ok]
    print("\n" + "═" * 70)
    print(f"  RESULT: {'PASS' if not failed else 'FAIL'} — {len(CHECKS) - len(failed)}/{len(CHECKS)} adversarial checks")
    for n in failed:
        print(f"    ❌ {n}")
    print("═" * 70)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
