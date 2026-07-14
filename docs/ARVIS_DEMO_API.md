# ARVIS Demo Capabilities API

**Version:** 1.0  
**Base Path:** `/api/v1/demo`  
**Streaming Path:** `/api/v1/stream`  
**Target Audience:** Frontend engineers, integrators, and demo operators building on the ARVIS operational cognition platform.

---

## 1. What is ARVIS?

### Core Positioning

**ARVIS (Autonomous Reasoning for Vast Infrastructure Systems)** is not a dashboard, an analytics layer, or an autonomous building controller.

ARVIS is **operational intelligence infrastructure for commercial buildings**.

It sits above existing Building Management Systems (BMS) such as Siemens Desigo CC, Honeywell Forge, Schneider EcoStruxure, or legacy SCADA environments, and continuously reasons over infrastructure behavior in real time.

Instead of only showing telemetry, alarms, or dashboards, ARVIS interprets *why* infrastructure behavior is happening, what systems are involved, what operational or financial impact it may create, and what actions operators should take.

The platform operates in a **secure read-only deployment mode** and does not directly control equipment. Its role is **operational cognition**.

Existing systems monitor. ARVIS understands.

---

### Real-World Deployment Target

ARVIS is designed for high-stakes commercial buildings — the reference deployment is **Marina Heights Tower** (West Bay, Doha, Qatar): a 32-floor mixed-use tower with 78,000 m², 4× 800-ton Carrier chillers, 142 air handling units (AHUs), and 4 cooling towers. Operating in Qatar means peak ambient temperatures of 47–51°C, humidity above 75% routinely, and chiller plants running at 85–95% load through summer.

---

### What ARVIS Actually Does

Modern commercial buildings generate massive volumes of telemetry:
* HVAC readings
* Occupancy signals
* Chiller plant metrics
* Energy consumption
* Alarm cascades
* Sensor drift
* Equipment health indicators
* Environmental compliance metrics

But traditional BMS platforms fundamentally stop at monitoring. They expose raw data; they do not explain infrastructure behavior. As buildings become larger and more interconnected, this creates a growing operational gap:
* **Alarm floods** bury critical failures in noise.
* **Ghost energy waste** goes unnoticed for months.
* **Root causes** remain hidden behind long symptom chains.
* **Institutional knowledge** disappears during staff turnover.
* **Manual sustainability reporting** becomes operationally impossible at scale.

ARVIS was built to close that gap. The platform continuously observes infrastructure telemetry, groups correlated events, traces causal chains across systems, applies infrastructure-specific reasoning models, and generates operator-facing advisories with evidence-backed explanations.

ARVIS does not replace BMS infrastructure. It makes existing infrastructure operationally intelligible.

---

### The ARVIS Intelligence Model

At the core of ARVIS is a **multi-agent operational reasoning architecture**. Specialized infrastructure agents collaborate across:
* Alarm interpretation
* Equipment diagnostics
* Energy analysis
* Maintenance reasoning
* Comfort optimization
* Compliance validation
* Institutional memory retrieval
* Operational planning

Each agent evaluates infrastructure behavior from a different operational perspective. Their outputs are verified through BFT (Byzantine Fault-Tolerant) consensus and multi-gate evidence validation systems (including H4 Faithfulness, H2 Claim Verification, and H6 Physics validation) before recommendations are surfaced to operators.

This allows ARVIS to:
* Collapse hundreds of alarms into a single root cause.
* Detect operational drift invisible to threshold-based monitoring.
* Explain causal relationships between infrastructure systems.
* Preserve operational knowledge as persistent software memory (Skillbook).
* Generate actionable recommendations instead of raw telemetry.

The system is designed for high-consequence infrastructure environments where reliability, explainability, and operational trust are critical.

---

### Why Qatar Matters

ARVIS is being developed with **Qatar** as its primary operational environment. Qatar represents one of the most infrastructure-intensive climates globally:
* Extreme cooling loads (peak ambient temperatures of 47–51°C, humidity above 75% routinely).
* Continuous HVAC dependency.
* Rapidly expanding commercial infrastructure.
* Growing sustainability mandates and increasing operational complexity across smart buildings.

The region is also entering a structural transition toward AI-assisted infrastructure operations with:
* **GSAS (Global Sustainability Assessment System)** becoming the GCC-wide sustainability benchmark.
* **GSO 3000:2025** standardization.
* **ESG disclosure mandates** expanding across regulated entities.
* Increasing focus on **sovereign and localized AI infrastructure**.

Buildings can no longer rely solely on human interpretation of fragmented telemetry. Infrastructure must become operationally self-explanatory. ARVIS is being designed specifically for this transition.

---

### Deployment Philosophy

ARVIS is intentionally designed as a **non-invasive infrastructure layer**. The platform:
* Connects to existing BMS ecosystems.
* Operates strictly in **read-only mode**.
* Requires **no equipment replacement** and introduces **zero additional hardware dependency**.
* Integrates across heterogeneous vendor environments.
* Supports **sovereign and air-gapped deployment environments** to meet enterprise security constraints.

This enables rapid adoption inside commercial towers, airports, government facilities, industrial infrastructure, and other mission-critical operational environments without requiring operators to redesign existing building systems.

---

### Why This Matters for the Frontend

The frontend is not simply visualizing telemetry. **It is exposing the reasoning process of an operational intelligence system.**

Trust is a core requirement in high-consequence building operations. The interface must make the system’s reasoning transparent rather than behaving like a conventional dashboard. Operators must be able to investigate:
* What ARVIS observed.
* Which systems and agents were involved in the reasoning.
* What evidence was cited and validated.
* How causal relationships were identified.
* Why specific recommendations were generated.
* How confident the system is in its conclusions.

ARVIS is designed to function more like an **infrastructure investigation engine** than a monitoring console.

---

## 2. What This API Provides

The **Demo Capabilities API** exposes ARVIS's reasoning brain against a **simulated building body**. Real cognitive logic (agents, BFT consensus, verification gates) drives a controlled physics simulation (telemetry, alarms, equipment behavior). This lets you demonstrate ARVIS's full operational cognition capabilities without needing live BMS hardware.

Five capability groups, 14 endpoints, plus SSE streaming:

| Group | Purpose | Endpoint Count |
|---|---|---|
| Live Building Telemetry | Read current building state | 4 |
| Baseline Calibration | Seed normal-operation baselines | 2 |
| Fault Injection | Inject curated incident scenarios | 3 |
| Swarm Reasoning | Query the multi-agent brain | 2 |
| Explainability + Brain | Causal chains, confidence, meta-state | 3 |
| **SSE Streams** | Push events (telemetry, swarm activity) | 3 streams |

---

## 3. Architectural Model

```
┌─────────────────────────────────────────────────────────────────┐
│                          FRONTEND                                │
│  (your work — React, Vue, Svelte, anything that speaks HTTP+SSE)│
└──────────────────┬──────────────────────────────┬───────────────┘
                   │ REST                         │ SSE
                   │ JSON                         │ event-stream
                   ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              ARVIS DEMO API  (FastAPI, /api/v1)                 │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  REST Routes   │  │  SSE         │  │  Demo            │   │
│  │  (14 endpts)   │  │  Broadcaster │  │  Orchestrator    │   │
│  │  routes_demo.py│  │  (singleton) │  │  (sim driver)    │   │
│  └────────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
└───────────┼─────────────────┼───────────────────┼─────────────┘
            │                 │                   │
            ▼                 ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│  BMSStateEngine │  │  LLM Agent      │  │  Multi-Agent     │
│  (sim physics)  │  │  (chat brain)   │  │  Swarm + BFT     │
│  - 12k points   │  │  - intent class │  │  - 13 agents     │
│  - 18 equipment │  │  - depth plan   │  │  - H2/H4/H6      │
│  - alarms       │  │  - synthesis    │  │  - skillbook     │
└─────────────────┘  └─────────────────┘  └──────────────────┘
```

**Key insight:** the **cognitive layer is real** (production agent code, real BFT consensus, real H4/H2/H6 verification). The **physical layer is simulated** — building telemetry comes from a deterministic physics model, not live BACnet.

---

## 4. Glossary

| Term | Definition |
|---|---|
| **BMS** | Building Management System — software that controls HVAC, lighting, etc. (Siemens Desigo CC, Schneider, Honeywell) |
| **AHU** | Air Handling Unit — moves conditioned air through ductwork to occupied zones |
| **Chiller** | Large refrigeration machine that produces chilled water for cooling |
| **Cooling Tower** | Rooftop heat-rejection equipment paired with chillers |
| **VAV** | Variable Air Volume box — terminal device that throttles airflow per zone |
| **CHW / CHWST / CHWRT** | Chilled water / supply temp / return temp |
| **SAT / MAT / RAT** | Supply / Mixed / Return air temperature on an AHU |
| **COP** | Coefficient of Performance — chiller efficiency metric (kW cooling per kW electric) |
| **TR / RT** | Ton of Refrigeration — cooling capacity unit (1 TR ≈ 3.517 kW thermal) |
| **PLR** | Part-Load Ratio — current load divided by rated capacity |
| **Skillbook** | Persistent memory store of learned operational patterns and institutional knowledge |
| **Swarm** | Collection of specialized AI agents that collaborate on each query |
| **BFT Consensus** | Byzantine Fault-Tolerant agreement protocol — multiple agents must affirm a recommendation |
| **H4 Faithfulness** | Verification gate that checks output claims against cited evidence |
| **H2 Claim Verify** | Per-claim grounding check |
| **H6 Physics** | Thermodynamic sanity check (e.g., COP cannot exceed Carnot limit) |
| **GSAS** | Global Sustainability Assessment System — Qatar green-building rating framework |
| **Advisory** | A single completed reasoning output from the swarm (has ID, evidence, confidence) |
| **Evidence ID** | Unique identifier for a piece of cited data (sensor reading, alarm, tool result) |
| **Source Point ID** | BMS point that originated an alarm; empty = inference-based (phantom risk) |

---

## 5. Authentication

### Setup

The API expects an environment variable:

```bash
ARVIS_AUTH_SECRET=<your-secret>
```

If unset, the server generates an ephemeral secret at startup and logs a warning:

```
ARVIS_AUTH_SECRET not set — generated ephemeral secret.
Tokens will be invalidated on restart.
```

### Token Flow

> **Note:** Token issuance flow may use a separate `/auth/login` or `/api/v1/auth/token` endpoint depending on deployment. Check `/docs` (Swagger UI) on your running instance to confirm the exact route. For demo mode against `localhost`, many deployments allow unauthenticated access to `/api/v1/demo/*` — verify with:

```bash
curl http://127.0.0.1:8000/api/v1/demo/scenario/list
```

If you get a 401, you'll need a Bearer token in subsequent requests:

```http
GET /api/v1/demo/building/overview
Authorization: Bearer <token>
```

---

## 6. Running the API Locally

### Prerequisites

- Python 3.12+
- Bedrock credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION=us-east-1`) — ARVIS uses Anthropic/Minimax/Moonshot models via Amazon Bedrock
- ~16 GB RAM (swarm runs multiple LLMs concurrently)

### Install

```bash
cd E:/Automation
pip install -r requirements.txt
```

### Run (Development)

```bash
# PowerShell
cd E:/Automation
$env:ARVIS_AUTH_SECRET="dev-secret-change-me"
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --log-level info
```

```bash
# Bash / WSL
cd /mnt/e/Automation
export ARVIS_AUTH_SECRET="dev-secret-change-me"
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload --log-level info
```

### Verify

| Check | Command | Expected |
|---|---|---|
| Server up | Open `http://127.0.0.1:8000/docs` | Swagger UI loads |
| Demo router live | `curl http://127.0.0.1:8000/api/v1/demo/scenario/list` | 5 scenarios JSON |
| SSE live | `curl -N http://127.0.0.1:8000/api/v1/stream/monitor` | Open connection, events trickle |
| OpenAPI schema | `curl http://127.0.0.1:8000/openapi.json` | Full schema JSON |

### Production Notes

- **Do not use `--workers > 1` with SSE.** The `SSEBroadcaster` is a singleton; multiple workers means events broadcast in worker A never reach subscribers on worker B. Either run single-worker behind a reverse proxy, or migrate broadcaster to Redis pub/sub.
- **CORS.** If frontend runs on a different origin (e.g. `localhost:5173` for Vite, `localhost:3000` for Next.js), add CORS middleware to `api/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 7. Endpoint Reference

### Group 1: Live Building Telemetry

Read-only snapshots of the simulated building.

---

#### `GET /api/v1/demo/building/overview`

Building-wide health and load summary. Lightweight — safe to poll every 5 seconds.

**Response:**

```json
{
  "building_name": "Marina Heights",
  "timestamp": "2026-05-26T22:30:00Z",
  "equipment_count": 18,
  "equipment_by_type": {
    "chiller": 4,
    "ahu": 8,
    "pump": 4,
    "cooling_tower": 2
  },
  "active_alarms": 3,
  "total_power_kw": 1842.5,
  "outdoor_temp_c": 44.2,
  "calibration_status": "complete"
}
```

**Field notes:**
- `calibration_status`: `"not_started"`, `"running"`, `"complete"` — UI should block advanced features until `"complete"`.
- `active_alarms`: count of currently unacknowledged alarms.

---

#### `GET /api/v1/demo/building/equipment/{equipment_id}`

Per-equipment live points snapshot.

**Path Param:** `equipment_id` — e.g. `chiller_01`, `ahu_07`, `pump_03`, `ct_01`. Full ID list in `/building/topology` response.

**Response (chiller example):**

```json
{
  "equipment_id": "chiller_01",
  "type": "chiller",
  "name": "Chiller 01 (800TR)",
  "location": "Basement, Plant Room",
  "status": "running",
  "points": {
    "load_pct": 78.3,
    "kw": 425.1,
    "chwst_c": 6.4,
    "chwrt_c": 11.2,
    "cop": 5.67,
    "vib_rms_mm_s": 0.83,
    "cond_temp_c": 33.05
  },
  "last_updated": "2026-05-26T22:30:00Z"
}
```

**Response (AHU example):**

```json
{
  "equipment_id": "ahu_07",
  "type": "ahu",
  "name": "AHU Floor 12 (Mechanical)",
  "location": "Floor 12, Zone A",
  "status": "running",
  "points": {
    "sat_c": 16.4,
    "mat_c": 25.9,
    "rat_c": 24.1,
    "sf_spd_pct": 76.0,
    "rf_spd_pct": 71.5,
    "chw_valve_pct": 58.2,
    "flt_dp_pa": 145.0,
    "kw": 12.8
  }
}
```

**Errors:** `404` if equipment ID unknown.

---

#### `GET /api/v1/demo/building/alarms`

Active alarm queue. Prefer SSE `swarm_event` channel for push updates, fall back to 3-second polling.

**Response:**

```json
{
  "count": 2,
  "alarms": [
    {
      "alarm_id": "6af984bb-e733-49f2-acfe-3c2c2bf5eb12",
      "equipment_id": "ahu_07",
      "severity": "high",
      "message": "MAT rising above threshold",
      "triggered_at": "2026-05-26T22:25:00Z",
      "duration_min": 5.2,
      "source_point_id": "ahu_07/MAT",
      "status": "active"
    }
  ]
}
```

**Field notes:**
- `severity`: `"low"`, `"medium"`, `"high"`, `"critical"`
- `source_point_id`: **empty string = inference-generated phantom alarm.** Surface a warning badge in UI — these are unverified.
- `status`: `"active"`, `"acknowledged"`, `"cleared"`

---

#### `GET /api/v1/demo/building/topology`

Spatial layout for floor-plan rendering. Static after server start — cache on frontend after first load.

**Response:**

```json
{
  "floors": 32,
  "total_area_m2": 78000,
  "equipment": [
    {"id": "chiller_01", "type": "chiller", "name": "Chiller 01 (800TR)", "location": "Basement, Plant Room"},
    {"id": "chiller_02", "type": "chiller", "name": "Chiller 02 (800TR)", "location": "Basement, Plant Room"},
    {"id": "chiller_03", "type": "chiller", "name": "Chiller 03 (800TR)", "location": "Basement, Plant Room"},
    {"id": "chiller_04", "type": "chiller", "name": "Chiller 04 (800TR)", "location": "Basement, Plant Room"},
    {"id": "ahu_01", "type": "ahu", "name": "AHU Floor 1 (Lobby)", "location": "Floor 1, Zone A"},
    {"id": "ahu_02", "type": "ahu", "name": "AHU Floor 2 (Retail)", "location": "Floor 2, Zone A"},
    {"id": "ahu_07", "type": "ahu", "name": "AHU Floor 12 (Mechanical)", "location": "Floor 12, Zone A"},
    {"id": "ahu_08", "type": "ahu", "name": "AHU Floor 19 (Executive)", "location": "Floor 19, Zone A"},
    {"id": "pump_01", "type": "pump", "name": "Primary Chilled Water Pump 1", "location": "Basement, Plant Room"},
    {"id": "ct_01", "type": "cooling_tower", "name": "Cooling Tower 1", "location": "Roof, North Wing"}
  ]
}
```

---

### Group 2: Baseline Calibration

Before fault injection means anything, ARVIS needs ~30 simulated days of "normal" telemetry to learn what normal looks like. Calibration runs the simulator at 100× wall-clock speed.

---

#### `POST /api/v1/demo/calibrate/start`

Triggers calibration. Idempotent — re-calling while already running returns the existing run.

**Body:** `{}` (no parameters)

**Response:**

```json
{
  "calibration_id": "cal_1779812308",
  "status": "running",
  "started_at": "2026-05-26T22:30:00Z",
  "estimated_completion_sec": 8
}
```

---

#### `GET /api/v1/demo/calibrate/status`

Poll until `status: "complete"`. SSE `system` channel also broadcasts progress.

**Response:**

```json
{
  "calibration_id": "cal_1779812308",
  "status": "complete",
  "progress_pct": 100,
  "baselines_seeded": 12386,
  "duration_sec": 7.4,
  "completed_at": "2026-05-26T22:30:08Z"
}
```

---

### Group 3: Fault Injection (Scenarios)

Five curated incident scenarios. Pick one, inject, watch the swarm react.

---

#### `GET /api/v1/demo/scenario/list`

All available scenarios.

**Response:**

```json
{
  "scenarios": [
    {
      "id": "chiller_vibration",
      "name": "Chiller Bearing Degradation",
      "description": "Progressive vibration rise on chiller_02 over 30 minutes, mimicking bearing wear.",
      "target_equipment": ["chiller_02"],
      "expected_alerts": ["vibration_anomaly", "bearing_wear_predicted"]
    },
    {
      "id": "ahu_temp_drift",
      "name": "AHU Mixed-Air Temperature Drift",
      "description": "Outdoor air damper actuator slip on ahu_07 — MAT rises 4°C above expected.",
      "target_equipment": ["ahu_07"],
      "expected_alerts": ["mat_offset", "damper_fault", "sat_deviation"]
    },
    {
      "id": "ghost_operation",
      "name": "Ghost Operation — Off-Hours Cooling",
      "description": "AHU continues running after schedule end. Energy waste, no occupants.",
      "target_equipment": ["ahu_03"],
      "expected_alerts": ["schedule_violation", "energy_waste"]
    },
    {
      "id": "sensor_corruption",
      "name": "Sensor Reading Corruption",
      "description": "Temperature sensor on chiller_01 returns implausible values (e.g. -50°C or 150°C).",
      "target_equipment": ["chiller_01"],
      "expected_alerts": ["sensor_fault", "data_integrity_warning"]
    },
    {
      "id": "extreme_ambient_surge",
      "name": "Extreme Doha Summer Surge",
      "description": "Outdoor temperature surges to 51.5°C, stressing the chiller plant near capacity.",
      "target_equipment": ["chiller_01", "chiller_02", "chiller_03", "chiller_04"],
      "expected_alerts": ["staging_overload", "capacity_warning", "high_ambient"]
    }
  ]
}
```

---

#### `POST /api/v1/demo/scenario/inject`

Inject a scenario into the running simulation.

**Body:**

```json
{
  "scenario_id": "chiller_vibration",
  "duration_minutes": 30,
  "intensity": 1.0
}
```

**Field notes:**
- `duration_minutes`: how long the fault persists in simulated time
- `intensity`: 0.5 (mild) to 2.0 (extreme); default 1.0

**Response:**

```json
{
  "injection_id": "inj_a1b2c3",
  "scenario_id": "chiller_vibration",
  "status": "active",
  "started_at": "2026-05-26T22:30:00Z",
  "expires_at": "2026-05-26T23:00:00Z"
}
```

**Errors:**
- `404`: scenario_id unknown
- `409`: scenario already active for same equipment

---

#### `GET /api/v1/demo/scenario/active`

Currently-running injections.

**Response:**

```json
{
  "active_count": 1,
  "injections": [
    {
      "injection_id": "inj_a1b2c3",
      "scenario_id": "chiller_vibration",
      "started_at": "2026-05-26T22:30:00Z",
      "elapsed_sec": 145,
      "remaining_sec": 1655,
      "intensity": 1.0
    }
  ]
}
```

---

### Group 4: Swarm Reasoning

This is the centerpiece. Send a query, get back a fully-verified advisory built by a swarm of agents.

---

#### `POST /api/v1/demo/reasoning/trigger`

Run the multi-agent swarm against a natural-language query.

**Body:**

```json
{
  "query": "What's wrong with chiller_02?",
  "context": {
    "equipment_focus": "chiller_02",
    "user_role": "facilities_manager"
  }
}
```

**Latency expectation:** 30–180 seconds. The swarm runs ~5–10 LLM calls in parallel + verification gates. Show a spinner + agent activity stream (subscribe to SSE `swarm_event` channel for live progress).

**Response:**

```json
{
  "advisory_id": "adv_4a97b9f5-b97",
  "query": "What's wrong with chiller_02?",
  "response": "CH-02 vibration elevated at 1.42 mm/s, ~64% above peer baseline (CH-01: 0.83, CH-03: 0.85). VIB_RMS reading is stale (last updated 4+ days ago) — likely sensor communication failure rather than mechanical fault. Recommend verifying VIB_RMS point in BMS before dispatching technician. Confidence: Medium.",
  "confidence": "medium",
  "agents_consulted": ["Alarm_Agent", "Maintenance_Agent", "Memory_Agent"],
  "evidence_count": 17,
  "verification": {
    "h4_passed": true,
    "h2_passed": true,
    "h6_physics_passed": true,
    "contradictions_corrected": 2,
    "claims_stripped": 4
  },
  "elapsed_sec": 87.4,
  "timestamp": "2026-05-26T22:31:27Z"
}
```

**Field notes:**
- `confidence`: `"high"`, `"medium"`, `"low"` — render as colored badge
- `verification.contradictions_corrected`: how many self-corrections the H4 gate forced — surface as a transparency indicator
- `verification.claims_stripped`: count of fabricated numerics the system removed before output

---

#### `GET /api/v1/demo/reasoning/latest`

Last completed advisory. Same response shape as `/trigger`.

---

### Group 5: Causal Explainability + Brain Dashboard

---

#### `GET /api/v1/demo/advisories/history`

Recent advisories list.

**Response:**

```json
{
  "count": 12,
  "advisories": [
    {
      "advisory_id": "adv_4a97b9f5",
      "query": "What's wrong with chiller_02?",
      "timestamp": "2026-05-26T22:31:27Z",
      "confidence": "medium",
      "elapsed_sec": 87.4
    }
  ]
}
```

---

#### `GET /api/v1/demo/explain/advisory/{advisory_id}`

Full reasoning chain for a single advisory. Use this for the "Why did ARVIS say this?" drawer in the UI.

**Response:**

```json
{
  "advisory_id": "adv_4a97b9f5",
  "query": "What's wrong with chiller_02?",
  "reasoning_chain": [
    {
      "step": 1,
      "agent": "Alarm_Agent",
      "action": "get_active_alarms",
      "tool_call": {"equipment_id": "chiller_02"},
      "result": "No active alarms on CH-02",
      "confidence": 0.9,
      "elapsed_ms": 1240
    },
    {
      "step": 2,
      "agent": "Maintenance_Agent",
      "action": "get_equipment_health",
      "tool_call": {"equipment_id": "chiller_02"},
      "result": "VIB_RMS = 1.42 mm/s, OIL_TEMP = 42°C, last update 4d stale",
      "confidence": 0.7,
      "elapsed_ms": 980
    },
    {
      "step": 3,
      "agent": "Memory_Agent",
      "action": "find_similar_skills",
      "tool_call": {"pattern": "vibration_elevated"},
      "result": "Matched 2 prior skills: bearing_wear_pattern (0.82), sensor_drift_pattern (0.71)",
      "confidence": 0.75,
      "elapsed_ms": 2100
    }
  ],
  "peer_votes": [
    {
      "agent": "Alarm_Agent",
      "vote": "affirm",
      "rationale": "Vibration delta matches stale-sensor pattern more than mechanical wear"
    },
    {
      "agent": "Maintenance_Agent",
      "vote": "affirm_with_caveat",
      "rationale": "Recommend physical verification before discounting bearing wear entirely"
    }
  ],
  "evidence_citations": [
    {
      "evidence_id": "ev_bd0a12f3",
      "source": "live_bms",
      "point": "chiller_02/VIB_RMS",
      "value": 1.4268,
      "timestamp": "2026-05-22T18:45:00Z",
      "staleness_min": 5800
    }
  ],
  "verification_log": {
    "h4_failures": [
      {
        "iteration": 1,
        "claim": "CH-02 bearing degradation confirmed",
        "reason": "Not supported by evidence; staleness suggests sensor fault",
        "correction_applied": true
      }
    ]
  },
  "financial_overhead": {
    "tokens_used": 24500,
    "estimated_cost_usd": 0.18,
    "wall_time_sec": 87.4
  }
}
```

---

#### `GET /api/v1/demo/intelligence/summary`

The "Brain Dashboard" — system-level meta-cognition state. Poll every 10 seconds.

**Response:**

```json
{
  "metacognition": {
    "safety_threshold_pct": 95.2,
    "uncertainty_floor": 0.15,
    "abstention_rate_pct": 8.1,
    "active_skills_count": 24
  },
  "trust_scores": {
    "Alarm_Agent": 0.87,
    "Maintenance_Agent": 0.91,
    "Strategic_Agent": 0.78,
    "Memory_Agent": 0.83,
    "Comfort_Agent": 0.86,
    "Energy_Agent": 0.80,
    "Briefing_Agent": 0.75,
    "Planning_Agent": 0.82
  },
  "gsas_compliance": {
    "overall_pct": 82.5,
    "energy_pct": 78.0,
    "water_pct": 91.0,
    "iaq_pct": 88.0,
    "comfort_pct": 84.0
  },
  "hallucination_stats": {
    "claims_stripped_today": 14,
    "h4_failures_today": 3,
    "corrections_applied_today": 11,
    "abstentions_today": 2
  },
  "system_health": {
    "swarm_busy": false,
    "queue_depth": 0,
    "avg_advisory_latency_sec": 72.4
  }
}
```

---

## 8. Server-Sent Events (SSE) Streaming

For push updates instead of polling. Lower latency, less bandwidth, better UX.

### Endpoints

| Endpoint | Channel | Use For |
|---|---|---|
| `GET /api/v1/stream/monitor` | monitor | Telemetry updates, swarm events, calibration progress, scenario state |
| `GET /api/v1/stream/chat` | chat | Interactive chat tasks, tool_use, agent thoughts |
| `GET /api/v1/stream/thoughts` | monitor (legacy alias) | Same as `/monitor` — older clients |

### Wire Format

Standard SSE — `Content-Type: text/event-stream`.

```
event: system
data: {"message": "Calibration started", "timestamp": "2026-05-26T22:30:00Z"}

event: telemetry
data: {"equipment_id": "chiller_01", "points": {"kw": 425.1, "load_pct": 78.3}}

event: swarm_event
data: {"agent": "Alarm_Agent", "action": "get_active_alarms", "status": "running"}

event: advisory_ready
data: {"advisory_id": "adv_xxx", "confidence": "medium"}
```

### Event Types (monitor channel)

| Event | Payload Shape | Purpose |
|---|---|---|
| `system` | `{message, timestamp, ...}` | Lifecycle events (sim started/paused, calibration milestones) |
| `telemetry` | `{equipment_id, points, timestamp}` | Periodic equipment state push |
| `swarm_event` | `{agent, action, status, result?, elapsed_ms?}` | Real-time agent activity (use for "thinking…" UI) |
| `alarm_triggered` | `{alarm_id, equipment_id, severity, message}` | New alarm fired |
| `scenario_started` | `{injection_id, scenario_id, target_equipment}` | Fault injection began |
| `advisory_ready` | `{advisory_id, confidence}` | Swarm finished; fetch full advisory |
| `vip_override` | `{operator, reason, equipment_id}` | Operator intervention detected |

### Frontend Client (JavaScript)

```javascript
const es = new EventSource('http://localhost:8000/api/v1/stream/monitor');

es.addEventListener('system', (e) => {
  const data = JSON.parse(e.data);
  showToast(data.message);
});

es.addEventListener('telemetry', (e) => {
  const data = JSON.parse(e.data);
  updateEquipmentCard(data.equipment_id, data.points);
});

es.addEventListener('swarm_event', (e) => {
  const data = JSON.parse(e.data);
  appendToActivityLog(`${data.agent}: ${data.action}`);
});

es.addEventListener('advisory_ready', (e) => {
  const data = JSON.parse(e.data);
  fetch(`/api/v1/demo/advisories/history`).then(/* ... */);
});

es.addEventListener('alarm_triggered', (e) => {
  const data = JSON.parse(e.data);
  showAlarmNotification(data);
});

es.onerror = (e) => {
  console.error('SSE connection lost', e);
  // EventSource auto-reconnects by default
};
```

### React Hook Example

```typescript
import { useEffect, useState } from 'react';

export function useSSE(url: string, eventTypes: string[]) {
  const [events, setEvents] = useState<Record<string, any[]>>({});

  useEffect(() => {
    const es = new EventSource(url);

    const handlers = eventTypes.map((type) => {
      const handler = (e: MessageEvent) => {
        setEvents((prev) => ({
          ...prev,
          [type]: [...(prev[type] || []).slice(-99), JSON.parse(e.data)],
        }));
      };
      es.addEventListener(type, handler);
      return { type, handler };
    });

    return () => {
      handlers.forEach(({ type, handler }) =>
        es.removeEventListener(type, handler)
      );
      es.close();
    };
  }, [url, eventTypes.join(',')]);

  return events;
}

// Usage
const events = useSSE('/api/v1/stream/monitor', ['telemetry', 'swarm_event']);
```

---

## 9. Error Handling

### Standard Error Response

```json
{
  "error": "scenario_not_found",
  "message": "Scenario id 'foo' not in registry",
  "status_code": 404,
  "timestamp": "2026-05-26T22:30:00Z"
}
```

### Common Status Codes

| Code | Meaning | Frontend Action |
|---|---|---|
| `200` | OK | Render data |
| `202` | Accepted (async kicked off) | Begin polling status endpoint |
| `400` | Bad request — malformed body | Show validation error to user |
| `401` | Unauthorized — missing/invalid token | Redirect to login |
| `404` | Not found — bad ID | Show "not found" state |
| `409` | Conflict — e.g. scenario already active | Show warning, offer override |
| `429` | Rate limit | Back off, show "too many requests" |
| `500` | Server error | Show generic error, log details for ops |
| `503` | Swarm busy / unavailable | Queue request, show "thinking…" with retry |

### Swarm-Specific Edge Cases

- **Abstention**: `confidence: "low"` + response says "ARVIS cannot deliver verified advisory". Treat as a soft failure — surface clearly, don't pretend it's a normal answer.
- **Hallucination clamp**: response may contain `"[unverified]"` markers inline. Render them as warning chips, not normal text.
- **Empty source_point_id**: any alarm with this field empty is inference-based and should carry a "Phantom Risk" badge in UI.

---

## 10. Recommended Frontend Architecture

### Page/Component Tree

```
App
├── CalibrationGate          (blocks UI until calibrated)
├── DashboardLayout
│   ├── BuildingOverviewCard  (poll /building/overview every 5s)
│   ├── BrainDashboard        (poll /intelligence/summary every 10s)
│   │   ├── TrustGauges       (per-agent trust scores)
│   │   ├── GSASBars          (compliance percentages)
│   │   └── HallucinationCounter
│   ├── FloorPlanView         (static /building/topology, click → modal)
│   │   └── EquipmentModal    (poll /building/equipment/{id} every 2s while open)
│   ├── AlarmFeed             (SSE alarm_triggered)
│   ├── ScenarioPanel         (/scenario/list, /scenario/inject)
│   ├── ReasoningConsole
│   │   ├── QueryInput        (POST /reasoning/trigger)
│   │   ├── AgentActivityLog  (SSE swarm_event)
│   │   ├── AdvisoryDisplay   (confidence badge, evidence chips)
│   │   └── ExplainDrawer     (/explain/advisory/{id})
│   └── AdvisoryHistory       (/advisories/history)
└── SSEProvider               (single EventSource, shared via context)
```

### State Strategy

| Data | Storage | Update Trigger |
|---|---|---|
| Topology | localStorage or in-memory cache | Once on mount |
| Equipment points | Component state | SSE `telemetry` event |
| Alarms | Global store (Zustand/Redux) | SSE `alarm_triggered` + initial poll |
| Active advisory | Component state | Response from `/reasoning/trigger` |
| Brain summary | Global store | Poll 10s |
| SSE connection | Context provider | Single connection shared app-wide |

### Polling vs Push Decision Matrix

| Endpoint | Strategy | Justification |
|---|---|---|
| `/building/overview` | Poll 5s | Aggregate, no granular push event |
| `/building/alarms` | SSE `alarm_triggered` | Event-driven, push beats poll |
| `/building/equipment/{id}` | Poll 2s when modal open | Granular; SSE telemetry too noisy |
| `/calibrate/status` | SSE `system` events | Push during calibration |
| `/intelligence/summary` | Poll 10s | Heavy compute, push not implemented |
| `/reasoning/trigger` response | POST → wait | Single response per request |
| Swarm progress | SSE `swarm_event` | Real-time UX during 30–180s wait |

---

## 11. TypeScript Client Stub

Drop into `src/api/arvis.ts` in your frontend:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
const DEMO_BASE = `${API_BASE}/api/v1/demo`;

// ──────────────── Types ────────────────

export type Confidence = 'high' | 'medium' | 'low';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type EquipmentType = 'chiller' | 'ahu' | 'pump' | 'cooling_tower';

export interface BuildingOverview {
  building_name: string;
  timestamp: string;
  equipment_count: number;
  equipment_by_type: Record<EquipmentType, number>;
  active_alarms: number;
  total_power_kw: number;
  outdoor_temp_c: number;
  calibration_status: 'not_started' | 'running' | 'complete';
}

export interface EquipmentDetail {
  equipment_id: string;
  type: EquipmentType;
  name: string;
  location: string;
  status: 'running' | 'standby' | 'fault' | 'offline';
  points: Record<string, number>;
  last_updated: string;
}

export interface Alarm {
  alarm_id: string;
  equipment_id: string;
  severity: Severity;
  message: string;
  triggered_at: string;
  duration_min: number;
  source_point_id: string; // empty = phantom risk
  status: 'active' | 'acknowledged' | 'cleared';
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  target_equipment: string[];
  expected_alerts: string[];
}

export interface Advisory {
  advisory_id: string;
  query: string;
  response: string;
  confidence: Confidence;
  agents_consulted: string[];
  evidence_count: number;
  verification: {
    h4_passed: boolean;
    h2_passed: boolean;
    h6_physics_passed: boolean;
    contradictions_corrected: number;
    claims_stripped: number;
  };
  elapsed_sec: number;
  timestamp: string;
}

export interface IntelligenceSummary {
  metacognition: {
    safety_threshold_pct: number;
    uncertainty_floor: number;
    abstention_rate_pct: number;
    active_skills_count: number;
  };
  trust_scores: Record<string, number>;
  gsas_compliance: {
    overall_pct: number;
    energy_pct: number;
    water_pct: number;
    iaq_pct: number;
    comfort_pct: number;
  };
  hallucination_stats: {
    claims_stripped_today: number;
    h4_failures_today: number;
    corrections_applied_today: number;
    abstentions_today: number;
  };
  system_health: {
    swarm_busy: boolean;
    queue_depth: number;
    avg_advisory_latency_sec: number;
  };
}

// ──────────────── Helper ────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${DEMO_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new ApiError(err.message || 'Request failed', res.status, err);
  }
  return res.json();
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public payload: any
  ) {
    super(message);
  }
}

// ──────────────── Endpoints ────────────────

export const arvis = {
  building: {
    overview: () => request<BuildingOverview>('/building/overview'),
    equipment: (id: string) => request<EquipmentDetail>(`/building/equipment/${id}`),
    alarms: () => request<{ count: number; alarms: Alarm[] }>('/building/alarms'),
    topology: () => request<{ floors: number; equipment: any[] }>('/building/topology'),
  },
  calibrate: {
    start: () => request<{ calibration_id: string; status: string }>('/calibrate/start', { method: 'POST', body: '{}' }),
    status: () => request<{ status: string; progress_pct: number }>('/calibrate/status'),
  },
  scenario: {
    list: () => request<{ scenarios: Scenario[] }>('/scenario/list'),
    inject: (body: { scenario_id: string; duration_minutes?: number; intensity?: number }) =>
      request('/scenario/inject', { method: 'POST', body: JSON.stringify(body) }),
    active: () => request<{ active_count: number; injections: any[] }>('/scenario/active'),
  },
  reasoning: {
    trigger: (body: { query: string; context?: Record<string, any> }) =>
      request<Advisory>('/reasoning/trigger', { method: 'POST', body: JSON.stringify(body) }),
    latest: () => request<Advisory>('/reasoning/latest'),
  },
  advisories: {
    history: () => request<{ count: number; advisories: any[] }>('/advisories/history'),
    explain: (id: string) => request<any>(`/explain/advisory/${id}`),
  },
  intelligence: {
    summary: () => request<IntelligenceSummary>('/intelligence/summary'),
  },
};

// ──────────────── SSE ────────────────

export type SSEEventType =
  | 'system'
  | 'telemetry'
  | 'swarm_event'
  | 'alarm_triggered'
  | 'scenario_started'
  | 'advisory_ready'
  | 'vip_override';

export function connectMonitor(handlers: Partial<Record<SSEEventType, (data: any) => void>>): EventSource {
  const es = new EventSource(`${API_BASE}/api/v1/stream/monitor`);
  for (const [type, handler] of Object.entries(handlers)) {
    es.addEventListener(type, (e: any) => handler(JSON.parse(e.data)));
  }
  return es;
}
```

---

## 12. Demo Walkthrough Script

A reference flow for a live demo, mapping API calls to UI states:

| Step | Operator Action | API Call | UI State |
|---|---|---|---|
| 1 | Open app | `GET /building/topology` | Floor plan renders |
| 2 | App auto-calibrates | `POST /calibrate/start`, SSE `system` | "Calibrating…" overlay, progress bar |
| 3 | Calibration done | SSE `system` `{status: complete}` | Overlay clears, dashboard active |
| 4 | Operator browses | `GET /building/overview`, SSE `telemetry` | Live KPI tiles update |
| 5 | Click chiller_02 | `GET /building/equipment/chiller_02` | Detail modal with live points |
| 6 | Pick a scenario | `GET /scenario/list` | Scenario dropdown populated |
| 7 | Inject vibration fault | `POST /scenario/inject` | Toast "Injection active", scenario badge |
| 8 | Watch alarm fire | SSE `alarm_triggered` | Red alarm card appears on chiller_02 |
| 9 | Ask the brain | `POST /reasoning/trigger` `{query: "What's wrong with chiller_02?"}` | Spinner + agent activity log |
| 10 | Watch swarm work | SSE `swarm_event` stream | Live "Alarm_Agent calling get_active_alarms…" entries |
| 11 | Advisory arrives | response from trigger + SSE `advisory_ready` | Advisory card with confidence badge |
| 12 | Click "Explain" | `GET /explain/advisory/{id}` | Drawer with reasoning chain, evidence chips, peer votes |
| 13 | Check brain health | `GET /intelligence/summary` | Trust gauges, GSAS bars, hallucination counter |

---

## Appendix A: Equipment ID Cheatsheet

| ID | Name | Type | Location |
|---|---|---|---|
| `chiller_01` | Chiller 01 (800TR) | chiller | Basement, Plant Room |
| `chiller_02` | Chiller 02 (800TR) | chiller | Basement, Plant Room |
| `chiller_03` | Chiller 03 (800TR) | chiller | Basement, Plant Room |
| `chiller_04` | Chiller 04 (800TR) | chiller | Basement, Plant Room |
| `ahu_01` | AHU Floor 1 (Lobby) | ahu | Floor 1, Zone A |
| `ahu_02` | AHU Floor 2 (Retail) | ahu | Floor 2, Zone A |
| `ahu_03` | AHU Floor 3 (Office) | ahu | Floor 3, Zone A |
| `ahu_04` | AHU Floor 4 (Office) | ahu | Floor 4, Zone A |
| `ahu_05` | AHU Floor 5 (Office) | ahu | Floor 5, Zone A |
| `ahu_06` | AHU Floor 6 (Office) | ahu | Floor 6, Zone A |
| `ahu_07` | AHU Floor 12 (Mechanical) | ahu | Floor 12, Zone A |
| `ahu_08` | AHU Floor 19 (Executive) | ahu | Floor 19, Zone A |
| `pump_01` | Primary CHW Pump 1 | pump | Basement, Plant Room |
| `pump_02` | Primary CHW Pump 2 | pump | Basement, Plant Room |
| `pump_03` | Condenser Water Pump 1 | pump | Basement, Plant Room |
| `pump_04` | Condenser Water Pump 2 | pump | Basement, Plant Room |
| `ct_01` | Cooling Tower 1 | cooling_tower | Roof, North Wing |
| `ct_02` | Cooling Tower 2 | cooling_tower | Roof, South Wing |

---

## Appendix B: Agent Roster

The swarm contains specialized agents. Trust scores in `/intelligence/summary` are per-agent.

| Agent | Specialty | Typical Tools |
|---|---|---|
| Alarm_Agent | Active alarms, clustering, root cause | `get_active_alarms`, `analyze_root_cause`, `analyze_cascade` |
| Maintenance_Agent | Equipment health, RUL, fault prediction | `get_equipment_health`, `predict_remaining_life`, `detect_equipment_faults` |
| Comfort_Agent | Zone temperature, SAT/MAT analysis | `get_zone_occupancy`, `get_point_history` |
| Energy_Agent | Power, COP, efficiency, waste | `analyze_energy`, `get_burn_rate`, `find_ghost_spaces` |
| Memory_Agent | Skillbook lookups, pattern recall | `query_skillbook`, `find_similar_skills`, `add_to_skillbook` |
| Strategic_Agent | High-level optimization, GSAS | `get_advisory_recommendations`, `simulate_change`, `compare_to_fleet` |
| Briefing_Agent | Operator briefings, shift handoffs | `generate_briefing`, `get_dashboard_overview` |
| Planning_Agent | Action planning, risk classification | `classify_gsas_action_risk` |
| Sensor_Fusion_Agent | Multi-sensor validation | `get_point_history`, `detect_equipment_faults` |
| Discovery_Agent | New equipment, point discovery | (varies) |
| Voice_Agent | Voice interaction | (varies) |
| Persona_Agent | Tone adaptation per user | (varies) |
| Mission_Agent | Long-running goals | (varies) |

---

## Appendix C: Confidence Levels — What They Mean

| Label | Color Suggestion | Meaning | UI Treatment |
|---|---|---|---|
| `high` | Green | 3+ corroborating evidence signals, all verification gates passed | Show as primary recommendation |
| `medium` | Amber | Limited evidence or partial verification | Surface with "verify before acting" CTA |
| `low` | Red | Insufficient trend data or failed verification | Show as advisory only, suggest on-site verification |

When ARVIS abstains, the response will say so explicitly (e.g. "ARVIS cannot deliver verified advisory"). Treat as `confidence: low` + a clear "Cannot answer" badge.

---

**End of document.**

For OpenAPI/Swagger spec, run the server and visit `http://localhost:8000/docs`.  
For source verification: `routes_demo.py`, `demo_presets.py`, `demo_orchestrator.py` in `agent_commercial/api/`.
