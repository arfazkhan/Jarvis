# ARVIS SOTA Implementation Plan
**Date:** 2026-05-18  
**Constraint:** ARVIS is strictly read-only — observes, reasons, recommends. Operators act. No BMS control ever.  
**Starting point:** ~45% SOTA. Target: ~85% SOTA.  
**Audit source:** ARVIS_AGENTIC_AUDIT.md

## Track Status
| Track | Description | Status |
|-------|-------------|--------|
| Track 1 | Wire Existing Memory to Reasoning | ✅ COMPLETE (2026-05-18) |
| Track 2 | Close the Feedback Loop | ✅ COMPLETE (2026-05-18) |
| Track 3 | Goal Execution Tracker | ✅ COMPLETE (2026-05-18) |
| Track 4 | Adaptive ReAct + Tool Error Recovery | ✅ COMPLETE (2026-05-18) |
| Track 5 | Cross-Agent Shared Knowledge Buffer | ✅ COMPLETE (2026-05-18) |

---

## Architecture Overview After Plan

```
                    ┌─────────────────────────────────────────────┐
                    │              PERCEPTION LAYER                │
                    │  BACnet → BMSStateEngine ← Modbus           │
                    │  Virtual Sensors, Water Meter                │
                    └──────────────────┬──────────────────────────┘
                                       │ read-only telemetry
                    ┌──────────────────▼──────────────────────────┐
                    │           MEMORY & CONTEXT LAYER            │
                    │  EmbeddingsStore (FAISS HNSW)               │
                    │  ChromaDB (operator patterns)               │
                    │  memory_manager (SQLite events)             │
                    │  ConversationBuffer (per session_id)        │
                    │  recommendation_outcomes table (new)        │
                    └──────────────────┬──────────────────────────┘
                                       │ semantic recall + history
                    ┌──────────────────▼──────────────────────────┐
                    │         REASONING LAYER (LLM)               │
                    │  _get_dynamic_context() ← FAISS injection   │
                    │  system_prompt ← calibration injection      │
                    │  BMSContext.active_calibration ← MetaCog    │
                    └──────────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────────────┐
                    │           SWARM LAYER (12 nodes)            │
                    │  Queen → intent routing → parallel ReAct    │
                    │  SharedKnowledgeBuffer (new, per-swarm-run) │
                    │  Adaptive max_turns (new)                   │
                    │  Tool error retry with corrected prompt     │
                    └──────────────────┬──────────────────────────┘
                                       │ advisory only
                    ┌──────────────────▼──────────────────────────┐
                    │         ADVISORY & GOAL LAYER               │
                    │  GoalExecutionTracker (new)                 │
                    │  Outcome measurement (read telemetry only)  │
                    │  Feedback → outcomes → calibration loop     │
                    └─────────────────────────────────────────────┘
```

---

## Track 1 — Wire Existing Memory to Reasoning ✅ COMPLETE
**Completed:** 2026-05-18  
**Files changed:** `bms_llm_agent.py`, `main.py`, `api/routes.py`, `arvis_core/swarm/queen.py`

### What was done

**1A — FAISS incident recall** (`bms_llm_agent.py:496-514`)
- `EmbeddingsStore.search(query, limit=3, threshold=0.65)` called at end of `_get_dynamic_context()`
- Top-3 semantically similar past incidents prepended to `history_summary` → injected into every LLM system prompt
- Dead-code double-return removed
- High/critical alarms stored to FAISS in `main.py:913-930` via `_on_alarm_for_correlator()`
- Severity enum `.value` handled correctly (`main.py:914-916`)

**1B — Real episodic memory endpoint** (`api/routes.py:2098-2138`)
- Stub replaced: queries `memory_manager.get_events_in_range(since, until)` for the target calendar day
- FAISS semantic fallback if SQLite returns nothing
- Returns `{day, date, key_events[], event_count}`

**1C — Multi-turn conversation context** (`queen.py:139-148`, `bms_llm_agent.py:872-874`)
- `chat_history` from `context` (already fetched from DB in `routes.py:634-643`) injected into BFT proposer prompt as last-6-message history prefix
- Fast-path `SwarmNode.process()` receives `chat_history` as `history=` param so single-agent path also sees conversation context
- `SwarmNode.process()` already accepts `history: Optional[List[Dict]]` (line 35) — no change needed there

---

### 1A — Wire FAISS Incident Recall into `_get_dynamic_context()`

**Problem:** `EmbeddingsStore.search(query, limit, threshold)` exists and works. Never called during LLM context assembly. Past incidents not retrieved.

**Where to add:** `agent_commercial/bms_llm_agent.py:451` — `_get_dynamic_context()`

**What to add (after line 527, before return):**

```python
# ── Semantic incident recall via FAISS ──────────────────────────────────
similar_incidents: List[str] = []
try:
    from agent_cognitive.embeddings_store import EmbeddingsStore
    store = EmbeddingsStore()
    hits = store.search(query, limit=3, threshold=0.65)
    for hit in hits:
        ts = hit.get("timestamp", "")[:10]
        summary = hit.get("summary", hit.get("text", ""))[:200]
        similar_incidents.append(f"[{ts}] {summary}")
except Exception:
    pass  # FAISS unavailable — degrade gracefully

# Inject into BMSContext.history_summary if incidents found
if similar_incidents:
    recall_block = "\n".join(f"  • {s}" for s in similar_incidents)
    ctx.history_summary = (
        f"Similar past incidents:\n{recall_block}\n\n"
        + ctx.history_summary
    )
```

**Also wire:** When new alarm/energy anomaly is detected, store embedding in FAISS.  
Add to `agent_commercial/main.py` in `_on_point_update()` or alarm callback:

```python
# After alarm is confirmed significant:
try:
    from agent_cognitive.embeddings_store import EmbeddingsStore
    store = EmbeddingsStore()
    store.add_text(
        text=f"{alarm.message} on {alarm.equipment_id} at {alarm.triggered_at}",
        meta={
            "equipment_id": alarm.equipment_id,
            "severity": alarm.severity,
            "timestamp": alarm.triggered_at,
            "summary": alarm.message,
            "type": "alarm",
        }
    )
except Exception:
    pass
```

**Acceptance test:** Query "vibration on CH-01" — BMSContext.history_summary should contain matching past incidents.

---

### 1B — Real Episodic Memory Endpoint

**Problem:** `GET /api/v1/memory/episodic/{day}` returns stub at `routes.py:2098-2104`.

**Replace stub body with:**

```python
@app.get("/api/v1/memory/episodic/{day}")
async def get_episodic_memory(day: int):
    mm = getattr(app.state, "memory_manager", None)
    store = None
    try:
        from agent_cognitive.embeddings_store import EmbeddingsStore
        store = EmbeddingsStore()
    except Exception:
        pass

    key_events = []

    # 1. Recent events from memory_manager (SQLite)
    if mm:
        try:
            from datetime import datetime, timedelta
            target_date = datetime.now() - timedelta(days=day)
            since = target_date.replace(hour=0, minute=0, second=0)
            until = since + timedelta(days=1)
            events = mm.get_events_in_range(since, until)
            for ev in events[:20]:
                key_events.append({
                    "time": ev.get("timestamp", "")[:19],
                    "type": ev.get("event_type", "event"),
                    "source": ev.get("source", ""),
                    "memory": str(ev.get("payload", ""))[:300],
                })
        except Exception:
            pass

    # 2. Semantic search for that day's context
    if store and not key_events:
        try:
            hits = store.search(f"events day {day} days ago", limit=5, threshold=0.5)
            for h in hits:
                key_events.append({
                    "time": h.get("timestamp", "")[:19],
                    "type": h.get("type", "recalled"),
                    "source": "faiss",
                    "memory": h.get("summary", h.get("text", ""))[:300],
                })
        except Exception:
            pass

    return {
        "day": day,
        "date": (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d"),
        "key_events": key_events,
        "event_count": len(key_events),
    }
```

---

### 1C — Multi-Turn Conversation Context Buffer

**Problem:** `chat()` at `bms_llm_agent.py:768` creates fresh context per call. `session_id` exists in API layer (`routes.py:618`) but never passed down to `BMSLLMAgent.chat()`.

**Step 1 — Extend `ChatRequest` schema in routes.py (already has session_id at line 618) — pass it through:**

`routes.py` chat endpoint — after generating/retrieving `session_id`, pass to agent:
```python
response = await copilot.llm_agent.chat(
    query=request.message,
    context={"session_id": session_id, ...},  # ADD session_id here
    channel=request.channel or "chat"
)
```

**Step 2 — Add conversation buffer in `bms_llm_agent.py`:**

In `__init__`:
```python
self._conversation_buffers: Dict[str, List[Dict[str, str]]] = {}
self._buffer_max_turns = 10  # Keep last 10 turns per session
```

In `chat()` before Queen call (around line 848):
```python
session_id = context.get("session_id", "default") if context else "default"

# Retrieve buffer
history = self._conversation_buffers.get(session_id, [])

# Append current user turn
history.append({"role": "user", "content": query})

# Trim to max_turns
if len(history) > self._buffer_max_turns * 2:
    history = history[-(self._buffer_max_turns * 2):]

# Pass history to Queen
result = await self.queen.execute_swarm(query, context={
    **(context or {}),
    "conversation_history": history,
})

# Append assistant response
if result.get("advice"):
    history.append({"role": "assistant", "content": result["advice"]})

self._conversation_buffers[session_id] = history
```

**Step 3 — In `execute_swarm()` (`queen.py:140-145`), inject history into proposer system prompt:**
```python
conv_history = context.get("conversation_history", [])
if conv_history:
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content'][:200]}" 
        for m in conv_history[-6:]  # last 3 turns
    )
    proposer_system += f"\n\nCONVERSATION HISTORY (last 3 turns):\n{history_text}"
```

**Acceptance test:** Two consecutive queries in same session — second query can reference first without repeating context.

---

## Track 2 — Close the Feedback Loop ✅ COMPLETE
**Completed:** 2026-05-18  
**Files changed:** `database.py`, `bms_llm_agent.py`, `main.py`, `api/routes.py`, `distiller.py`, `arvis_core/swarm/node.py`

### What was done

**2A — New DB tables** (`database.py:452-492` + helpers at end of class)
- `recommendation_outcomes` table (21): tracks predicted vs actual kwh_delta, accuracy, outcome_status
- `distilled_rules` table (22): replaces swarm_nodes.py source rewriting
- 5 helper methods: `save_recommendation_outcome`, `get_pending_outcomes`, `update_outcome`, `save_distilled_rule`, `get_distilled_rules`

**2B — Calibration + suggested_actions injected into LLM** (`bms_llm_agent.py:513-570`)
- `meta_cognition.reflect()` called in `_get_dynamic_context()` — overconfidence/well-calibrated verdict + ECE + high-Fisher EWC rules injected into `active_calibration` → goes into every system prompt via `BMSContext`
- `suggested_actions` (top 3 pending) fetched from DB and injected as `learned_patterns` calibration key

**2C — Distiller no longer rewrites source code** (`distiller.py:25,102-147,175-179`)
- `SWARM_NODES_FILE` constant removed
- `_inject_constraint_into_node_prompt` replaced with `_persist_rule_to_db` (async, writes to `distilled_rules` table)
- `run_distillation` now `await`s DB persistence instead of file write

**2C part2 — SwarmNode loads distilled rules at runtime** (`arvis_core/swarm/node.py:42-64`)
- At start of every `process()` call, fetches `distilled_rules` for this agent from DB
- Injects as extra system message: `"DISTILLED RULES (from past experience): ..."`
- Full graceful degradation if DB unavailable

**2D — Outcome measurement pipeline** (`main.py:708-714` + `main.py:884-940`)
- `_measure_pending_outcomes()` called every simulation cycle (read-only telemetry)
- Reads `MAIN_KWH_TOTAL` from state engine, computes actual vs predicted delta, calculates accuracy
- Writes back to `recommendation_outcomes` table with `accuracy` + `outcome_status`
- Feeds result to `MetaCognition.record_outcome()` for calibration closure

**2E — Operator accept wires MetaCognition + seeds outcome** (`api/routes.py:2039-2088`)
- On `POST /api/v1/advisory/recommendation/accept`: calls `meta_cognition.record_decision()` with operator context
- Seeds `recommendation_outcomes` row with `outcome_status=pending` so 24h measurement cycle picks it up

---

### 2A — Recommendation Outcome Tracking

**Problem:** `recommendations` table exists in DB (schema confirmed: `database.py:103+`). Has `accepted_at`, `rejected_at`, `status` fields. But **outcomes never measured** — did the recommendation actually improve the metric?

**New table needed** (add to `database.py` `_init_db()`):

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS recommendation_outcomes (
        outcome_id      TEXT PRIMARY KEY,
        recommendation_id TEXT NOT NULL,
        session_id      TEXT,
        predicted_kwh_delta  REAL,
        actual_kwh_delta     REAL,
        predicted_score      REAL,
        actual_score         REAL,
        outcome_status  TEXT DEFAULT 'pending',
        measured_at     TEXT,
        created_at      TEXT,
        notes           TEXT
    )
""")
```

**Measurement trigger** — add to `_simulation_loop()` in `main.py` (around line 680, after `online_learner.log_observation`):

```python
# Measure outcomes for accepted recommendations 24h ago
try:
    await self._measure_pending_outcomes()
except Exception:
    pass
```

New `_measure_pending_outcomes()` method (read-only — only reads telemetry, never acts):

```python
async def _measure_pending_outcomes(self):
    """Read telemetry to score past recommendations. Advisory only."""
    db = get_database()
    pending = await db.get_pending_outcomes()  # outcomes older than 24h, status='pending'
    for outcome in pending:
        current_kwh = self.state_engine.get_point_value("MAIN_KWH_TOTAL")
        if current_kwh and outcome.get("predicted_kwh_delta"):
            actual_delta = current_kwh - outcome.get("baseline_kwh", current_kwh)
            predicted = outcome["predicted_kwh_delta"]
            accuracy = 1.0 - abs(actual_delta - predicted) / max(abs(predicted), 1.0)
            await db.update_outcome(
                outcome["outcome_id"],
                actual_kwh_delta=actual_delta,
                outcome_status="measured",
                accuracy=accuracy,
                measured_at=datetime.now().isoformat(),
            )
            # Feed back to MetaCognition
            self.meta_cognition.record_decision(
                context={"recommendation_id": outcome["recommendation_id"]},
                decision=outcome.get("action", ""),
                confidence=outcome.get("confidence", 0.7),
                outcome="success" if accuracy > 0.7 else "miss",
                quality="good" if accuracy > 0.7 else "poor",
            )
except Exception:
    pass
```

---

### 2B — Inject Calibration into LLM System Prompt

**Problem:** `meta_cognition.reflect()` returns calibration + biases dict. `active_calibration` field exists in `BMSContext` (confirmed `prompt_builder.py:650`). Field is populated in `_get_dynamic_context()` with trust metrics. But `calibration` result from `reflect()` never injected.

**Where to add:** `_get_dynamic_context()` in `bms_llm_agent.py` (after line 520):

```python
# ── MetaCognition calibration injection ─────────────────────────────────
try:
    if self.meta_cognition:
        reflection = await self.meta_cognition.reflect(lookback_days=7)
        cal = reflection.get("calibration", {})
        biases = reflection.get("biases_detected", {})
        
        if cal.get("verdict") == "overconfident":
            ctx.active_calibration["meta_calibration"] = {
                "description": (
                    f"SELF-CALIBRATION: Recent recommendations were overconfident "
                    f"(ECE={cal.get('ece', 0):.3f}). Apply higher uncertainty. "
                    f"Biases detected: {', '.join(biases.keys()) or 'none'}."
                ),
                "weight_adjustment": -0.15,
            }
        elif cal.get("verdict") == "well_calibrated":
            ctx.active_calibration["meta_calibration"] = {
                "description": "Calibration nominal. Trust confidence scores.",
                "weight_adjustment": 0.0,
            }
            
        # Inject EWC rules that have high importance
        ewc_rules = getattr(self.meta_cognition, "calibration_rules", {})
        high_importance = [
            (k, v) for k, v in ewc_rules.items()
            if v.get("fisher_information", 0) > 2.0
        ]
        for rule_name, rule_data in high_importance[:3]:
            ctx.active_calibration[f"ewc_{rule_name}"] = {
                "description": rule_data.get("description", rule_name),
                "weight_adjustment": rule_data.get("weight_adjustment", 0.0),
            }
except Exception:
    pass
```

**Also wire:** After operator accepts/rejects advisory via API, record the decision:

In `routes.py` at the `POST /api/v1/operator/feedback` handler (or `/advisory/recommendation/accept`):

```python
# Record operator decision for MetaCognition
if copilot and copilot.meta_cognition:
    await copilot.meta_cognition.record_decision(
        context={"query": feedback.query, "session_id": session_id},
        decision=feedback.recommendation_id,
        confidence=feedback.confidence or 0.7,
        outcome="accepted" if feedback.accepted else "rejected",
        quality="good" if feedback.accepted else "poor",
    )
```

---

### 2C — Replace Distiller Source-Code Rewriting

**Problem:** `distiller.py:149` writes learned rules by **modifying `swarm_nodes.py` source code**. Fragile, dangerous in production.

**Replace with DB-injected rules approach:**

1. Add `distilled_rules` table to `database.py`:
```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS distilled_rules (
        rule_id     TEXT PRIMARY KEY,
        agent_name  TEXT NOT NULL,
        rule_text   TEXT NOT NULL,
        confidence  REAL DEFAULT 0.0,
        veto_count  INTEGER DEFAULT 0,
        active      INTEGER DEFAULT 1,
        created_at  TEXT,
        updated_at  TEXT
    )
""")
```

2. Modify `distiller.py:149` — instead of file modification:
```python
# OLD: Writes to swarm_nodes.py source file
# NEW: Writes to distilled_rules table
async def _persist_rule(self, agent_name: str, rule_text: str, confidence: float):
    db = get_database()
    rule_id = f"distilled_{agent_name}_{uuid.uuid4().hex[:8]}"
    await db.execute(
        "INSERT OR REPLACE INTO distilled_rules VALUES (?,?,?,?,?,?,?,?)",
        (rule_id, agent_name, rule_text, confidence, 1, 1,
         datetime.now().isoformat(), datetime.now().isoformat())
    )
```

3. In `SwarmNode.process()` (`node.py:35`), before building system_prompt, load applicable rules:
```python
# Load distilled rules for this node
try:
    db = get_database()
    rules = await db.fetch_all(
        "SELECT rule_text FROM distilled_rules WHERE agent_name=? AND active=1 ORDER BY confidence DESC LIMIT 5",
        (self.name,)
    )
    if rules:
        rule_block = "\n".join(f"  LEARNED: {r['rule_text']}" for r in rules)
        system_prompt = f"{system_prompt}\n\nLEARNED CONSTRAINTS:\n{rule_block}"
except Exception:
    pass
```

---

### 2D — Wire `suggested_actions` Back into Reasoning

**Problem:** `suggested_actions` table exists. `learning_engine.py` writes suggestions. Nothing reads them into LLM prompts.

**Add to `_get_dynamic_context()` (after line 527):**

```python
# ── Learning engine suggestions ──────────────────────────────────────────
try:
    db = get_database()
    suggestions = await db.fetch_all(
        """SELECT action, reason FROM suggested_actions 
           WHERE status='pending' ORDER BY created_at DESC LIMIT 3"""
    )
    if suggestions:
        sug_lines = "\n".join(f"  • {s['action']} ({s['reason']})" for s in suggestions)
        ctx.active_calibration["learned_patterns"] = {
            "description": f"Learning engine identified:\n{sug_lines}",
            "weight_adjustment": 0.0,
        }
except Exception:
    pass
```

---

## Track 3 — Goal Execution Tracker (Advisory-Only) ✅ COMPLETE
**Completed:** 2026-05-18  
**Files changed:** `agent_advisory/goal_execution_tracker.py` (new), `agent_cognitive/cognitive_loop.py`, `agent_commercial/api/routes.py`, `agent_commercial/main.py`  
**Constraint:** ARVIS read-only. GoalExecutionTracker OBSERVES whether goal conditions were met via telemetry. It does NOT send commands to BMS.

### What was done

**3A — Created `agent_advisory/goal_execution_tracker.py`**
- `GoalExecutionTracker` class subscribes to `proactive_goal_discovered` EventBus events
- Content-signature deduplication (same logic as `GoalDiscoveryEngine.known_goals`)
- `TrackedGoal` dataclass: status (active/met/expired/dismissed), reminder_count, deadline, met_at
- `check_all_goals()` — read-only telemetry sweep called every cognitive cycle:
  - Expiry: marks expired when `deadline < now`
  - Condition-met: `_check_risk_goal()` probes `alarm_engine.active_alarms` (read-only); `_check_efficiency_goal()` reads `MAIN_KWH_TOTAL` and checks ≥5% reduction
  - Reminder: re-publishes `goal_reminder` event if unmet after 24h (max 3 reminders)
- `dismiss_goal(goal_id, reason)` — operator dismiss, stops reminders
- `get_active_goals()`, `get_all_goals()`, `get_summary()` — REST query methods

**3B — Wired into `cognitive_loop.py`**
- `self.goal_tracker = None` added to `__init__`
- `_init_bms_engines()`: instantiates `GoalExecutionTracker(event_bus, bms_state, ...)` after `GoalDiscoveryEngine`
- `_run_commercial_cycle()` step 5.1: calls `self.goal_tracker.check_all_goals()` after each discovery cycle

**3C — REST endpoints in `api/routes.py`**
- `GET /api/v1/goals/active` — returns active goals + summary (savings QAR, count by status)
- `GET /api/v1/goals/all` — all goals (all statuses) 
- `POST /api/v1/goals/{goal_id}/dismiss` — operator dismiss with reason
- `goal_tracker` param added to `create_api()` + `app.state.goal_tracker`

**3D — Wired in `main.py`**
- `_start_api_server()` extracts `goal_tracker` from `self._cognitive_loop` and passes to `create_api()`

---

---

### 3A — Create `GoalExecutionTracker`

**New file:** `agent_advisory/goal_execution_tracker.py`

```python
"""
GoalExecutionTracker
--------------------
ARVIS is read-only. This tracker:
1. Receives ProactiveGoal objects from GoalDiscoveryEngine
2. Persists them with status tracking
3. Monitors telemetry (read-only) to check if conditions improved
4. Generates follow-up advisories if goal remains unmet
5. Records outcomes for feedback loop

It NEVER issues BMS commands. It ONLY reads and advises.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.goal_tracker")


@dataclass
class TrackedGoal:
    goal: Any                          # ProactiveGoal
    status: str = "active"             # active | met | expired | dismissed
    created_at: datetime = field(default_factory=datetime.now)
    deadline: Optional[datetime] = None
    follow_up_count: int = 0
    last_check: Optional[datetime] = None
    baseline_value: Optional[float] = None
    current_value: Optional[float] = None
    outcome_notes: str = ""


class GoalExecutionTracker:
    """
    Advisory-only goal lifecycle manager.
    Monitors read-only telemetry to check goal progress.
    Publishes follow-up advisories when goals remain unmet.
    """

    def __init__(self, event_bus, bms_state=None, db=None):
        self.event_bus = event_bus
        self.bms_state = bms_state
        self.db = db
        self._tracked: Dict[str, TrackedGoal] = {}

        # Subscribe to new goals
        self.event_bus.subscribe("proactive_goal_discovered", self._on_goal_discovered)

    def _on_goal_discovered(self, event: Dict[str, Any]):
        goal_data = event.get("payload", {}).get("goal", {})
        goal_id = goal_data.get("goal_id")
        if not goal_id or goal_id in self._tracked:
            return

        # Reconstruct minimal ProactiveGoal-like object
        from types import SimpleNamespace
        goal = SimpleNamespace(**goal_data)

        deadline = None
        if goal_data.get("recommended_deadline"):
            try:
                deadline = datetime.fromisoformat(goal_data["recommended_deadline"])
            except Exception:
                deadline = datetime.now() + timedelta(days=7)

        tracked = TrackedGoal(goal=goal, deadline=deadline)

        # Capture baseline telemetry (read-only)
        tracked.baseline_value = self._read_relevant_metric(goal_data)
        self._tracked[goal_id] = tracked
        logger.info("Tracking goal %s: %s", goal_id, goal_data.get("title", ""))

    def _read_relevant_metric(self, goal_data: Dict) -> Optional[float]:
        """Read current BMS value relevant to goal. Read-only."""
        if not self.bms_state:
            return None
        goal_type = goal_data.get("goal_type", "")
        try:
            if goal_type == "efficiency":
                return self.bms_state.get_point_value("MAIN_KWH_TOTAL")
            elif goal_type == "risk_mitigation":
                eq_ids = goal_data.get("equipment_ids", [])
                if eq_ids:
                    return self.bms_state.get_point_value(f"{eq_ids[0]}/VIBRATION")
            elif goal_type == "compliance":
                return self.bms_state.get_point_value("GSAS_SCORE")
        except Exception:
            pass
        return None

    async def check_all_goals(self) -> List[Dict[str, Any]]:
        """
        Periodic check — read telemetry, assess goal progress, publish advisories.
        Called from CognitiveLoop._run_commercial_cycle(). Read-only.
        """
        advisories = []
        now = datetime.now()

        for goal_id, tracked in list(self._tracked.items()):
            if tracked.status != "active":
                continue

            # Check expiry
            if tracked.deadline and now > tracked.deadline:
                tracked.status = "expired"
                advisories.append({
                    "type": "goal_expired",
                    "priority": "medium",
                    "goal_id": goal_id,
                    "message": (
                        f"Goal '{tracked.goal.title}' deadline passed "
                        f"without confirmed operator action. "
                        f"Recommend re-evaluating priority."
                    ),
                    "action": "Review and re-schedule or dismiss.",
                })
                continue

            # Read current metric (read-only)
            current = self._read_relevant_metric(
                tracked.goal.__dict__ if hasattr(tracked.goal, "__dict__") else {}
            )
            tracked.current_value = current
            tracked.last_check = now

            # Assess if goal appears met (heuristic: significant improvement)
            if (
                current is not None
                and tracked.baseline_value is not None
                and tracked.baseline_value != 0
            ):
                improvement = (tracked.baseline_value - current) / abs(tracked.baseline_value)
                if improvement > 0.05:  # >5% improvement
                    tracked.status = "met"
                    tracked.outcome_notes = f"Metric improved {improvement:.1%}"
                    advisories.append({
                        "type": "goal_met",
                        "priority": "low",
                        "goal_id": goal_id,
                        "message": (
                            f"Goal '{tracked.goal.title}' appears met. "
                            f"Metric improved {improvement:.1%} since tracking began."
                        ),
                    })
                    continue

            # Follow-up advisory if goal unmet after 24h
            hours_since_created = (now - tracked.created_at).total_seconds() / 3600
            if hours_since_created > 24 and tracked.follow_up_count < 3:
                tracked.follow_up_count += 1
                advisories.append({
                    "type": "goal_followup",
                    "priority": "medium",
                    "goal_id": goal_id,
                    "equipment_ids": getattr(tracked.goal, "equipment_ids", []),
                    "message": (
                        f"Reminder: '{tracked.goal.title}' (follow-up "
                        f"{tracked.follow_up_count}/3). "
                        f"Potential saving: "
                        f"{getattr(tracked.goal, 'potential_savings_qar', 0):.0f} QAR/month."
                    ),
                    "action": getattr(tracked.goal, "suggested_actions", ["Review and action"])[0],
                })

        return advisories

    def get_active_goals(self) -> List[Dict]:
        return [
            {
                "goal_id": gid,
                "title": getattr(t.goal, "title", ""),
                "status": t.status,
                "follow_ups": t.follow_up_count,
                "baseline": t.baseline_value,
                "current": t.current_value,
                "created_at": t.created_at.isoformat(),
                "deadline": t.deadline.isoformat() if t.deadline else None,
            }
            for gid, t in self._tracked.items()
        ]
```

---

### 3B — Wire GoalExecutionTracker into CognitiveLoop

**In `agent_cognitive/cognitive_loop.py`:**

In `_init_bms_engines()` (after line 114):
```python
from agent_advisory.goal_execution_tracker import GoalExecutionTracker
self._goal_tracker = GoalExecutionTracker(
    event_bus=self.event_bus,
    bms_state=self._bms_state,
)
```

In `_run_commercial_cycle()` (after step 5, goal discovery, around line 370):
```python
# Goal lifecycle check (read-only telemetry monitoring)
if self._goal_tracker:
    try:
        goal_advisories = await self._goal_tracker.check_all_goals()
        suggestions.extend(goal_advisories)
    except Exception as e:
        logger.debug("Goal tracker check failed: %s", e)
```

---

### 3C — Add Goal Tracking API Endpoints

**In `api/routes.py`:**

```python
@app.get("/api/v1/goals/active")
async def get_active_goals():
    """Advisory: goals currently being monitored for operator follow-through."""
    tracker = getattr(app.state, "goal_tracker", None)
    if not tracker:
        return {"goals": [], "note": "Goal tracker not initialized"}
    return {
        "goals": tracker.get_active_goals(),
        "note": "ARVIS monitors these read-only. Operator action required."
    }

@app.post("/api/v1/goals/{goal_id}/dismiss")
async def dismiss_goal(goal_id: str):
    """Operator dismisses a tracked goal."""
    tracker = getattr(app.state, "goal_tracker", None)
    if tracker and goal_id in tracker._tracked:
        tracker._tracked[goal_id].status = "dismissed"
    return {"status": "dismissed", "goal_id": goal_id}
```

**Wire tracker into `app.state` in `routes.py` `create_api()`:**
```python
# After goal_discovery is initialized in main.py, pass tracker to API
app.state.goal_tracker = goal_tracker  # new param to create_api()
```

---

## Track 4 — Adaptive ReAct + Tool Error Recovery ✅ COMPLETE
**Completed:** 2026-05-18  
**Files changed:** `arvis_core/swarm/node.py`, `arvis_core/swarm/queen.py`

### What was done

**4A — LLM-planned depth + progress-based termination** (`node.py`)

Replaced hardcoded `max_turns=3` (and later keyword-bucket `_compute_max_turns`) with a two-layer system:

Layer 1 — LLM depth planner (runs once before loop):
- `_llm_plan_depth(query)` fires a single cheap `ask_json` call
- LLM reads the actual query semantics and returns `{turns: N, reason: "..."}` using calibration rubric:
  - 1-2: simple lookup / current status
  - 3-4: multi-equipment analysis / basic fault diagnosis
  - 5-6: root cause / cross-system correlation / energy audit
  - 7-8: full compliance assessment / multi-system optimization
- Result clamped to `[1, 8]` → stored as `planned_turns`
- Falls back to 3 on any failure

Layer 2 — Progress-based termination (replaces count-based exit):
- **Natural exit**: LLM stops calling tools → exits immediately regardless of turn count
- **Soft nudge at `planned_turns`**: injects "you've completed your planned N-step analysis — synthesize unless one critical tool call remains." LLM decides whether to stop or take one more step. Fires at most once.
- **Spin detection**: `(tool_name + args_hash)` tracked in `seen_call_sigs` set. Same call twice → inject `SPIN DETECTED` redirect message, `consecutive_errors += 1`
- **Stagnation**: 3 consecutive errors/spins → force synthesis from accumulated evidence
- **Hard ceiling = 8**: absolute safety net, never exceeded regardless of planner output

**4B — Tool error hint injection** (`node.py`)
- Every tool error appends `HINT: Check argument types... try corrected args or alternative tool`
- Not restricted to turn 0 — fires on every error so LLM always has recovery guidance
- Spin redirect message is distinct (`SPIN DETECTED`) so LLM knows the failure mode

**4C — Veto re-route to alternate nodes** (`queen.py:179-228`)
- On BFT `REJECTED`: collects up to 2 nodes NOT in original proposer/quorum set
- Runs alternate nodes in parallel via `asyncio.gather()`
- If any alternate produces valid response: synthesizes consensus from alternates
- Only falls through to hard veto JSON if alternates all fail or none available

---

---

### 4A — Adaptive `max_turns`

**In `node.py:53`**, replace hardcoded `max_turns=3`:

```python
def _compute_max_turns(self, query: str, tools: List) -> int:
    """Scale turns by query complexity signals."""
    q_lower = query.lower()
    if any(w in q_lower for w in ["root cause", "why", "analyze", "investigate", "compare"]):
        return 5  # Complex reasoning needs more turns
    if any(w in q_lower for w in ["what is", "status", "show me", "list"]):
        return 2  # Simple lookup
    return 3  # Default

max_turns = self._compute_max_turns(query, tools)
```

---

### 4B — Tool Error Retry with Corrected Prompt

**In `node.py:97-107`**, after tool error:

```python
except Exception as e:
    error_msg = f"Error executing tool {tool_name}: {str(e)}"
    tool_result_content = error_msg
    
    # NEW: If first-turn tool error, inject correction hint
    if current_turn == 0:
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": f"{error_msg}\n\nHINT: Check tool argument types and required fields. Try with corrected arguments or use an alternative tool.",
        })
        # Don't return — let the loop retry with the correction in context
        continue
```

---

### 4C — Queen Veto Retry with Alternate Nodes

**In `queen.py:171-188`**, after veto block:

```python
# If vetoed, retry with next-best nodes that weren't in original set
if veto_result:
    logger.warning("BFT consensus vetoed. Attempting re-route to alternate nodes.")
    original_node_names = {n.name for n in active_nodes}
    alternate_nodes = [
        n for n in self.nodes.values()
        if n.name not in original_node_names
    ][:2]
    if alternate_nodes:
        alt_proposals = await asyncio.gather(*[
            node.process(query, context, channel=channel)
            for node in alternate_nodes
        ], return_exceptions=True)
        valid_alts = [r for r in alt_proposals if isinstance(r, dict)]
        if valid_alts:
            return await self._synthesize_consensus(query, valid_alts, context)
    # Final fallback
    return {"advice": veto_result, "context": context}
```

---

## Track 5 — Cross-Agent Shared Knowledge Buffer ✅ COMPLETE
**Completed:** 2026-05-18  
**Files changed:** `arvis_core/swarm/queen.py`

### What was done

**5A — `shared_kb` in parallel path** (`queen.py:255-278`)
- After all nodes complete, tool results extracted from every node's `history` into `shared_kb: Dict[str, Any]`
- Key format: `"NodeName:tool_name"` — unambiguous provenance
- JSON tool results parsed to dicts; non-JSON truncated to `{"raw": str[:300]}`
- `shared_kb` injected as `cross_agent_findings` into `full_grounding_context` passed to `_synthesize_consensus()`

**5A — `proposer_kb` in BFT path** (`queen.py:162-179`)
- Proposer's tool results extracted into `proposer_kb` immediately after proposer runs
- `proposer_kb` injected into `VotingRound.context` as `cross_agent_findings` — quorum voters now see what proposer actually measured when casting their vote
- After consensus passes: quorum voters' own tool observations merged with `proposer_kb` into `bft_kb` for synthesis (`queen.py:239-251`)

**5A — `_synthesize_consensus` surfaces cross-agent correlations** (`queen.py:305-315`, `queen.py:276-284`)
- System prompt updated with guideline 5: "use CROSS-AGENT TOOL FINDINGS to surface correlations individual agents missed"
- User message includes `CROSS-AGENT TOOL FINDINGS` section (capped at 8 entries, 250 chars each to avoid bloat)
- Synthesis prompt explicitly instructs: "if Energy_Agent found high consumption on AHU-03, check if Comfort_Agent or Maintenance_Agent findings relate to same equipment"

**What this unlocks:**
- Before: Energy_Agent sees AHU-03 at 140% load. Comfort_Agent reasons independently — doesn't know. Queen synthesis sees two disconnected proposals.
- After: Queen synthesis sees `Energy_Agent:get_energy_consumption → {equipment: AHU-03, load_pct: 140}` alongside Comfort_Agent's zone temps. LLM can correlate: overcooling + overload = same root cause.

---

### 5A — Per-Swarm-Run SharedKnowledgeBuffer (original spec)

**Problem:** Energy_Agent discovers "AHU-03 consuming 20% above baseline." Comfort_Agent reasons about AHU-03 comfort — doesn't know about the energy anomaly.

**In `queen.py:78`**, add at start of `execute_swarm()`:

```python
# Shared knowledge buffer — populated by each node, available to all
shared_kb: Dict[str, Any] = {}
```

After each node's `process()` call returns, extract key facts and add to `shared_kb`:

```python
for result, node in zip(results, active_nodes):
    if isinstance(result, dict) and result.get("history"):
        # Extract tool results from history (tool-call role messages)
        for msg in result["history"]:
            if msg.get("role") == "tool":
                try:
                    fact = json.loads(msg["content"])
                    if isinstance(fact, dict):
                        shared_kb[f"{node.name}:{msg.get('name','tool')}"] = fact
                except Exception:
                    pass
```

Inject `shared_kb` into context for **subsequent** node calls or final synthesis:

```python
synthesis_context = {
    **(context or {}),
    "cross_agent_findings": shared_kb,
}
advice = await self._synthesize_consensus(query, proposals, synthesis_context)
```

**In `_synthesize_consensus()`**, inject shared_kb into synthesis prompt:

```python
if context.get("cross_agent_findings"):
    findings = context["cross_agent_findings"]
    findings_text = "\n".join(
        f"  [{k}]: {json.dumps(v)[:200]}"
        for k, v in list(findings.items())[:5]
    )
    synthesis_prompt += f"\n\nFINDINGS FROM OTHER AGENTS:\n{findings_text}"
```

---

## Phase Summary & Ordering

```
Week 1-2:   Track 1 (Memory wiring)
            ├── 1A: Wire FAISS into _get_dynamic_context()
            ├── 1B: Real episodic memory endpoint
            └── 1C: Multi-turn conversation buffer

Week 3-4:   Track 2 (Feedback loop)
            ├── 2A: recommendation_outcomes table + measurement
            ├── 2B: MetaCognition calibration → LLM prompt injection
            ├── 2C: Distiller → DB rules (replace source rewriting)
            └── 2D: suggested_actions → LLM context

Week 4:     Track 4 (ReAct hardening)
            ├── 4A: Adaptive max_turns
            ├── 4B: Tool error retry
            └── 4C: Queen veto re-route

Week 5:     Track 5 (Cross-agent KB)
            └── 5A: SharedKnowledgeBuffer in execute_swarm()

Week 5-7:   Track 3 (Goal tracker)
            ├── 3A: GoalExecutionTracker (new file)
            ├── 3B: Wire into CognitiveLoop
            └── 3C: API endpoints
```

---

## What Each Track Unlocks

| Track | Before | After |
|-------|--------|-------|
| 1 — Memory | "Never seen this before" every query | "3 months ago CH-01 had same vibration — failed 2 weeks later" |
| 2 — Feedback | Recommends, never learns if right | Measures actual vs predicted, adjusts confidence, injects lessons |
| 3 — Goal tracker | Goals generated, discarded | Goals tracked, operator reminded, outcomes recorded |
| 4 — ReAct | Gives up after 3 turns, no retry | Scales depth, retries on error, re-routes on veto |
| 5 — Cross-agent KB | Each node reasons in isolation | Energy anomaly from Energy_Agent informs Comfort_Agent reasoning |

---

## SOTA Score After Each Track

| After Track | Score |
|-------------|-------|
| Baseline now | ~45% |
| + Track 1 (memory) | ~58% |
| + Track 2 (feedback) | ~68% |
| + Track 4 (ReAct) | ~73% |
| + Track 5 (cross-agent) | ~78% |
| + Track 3 (goal tracker) | ~85% |

---

## Read-Only Constraint Checklist

Every new component verified against ARVIS read-only constraint:

| Component | Reads BMS? | Writes BMS? | Safe? |
|-----------|-----------|-------------|-------|
| FAISS incident recall | No | No | ✅ |
| Conversation buffer | No | No | ✅ |
| Episodic memory endpoint | DB only | No | ✅ |
| Outcome measurement | Reads telemetry | No BMS write | ✅ |
| MetaCognition injection | No | No | ✅ |
| Distilled rules → DB | No | No | ✅ |
| GoalExecutionTracker | Reads telemetry | **Never** issues commands | ✅ |
| Adaptive max_turns | No | No | ✅ |
| Tool error retry | No | No | ✅ |
| SharedKnowledgeBuffer | Reads tool results | No | ✅ |

**No component in this plan controls, writes to, or commands any BMS device.**  
All goal tracking, feedback measurement, and telemetry reads are observation-only.  
Operator action remains the sole actuator.

---

## Files Created / Modified

| File | Action | Track |
|------|--------|-------|
| `agent_cognitive/embeddings_store.py` | Wire `search()` into `_get_dynamic_context` | 1A |
| `agent_commercial/bms_llm_agent.py` | Add FAISS recall, conv buffer, calibration injection | 1A, 1C, 2B |
| `agent_commercial/api/routes.py` | Fix episodic endpoint, add goal endpoints, pass session_id | 1B, 1C, 3C |
| `agent_commercial/database.py` | Add `recommendation_outcomes`, `distilled_rules` tables | 2A, 2C |
| `agent_commercial/main.py` | Add `_measure_pending_outcomes()`, alarm → FAISS store | 1A, 2A |
| `agent_cognitive/meta_cognition.py` | Wire `reflect()` result into `_get_dynamic_context` | 2B |
| `agent_cognitive/distiller.py` | Replace file-write with DB rule persistence | 2C |
| `arvis_core/swarm/node.py` | Adaptive max_turns, tool error retry | 4A, 4B |
| `arvis_core/swarm/queen.py` | Veto re-route, SharedKnowledgeBuffer | 4C, 5A |
| `agent_cognitive/cognitive_loop.py` | Wire GoalExecutionTracker | 3B |
| `agent_advisory/goal_execution_tracker.py` | **New file** | 3A |

---

*Plan generated from ARVIS_AGENTIC_AUDIT.md evidence. All file:line references verified against live codebase.*
