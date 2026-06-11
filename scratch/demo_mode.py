"""
ArvisX DEMO MODE — the 48-hour WhatsApp demo, one command.

Runs the full stack on your machine: in-process MQTT broker + the real ArvisX API
(uvicorn :8090, heartbeat on) + the digital twin publishing at TRUE 1:1 physics with
a realistic gateway cadence. The building is commissioned automatically, learns, and
the readiness gate arms it. Then the script follows a SCHEDULE:

  Act 1 (hour 0 → FAULT_AT)   healthy building. Your phone gets the daily digest,
                              answers questions, stays quiet. Anti-fatigue on display.
  Act 2 (hour FAULT_AT)       a degradation starts DEVELOPING in real time — booster
                              bearing wear, power creeping ~0.2%/minute. Within ~45
                              minutes ArvisX catches it vs the building's own learned
                              normal → your phone buzzes with the money-framed alert.
  Act 3                       you reply "create work order" — the loop closes.

Pair it with the WhatsApp bot (see scratch/DEMO_MODE_HOWTO.md) pointed at
http://127.0.0.1:8090 with YOUR number as owner.

Env knobs (defaults = the real 48h demo):
  DEMO_TOTAL_MIN   total runtime in minutes        (default 2880 = 48h)
  DEMO_FAULT_AT_MIN minute the degradation starts  (default 1800 = hour 30)
  DEMO_CADENCE_S   telemetry cadence seconds       (default 30)
  DEMO_API_PORT    API port                        (default 8090 — bot default)
  DEMO_MQTT_PORT   broker port                     (default 1887)

Run:  venv\\Scripts\\python -u scratch\\demo_mode.py
Stop: Ctrl+C (state persists in the demo DB; restarting resumes warm).
"""
import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TOTAL_MIN = float(os.environ.get("DEMO_TOTAL_MIN", "2880"))
FAULT_AT_MIN = float(os.environ.get("DEMO_FAULT_AT_MIN", "1800"))
CADENCE_S = float(os.environ.get("DEMO_CADENCE_S", "30"))
CREEP_PCT_PER_MIN = float(os.environ.get("DEMO_CREEP_PCT_PER_MIN", "0.2"))
API_PORT = int(os.environ.get("DEMO_API_PORT", "8090"))
MQTT_PORT = int(os.environ.get("DEMO_MQTT_PORT", "1887"))
BROKER = "127.0.0.1"
API = f"http://127.0.0.1:{API_PORT}/api/v1"

os.environ["ARVISX_SOURCE"] = "mqtt"
os.environ["ARVISX_MQTT_BROKER"] = BROKER
os.environ["ARVISX_MQTT_PORT"] = str(MQTT_PORT)
os.environ.setdefault("ARVISX_DB", str(ROOT / "scratch" / "demo_mode.db"))
os.environ.pop("ARVISX_API_KEY", None)          # local demo: open API for the bot
os.environ["ARVIS_X_LLM"] = os.environ.get("ARVIS_X_LLM", "0")
os.environ["ARVISX_HEARTBEAT"] = "1"
os.environ.setdefault("ARVISX_HEARTBEAT_INTERVAL", "300")

LOG = ROOT / "scratch" / "demo_timeline.jsonl"
T0 = time.monotonic()
EL_MIN = lambda: (time.monotonic() - T0) / 60.0


def log(kind, **data):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"),
           "t_min": round(EL_MIN(), 1), "kind": kind, **data}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{rec['t_min']:>7.1f}m] {kind} {data if data else ''}", flush=True)


def start_broker():
    from amqtt.broker import Broker
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"{BROKER}:{MQTT_PORT}"}},
           "sys_interval": 0, "auth": {"allow-anonymous": True}}

    async def _run():
        await Broker(cfg).start()
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())


def start_api():
    import uvicorn
    from arvisx.api import create_app
    config = uvicorn.Config(create_app(), host="0.0.0.0", port=API_PORT, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()


def http(method, path, body=None):
    import urllib.request
    req = urllib.request.Request(API + path, method=method,
                                 headers={"Content-Type": "application/json"},
                                 data=(json.dumps(body).encode() if body is not None else None))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def commission_if_needed():
    existing = http("GET", "/commission/buildings").get("buildings", [])
    if existing:                                    # warm restart — keep the building
        b = existing[0]
        log("building_resumed", building=b["building_id"], state=b["state"])
        return b["building_id"]
    bid = http("POST", "/commission/building", {"name": "Demo Towers"})["building_id"]
    http("POST", f"/commission/building/{bid}/services",
         {"services": ["water", "power_backup", "stp", "pool", "fire", "gas"]})
    http("POST", f"/commission/building/{bid}/transition", {"state": "assets"})
    for aid, typ in [("UG-TANK-01", "underground_tank"), ("OH-TANK-01", "overhead_tank"),
                     ("XFER-PUMP-01", "transfer_pump"), ("BOOST-PUMP-01", "booster_pump"),
                     ("GEN-01", "diesel_generator"), ("GEN-BATT-01", "generator_battery"),
                     ("STP-BLOWER-01", "stp_blower"), ("POOL-FILT-01", "pool_filtration_pump"),
                     ("FIRE-PUMP-01", "fire_pump"), ("GAS-PLANT-01", "gas_plant")]:
        http("POST", f"/commission/building/{bid}/assets",
             {"asset": {"id": aid, "type": typ, "name": aid}})
    http("POST", f"/commission/building/{bid}/transition", {"state": "signals"})
    http("POST", f"/commission/building/{bid}/signals",
         {"source": "arvisx/BOOST-PUMP-01/power_kw", "asset_id": "BOOST-PUMP-01", "signal": "power_kw"})
    http("POST", f"/commission/building/{bid}/transition", {"state": "dependencies"})
    http("POST", f"/commission/building/{bid}/dependencies",
         {"service": "water", "nodes": [{"asset_id": "BOOST-PUMP-01", "role": "distribution"}]})
    http("POST", f"/commission/building/{bid}/transition", {"state": "learning"})
    log("building_commissioned", building=bid, state="learning")
    return bid


def main():
    LOG.write_text("")
    print("═" * 70)
    print(f"  ARVISX DEMO MODE — {TOTAL_MIN/60:.0f}h run · incident at hour {FAULT_AT_MIN/60:.0f} "
          f"· telemetry every {CADENCE_S:.0f}s (1:1 physics)")
    print(f"  API for the bot: http://127.0.0.1:{API_PORT}  (see DEMO_MODE_HOWTO.md)")
    print("═" * 70)

    threading.Thread(target=start_broker, daemon=True).start()
    time.sleep(2.5)
    threading.Thread(target=start_api, daemon=True).start()
    for _ in range(60):
        time.sleep(0.5)
        try:
            http("GET", "/community/overview")
            break
        except Exception:
            continue
    log("infra_up", api=API, broker=f"{BROKER}:{MQTT_PORT}")

    from arvisx.twin import CommunityTwin, TwinPublisher
    twin = CommunityTwin(start=datetime.now(), seed=99)   # sim clock = wall clock (true 1:1)
    twin.base_demand_lph = 2200.0                          # keep the booster continuously loaded
    pub = TwinPublisher(twin, BROKER, MQTT_PORT)
    bid = commission_if_needed()

    operational = False
    fault_started = False
    alert_seen = False
    last_step = time.monotonic() - CADENCE_S
    next_gate_try = 0.0
    next_probe = 0.0

    try:
        while EL_MIN() < TOTAL_MIN:
            now = time.monotonic()

            if now - last_step >= CADENCE_S:
                dt_hours = (now - last_step) / 3600.0
                last_step = now
                if EL_MIN() >= FAULT_AT_MIN:
                    if not fault_started:
                        fault_started = True
                        log("ACT_2", event="degradation begins — booster bearing wear (develops in real time)")
                    twin.boost_creep_factor *= (1 + CREEP_PCT_PER_MIN / 100.0) ** (CADENCE_S / 60.0)
                for t, p in twin.step(dt_hours):
                    pub.client.publish(t, p, qos=1)
                try:
                    http("GET", "/community/overview")     # learning/report tick
                except Exception:
                    pass

            # While learning: try the readiness gate every 2 minutes until approved.
            if not operational and EL_MIN() >= next_gate_try:
                next_gate_try = EL_MIN() + 2
                try:
                    rd = http("POST", f"/commission/building/{bid}/evaluate-readiness")
                    if rd.get("approved"):
                        operational = True
                        log("OPERATIONAL", coverage=rd.get("coverage"),
                            note="gate approved on evidence — alerts armed, digest live")
                except Exception:
                    pass

            # Probe every 5 minutes: surface what the phone is about to experience.
            if EL_MIN() >= next_probe:
                next_probe = EL_MIN() + 5
                try:
                    risks = http("GET", "/community/risks")["risks"]
                    creep = [r for r in risks if r["asset_id"] == "BOOST-PUMP-01"
                             and ("creep" in r["message"].lower() or "normal" in r["message"].lower())]
                    if creep and not alert_seen:
                        alert_seen = True
                        log("INCIDENT_CAUGHT", message=creep[0]["message"],
                            minutes_after_onset=round(EL_MIN() - FAULT_AT_MIN, 1))
                    log("pulse", risks=len(risks), creep=len(creep),
                        operational=operational, fault=fault_started)
                except Exception as e:
                    log("probe_error", error=str(e)[:80])

            time.sleep(1.0)
    except KeyboardInterrupt:
        log("stopped_by_user")
    finally:
        pub.close()
        log("demo_done", operational=operational, fault_started=fault_started,
            incident_caught=alert_seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
