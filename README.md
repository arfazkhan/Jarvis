# ARVIS Ops Copilot — Commercial BMS AI

> Adaptive Responsive Virtual Intelligence for Structures. Gives commercial buildings a cognitive brain.

---

## What It Is

ARVIS Ops is an **AI-powered building management system** that acts as a co-pilot for facility managers and operations teams. It speaks natural language (English/Arabic), understands building equipment, triages alarms, predicts failures, optimizes energy, and ensures GSAS compliance — all through a multi-agent swarm architecture.

Originally a home automation project, it pivoted to commercial BMS to serve the Qatar/GCC market where building operations are complex, high-value, and underserved by generic AI.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      ARVIS Ops Copilot                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │   Chat API  │    │  Briefing    │    │   Dashboard   │  │
│  │   (REST)    │    │  Scheduler    │    │   (Next.js)   │  │
│  └──────┬──────┘    └──────┬───────┘    └───────┬───────┘  │
│         │                   │                    │           │
│         └───────────────────┼────────────────────┘           │
│                             ▼                                │
│              ┌─────────────────────────────┐                 │
│              │    BMS LLM Agent (Groq)     │                 │
│              │   Layered Prompt Builder    │                 │
│              └─────────────┬───────────────┘                 │
│                            │                                  │
│         ┌──────────────────┼──────────────────┐              │
│         ▼                  ▼                  ▼              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Swarm Node │  │  Swarm Node │  │  Swarm Node │          │
│  │  (Thermal)  │  │  (Energy)   │  │  (Safety)   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                 │                 │                  │
│         └─────────────────┼─────────────────┘                  │
│                           ▼                                    │
│              ┌─────────────────────────────┐                  │
│              │    BFT Consensus Engine     │                  │
│              │    (Peer Review / Veto)     │                  │
│              └─────────────┬───────────────┘                  │
│                            │                                   │
│         ┌──────────────────┼──────────────────┐               │
│         ▼                  ▼                  ▼               │
│  ┌────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │ 33 BMS      │  │ Trust       │  │ World       │           │
│  │ Tools      │  │ Governor     │  │ Model       │           │
│  └────────────┘  └─────────────┘  └─────────────┘            │
│                                                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
           ┌──────────────┐  ┌──────────────┐
           │  BACnet      │  │  Virtual     │
           │  Adapter     │  │  Simulated   │
           │  (BAC0/YABE) │  │  BMS         │
           └──────────────┘  └──────────────┘
```

---

## Core Capabilities

### 1. Natural Language Operations
Query building state in plain English or Arabic:
- "What's wrong with AHU-07?"
- "Show me critical alarms"
- "ما حالة نظام التبريد؟" (Arabic)

### 2. Intelligent Alarm Management
- Correlation-based clustering (root cause grouping)
- Priority queue (safety > comfort > energy)
- Nuisance alarm suppression
- Acknowledge, snooze, escalate

### 3. Proactive Briefings
Scheduled intelligence push to operators:
- **Morning** (7AM): Top 3 priorities for the day
- **Urgent** (real-time): Critical risks requiring immediate action
- **Weekly** (Sunday): Fleet optimization and long-term goals

### 4. Predictive Maintenance
ML ensemble for failure prediction:
- **XGBoost** + **Weibull** + **LSTM** models
- Equipment health scoring (CH-01, AHU-07, etc.)
- Remaining useful life (RUL) estimation
- Anomaly detection via Isolation Forest

### 5. Energy Optimization
- Real-time consumption vs. target tracking
- Anomaly detection (Isolation Forest)
- Peak hour awareness (Qatar: 12-6PM)
- Weather-contextualized baselines

### 6. GSAS-Aware Operations (Qatar)
Turns **Green Sustainability Assessment System** targets into daily operating priorities:
- 8 categories: UC, S, E, W, M, IE, CE, MO
- Star rating projection (1-6 stars)
- Compliance reports with improvement recommendations
- Recommendation scoring by GSAS category, target delta, confidence, and evidence
- Prioritizes actions that move energy, water, comfort, and operations metrics closer to GSAS targets

### 7. LLM-Driven Auto-Configuration
New building? Run `scripts/auto_config_cli.py` and ARVIS will:
1. Discover all BACnet devices via Who-Is
2. Enumerate every object instance across all devices
3. Ask the LLM to infer equipment types, names, and point semantics
4. Generate a complete `config/bms_config.yaml` — no manual YAML editing required

```bash
# On-site at new building (simulator mode for testing)
python scripts/auto_config_cli.py --mode simulator --building-id DOHA-TOWER-01

# Real hardware
python scripts/auto_config_cli.py --mode bacnet --port 47808 --building-id DOHA-TOWER-01 --verbose
```

Output: `config/bms_config.yaml` + `config/discovery_report.json` (raw audit trail)

### 8. Multi-Agent Swarm
12 specialized agents with **BFT consensus** — any safety-relevant proposal must pass peer review before being surfaced to the operator.

### 9. Trust Calibration
System adapts verbosity and confidence based on operator follow-through. Low trust → more evidence, less hype.

---

## Supported Equipment

| Type | Examples |
|------|----------|
| Air Handling Units | AHU-01, AHU-02 |
| Chillers | CH-01, CH-02 |
| Cooling Towers | CT-01 |
| Variable Air Volume | VAV-01A, VAV-01B |
| Fan Coil Units | FCU-01, FCU-02 |
| Pumps | P-01, P-02 |
| VFDs, Dampers, Valves | — |
| Electric/Water/Gas Meters | — |

**Protocol:** BACnet (BAC0, YABE simulator) via port 47808/47809. Modbus adapter available.

---

## 33 BMS Tools

### Equipment
- `get_equipment_status` — Equipment state + data points + alarms
- `get_equipment_points` — All points for an equipment
- `set_equipment_mode` — Change mode (occupied, standby, etc.)
- `get_equipment_history` — Historical values

### Alarms
- `get_active_alarms` — Sorted by priority
- `acknowledge_alarm` — With operator name + note
- `get_alarm_details` — Full alarm context
- `investigate_alarm` — Auto-correlation + root cause

### Energy
- `get_energy_readings` — kWh, cost, tariff
- `get_energy_target` — Daily/monthly targets
- `get_energy_anomaly` — Isolation Forest anomalies

### Operations
- `generate_briefing` — Proactive briefing (overnight/daily/weekly)
- `get_optimization_recommendations` — Energy/comfort wins
- `get_contextual_history` — Equipment history

### Maintenance
- `predict_equipment_failure` — XGBoost + Weibull + LSTM
- `get_equipment_health` — Health score 0-100
- `get_maintenance_tasks` — Pending and scheduled
- `calculate_rul` — Remaining useful life

### GSAS
- `get_gsas_status` — Compliance status
- `get_gsas_score_breakdown` — Category scores
- `get_gsas_recommendations` — Improvement actions
- `calculate_gsas_projection` — Star rating projection

### ML Analytics
- `forecast_energy` — Prophet + LightGBM hourly forecast
- `detect_energy_anomalies` — Recent anomaly detection
- `get_trend_analysis` — Equipment/energy trends

### Skillbook
- `query_skillbook` — Building institutional memory
- `add_skillbook_entry` — Learned knowledge
- `get_equipment_quirks` — Equipment-specific notes
- `hybrid_search_knowledge` — Routes technical-manual search through tree, vector, or hybrid RAG

### Advisory
- `generate_recommendations` — Multi-domain recommendations
- `get_trust_metrics` — Operator follow-through
- `get_equipment_graph` — Equipment topology

---

## Technical Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| LLM | Groq (Llama 3.3 70B) + OpenAI fallback |
| Framework | FastAPI (REST + SSE) |
| Frontend | Next.js 15 (TypeScript, Tailwind) |
| Protocol | BACnet (BAC0/YABE), Modbus |
| Vector Store | FAISS, ChromaDB |
| ML | scikit-learn, XGBoost, Prophet, LSTM |
| Scheduling | APScheduler (cron) |
| Storage | SQLite + in-memory state |

---

## Key Files

| Path | Purpose |
|------|---------|
| `agent_commercial/main.py` | OpsCopilot orchestrator + CLI |
| `agent_commercial/api/routes.py` | FastAPI REST endpoints |
| `agent_commercial/bms_state_engine.py` | Central state store |
| `agent_commercial/alarm_engine.py` | Alarm processing + correlation |
| `agent_commercial/briefing_engine.py` | Proactive briefing generator |
| `agent_commercial/gsas_reporter.py` | GSAS compliance tracking |
| `agent_unified/llm.py` | K2 hybrid LLM (reasoning + tool) |
| `agent_unified/tools/bms/` | 33 BMS tool definitions |
| `agent_advisory/` | Goals, trust, explainer, world model |
| `arvis_core/swarm/` | Swarm nodes + BFT consensus |
| `arvis_core/memory/` | Memory orchestrator + context |
| `dashboard/` | Next.js ops dashboard |

---

## Running

```bash
# Environment
export GROQ_API_KEY=your_key_here
export ARVIS_VERTICAL=COMMERCIAL

# API server
python -m api.main

# CLI (simulator mode)
python -m agent_commercial.main --mode simulator

# Run tests
python -m pytest tests/gauntlet_omega.py -v
python -m pytest tests/gauntlet_alpha_gsas.py -v
```

---

## Testing

| Test | What It Validates |
|------|-------------------|
| `gauntlet_omega.py` | 18-day simulation: cognitive degradation, authority conflict, explainability |
| `gauntlet_alpha_gsas.py` | 6-phase GSAS compliance: energy targets, comfort, sensor faults |
| `gauntlet_explainability.py` | Greenwashing detection, glass-box AI reasoning |
| `super_gauntlet.py` | End-to-end multi-agent swarm + consensus |

---

## Candid Limitations

Know these before piloting.

### Hardware Connectivity
| Limitation | Impact | Mitigation |
|------------|--------|------------|
| BACnet read-only (no control commands) | Cannot adjust setpoints, start/stop equipment via ARVIS | Add write commands after pilot validation with safety review |
| BAC0 library on Windows only (Linux requires BACnet stack) | YABE + BAC0 dev environment is Windows-only | Simulator mode for development; real hardware deployment on Linux needs a BACnet daemon |
| No BBMD (Broadcast Management Device) support | Cannot reach devices across VLANs/subnets | Deploy ARVIS on the same BACnet/IP subnet as the BMS controllers |
| Point discovery is slow (Who-Is + read each object) | ~15-30 min for a 50-device building | Auto-config runs in background; operator can review while it runs |

### Auto-Configurator
| Limitation | Impact | Mitigation |
|------------|--------|------------|
| LLM inference of equipment type from raw BACnet object names is probabilistic | May mis-identify a VAV as an AHU if object names are non-standard | Output includes a human-review step + editable YAML before committing |
| Object description strings are often vendor-specific and cryptic | Auto-config may produce generic names like `analogInput_5` | Operator should rename during review step; skillbook captures vendor quirks |
| Cannot infer topology (parent/child relationships) from BACnet alone | Equipment hierarchy (CH-01 → AHU-01 → VAV-01A) must be entered manually | Provide a topology template in config based on building type (tower, mall, hospital) |

### ML / Advisory
| Limitation | Impact | Mitigation |
|------------|--------|------------|
| ML models (XGBoost, Isolation Forest, Prophet) have **no real training data** | All predictions are baseline/synthetic until real sensor history is captured | Models improve with each month of real data; 3-month minimum before predictions are reliable |
| Predictive maintenance requires ~1 year of historical failure data | Without this, RUL estimates are generic (Weibull defaults) | Seed with OEM published MTBF numbers; refine over time |
| Trust governor needs at least 4 weeks of operator follow-through data | Recommendations start at high verbosity until trust is established | Manual override available; trust data is per-building, per-operator |

### Operational
| Limitation | Impact | Mitigation |
|------------|--------|------------|
| No persistence layer (state is in-memory) | Restart wipes current state | Add SQLite/PostgreSQL persistence before production; roadmap in progress |
| No user auth on simulator mode | Anyone with network access can query | Enable auth middleware before production deployment |
| Dashboard is read-only (no control) | Operator cannot act from dashboard | Control via chat API only; dashboard shows state for now |

### Known Gaps (Roadmap)
- [ ] Modbus adapter not yet integrated (BACnet only)
- [ ] No role-based access control (operator, admin, viewer)
- [ ] No audit log persistence (logs go to stdout/Loki only)
- [ ] GSAS scoring uses static weights (v2.1 spec not fully calibrated against GORD)
- [ ] Swarm BFT consensus is simulated (in-memory only, no distributed setup)
- [ ] No OPC-UA support (BACnet only)

---

## README Status

This is a **living document** — as the codebase evolves, so does this README. Last verified against actual implementation on the `commercial-bms` branch.

Stale home automation references (CosyVoice, VibeVoice, Matter/Thread, residential agent modules) have been removed. Only commercial BMS code remains.
