# Home Agent — 7-Phase PRD & Folder Structure

**Version:** 1.0
**Date:** 2025-11-24

---

# Project root — recommended folder structure

```
home-agent/
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── config/
│   ├── settings.py
│   └── logging.yaml
├── scripts/
│   ├── start_dev.sh
│   ├── start_prod.sh
│   └── flash_esp32.sh
├── agent/
│   ├── __init__.py
│   ├── main.py
│   ├── event_bus/
│   │   └── event_bus.py
│   ├── state_engine/
│   │   ├── state_engine.py
│   │   └── persistence.py
│   ├── automations/
│   │   ├── automation_engine.py
│   │   └── scheduler.py
│   ├── controllers/
│   │   ├── matter_controller.py
│   │   └── virtual_device.py
│   ├── llm_agent/
│   │   ├── llm_agent.py
│   │   └── prompt.py
│   ├── learning/
│   │   ├── learning_engine.py
│   │   └── pattern_analyzer.py
│   ├── web/
│   │   ├── app.py
│   │   └── ui/
│   │       └── dashboard_assets
│   └── utils/
│       └── logging_config.py
├── agent_cognitive/            # PHASE 1
│   ├── __init__.py
│   ├── memory_manager.py
│   ├── embeddings_store.py
│   ├── context_graph.py
│   ├── prediction_engine.py
│   ├── preference_model.py
│   └── cognitive_loop.py
├── agent_conversation/         # PHASE 2
│   ├── __init__.py
│   ├── dialogue_manager.py
│   ├── persona_engine.py
│   ├── sentiment_analyzer.py
│   ├── stt_adapter.py
│   └── tts_adapter.py
├── agent_planning/             # PHASE 3
│   ├── __init__.py
│   ├── plan_generator.py
│   ├── dependency_graph.py
│   ├── plan_validator.py
│   └── plan_executor.py
├── agent_sensors/              # PHASE 4
│   ├── __init__.py
│   ├── virtual_sensors.py
│   ├── presence_model.py
│   └── state_estimator.py
├── agent_personality/          # PHASE 5
│   ├── __init__.py
│   ├── personality_profile.py
│   ├── emotional_state.py
│   └── tone_adapter.py
├── agent_missions/             # PHASE 6
│   ├── __init__.py
│   ├── mission_planner.py
│   ├── mission_executor.py
│   └── mission_simulator.py
├── agent_web_ui/               # PHASE 7
│   ├── __init__.py
│   ├── ui_server.py
│   └── components/
│       ├── reasoning_log.py
│       ├── plan_graph_view.py
│       └── patterns_view.py
├── firmware/                   # firmware / ESP32-H2 code & templates
│   ├── esp32_h2/
│   │   ├── platformio.ini
│   │   └── src/
│   │       └── main.cpp
│   └── docs/
├── docs/
│   ├── architecture.md
│   ├── prd/
│   │   ├── phase1_cognitive.md
│   │   ├── phase2_conversation.md
│   │   └── ...
│   └── runbook.md
├── tests/
│   ├── conftest.py
│   ├── test_core.py
│   └── test_cognitive.py
└── tools/
    └── offline_models/
```

---

# PRD for each Phase (detailed)

> Each phase includes: Purpose, Goals, Success Metrics, Features, APIs & Data Models, Security & Privacy, Test Plan, Milestones (sprints) and Acceptance Criteria.

---

# PHASE 1 — Cognitive Layer (True Intelligence Engine)

## Purpose

Add a persistent, queryable long-term memory, context modeling and predictive capability so the agent moves from reactive automations to anticipatory assistance.

## Goals

* Implement a memory store that retains structured representations and embeddings of events and user preferences.
* Provide a context graph that links users, places, routines, and device groups.
* Offer probabilistic predictions for likely next actions and surface suggestions/auto-executions.

## Success Metrics

* Prediction precision@1 ≥ 70% for low-risk actions (after 30 days of simulated usage).
* Memory retrieval latency < 50ms (p95).
* False positive auto-executions < 2% (measured over simulated month).

## Features

1. **Memory Manager**

   * Append-only storage for events and summaries.
   * Periodic compacting and summary generation.
   * Export / delete user data (GDPR).

2. **Embeddings Store**

   * Local/in-process vector store (FAISS or simple ANN for MVP) for semantic lookup.

3. **Context Graph**

   * Node types: user, device, room, routine, habit.
   * Queryable relationships and time-annotated edges.

4. **Preference Model**

   * Tracks per-user preferences (lighting, temperature, music).
   * Learns slowly and applies decay.

5. **Prediction Engine**

   * Takes recent events + memory to output probable next actions with confidence & risk.

6. **Cognitive Loop**

   * Runs periodically and on-demand; writes suggestions to Automation Engine or asks user.

## APIs & Data Models

* `GET /api/cognitive/context?subject=home` → returns context snippet
* `POST /api/cognitive/predict` {state_snapshot} → returns list of predicted actions
* Internal models:

  * `MemoryEvent` {timestamp, source, type, payload, embedding_id}
  * `Preference` {user_id, key, value, confidence}

## Security & Privacy

* All memory stored locally by default; cloud upload only with explicit opt-in.
* PII redaction before embeddings.
* Retention policy configurable (default 90 days for raw events; long-term summaries retained).

## Test Plan

* Unit tests for memory append/read/compact.
* Performance tests for embedding lookup (p95 < 50ms).
* Simulation tests: generate 30d of history, measure prediction precision.
* Privacy tests: ensure PII not present in embeddings.

## Milestones (3 sprints)

* Sprint 1 (1 week): Memory Manager + storage; basic CRUD APIs
* Sprint 2 (1 week): Embeddings store + simple semantic query
* Sprint 3 (2 weeks): Prediction engine + cognitive loop + integration tests

## Acceptance Criteria

* Memory store passes corruption/recovery tests
* Embedding lookups within latency bounds
* Prediction API returns plausible ranked actions on test dataset

---

# PHASE 2 — Natural Interaction Layer (Conversation + Voice)

## Purpose

Provide a persistent conversational interface with multi-modal input (text + voice) and persona-driven responses.

## Goals

* Implement a dialogue manager that keeps session + long-term context.
* Add lightweight sentiment analysis and mood detection.
* Integrate STT/TTS adapters (abstracted) so offline/local option can be swapped with cloud.

## Success Metrics

* End-to-end voice intent recognition accuracy > 85% (simulated) for core intents.
* Response latency < 1.2s for local flows (text); < 3s for STT+LLM flows.
* Sentiment classification F1 > 0.7 on test dialogs.

## Features

1. **Dialogue Manager** — session stacks, context windows, grounding to memory
2. **Persona Engine** — short-term tone tuning and long-term persona evolution
3. **Sentiment & Emotion Detector** — simple classifiers (rule + small model)
4. **STT Adapter** — pluggable (Whisper, Vosk, browser-based) with fallback
5. **TTS Adapter** — pluggable (local + cloud)
6. **Command Normalizer** — maps natural language to intents & probabilistic parameters

## APIs & Data Models

* `POST /api/converse` {user_id, text, context_id} → conversation response
* `POST /api/voice/recognize` (binary audio) → text
* `GET /api/converse/history?user_id=...` → recent conversation snippets

## Security & Privacy

* Voice audio not stored unless opt-in.
* Transcripts stored only with retention policy.
* All LLM prompts scrubbed for PII before external calls.

## Test Plan

* Intent classification unit tests.
* Conversation flow E2E tests with mocked LLM.
* Latency & throughput benchmarks.

## Milestones (3 sprints)

* Sprint 1 (1 week): Conversation manager skeleton + text flows
* Sprint 2 (1 week): Integrate sentiment + persona engine
* Sprint 3 (2 weeks): STT/TTS adapters + E2E tests

## Acceptance Criteria

* Dialog manager maintains correct context across 10-turn conversations
* STT/TTS roundtrip works with chosen adapters in CI/mocked mode

---

# PHASE 3 — Autonomous Action Planning (Plan Executor)

## Purpose

Enable multi-step, dependency-aware plan generation and execution from high-level intents.

## Goals

* LLM produces structured plans that the Plan Validator sanitizes and the Plan Executor runs.
* Support parallelism and transactional rollback for failed steps.

## Success Metrics

* Plan validation catches >95% of simulated conflict cases
* Execution rollback recovers 99% of partial failures to safe state
* End-to-end plan latency (generate+validate) < 2s for typical plans

## Features

1. **Plan Generator** — LLM-based plan with deterministic schema
2. **Dependency Graph & Scheduler** — topological ordering + parallel execution
3. **Plan Validator (Safety)** — conflict, rate-limit, high-risk device checks
4. **Execution Engine** — step executor with retries, backoff, compensation actions
5. **Plan Simulator** — dry-run mode for UI and testing

## APIs & Data Models

* `POST /api/plan` {goal_text, constraints} → plan object
* `POST /api/plan/execute` {plan_id, mode: auto|dry-run}
* Plan schema: `{id, steps:[{id, device, action, deps, retry}], metadata}`

## Security & Privacy

* No automatic plan executes high-risk actions (locks, garage) without explicit user allowlist
* All plan steps audited in reasoning log

## Test Plan

* Conflict injection tests (contradictory step pairs)
* Partial failure tests (simulate relay failures) and observe compensations
* Parallelism tests to ensure non-conflicting steps run concurrently

## Milestones (3 sprints)

* Sprint 1 (1 week): Plan schema + generator adapter
* Sprint 2 (2 weeks): Dependency graph + executor with retries
* Sprint 3 (1 week): Validator + rollback and dry-run

## Acceptance Criteria

* Validator rejects unsafe or policy-violating plans
* Executor demonstrates successful rollback in injected failure tests

---

# PHASE 4 — Sensor Fusion (Perception)

## Purpose

Provide robust, probabilistic sensing to infer occupancy, activity and environmental state, using virtual sensors now and physical sensors later.

## Goals

* Build a virtual sensor suite to simulate realistic inputs for offline development.
* Implement a state estimator that fuses signals (motion, wifi, light, schedule) into occupancy and activity

## Success Metrics

* Occupancy inference accuracy > 90% in standard scenarios (simulated)
* Inference latency < 100ms
* False awake detection < 5% at night

## Features

1. **Virtual Sensors** — motion, light, temperature, wifi presence, device usage
2. **Presence Model** — Bayesian or heuristic-based fusion
3. **State Estimator** — exposes `presence`, `occupied_rooms`, `activity` to State Engine
4. **Calibration Tools** — simulate personas and test scenarios

## APIs & Data Models

* `GET /api/sensors` → listing
* `POST /api/sensors/event` → inject sensor event (for simulation)
* Sensor event model: `{sensor_id, type, value, ts}`


## Security & Privacy

* Presence inference stored only in local memory; retention policy applies.
* Users can **disable presence inference** globally via config or API.
* No sensor data is sent to cloud by default; any export requires explicit opt-in.

## Test Plan

* Simulate **30 days** for multiple personas (student, family, WFH) and validate inferred occupancy.
* Edge cases:

  * short motion blips (avoid false “awake” at night),
  * WiFi flapping (connect / disconnect loops),
  * multiple occupants (conflicting patterns).
* Regression tests to ensure inaccurate sensors don’t cause unsafe actions.

## Milestones (2 sprints)

* **Sprint 1 (1 week)**

  * Virtual sensor harness (`virtual_sensors.py`)
  * `/api/sensors` and `/api/sensors/event` APIs
  * Simple presence heuristics
* **Sprint 2 (2 weeks)**

  * Presence fusion model (combine multiple sensors)
  * `state_estimator.py` integration with State Engine
  * End-to-end tests with simulated personas

## Acceptance Criteria

* Presence predictions remain stable under noisy inputs (no flicker between `home`/`away`).
* Estimator produces consistent `presence`, `occupied_rooms`, and `activity` signals that appear in:

  * `/api/state`
  * and are consumable by Cognitive Layer & Planning.

---

## 💙 PHASE 5 — Emotional Personalized AI

### Purpose

Give the agent a *personality* and emotional awareness so it feels like **your** assistant, not a generic bot.

### Goals

* Build a persistent **persona profile** per primary user.
* Implement **emotional state estimation** from text (and later voice).
* Adapt:

  * tone,
  * verbosity,
  * suggestion style
    based on personality + emotional state.

### Success Metrics

* In a small annotated sample of conversations, tone adaptation is rated “appropriate” in **≥ 85%** of cases.
* Emotional inference precision **> 70%** for basic emotional buckets:

  * tired,
  * happy,
  * annoyed,
  * neutral.

### Features

1. **Personality Profile (`personality_profile.py`)**

   * Stores:

     * `humor_level` (low/med/high),
     * `directness` (soft/neutral/blunt),
     * `formality` (casual/neutral/formal),
     * `verbosity` (short/normal/detailed).
   * Also some domain prefs: “hates bright white lights”, “likes warm tone”, etc.
   * Editable via API or config.

2. **Emotional State (`emotional_state.py`)**

   * Combines:

     * recent sentiment from text,
     * frequency of commands,
     * recent automations (e.g., late-night activity),
   * Outputs coarse emotional state with a confidence score.

3. **Tone Adapter (`tone_adapter.py`)**

   * Wraps responses from LLM/agent with:

     * different phrasing templates,
     * different level of explanation,
     * “Arfaz-style” flavor if you want it.
   * Respects safety: emergency / critical warnings stay neutral/clear.

4. **Preference Evolution**

   * Updates profile based on:

     * explicit feedback: “don’t do that”, “that’s perfect”,
     * implicit behavior: always overriding the same suggestion.

### APIs & Data Models

* `GET /api/personality/{user_id}`
  → returns current persona profile
* `POST /api/personality/{user_id}`
  → update profile fields (tone, verbosity, etc.)
* `POST /api/personality/{user_id}/feedback`
  `{ "response_id": "...", "liked": true/false }`

**Internal models:**

```json
{
  "user_id": "arfaz",
  "humor": "medium",
  "directness": "blunt",
  "formality": "casual",
  "verbosity": "normal",
  "context_tags": ["night_owl", "builder"]
}
```

### Security & Privacy

* Personality & emotion data = **sensitive**:

  * opt-in only.
  * export/delete endpoints must exist.
* No personality profile data is sent to cloud LLM unless:

  * explicitly allowed,
  * and scrubbed to avoid identity leakage.

### Test Plan

* Unit tests for:

  * profile CRUD,
  * tone adapter template selection,
  * emotional state transitions.
* Snapshot tests for responses under different persona configs:

  * `blunt + casual`,
  * `soft + formal`, etc.
* Regression: ensure safety-critical outputs ignore persona (no jokey fire alarms).

### Milestones (3 sprints)

* **Sprint 1 (1 week)**

  * Persona model & storage
  * `GET/POST /api/personality`
* **Sprint 2 (1 week)**

  * Emotional estimator integrated with dialog/commands
* **Sprint 3 (2 weeks)**

  * Tone adapter tied into all user-facing responses
  * Feedback loop + tuning

### Acceptance Criteria

* Persona stored, retrieved and editable via API & config.
* Observably different tone/styles between different persona profiles.
* Safety-critical responses do **not** change tone in risky ways.

---

## 🎯 PHASE 6 — Mission-Level Autonomy

### Purpose

Move from one-shot commands (“turn this on”) to **multi-day missions** like:

* “I’m going on a trip.”
* “Help me sleep better.”
* “Optimize my energy usage this month.”

### Goals

* Define a **Mission** abstraction:

  * high-level goal,
  * sub-goals,
  * plans over time.
* Implement mission planner + executor + simulator.

### Success Metrics

* **0 safety violations** in 10,000 simulated mission-hours.
* Mission completion rate **> 95%** under normal conditions.
* Mission restart after process restart works reliably (checkpointing).

### Features

1. **Mission Planner (`mission_planner.py`)**

   * Input: mission template + parameters.
     e.g. `"vacation_mode"`, `{ start_date, end_date, pets: true }`
   * Output:

     * timeline of actions,
     * triggers (time, presence, anomalies),
     * constraints.

2. **Mission Executor (`mission_executor.py`)**

   * Manages state machine:

     * `PENDING → RUNNING → PAUSED → COMPLETED / FAILED`.
   * Uses:

     * Plan Executor (Phase 3),
     * Sensor Fusion (Phase 4),
     * Cognitive predictions.

3. **Mission Simulator (`mission_simulator.py`)**

   * Runs missions against **simulated history/sensors**
   * Used for:

     * offline testing,
     * dry-run in UI (“show me what vacation mode would do”).

4. **Reporting & Notifications**

   * Per mission:

     * status,
     * last actions,
     * upcoming actions,
     * anomalies (“front door opened while in vacation mode”).

### APIs & Data Models

* `POST /api/mission/start`
  `{ "template": "vacation_mode", "params": { ... } }` → `{ "mission_id": "..." }`
* `GET /api/mission/{id}`
  → `{ status, progress, next_actions, anomalies }`
* `POST /api/mission/{id}/pause`
* `POST /api/mission/{id}/resume`
* `POST /api/mission/{id}/stop`

**Mission model (internal):**

```json
{
  "id": "mission_123",
  "template": "vacation_mode",
  "status": "running",
  "goals": ["reduce_energy", "simulate_presence", "security"],
  "checkpoints": [],
  "plans": [ /* references to plan graphs */ ]
}
```

### Security & Privacy

* High-risk actions (locks, shutters, alarms) allowlisted per user.
* Full mission audit log:

  * when,
  * why,
  * triggered by what context.

### Test Plan

* End-to-end simulations for each mission template.
* Inject failures:

  * sensor offline,
  * device unreachable,
  * state corruption.
* Verify:

  * watchdogs,
  * checkpoint restore,
  * user notifications.

### Milestones (3 sprints)

* **Sprint 1 (1 week)**

  * Mission schema, basic planner
  * Start/stop APIs
* **Sprint 2 (2 weeks)**

  * Executor with checkpoints & failure handling
  * Integrate with Plan Executor
* **Sprint 3 (1 week)**

  * Simulator + mission status reporting
  * UI hooks (at least JSON in web dashboard)

### Acceptance Criteria

* Mission survives process restart and continues from last checkpoint.
* “Vacation mode” mission:

  * lowers energy,
  * simulates presence at night,
  * never disables high-risk devices outside policy.

---

## 🧠 PHASE 7 — Internal Reasoning Console (Jarvis Core UI)

### Purpose

Make the system’s “mind” visible:

* what it knows,
* what it predicts,
* why it chose a specific action.

This is where it starts feeling **alive**.

### Goals

* Visualize:

  * plans,
  * predictions,
  * patterns,
  * missions,
  * sensor fusion outputs.
* Provide:

  * audit trail of LLM reasoning + tool calls,
  * UI to dry-run plans and approve risky actions.

### Success Metrics

* 100% of executed plans have:

  * a matching reasoning log entry,
  * visible in UI.
* Reasoning queries:

  * p95 latency < 200ms for last 1000 entries.

### Features

1. **Reasoning Log (`reasoning_log.py`)**

   * Structured entries:

     * timestamp,
     * source (LLM/learning/mission),
     * input context,
     * tools used,
     * decisions taken.
   * Queryable via API:

     * filter by device, time window, mission.

2. **Plan Graph View (`plan_graph_view.py`)**

   * Shows DAG:

     * nodes = actions,
     * edges = dependencies,
     * colored by status (pending/running/success/failure).
   * Supports:

     * hovering for details,
     * step logs.

3. **Patterns & Insights View (`patterns_view.py`)**

   * Visualizes:

     * wake/bedtime drift,
     * recurring patterns,
     * candidate automations (with “accept / reject” UX).

4. **Mission Dashboard**

   * All active missions, their state, and recent anomalies.

5. **Safety Panel**

   * Policies:

     * which devices are high-risk,
     * what the LLM is allowed/blocked from doing,
     * toggles for strict/safe mode.

### APIs & Data Models

* `GET /api/reasoning?limit=100&device_id=switch_1`
* `GET /api/plans/{id}` → plan graph + status
* `GET /api/patterns` → trends/habits summary
* `GET /api/missions` → current missions summary
* `POST /api/plan/dryrun` { plan_id } → simulated outcome

### Security & Privacy

* Reasoning console default accessible only on:

  * localhost,
  * or authenticated session.
* Logs store **minimal PII**; full raw logs available only in secure “debug mode”.

### Test Plan

* UI E2E tests:

  * plan graph render,
  * log filtering,
  * performance under 10k log entries.
* Consistency tests:

  * each executed plan has a corresponding log entry.
* Security tests:

  * console not accessible without proper auth (when enabled).

### Milestones (3 sprints)

* **Sprint 1 (1 week)**

  * Reasoning log backend + simple `/api/reasoning`
  * Basic HTML/JSON UI in existing Flask app
* **Sprint 2 (2 weeks)**

  * Plan graph + patterns view
  * Pagination & filters
* **Sprint 3 (1 week)**

  * Mission dashboard + safety panel
  * Polishing & docs

### Acceptance Criteria

* You can open the web UI and see:

  * what the agent is thinking,
  * why it did something,
  * what it plans to do next.
* You can **dry-run** a plan and approve/deny before execution.

---

## 🌐 Cross-Phase Non-Functional Requirements (NFRs)

1. **Security**

   * Local-first by default.
   * Cloud LLM only with explicit opt-in.
   * High-risk actions guarded with extra confirmations.

2. **Privacy**

   * Export + delete for:

     * memory,
     * conversation logs,
     * personality profiles.
   * Configurable retention windows (events vs summaries).

3. **Reliability & Safety**

   * Atomic persistence.
   * Rate-limiting (500ms per endpoint).
   * Watchdogs for missions and schedulers.

4. **Performance**

   * Event → state update: **< 50ms (p99)**.
   * API response: **< 200ms (p95)**.
   * Embedding lookup: **< 50ms (p95)**.

5. **Observability**

   * Structured logs.
   * Metrics (Prometheus-ready).
   * Trace IDs for plans/missions.

6. **CI/CD**

   * Tests for each module.
   * Aggressive test suite you already have stays the base.

7. **Extensibility**

   * Everything adapter-based:

     * LLM,
     * STT/TTS,
     * storage,
     * vector DB.

---

## 🗺️ High-Level Roadmap (recap)

* **Phase A (infra)** → folders, stubs, CI.
* **Phase 1** → Cognitive Layer (memory + prediction).
* **Phase 2** → Conversation & voice.
* **Phase 3** → Plan graphs + executor.
* **Phase 4** → Sensor fusion.
* **Phase 5** → Personality + emotional layer.
* **Phase 6** → Missions.
* **Phase 7** → Reasoning console UI.

---

