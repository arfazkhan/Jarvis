# Home Agent — **Technical PRD**

**Depth:** Technical (full internal engineering Bible)
**Audience:** Firmware engineers, backend devs, ML engineers, system architects, QA, hardware engineers
**Date:** 2025-11-23
**Owner:** Arfaz Khan Hijas Khan

---

> **Executive summary (1–2 lines)**
> Build “Home Agent”: an LLM-driven, local-first home automation platform controlling a custom **ESP32-H2 8-gang Matter-over-Thread** switch. The system reasons, executes, learns patterns, and creates/edits automations autonomously while keeping safety and auditable control.

---

# Table of contents

1. Vision & success metrics
2. Scope (in-scope / out-of-scope)
3. Functional requirements (detailed)
4. Non-functional requirements (NFRs) & constraints
5. System architecture (components + interactions)
6. Hardware specification & schematics (detailed)
7. Firmware spec (ESP-Matter) — endpoints, clusters, flows
8. Matter Controller spec (Python) — APIs & behavior
9. Agent software design — modules, data flows, sequence diagrams
10. LLM integration — prompts, tool schema, safety patterns
11. Data model & event schemas
12. Automation & learning engine — algorithms and rules
13. Security, privacy & fail-safes
14. Testing plan & QA strategy
15. Deployment, CI/CD, OTA, monitoring
16. BOM, cost estimate, procurement notes
17. Roadmap, milestones, timeline (detailed)
18. Risks, mitigations, alternatives
19. Appendix (GPIO map, sample prompts, example sequences, CLI examples)

---

# 1. Vision & success metrics

**Vision:** An on-premises home automation brain that reasons like a human (using LLMs), executes through Matter over Thread, learns user habits, and safely creates/modifies automations — all while owning the entire stack.

**Primary success metrics (first 6 months):**

* Functional: Ability to run 95% of valid tool calls end-to-end on real hardware (LLM → matter_controller → ESP32 relays).
* Latency: Median decision-to-action time ≤ 1.5s for local LLM calls; ≤ 2.5s if using cloud LLM.
* Reliability: 99% uptime for the local agent on target hardware.
* Safety: 0 unsafe actions (high-risk device actions) without explicit confirmation.
* Learning: System suggests ≥1 useful routine per 30 active days and 60% adoption rate for suggested automations after user confirmation.
* Resource usage: Local agent runs within 60% CPU and 70% RAM on target mini-PC (Raspberry Pi 4 / Orange Pi 5 equivalent) under typical load.

---

# 2. Scope

**In-scope (MVP → v1):**

* ESP32-H2 8-relay device firmware (Matter over Thread, 8 On/Off endpoints).
* Thread commissioning via Border Router (HomePod mini / Nest Hub / OpenThread BR).
* Python-based Home Agent on Orange Pi/RPi/mini PC.
* Event Bus, State Engine, Tool Executor, Automation Engine, Learning Engine.
* LLM integration (cloud first, hybrid later). Tool-calling style.
* Virtual device simulation for dev.
* CLI and minimal web UI for inspecting state, approving routines, and manual exec.
* OTA support for ESP32 (ESP-IDF / ESP-Matter pattern).
* Logging and basic monitoring.

**Out-of-scope (v1):**

* Hardware enclosure certification, mass production.
* Integrated wake-word hardware; advanced always-on mic array.
* Per-channel energy metering (can be added v2).
* Integration with external proprietary cloud ecosystems (beyond Matter discovery).
* Full local LLM for heavy reasoning (optional future).

---

# 3. Functional requirements (FRs)

## FR-001 Device control

* FR-001.1: Agent must send On/Off commands to any endpoint on the ESP32 device via Matter controller API.
* FR-001.2: System must read and persist device state changes from hardware events.

## FR-002 Event stream

* FR-002.1: All system events (relay_toggled, voice_command, time_tick, presence_update, routine_trigger) must be published on Event Bus.
* FR-002.2: Event Bus must support subscription by component and guarantee in-order delivery per event source.

## FR-003 LLM reasoning & tools

* FR-003.1: LLM must receive state_summary + latest_event + available_routines + safety_profile and return structured tool calls only.
* FR-003.2: System must support tool schema: turn_on, turn_off, set_level, create_routine, modify_routine, run_routine, ask_user, log_note.

## FR-004 Automation creation & execution

* FR-004.1: Learning Engine must produce candidate routines based on history and propose via ask_user for approval.
* FR-004.2: Upon user approval, create_routine stores routine and schedules triggers.

## FR-005 Safety & confirmation

* FR-005.1: Actions controlling high-risk devices (heaters, door locks) must require explicit human confirmation.
* FR-005.2: System must maintain an audit trail (who/what/when) for all actions and routine creations.

## FR-006 Learning Engine

* FR-006.1: Runs on configurable cadence (default 60 minutes), analyzes last N events, suggests up to 3 routines.
* FR-006.2: Avoids duplicating existing routines; ensures conservatism thresholds (e.g., pattern occurs ≥ X times in Y days).

## FR-007 Developer ergonomics

* FR-007.1: VirtualMatterDevice to fully emulate endpoints for offline dev.
* FR-007.2: CLI tooling to simulate events: `ha-cli event publish --type relay_toggled ...`.

## FR-008 OTA & firmware

* FR-008.1: Supports OTA update for ESP32 via Matter OTA mechanisms.
* FR-008.2: Firmware must support factory reset & fresh commissioning.

## FR-009 Telemetry & monitoring

* FR-009.1: Agent logs events/decisions to file (structured JSON) and rotates logs.
* FR-009.2: Basic health endpoint (HTTP) for uptime, memory, event queue length.

---

# 4. Non-functional requirements (NFRs) & constraints

* **Latency:** Decision cycle (event → LLM → tool call → matter command) median ≤ 1.5s local/ ≤ 2.5s cloud.
* **Throughput:** Agent must handle 20 events/sec burst without loss.
* **Availability:** 99% uptime for the agent process; automated restart on crash.
* **Scalability:** Support multiple devices (≥ 10 devices / 100 endpoints) without redesign.
* **Security:** TLS for any cloud communication; device-to-agent communication local and authenticated.
* **Privacy:** All persistent logs and user data stored locally; explicit opt-in for cloud LLM calls.
* **Testability:** Unit tests for each module; integration tests with virtual device, staging hardware.
* **Maintainability:** Clear module boundaries; documented APIs; automated tests.
* **Power:** Target agent host must operate within typical RPi/Orange Pi power envelope.

---

# 5. System architecture

## 5.1 Logical components

* **ESP32-H2 8-Gang Switch (Device Layer)** — Matter endpoint device.
* **Thread Border Router** — existing device.
* **Matter Controller** — Python interface to CHIP tooling / SDK.
* **Event Bus** — local pub/sub.
* **State Engine** — canonical home model & history.
* **LLM Agent** — decision-making component; issues tool calls.
* **Tool Executor** — executes tool calls (calls Matter Controller / automations).
* **Automation Engine** — stores schedules & triggers.
* **Learning Engine** — periodic pattern detection -> suggestions.
* **Voice Pipeline (optional)** — STT/TTS integration (Whisper/Coqui).
* **CLI / Web UI** — ops & approvals.
* **Logging & Monitoring** — health & audit logs.

## 5.2 Deployment topology

* Single host (Orange Pi / RPi / mini PC) runs: Event Bus, State Engine, LLM Agent, Automation, Learning, Matter Controller.
* Local network includes Thread Border Router bridging Thread to IP.
* ESP32-H2 devices join Thread network and are reachable by Matter Controller via BR.

## 5.3 Interaction flow (simplified sequence)

1. Device (ESP32) endpoint toggled (by user or tool) → Thread message → Border Router → Matter Controller emits event → Event Bus.
2. State Engine updates model and persists event.
3. Event Bus notifies LLM Agent (if subscribed) — LLM takes context + returns tool calls.
4. Tool Executor receives tool calls → calls Matter Controller → action executed.
5. Action triggers device state change event → loop continues.
6. Learning Engine periodically ingests history and requests routine proposals from LLM.

---

# 6. Hardware specification & schematics

> **Prototype mode — LOW-VOLTAGE test (recommended during development).** Do not wire mains until you understand isolation, clearances, and safety.

## 6.1 Core components

* **MCU:** ESP32-H2 Mini Dev Board (supports 802.15.4, BLE, IEEE 802.15.4 radio, 3.3V IO)

  * Key pins: 8 usable GPIO outputs for relays; UART for flashing & debug; USB-C for power.
* **Relay board:** 8-channel 5V relay module (optocoupler + transistor driver recommended).
* **Level shifter:** 8-channel bi-directional (A-side 3.3V, B-side 5V) or transistor drivers (ULN2803) — ensures robust triggering.
* **Power supply:** 5V @ ≥ 2A (to drive relays) + 3.3V regulator (if powering ESP32 separately). Recommended: isolated 5V supply during mains switching.
* **PCB:** Custom PCB recommended for production; prototyping via perfboard acceptable.
* **Connectors & safety:** Terminal blocks for mains (when present) with proper spacing; fuse, surge protection.

## 6.2 Electrical wiring (prototype, low-voltage)

* ESP32 3.3V → Level shifter VCCA
* ESP32 GND → common GND
* Level shifter VCCB → 5V power supply
* Relay VCC → 5V
* Relay GND → GND (shared)
* ESP32 GPIOx → Level shifter A1..A8 → B1..B8 → Relay IN1..IN8

## 6.3 AC mains wiring (production; documented, follow safety)

* Mains Live → Relay COM
* Relay NO → Load Live
* Load Neutral → Neutral bus
* Use opto-isolated relay modules / SSR for inductive loads
* Include RC snubbers where needed
* Use proper creepage, clearance, fuses, and earth bonding

## 6.4 PCB-level considerations

* Keep MCU and relay high-voltage traces separated with isolation barrier.
* Add TVS diodes and flyback diodes (if switching DC inductive loads).
* Add an EMI filter and snubber circuits for inductive loads.
* Use screw terminal connectors for field wiring.

---

# 7. Firmware spec (ESP-Matter)

## 7.1 Firmware stack

* **ESP-IDF** (latest stable compatible with ESP32-H2)
* **ESP-Matter** (Espressif’s Matter implementation)
* OpenThread port (built-in with ESP-IDF on H2)
* Application layer for mapping Matter OnOff cluster to GPIOs and relay driver.

## 7.2 Matter model (device definition)

* **Device Type:** On/Off Light or Switch (use On/Off cluster)
* **Endpoints:** 8 logical endpoints (IDs: 1..8)
* **Clusters:** On/Off cluster per endpoint; Basic, Descriptor, Identify clusters as needed
* **Attributes:** OnOff attribute for each endpoint; optional Name/Location

## 7.3 Behavior

* **On/Off command** → write to GPIO → toggle relay via driver → send attribute report (report-on-change).
* **Attribute reporting:** report On/Off changes back to controller.
* **Local pushbuttons (optional):** read GPIO on interrupts and update cluster attributes and report back.
* **Commissioning:** Matter commissioning via QR code / setup code (displayable via serial log or e-paper on production board).
* **OTA:** Support Matter OTA image generation & apply.

## 7.4 Thread behavior

* Use OpenThread configuration: Short Poll Interval defaults (or adjust for battery devices if any).
* Ensure device can join fabric and auto-reconnect after BR outage.

## 7.5 Safety & watchdogs

* Hardware watchdog that reboots MCU if firmware hung.
* Graceful state recovery after reboot using persisted attributes (NVS).

## 7.6 Example pseudo-code (OnOff handler)

```c
on_onoff_command(endpoint, value) {
    gpio_write(RELAYS[endpoint], value);
    update_onoff_attribute(endpoint, value);
    report_attribute(endpoint, "OnOff", value);
}
```

---

# 8. Matter Controller (Python) — spec & APIs

## 8.1 Purpose

Abstract Matter interactions for the Tool Executor. Provide discovery, read, write, subscription to device events.

## 8.2 Implementation options

* **Option A:** Use `chip-tool` CLI calls wrapped by subprocess — quicker to prototype.
* **Option B:** Use Python Matter SDK (if available and stable) — cleaner integration.
* **Option C:** Use third-party libs that wrap CHiP (evaluate stability).

Start with Option A during dev, migrate to SDK.

## 8.3 API surface (module: `matter_controller.py`)

```python
class MatterController:
    def discover() -> dict  # returns {device_id: {endpoints: [1..n]}}
    def turn_on(device_id: str, endpoint: int) -> bool
    def turn_off(device_id: str, endpoint: int) -> bool
    def set_level(device_id: str, endpoint: int, level: int) -> bool
    def read_state(device_id: str, endpoint: int) -> dict
    def subscribe_events(callback) -> subscription_handle
    def unsub(handle)
```

## 8.4 Event handling

* MatterController must convert incoming attribute reports to Event Bus events:

  * `relay_toggled` with payload `{device, endpoint, state}`
* Gracefully handle transient network issues; retry with exponential backoff.

## 8.5 Error behavior

* Sync (blocking) APIs return success/failure; synchronous tooling should raise exceptions for non-recoverable errors.
* All calls produce structured logs.

---

# 9. Agent software design — modules, data flows, sequence diagrams

## 9.1 Module responsibilities (recap)

* **event_bus:** pub/sub core
* **state_engine:** canonical model + history
* **llm_agent:** receives events and state summary; calls LLM; returns tool calls to be executed
* **tools.executor:** executes tool calls via matter_controller
* **controllers.matter_controller:** abstracts matter
* **automations.automation_engine:** stores routines & triggers them
* **learning.learning_engine:** periodically requests pattern detection
* **voice:** optional STT/TTS wrapper

## 9.2 Data flow (detailed sequence)

**Sequence: voice command → bedtime routine creation**

1. Mic/STT converts audio to text → publish `voice_command` event with `payload: {text}`.
2. EventBus → LLM Agent subscribed to `voice_command`.
3. LLMAgent composes context:

   * `state_summary = state_engine.summary()` (human-readable)
   * `event` (voice_command)
   * `routines = automation_engine.list()`
   * `preferences`, `safety`
4. LLMAgent calls cloud LLM with `SYSTEM_PROMPT` + `TOOLS_SCHEMA`.
5. LLM returns tool calls:

   * `[{"tool":"create_routine","args":{...}}, ... ]`
6. Tool Executor receives tool calls:

   * For create_routine: call automation_engine.create(...) and log
7. Automation Engine persists routine to DB and schedules triggers
8. Tool Executor publishes `routine_created` event
9. StateEngine appends history and updates summaries.

## 9.3 Sequence diagram (text)

```
User -> Mic/STT -> EventBus (voice_command)
EventBus -> LLMAgent -> LLM -> LLMAgent (tool_calls)
LLMAgent -> ToolExecutor -> MatterController -> Thread -> Device
Device -> BorderRouter -> MatterController -> EventBus -> StateEngine
```

---

# 10. LLM integration — prompts, tool schema, safety patterns

We already created System Prompt and Tool Schema earlier. Repeat and expand here with safety constraints and examples.

## 10.1 System prompt (engineer-friendly)

* Contains goals, rules, safety constraints, and the instruction: **Return only JSON tool calls**.
* Emphasize idempotency and no side effects without explicit tool use.

(Use `agent/llm_agent/prompt.py` as canonical source.)

## 10.2 Tool schema (canonical)

* Tools: turn_on, turn_off, set_level, create_routine, modify_routine, run_routine, ask_user, log_note.
* For function-calling, use the provider's tool/schema mechanism or a structured JSON response that you parse.

## 10.3 Safety guardrails

* Provide `safety` object in context with:

  * `high_risk_devices: ["heater_1","door_lock_1"]`
  * `quiet_hours: [{start: "23:00", end:"06:00"}]`
  * `max_daily_autocreate: 5`
* LLM must call `ask_user` before creating or modifying automations for high-risk or nighttime actions.

## 10.4 Prompt engineering best practices

* Keep `state_summary` compact (≤ 200 tokens) but informative (room states + time + recent 5 events).
* For learning cycles, send compressed statistics, e.g., frequency of action X in time bucket Y.

## 10.5 Example payload to LLM (condensed)

```json
{
  "event": {...},
  "state_summary": "Living room: endpoints 1 ON,2 OFF; bedroom all OFF; time 23:05; presence: home; last_events: ...",
  "routines": {...},
  "preferences": {...},
  "safety": {"high_risk_devices":["heater_1"], "quiet_hours":[{"start":"23:00","end":"06:00"}]}
}
```

---

# 11. Data model & event schemas

## 11.1 Event format

```json
{
  "id": "<uuid4>",
  "type": "relay_toggled|voice_command|time_tick|presence_update|routine_trigger|automation_created",
  "source": "matter_controller|llm_agent|user|learning_engine",
  "timestamp": 1700750000.123,
  "payload": { ... }
}
```

## 11.2 Relay toggled payload

```json
{
  "device": "switch_1",
  "endpoint": 3,
  "state": "on",
  "cause": "user|agent|automation",
  "meta": { "source_tx_id": "..."}
}
```

## 11.3 Routine definition

```json
{
  "name": "bedtime",
  "trigger": {"type":"time", "cron": "23:30"},
  "conditions": [{"type":"presence", "value":"home"}],
  "actions": [
    {"tool":"turn_off", "args": {"device_id":"switch_1","endpoint":1}},
    {"tool":"turn_on", "args": {"device_id":"switch_1","endpoint":8}}
  ],
  "created_by": "learning_engine|user",
  "created_at": 1700750000
}
```

## 11.4 State model

```json
{
  "time": "2025-11-23T23:20:00Z",
  "presence": "home|away",
  "rooms": {
    "living_room": {"devices": {"switch_1": {1:"on",2:"off"}}}
  },
  "history": [<events>],
  "routines": {...}
}
```

---

# 12. Automation & learning engine — algorithms and rules

## 12.1 Learning algorithm (MVP)

* Input: last N events (N configurable, default 200), last M days (configurable).
* Preprocessing:

  * Aggregate events by time-of-day buckets (hourly).
  * Identify action sequences (A → B within T minutes).
  * Count frequencies and compute confidence score: `p = occurrences / observed_days`.
* Heuristic for action → routine proposal:

  * Pattern occurs ≥ 4 times in last 7 days → confidence high.
  * Sequence length ≤ 4 actions.
  * Occurs within same time window ±15 minutes.
* Output: up to 3 candidate routines with confidence and human-readable explanation.
* For each candidate:

  * If a similar routine exists (Jaccard overlap ≥ 0.7), skip.
  * Otherwise produce tool_calls: `create_routine(...)` and `ask_user(...)`.

## 12.2 Advanced learning (v2+)

* Use embedding-based similarity for action clusters.
* Use simple time-series models (exponential smoothing) to detect trends.
* Use small local model (LSTM/Transformer) to predict next action (for advanced proactive suggestions).

## 12.3 Automation triggering & conditions

* Routines have triggers: time-based (cron), event-based (no motion X), composite conditions (presence home AND time window).
* Automation engine uses scheduler (APScheduler or cron) for time triggers; event-based triggers use Event Bus.

---

# 13. Security, privacy & fail-safes

## 13.1 Local-first & cloud opt-in

* Default: all processing local. Cloud LLM usage must be opt-in.
* If cloud LLM used, only send minimal context (hash device IDs, avoid PII).

## 13.2 Authentication & access control

* Agent exposes management HTTP endpoint protected by token (configurable) and local IP restriction.
* CLI and UI require token-based auth.

## 13.3 Audit & immutability

* All actions and decisions logged with timestamp, actor (LLM/agent/user), and tool calls (append-only).
* Provide an audit exporter.

## 13.4 Fail-safe rules

* Timeouts: LLM tool call execution must time out if not completed within T seconds (configurable).
* Circuit breaker: if external LLM errors exceed threshold, switch to safe mode (no new automations).
* Safety whitelist/blacklist of devices (only known devices can be auto-controlled).

## 13.5 Firmware & OTA security

* Signed OTA images only. Use Matter OTA signing recommended flow.

---

# 14. Testing plan & QA strategy

## 14.1 Unit tests

* Event Bus, State Engine, Automation Engine, Tool Executor (mock matter), Learning Engine (simulate history).

## 14.2 Integration tests (software-only)

* Start agent with Virtual Matter Device; inject events; assert state transitions; assert LLM responses mocked.

## 14.3 Hardware-in-the-loop tests

* ESP32-H2 on bench, virtual matter controller replaced with chip-tool; run automated sequences verifying relay clicks and attribute reports.

## 14.4 LLM testing strategy

* Use mocking for LLM responses in CI.
* Integration tests with deterministic LLM (seeding or using small local model) to verify tool call parsing.

## 14.5 Safety tests

* Simulate edge cases that trigger safety constraints (nighttime, high-risk devices).
* Tests to ensure ask_user is called before high-risk actions.

## 14.6 Load tests

* Flood Event Bus with events (20/s) and verify state engine and agent hold up.

## 14.7 Regression & e2e

* Scenarios: voice → create routine; learning → propose routine; routine trigger → actions; manual override → learning adaptation.

---

# 15. Deployment, CI/CD, OTA, monitoring

## 15.1 CI/CD

* Repo runs unit tests on PR. Linting + static analysis.
* Integration tests run in a staging CI job with virtual device.
* Release pipeline produces Docker image for agent, and signed ESP32 firmware artifacts.

## 15.2 Deployment

* Agent can be run as systemd service or a Docker container on RPi/Orange Pi.
* Provide install script & config wizard.

## 15.3 OTA

* ESP-Matter supports Matter OTA workflows (CHIP OTA).
* Provide staging and production OTA servers.

## 15.4 Monitoring & health

* Expose `/health` endpoint with metrics: memory, CPU, event backlog, last LLM call time.
* Optional push to external monitoring (Prometheus / Grafana) — local-first preference.

---

# 16. BOM, cost estimate, procurement notes

**Prototype per unit:**

* ESP32-H2 Mini Dev Board — ₹999 (estimate)
* 8-channel relay module — ₹400–₹800
* 8-channel level shifter / driver — ₹200–₹500
* 5V 2A power supply — ₹300
* Terminal blocks, wires, perfboard — ₹300
* Misc (enclosure, screws) — ₹300

**Total prototype cost:** ≈ ₹2500–₹3500 per unit

**Procurement notes:**

* Buy relay boards with optocouplers & transistor drivers.
* Get a stable 5V isolated supply for mains switching stage.
* Buy 2–3 ESP32-H2 dev boards for development and backups.

---

# 17. Roadmap, milestones, timeline (detailed)

*Assume a single full-time engineer + part-time ML engineer + firmware engineer. Adjust resource accordingly.*

**Week 0 (prep):** environment, repo, virtual device, basic skeleton.
**Week 1–2:** Build hardware prototype (ESP32 perfboard + relays) & get ESP-Matter example on H2 working with single endpoint.
**Week 3:** Expand to 8 endpoints; basic attribute reporting; commissioning test.
**Week 4:** Matter Controller wrapper (Python, CLI) + virtual device integration.
**Week 5–6:** Build Event Bus, State Engine, Tool Executor, Automation Engine; CLI & small web UI.
**Week 7–8:** Integrate LLM Agent with tool schema; simple voice command flow; first end-to-end tests with virtual device.
**Week 9–10:** Learning Engine; scheduled learning cycles; propose routines; UI approval flow.
**Week 11:** Hardware-in-the-loop; commission ESP32 device to BR; test end-to-end with actual relays (low-voltage).
**Week 12:** Safety audits, OTA flow test, logging & monitoring, QA passes.
**Week 13–14:** Polish, documentation, and demo package.

---

# 18. Risks, mitigations, alternatives

## Risk: ESP32-H2 availability or delays

**Mitigation:** Use virtual device & begin all software work. Consider backup: Nordic nRF7000 or similar Thread-enabled dev boards (evaluate porting cost).

## Risk: Matter/CHIP tooling instability

**Mitigation:** Start with chip-tool and keep SDK abstraction; maintain fallback.

## Risk: LLM hallucinations causing bad automations

**Mitigation:** Strict safety schema; require ask_user for risky changes; have kill-switch; log all decisions.

## Risk: Thread BR availability in test environment

**Mitigation:** Use OpenThread Border Router dev board as temporary BR.

## Risk: Mains safety & certification

**Mitigation:** Extensive safety documentation; testing with low-voltage loads before mains; consult certified electrician for production.

---

# 19. Appendix

## 19.1 GPIO mapping (recommended)

| Endpoint | Relay Input | ESP32-H2 GPIO |
| -------- | ----------- | ------------- |
| 1        | IN1         | GPIO2         |
| 2        | IN2         | GPIO3         |
| 3        | IN3         | GPIO4         |
| 4        | IN4         | GPIO5         |
| 5        | IN5         | GPIO6         |
| 6        | IN6         | GPIO7         |
| 7        | IN7         | GPIO8         |
| 8        | IN8         | GPIO9         |

(Validate chosen GPIOs on your exact H2 dev board pinout; avoid strapping pins and reserved pins.)

## 19.2 Sample LLM prompt (condensed)

Use `agent/llm_agent/prompt.py` (system prompt + tool schema). Key lines:

* “You are Home Agent… NEVER output plain text, only JSON tool calls.”
* Provide `state_summary` concise and `recent_events` list.

## 19.3 Example tool call (JSON)

```json
[
  {"tool":"turn_off","args":{"device_id":"switch_1","endpoint":2}},
  {"tool":"ask_user","args":{"message":"Should I make this a bedtime routine?"}}
]
```

## 19.4 Example test scenarios

* Scenario A: Night timeout — living room left ON, no motion 20 min → agent turns off non-bedroom lights and asks to create routine.
* Scenario B: Multi-step command — “prepare for sleep” → turn off living room, dim bedside, turn on night light.
* Scenario C: Learning cycle proposes routine — user approves — repeated run confirm.

## 19.5 Developer CLI examples

* Publish event:

  ```
  ha-cli event publish --type relay_toggled --device switch_1 --endpoint 3 --state on
  ```
* Run routine:

  ```
  ha-cli routine run --name bedtime
  ```

---

