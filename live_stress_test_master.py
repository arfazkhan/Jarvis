"""
ARVIS Interactive Pilot — Step-by-Step API Test
=================================================

Realistic pilot workflow:
  1. Initialize building equipment
  2. Start simulation via /demo/control (DemoOrchestrator)
  3. Let ARVIS learn (monitor for ~30s)
  4. Inject faults randomly while ARVIS is learning
  5. Watch ARVIS detect and respond
  6. Check advisories

NOTE: SSE stream is connected ONLY at the monitoring phase,
never alongside regular HTTP calls — uvicorn dev mode runs
a single worker, so an open SSE blocks all other requests.
"""

import asyncio
import httpx
import json
import random
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pilot_test")

BASE = "http://127.0.0.1:8000/api/v1"
TOKEN = "pilot_admin_token"
HDRS = {"X-ARVIS-KEY": TOKEN}


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

async def api(method: str, path: str, body=None, timeout=60.0):
    """Fire a single HTTP request and return (status, json)."""
    url = f"{BASE}{path}"
    async with httpx.AsyncClient(timeout=timeout) as c:
        if method == "GET":
            r = await c.get(url, headers=HDRS)
        else:
            r = await c.post(url, headers=HDRS, json=body or {})
    logger.info(f"{method} {path} -> {r.status_code}")
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:500]}


def pretty(label, status, body):
    icon = "✅" if status == 200 else "❌"
    print(f"\n{icon} {label} [{status}]")
    print(json.dumps(body, indent=2, default=str))


async def sse_monitor(duration=20):
    """Connect to SSE and print thoughts for a fixed duration."""
    url = f"{BASE}/stream/thoughts?token={TOKEN}"
    print(f"\n🔗 Connecting to SSE stream for {duration}s...")

    try:
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("GET", url) as resp:
                print(f"   SSE Connected (status {resp.status_code})")
                deadline = asyncio.get_event_loop().time() + duration
                evt = "message"

                async for line in resp.aiter_lines():
                    if asyncio.get_event_loop().time() > deadline:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        evt = line[6:].strip()
                    elif line.startswith("data:"):
                        raw = line[5:].strip()
                        ts = datetime.now().strftime("%H:%M:%S")
                        try:
                            d = json.loads(raw)
                            msg = d.get("content") or d.get("message") or json.dumps(d)
                            print(f"   🧠 [{evt}] {ts}  {msg}")
                        except Exception:
                            print(f"   🧠 [{evt}] {ts}  {raw}")
    except Exception as e:
        logger.error(f"SSE error: {e}")


# ──────────────────────────────────────────────────────────────
# FAULT LIBRARY
# ──────────────────────────────────────────────────────────────

FAULT_LIBRARY = [
    {
        "type": "EQUIPMENT_FAULT",
        "target": "CH-01",
        "parameter": "VIBRATION",
        "value": 5.8,           # dangerously high vibration
        "duration_hours": 2,
        "label": "Chiller-01 bearing degradation"
    },
    {
        "type": "EQUIPMENT_FAULT",
        "target": "AHU-02",
        "parameter": "SAT",
        "value": 36.0,          # supply air way too hot
        "duration_hours": 1,
        "label": "AHU-02 cooling coil failure"
    },
    {
        "type": "WEATHER_EVENT",
        "target": "BUILDING",
        "value": 52,            # extreme outdoor temp
        "duration_hours": 4,
        "label": "Heatwave 52°C"
    },
    {
        "type": "EQUIPMENT_FAULT",
        "target": "P-01",
        "parameter": "VIBRATION",
        "value": 4.2,
        "duration_hours": 1,
        "label": "Pump-01 impeller cavitation"
    },
    {
        "type": "VIP_OVERRIDE",
        "target": "Zone A, Floor 3",
        "value": 18,            # VIP wants 18°C
        "duration_hours": 2,
        "label": "VIP override: 18°C on Floor 3"
    },
]


# ──────────────────────────────────────────────────────────────
# MAIN SEQUENCE
# ──────────────────────────────────────────────────────────────

async def main():
    print("\n" + "=" * 72)
    print("  🏢  ARVIS INTERACTIVE PILOT — STEP-BY-STEP API TEST")
    print("=" * 72)

    # ── 1. Initialize Building ──────────────────────────────────
    print("\n━━━ STEP 1: Initialize Building Equipment ━━━")
    s, b = await api("POST", "/demo/initialize-building", {
        "building_id": "WEST-BAY-TOWER-01",
        "equipment": [
            {"id": "CH-01", "type": "CHILLER", "location": "Basement"},
            {"id": "CH-02", "type": "CHILLER", "location": "Basement"},
            {"id": "AHU-01", "type": "AHU", "location": "Floor 1"},
            {"id": "AHU-02", "type": "AHU", "location": "Floor 2"},
            {"id": "AHU-03", "type": "AHU", "location": "Floor 3"},
            {"id": "AHU-04", "type": "AHU", "location": "Floor 4"},
            {"id": "P-01", "type": "PUMP", "location": "Basement"},
            {"id": "CT-01", "type": "COOLING_TOWER", "location": "Roof"}
        ]
    })
    pretty("Building Initialized", s, b)
    if s != 200:
        print("⛔ Cannot proceed without building init. Exiting.")
        return
    await asyncio.sleep(1)

    # ── 1.5 Verify Equipment Details ─────────────────────────────
    print("\n━━━ STEP 1.5: Verify Realtime Equipment Status ━━━")
    s, b = await api("GET", "/demo/equipment/details")
    pretty("Equipment Details", s, b)
    await asyncio.sleep(1)


    # ── 2. Start Simulation (DemoOrchestrator) ──────────────────
    print("\n━━━ STEP 2: Start Simulation (speed=5000) ━━━")
    s, b = await api("POST", "/demo/control", {"action": "START", "speed": 5000})
    pretty("Simulation Started", s, b)
    if s != 200:
        print("⛔ Simulation failed to start. Exiting.")
        return

    # ── 3. Let ARVIS Learn (monitor status) ─────────────────────
    print("\n━━━ STEP 3: Learning Phase (30s) — ARVIS baselines the building ━━━")
    for i in range(6):
        await asyncio.sleep(5)
        s, b = await api("GET", "/demo/status")
        state = b.get("agent_state", "?")
        day = b.get("sim_day", "?")
        sim_t = b.get("sim_time", "?")
        print(f"   📡 [{i*5+5}s] State={state}  Day={day}  SimTime={sim_t}")

    # ── 4. Random Fault Injection ───────────────────────────────
    print("\n━━━ STEP 4: Injecting Random Faults ━━━")
    faults_to_inject = random.sample(FAULT_LIBRARY, min(3, len(FAULT_LIBRARY)))

    for fault in faults_to_inject:
        label = fault.pop("label", fault["type"])
        print(f"\n   ⚡ Injecting: {label}")
        s, b = await api("POST", "/sim/inject", fault)
        pretty(f"Fault: {label}", s, b)
        # Wait a bit between faults for ARVIS to react
        await asyncio.sleep(5)

    # ── 5. Let ARVIS React (15s) ────────────────────────────────
    print("\n━━━ STEP 5: Reaction Phase (15s) — ARVIS processes faults ━━━")
    for i in range(3):
        await asyncio.sleep(5)
        s, b = await api("GET", "/demo/status")
        state = b.get("agent_state", "?")
        pending = b.get("pending_advisories", 0)
        total = b.get("total_advisories", 0)
        print(f"   📡 [{i*5+5}s] State={state}  Pending={pending}  Total={total}")

    # ── 6. Check Advisories ─────────────────────────────────────
    print("\n━━━ STEP 6: Check Pending Advisories ━━━")
    s, b = await api("GET", "/demo/advisories/pending")
    pretty("Pending Advisories", s, b)

    # ── 7. Check Other Endpoints (Briefing, Fleet, Real Energy) ─
    print("\n━━━ STEP 7: Verify Compatibility Endpoints & Real Energy Data ━━━")
    s, b = await api("GET", "/briefing/morning")
    pretty("Morning Briefing", s, b)

    s, b = await api("GET", "/fleet/benchmark/DOHA-TOWER-001")
    pretty("Fleet Benchmark", s, b)

    print("\n  --- Energy & Sustainability Real Data ---")
    s, b = await api("GET", "/bms/energy/consumption/history?range=week")
    pretty("Energy History (7 Days)", s, b)
    
    s, b = await api("GET", "/bms/energy/sustainability")
    pretty("Sustainability & GSAS", s, b)
    
    s, b = await api("GET", "/bms/energy/distribution")
    pretty("Power Distribution", s, b)
    
    s, b = await api("GET", "/bms/energy/assets/critical")
    pretty("Critical Asset Telemetry", s, b)

    # ── 8. SSE Monitor (last step, blocks worker) ───────────────
    print("\n━━━ STEP 8: Live SSE Thought Stream (20s) ━━━")
    await sse_monitor(duration=20)

    # ── Done ────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  🏁  PILOT TEST COMPLETE")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted by user.")
