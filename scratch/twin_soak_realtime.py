"""
ArvisX REAL-TIME SOAK — no simulated time. The twin runs at 1:1 wall-clock, telemetry
at a realistic gateway cadence (every 20s), against a REAL uvicorn server over HTTP
(not TestClient), with the autonomous heartbeat on. This is the closest thing to a
deployment without hardware: real seconds, real network stack, real background loops.

Timeline (default 45 wall-clock minutes, ARVISX_SOAK_MINUTES to change):
  t+0       broker + uvicorn up, building commissioned → LEARNING
  t+0..12m  healthy telemetry @20s; baselines learn from real-time stream
  t+12m     data-driven readiness gate → OPERATIONAL (no timer, evidence only)
  t+14m     REAL-TIME DEGRADATION DRIP: booster power +0.4%/tick (bearing wear
            unfolding over real minutes) → must be caught vs its own learned normal
  t+18m     SENSOR DEATH: battery sensor stops publishing — only real elapsed time
            can expose this (stale detection = 900 real seconds of silence)
  t+end     verdict: gate honest, no false alarms while healthy, creep caught with
            first-detection latency, stale sensor caught, heartbeat ticked, alerts.

Run (foreground or background):  venv python scratch/twin_soak_realtime.py
Outputs: scratch/soak_timeline.jsonl (every probe) + scratch/SOAK_REPORT.md (verdict)
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

BROKER, BPORT = "127.0.0.1", 1886
API = "http://127.0.0.1:8096/api/v1"
SOAK_MIN = float(os.environ.get("ARVISX_SOAK_MINUTES", "45"))
CADENCE_S = float(os.environ.get("ARVISX_SOAK_CADENCE_S", "20"))
GATE_MIN = float(os.environ.get("ARVISX_SOAK_GATE_MIN", "12"))
DRIP_MIN = float(os.environ.get("ARVISX_SOAK_DRIP_MIN", "14"))
DROPOUT_MIN = float(os.environ.get("ARVISX_SOAK_DROPOUT_MIN", "18"))

os.environ["ARVISX_SOURCE"] = "mqtt"
os.environ["ARVISX_MQTT_BROKER"] = BROKER
os.environ["ARVISX_MQTT_PORT"] = str(BPORT)
os.environ["ARVISX_DB"] = str(Path(tempfile.mkdtemp(prefix="arvisx_soak_")) / "arvisx.db")
os.environ.pop("ARVISX_API_KEY", None)
os.environ["ARVIS_X_LLM"] = "0"
os.environ["ARVISX_HEARTBEAT"] = "1"
os.environ["ARVISX_HEARTBEAT_INTERVAL"] = "120"

TIMELINE = ROOT / "scratch" / "soak_timeline.jsonl"
REPORT = ROOT / "scratch" / "SOAK_REPORT.md"


def log_event(kind: str, **data):
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "t_min": round(EL() / 60, 1),
           "kind": kind, **data}
    with open(TIMELINE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{rec['t_min']:>5.1f}m] {kind} {data if data else ''}", flush=True)


T0 = time.monotonic()
EL = lambda: time.monotonic() - T0


def start_broker():
    from amqtt.broker import Broker
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cfg = {"listeners": {"default": {"type": "tcp", "bind": f"{BROKER}:{BPORT}"}},
           "sys_interval": 0, "auth": {"allow-anonymous": True}}

    async def _run():
        await Broker(cfg).start()
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())


def start_api():
    import uvicorn
    from arvisx.api import create_app
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=8096, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server.run()


def http(method: str, path: str, body=None):
    import urllib.request
    req = urllib.request.Request(API + path, method=method,
                                 headers={"Content-Type": "application/json"},
                                 data=(json.dumps(body).encode() if body is not None else None))
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def commission():
    bid = http("POST", "/commission/building", {"name": "Soak Towers"})["building_id"]
    http("POST", f"/commission/building/{bid}/services",
         {"services": ["water", "power_backup", "stp", "pool", "fire"]})
    http("POST", f"/commission/building/{bid}/transition", {"state": "assets"})
    for aid, typ in [("UG-TANK-01", "underground_tank"), ("OH-TANK-01", "overhead_tank"),
                     ("XFER-PUMP-01", "transfer_pump"), ("BOOST-PUMP-01", "booster_pump"),
                     ("GEN-01", "diesel_generator"), ("GEN-BATT-01", "generator_battery"),
                     ("STP-BLOWER-01", "stp_blower"), ("POOL-FILT-01", "pool_filtration_pump"),
                     ("FIRE-PUMP-01", "fire_pump")]:
        http("POST", f"/commission/building/{bid}/assets",
             {"asset": {"id": aid, "type": typ, "name": aid}})
    http("POST", f"/commission/building/{bid}/transition", {"state": "signals"})
    http("POST", f"/commission/building/{bid}/signals",
         {"source": "arvisx/BOOST-PUMP-01/power_kw", "asset_id": "BOOST-PUMP-01", "signal": "power_kw"})
    http("POST", f"/commission/building/{bid}/transition", {"state": "dependencies"})
    http("POST", f"/commission/building/{bid}/dependencies",
         {"service": "water", "nodes": [{"asset_id": "BOOST-PUMP-01", "role": "distribution"}]})
    http("POST", f"/commission/building/{bid}/transition", {"state": "learning"})
    return bid


def main():
    TIMELINE.write_text("")
    print("═" * 70)
    print(f"  ARVISX REAL-TIME SOAK — {SOAK_MIN:.0f} wall-clock minutes, cadence {CADENCE_S:.0f}s")
    print("═" * 70)

    threading.Thread(target=start_broker, daemon=True).start()
    time.sleep(2.5)
    threading.Thread(target=start_api, daemon=True).start()
    for _ in range(40):
        time.sleep(0.5)
        try:
            http("GET", "/community/overview")
            break
        except Exception:
            continue
    log_event("infra_up", broker=f"{BROKER}:{BPORT}", api=API)

    from arvisx.twin import CommunityTwin, TwinPublisher
    twin = CommunityTwin(start=datetime.now(), seed=42)
    twin.base_demand_lph = 2200.0      # keep the booster continuously loaded at 1:1
    pub = TwinPublisher(twin, BROKER, BPORT)

    bid = commission()
    log_event("commissioned", building=bid, state="learning")

    results = {"false_alarm_while_healthy": False, "gate": None, "first_creep_min": None,
               "stale_detected_min": None, "alerts": 0, "heartbeat_ticks": 0}
    dropout = drip = False
    last_step = time.monotonic()
    next_probe = 0.0

    while EL() < SOAK_MIN * 60:
        # ── publish at gateway cadence, twin physics at TRUE 1:1 ─────────
        now = time.monotonic()
        if now - last_step >= CADENCE_S:
            dt_hours = (now - last_step) / 3600.0
            last_step = now
            if EL() >= DRIP_MIN * 60:
                if not drip:
                    drip = True
                    log_event("fault_injected", fault="power creep drip +0.4%/tick (real-time)")
                twin.boost_creep_factor *= 1.004
            msgs = twin.step(dt_hours)
            if EL() >= DROPOUT_MIN * 60:
                if not dropout:
                    dropout = True
                    log_event("sensor_death", sensor="GEN-BATT-01/battery_voltage stops publishing")
                msgs = [(t, p) for t, p in msgs if "GEN-BATT-01" not in t]
            for t, p in msgs:
                pub.client.publish(t, p, qos=1)
            try:
                http("GET", "/community/overview")     # dashboard poll = learning tick
            except Exception as e:
                log_event("probe_error", error=str(e)[:80])

        # ── gate at GATE_MIN ─────────────────────────────────────────────
        if results["gate"] is None and EL() >= GATE_MIN * 60:
            rd = http("POST", f"/commission/building/{bid}/evaluate-readiness")
            results["gate"] = rd
            log_event("readiness_gate", approved=rd.get("approved"),
                      coverage=rd.get("coverage"), state=rd.get("state"))

        # ── probe every 60s ──────────────────────────────────────────────
        if EL() >= next_probe:
            next_probe = EL() + 60
            try:
                risks = http("GET", "/community/risks")["risks"]
                creep = [r for r in risks if r["asset_id"] == "BOOST-PUMP-01"
                         and ("creep" in r["message"].lower() or "normal" in r["message"].lower())]
                if creep and not drip:
                    results["false_alarm_while_healthy"] = True
                    log_event("FALSE_ALARM", risk=creep[0]["message"])
                if creep and drip and results["first_creep_min"] is None:
                    results["first_creep_min"] = round(EL() / 60, 1)
                    log_event("creep_detected", message=creep[0]["message"],
                              latency_min=round(EL() / 60 - DRIP_MIN, 1))
                sq = http("GET", "/signal-quality")
                stale = [s for s in sq.get("stale_signals", []) if s[0] == "GEN-BATT-01"]
                if stale and results["stale_detected_min"] is None:
                    results["stale_detected_min"] = round(EL() / 60, 1)
                    log_event("stale_sensor_detected", signal="GEN-BATT-01", age_s=stale[0][2])
                alerts = http("GET", "/whatsapp/alerts")
                results["alerts"] += alerts["count"]
                hb = http("GET", "/heartbeat/status")
                results["heartbeat_ticks"] = hb.get("ticks", 0)
                log_event("probe", risks=len(risks), creep=len(creep),
                          new_alerts=alerts["count"], hb_ticks=results["heartbeat_ticks"])
            except Exception as e:
                log_event("probe_error", error=str(e)[:100])
        time.sleep(1.0)

    pub.close()

    # ── verdict ──────────────────────────────────────────────────────────
    checks = [
        ("readiness gate approved on evidence", bool((results["gate"] or {}).get("approved"))),
        ("no false creep alarm while healthy", not results["false_alarm_while_healthy"]),
        ("real-time creep caught", results["first_creep_min"] is not None),
        ("dead sensor caught via real elapsed time", results["stale_detected_min"] is not None),
        ("autonomous heartbeat ticked", results["heartbeat_ticks"] > 0),
        ("alerts pushed", results["alerts"] > 0),
    ]
    passed = all(ok for _, ok in checks)
    lines = ["# ArvisX Real-Time Soak Report", "",
             f"- Duration: {SOAK_MIN:.0f} wall-clock minutes, telemetry every {CADENCE_S:.0f}s (true 1:1 physics)",
             f"- Gate: approved={(results['gate'] or {}).get('approved')} coverage={(results['gate'] or {}).get('coverage')} at t+{GATE_MIN:.0f}m",
             f"- Degradation drip from t+{DRIP_MIN:.0f}m → first detected t+{results['first_creep_min']}m "
             f"(latency {None if results['first_creep_min'] is None else round(results['first_creep_min'] - DRIP_MIN, 1)} real minutes)",
             f"- Sensor death at t+{DROPOUT_MIN:.0f}m → stale detected t+{results['stale_detected_min']}m",
             f"- Heartbeat ticks: {results['heartbeat_ticks']}, alerts pushed: {results['alerts']}", "", "## Checks"]
    lines += [f"- {'PASS' if ok else 'FAIL'} — {n}" for n, ok in checks]
    lines += ["", f"**RESULT: {'PASS' if passed else 'FAIL'}**"]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    log_event("soak_done", result="PASS" if passed else "FAIL",
              **{k: v for k, v in results.items() if k != "gate"})
    print(f"\nreport → {REPORT}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
