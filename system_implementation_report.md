# Home Agent - System Implementation Report
**Date:** Mon Nov 24 2025
**Status:** Software Prototype / MVP Complete

## 1. System Architecture
The system implements a **local-first, event-driven architecture** designed to run on a single host (e.g., Raspberry Pi). It decouples decision-making (LLM) from execution (automation engine) via a synchronous Event Bus.

### Data Flow
1.  **Events** (e.g., sensor readings, time ticks) are published to the `EventBus`.
2.  **State Engine** consumes events, updates the canonical state model, and persists changes to disk.
3.  **Automation Engine** triggers routines based on time (cron) or event patterns.
4.  **Learning Engine** periodically analyzes history to detect patterns and prompts the LLM for optimizations.
5.  **Tool Executor** translates abstract commands into specific device calls (currently virtual).

## 2. Core Components

### 2.1 Event Bus (`agent/event_bus/event_bus.py`)
- **Implementation:** A lightweight, synchronous Pub/Sub system using a Python dictionary `{"event_type": [callbacks]}`.
- **Behavior:** `publish()` iterates through subscribers and executes them immediately in the caller's thread.
- **Error Handling:** Subscriber exceptions are caught and logged to prevent cascading failures, but individual event processing is not retried.

### 2.2 State Engine (`agent/state_engine/state_engine.py`)
- **State Model:**
  - `devices`: Dictionary mapping `device_id` -> `endpoint_id` -> `state` (on/off).
  - `history`: Rolling buffer of the last 1000 events.
- **Persistence Strategy:**
  - **Atomic Writes:** Uses `StatePersistence` to write to a `.tmp` file before atomically renaming it to `state.json`.
  - **Write Debouncing:** Implements a `dirty` flag and `last_save_time` to limit disk writes to at most once per second (`min_save_interval = 1.0`), preventing IO saturation during burst loads.
  - **Recovery:** On startup, it loads `state.json`. If corrupted, it attempts to load `state.json.backup` or initializes with defaults.

### 2.3 Automation Engine (`agent/automations`)
- **Routine Model:** Routines are JSON objects containing:
  - `trigger`: `{"type": "time", "cron": "..."}` or `{"type": "event", ...}`.
  - `actions`: List of commands (e.g., `control_relay(1, on)`).
  - `conditions`: List of state checks (e.g., `{"presence": "home"}`).
- **Scheduler (`scheduler.py`):**
  - Uses `croniter` library for full Cron syntax support.
  - Runs in a dedicated background thread (`_run_loop`) checking triggers every 5 seconds.
  - Maintains `next_run` timestamps in `routines.json` to handle restarts without missed or duplicate executions.
- **Condition Evaluation:** Before execution, `_check_conditions` verifies the current system state matches requirements.

### 2.4 Intelligence Layer
- **LLM Agent (`agent/llm_agent`):**
  - **Integration:** Wraps the Groq API (`llama-4-scout-17b-16e-instruct`).
  - **Context:** Constructs a prompt containing the current state summary, recent events, and available tools.
  - **Output:** strictly adheres to a JSON tool-call schema (`TOOLS_SCHEMA`) defined in `prompt.py`.
- **Learning Engine (`agent/learning`):**
  - **Pattern Analysis (`pattern_analyzer.py`):**
    - **Clustering:** Groups events occurring within a 2-hour window.
    - **Anomaly Detection:** Uses Z-score (threshold 2.0 std devs) to flag events at unusual times.
    - **Habit Drift:** Calculates weekly averages of "first light on" (wake) and "last light off" (bed) to detect shifts > 30 minutes.
  - **Cycle:** Runs periodically (default 60m) to feed this analysis to the LLM for routine suggestions.

### 2.5 Hardware Abstraction (`agent/controllers`)
- **Matter Controller:** Currently implements a `VirtualMatterDevice` simulating an 8-channel relay board.
- **Real Implementation:** The code for `chip-tool` interaction exists but is commented out/stubbed. The system currently logs `[REAL Matter] ...` actions to stdout without executing shell commands.

### 2.6 Web Interface (`agent/web`)
- **Stack:** Flask application serving a simple dashboard.
- **Capabilities:**
  - Real-time state inspection (`/api/state`).
  - Manual event injection (`/api/event`).
  - Simulation triggers (`/api/simulate`).
  - Visualization of detected patterns and anomalies (`/api/patterns`).

## 3. Security & Safety Features
- **Hardware Rate Limiting:** `AutomationEngine` enforces a 500ms minimum interval between toggles on the same endpoint to prevent relay damage.
- **Concurrency Isolation:** API tests use isolated Flask application contexts to prevent thread leakage.
- **Input Sanitization:** The system is tested against malicious JSON payloads (1MB size) and injection attacks.

## 4. Implementation Gaps vs Production
1.  **Physical I/O:** No actual GPIO or Matter-over-Thread communication is active.
2.  **Voice Stack:** No STT/TTS integration; voice commands must be simulated via text events.
3.  **User Auth:** The API currently has no authentication mechanism (tests assume open access or mock tokens).

## 5. Summary
The codebase represents a **fully functional logic core**. It successfully simulates a smart home environment with persistent state, complex scheduling, and AI-driven learning. It handles "chaos" scenarios (disk corruption, thread exhaustion) gracefully but requires hardware drivers to be operational in the real world.
