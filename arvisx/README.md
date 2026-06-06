# ArvisX — Residential Operations Intelligence

ArvisX is the **operational intelligence layer for residential communities**. It sits
*above* fragmented infrastructure (water, power-backup, STP, pool, fire, common-area
AC) — equipment that has **no unified BMS** — and turns scattered signals into one
answer: **"what needs attention before residents are affected?"**

It is **read-only and advisory** — it never controls equipment. It monitors, learns,
reasons, and recommends; a human acts.

> ArvisX is a separate package from commercial ARVIS. It reuses the same grounding
> philosophy: a **deterministic trust floor** does the detecting; an **LLM reasoning
> layer** sits on top for cross-system cause + natural-language answers, kept honest by
> the floor (evidence-bound, never "confirmed" without inspection, abstains on thin data).

---

## Capabilities

| Layer | What it does |
|---|---|
| **Monitoring** | Continuous per-asset health score + alerts from live signals |
| **Service health** | 6 community tiles — Water, Power Backup, Pool, STP, Fire, Energy — risk-driven (turns yellow/red when an action is open) |
| **Preventive maintenance** | Service-due, runtime-over-threshold, test-overdue, fuel/level/battery |
| **Pattern learning + drift** | Learns each signal's own normal (median/MAD); flags drift ("3σ above its own baseline") — early degradation a fixed threshold misses |
| **PM virtual sensors** | Derive PM indicators from cheap signals (CT/power/runtime): power-creep (bearing wear), short-cycling, duty-cycle, dry-run, pool turnover |
| **Ghost-floor detection** | Virtual occupancy from CO2 + motion → flags empty-but-conditioned areas → energy waste (kW + QAR/day) |
| **Sensor fusion** | Combines CT + temperature + presence into a conclusion; **confidence = number of independent sensors agreeing** (1→Low, 2→Medium, 3+→High) |
| **Grounded advisory** | Ranked root-cause for a flagged asset — rules floor always, optional LLM differential with cited evidence + discriminating test |
| **Reasoning** | `correlate` — common root cause across simultaneous risks; `ask` — natural-language Q&A over live state |
| **Work orders** | Auto-generate tickets from risks (dedup, auto-close on clear, reopen on recurrence), priority P1–P4 |
| **Institutional memory** | Skillbook (learned fault patterns), fault history, warm-start, **outcome feedback** (close a ticket with the real cause → ArvisX learns it) |

Everything is **honest**: nothing is `confirmed` without physical inspection; it abstains
("likely empty — verify", "insufficient evidence") rather than fabricate; the LLM is
evidence-bound (hallucinated references are dropped).

---

## Quick start

```bash
# (one-time) extra deps beyond the commercial stack
pip install -r arvisx/requirements.txt        # paho-mqtt, python-dotenv

# Dashboard from the simulator (no hardware)
python -m arvisx.demo                          # PRD fault scenario → dashboard
python -m arvisx.demo --healthy                # nominal community
python -m arvisx.demo --advise                 # + grounded advisories (rules floor)
ARVIS_X_LLM=1 python -m arvisx.demo --advise   # + LLM ranked differential

# Run the API (dashboard backend) on :8090
python -m arvisx.api

# Headline demos
python -m arvisx.fusion                        # sensor fusion: cheap sensors → confident conclusions
python -m arvisx.degradation                   # "catch a failing pump from one power wire"

# Tests (hermetic — no broker, no cloud)
python -m pytest arvisx/tests/test_arvisx.py -q     # 50 tests
```

---

## API reference (`/api/v1`)

**Community dashboard**
| Method | Path | Returns |
|---|---|---|
| GET | `/community/overview` | the 6 service-health tiles |
| GET | `/community/risks` | active risks (sorted by severity) |
| GET | `/community/assets` | asset explorer (status, health, runtime, next maintenance) |
| GET | `/community/report` | all of the above in one payload |
| POST | `/scenario/{healthy\|prd}` | switch the simulated state |

**Per-asset**
| GET | `/asset/{id}/advisory` | grounded RCA (+ `institutional_memory` if a prior skill matches) |
| GET | `/asset/{id}/history` | fault/event history for the asset |

**Reasoning (the "thinking")**
| POST | `/reason/correlate` | common root cause across the active risks (or "independent") |
| POST | `/ask` `{"question": "..."}` | natural-language answer grounded in live state |

**Work orders**
| GET | `/workorders` | all tickets (auto-reconciled) |
| GET | `/workorders/{id}` | one ticket |
| POST | `/workorders/sync` | reconcile tickets vs current risks |
| POST | `/workorders/{id}/status/{status}` | ack / in_progress / done / cancelled |
| POST | `/workorders/{id}/close` `{"actual_cause": "..."}` | close with the real cause → **teaches the skillbook** |

**Memory**
| GET | `/skillbook` | learned fault patterns (confirmed first) |

LLM endpoints (`advisory`, `reason/correlate`, `ask`) need `ARVIS_X_LLM=1`; without it
they fall back to the deterministic floor (advisory = rules floor; correlate/ask =
"reasoning unavailable").

---

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `ARVISX_API_PORT` | `8090` | API port |
| `ARVISX_SOURCE` | `sim` | `sim` (simulator) or `mqtt` (live ingest) |
| `ARVISX_MQTT_BROKER` / `ARVISX_MQTT_PORT` | `localhost` / `1883` | broker for MQTT mode |
| `ARVIS_X_LLM` | unset | `1` enables the LLM advisory/reasoning layers |
| `ARVISX_DB` | `arvisx/data/arvisx.db` | SQLite path (institutional memory) |
| `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` | — | air-gapped runtime (recommended) |

---

## Live ingest (MQTT)

ArvisX ingests fragmented device signals over MQTT (the IoT lingua franca). Topic
convention: `arvisx/<asset_id>/<signal>`.

```bash
docker run -it -p 1883:1883 eclipse-mosquitto     # a broker
ARVISX_SOURCE=mqtt python -m arvisx.api           # ArvisX subscribes arvisx/#
python -m arvisx.ingest.mock_publisher --scenario prd   # emit a community's signals
```
Example messages: `arvisx/BOOST-PUMP-01/current_a 12.0`, `arvisx/GEN-01/fuel_level_pct 18`,
`arvisx/ZONE-CLUB/co2_ppm 430`. The fleet must be seeded first (commissioning); stray
topics for unknown assets are dropped.

---

## Sensor / hardware foundation (universal, no vendor-API chase)

| Family | Sensors | Feeds |
|---|---|---|
| **Electrical** | CT clamps, energy meters → `current_a` / `power_kw` | run-state, power-creep, dry-run, cycling |
| **Environment** | temperature, humidity → `room_temp_c` / `humidity_pct` | overheat, cooling-effectiveness, leak |
| **Presence** | PIR / mmWave → `motion_events_15m` (+ CO2) | occupancy, ghost-floor |
| **Existing controllers** | RS485 / Modbus / MQTT / REST | whatever the building already exposes |

Edge node (ESP32 / Pi) normalizes these to MQTT → ArvisX. Every building has electricity
and rooms, so this covers AC / pumps / pool / STP / generator with **one hardware stack**.

---

## How the intelligence is layered

```
 cheap sensors → edge node → MQTT
        ↓
 ┌──────────── DETERMINISTIC FLOOR (trust: auditable, fast, offline, no hallucination) ───────────┐
 │  health scoring · PM rules · drift learning · PM virtual sensors · fusion · ghost detection      │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
        ↓ risks
 ┌──────────── LLM REASONING (kept honest by the floor) ──────────────────────────────────────────┐
 │  grounded advisory (ranked differential) · correlate (common cause) · ask (why?)                 │
 └──────────────────────────────────────────────────────────────────────────────────────────────┘
        ↓
 work orders  ·  skillbook (learn)  ·  fault history (remember)  ·  outcome feedback (improve)
```

The deterministic layers *should* stay deterministic — you don't want an LLM deciding "is
the tank low." The LLM does only what rules can't: cross-system cause, novel reasoning,
plain-language answers — and the floor keeps it from hallucinating.

---

## Status (prototype)

**Proven in software (50 tests):** the full chain — sense → health → drift → virtual
sensors → fusion → ghost → grounded advisory → reasoning → work orders → memory. Both
deterministic and LLM paths; MQTT loopback without a broker; persistence survives restart.

**Not yet (real-world):** a frontend UI, validation against a live broker / real edge
hardware, deployment in an actual building, and the physical edge-gateway firmware. The
software is feature-complete; what remains is hardware + a building.

**Honest limits:** Fire systems are **supplementary visibility only**, never the certified
system of record. The LLM reasoning needs provider creds (`.env`) + `ARVIS_X_LLM=1`, and
degrades to the deterministic floor when unavailable.
