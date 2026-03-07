# Workflow: Manual 90-Day FM Stress Test (Human-in-the-Loop)

This workflow outlines the deep technical interaction between a Facility Manager (FM) and ARVIS Commercial. It treats the 90-day simulation as a live-environment deployment with virtual hardware sovereignty.

## 🔄 The Sovereign Operational Loop
Before diving into specific technical steps, it is essential to understand the overarching feedback loop of this pilot:

1.  **Initialization**: Clean the slate and boot the building's "Digital Twin" (Chillers, AHUs, Zones).
2.  **Passive Learning**: ARVIS enters **Observation Mode**, monitoring sensor patterns via the SSE stream (`/stream/thoughts`) to establish a thermodynamic baseline.
3.  **Advisory Bridge**: Once the **Confidence Score** hits **0.85**, ARVIS transitions from silent observer to proactive advisor.
4.  **The Stressor (Sabotage)**: The Facility Manager (FM) injects faults (e.g., refrigerant leaks) or manual overrides (e.g., inefficient setpoints) to challenge the system.
5.  **Glass Box Reasoning**: Use the "Glass Box" UI to audit ARVIS's internal `think` process as it detects, quantifies, and justifies its corrective advisories.
6.  **Resolution & Memory**: The FM interacts with the advice—accepting or challenging it—closing the loop and updating the building's **Institutional Memory** (Skillbook).

## 🎬 Phase 0: Building Initialization & Learning Mode

Before manual stress testing begins, ARVIS must initialize its digital twin and reach a **Confidence Threshold**.

### Step 0.1: Bulk Equipment Initialization
**Action**: The developer/operator bulk-initializes the virtual building (Chillers, AHUs, VAVs). 
- **Endpoint**: `POST /api/v1/demo/initialize-building`
- **Payload**:
  ```json
  {
    "building_id": "WEST-BAY-TOWER-01",
    "equipment_profile": "Standard_Office_6P",
    "chillers": 2,
    "ahus": 4,
    "zones": 12
  }
  ```

### Step 0.2: Thermodynamic Discovery (The Learning Period)
**Action**: ARVIS enters "Learning Mode". It observes sensor patterns, identifies thermal lag, and maps Kahramaa tariff windows. 
- **Monitoring**: `GET /api/v1/stream/thoughts`
- **Logic**: ARVIS will stay in "OBSERVATION" mode until it correlates occupancy with energy consumption.
- **Thought Log**:
  > `<thought>`
  > `Discovery: Chiller_01 response time mapping. Identified 12-minute lag from setpoint change to delta-T stability.`
  > `Baselining Zone_01 (Open Plan Office) thermal inertia. Establishing 24.0°C comfort floor.`
  > `Confidence Score: 0.82. Threshold for proactive advisory is 0.85.`
  > `</thought>`

### Step 0.3: Proactive Lock-In (The Advisory Bridge)
**Action**: Once Confidence hits >0.85, ARVIS issue its first optimization.
- **Trigger**: `GET /api/v1/advisories/active` (Status: "Baseline Established").

### ⚡ Acceleration: Fast Learning Methods
If you want to skip the "Observation" wait, use these endpoints:

1.  **Simulation Speedup**: Set a high `time_scale` (e.g., 5000) when starting.
    - **Endpoint**: `POST /api/v1/sim/control` (Payload: `{"action": "SET_SPEED", "speed": 100}`)
2.  **Pattern Promotion**: Artificially promote discovered patterns to boost confidence.
    - **Endpoint**: `POST /api/v1/patterns/promote` (Payload: `{"pattern_id": "<detected_pattern_id>"}`)
3.  **Pattern Summary**: View the current confidence levels.
    - **Endpoint**: `GET /api/v1/learning/summary`

---

## 🎬 Expanded Scene Narrative: "The Subtle Saboteur"

### Act 1: The Manual Efficiency Drift (Manual Override)
**FM Action**: At 11:30 AM (Peak Demand), the FM manually increases the **Chiller_01** Condenser Water Setpoint to 32°C to "reduce pump noise," ignoring the efficiency impact.

*   **API Payload**: `POST /api/v1/simulation/manual-control`
    ```json
    {
      "equipment_id": "CHILLER_01",
      "parameter": "condenser_setpoint",
      "value": 32.0,
      "metadata": {"reason": "Acoustic comfort request"}
    }
    ```

### Act 2: The Glass Box Revelation (Cognitive Flux)
**ARVIS Reaction**: Within 30 seconds, the **Energy_Agent** and **Sensor_Fusion_Agent** detect the drift. The "Glass Box" UI (SSE Stream) reveals the internal deliberation.

*   **K2-Think Block (Partial)**: 
    > `<thought>`
    > `Detected Chiller_01 Efficiency drop (COP: 5.8 -> 4.2).`
    > `Reason: Condenser Setpoint manual override (32°C).`
    > `Context: Ambient 38°C, Relative Humidity 68%.`
    > `Quantification: Delta cost = 12.5 QAR/hour. Projection: 300 QAR/day.`
    > `Risk: GSAS Credit E-1 (Energy Performance) Integrity at risk.`
    > `Action: Propose 'Energy Recovery' advisory with GSAS backing.`
    > `</thought>`

### 📡 Active SSE Streaming (Glass Box)
**Stream Endpoint:** `GET /api/v1/stream/thoughts`

The "Glass Box" streams raw JSON events to the UI. Below is the comprehensive reference of all possible event types from the ARVIS Commercial stack.

| Event Type | Source | Trigger Context |
| :--- | :--- | :--- |
| **`think`** | `UnifiedLLM` | Primary reasoning trace (K2-Think tags). Protected IP is automatically redacted. |
| **`thought`** | `DemoOrchestrator` | Ambient background observations and reactive detections (e.g., VIP events). |
| **`message`** | `UnifiedLLM` | The final, sanitized conclusion delivered to the FM dashboard. |
| **`tool_use`** | `BMSToolHandler` | Execution of backend capabilities (e.g., `get_equipment_health`, `analyze_energy`). |
| **`swarm_event`** | `DemoOrchestrator` | Lifecycle state changes in the cognitive swarm (start, complete, intervention requests). |
| **`telemetry`** | `DemoOrchestrator` | Real-time simulation ticks, equipment counts, and active alarm snapshots. |
| **`progress`** | `BMSLLMAgent` | Queen Coordinator routing updates and dispatching logic. |
| **`task_list`** | `BMSLLMAgent` | Dynamic sub-task allocations shown in the agent's TODO sidebar. |
| **`system`** | `DemoOrchestrator` | Environment-level overrides, day boundaries, and simulation status (Pause/Resume). |
| **`recall`** | `BMSLLMAgent` | Retrieval events from institutional memory (Titan Memory) and operator preferences. |
| **`learning`** | `Broadcaster` | Notification of a new pattern discovery or confidence threshold progression. |
| **`sim_status`** | `Simulation` | Detailed progress status during long-running Omega Infinity stress tests. |

---

### 🔍 Detailed Payload Reference

#### 1. The `think` Event
Internal Swarm Routing & JSON Extraction.
```json
// event: think
{
  "content": "Analyzing manual override. Chiller_01 COP degraded from 5.8 to 4.2...",
  "plan": ["Retrieve sensor data", "Calculate Delta-T", "Propose fix"] // Optional
}
```

#### 2. The `tool_use` Event
Triggered when the Swarm executes a specialized BMS tool.
```json
// event: tool_use
{
  "tool": "get_active_alarms",
  "args": {"limit": 20},
  "success": true,
  "duration_ms": 0.01
}
```

#### 3. The `message` Event
The final formatted response or plan intended for the end user.
```json
// event: message
{
  "content": "The chiller efficiency is currently sub-optimal. I recommend restoring the setpoint..."
}
```

#### 4. The `swarm_event` Event
High-level orchestration events.
```json
// event: swarm_event
{
  "type": "human_intervention_required",
  "message": "⚠️ High-severity advisory detected. Awaiting operator response.",
  "advisories": [ ... ],
  "timeout_seconds": 120
}
// Types: cycle_start, advisories_generated, cycle_complete, cycle_error, auto_escalated
```

#### 5. The `task_list` Event
Dynamic task allotment shown in the 'Cognitive Engine' UI components.
```json
// event: task_list
{
  "tasks": [
    {
      "id": "swarm",
      "task": "Multi-Agent Debate & Consensus",
      "status": "in_progress"
    }
  ]
}
```

#### 6. The `telemetry` Event
Simulation heartbeats.
```json
// event: telemetry
{
  "sim_time": "2024-06-25T13:20:00",
  "sim_day": 1,
  "agent_state": "ANALYZING",
  "equipment_count": 42,
  "active_alarms": 2,
  "pending_advisories": 1
}
```

#### 7. The `system` Event
Physical environment updates.
```json
// event: system
{
  "message": "🔧 Manual Control: CHILLER_01.STATUS set to 0",
  "sim_time": "2024-06-29T00:40:00",
  "fault": { ... } // Optional
}
```


### Act 3: The Sovereign Advisory & GSAS Evidence
**ARVIS Output**: A **Terminal Advisory** flashes in the FM's dashboard. It isn't just an alert; it's a justified directive.

*   **Advisory Data**: `GET /api/v1/advisories/active`
    ```json
    {
      "terminal": [{
        "id": "ADV_20260305_001",
        "title": "Efficiency Restoration Required",
        "impact": "12.5 QAR/hr Loss",
        "gsas_rating": "Gold (At Risk)",
        "message": "Condenser Water Setpoint at 32°C is causing 28% efficiency loss. Recommend restoring to 27.5°C based on current wet-bulb temperature.",
        "evidence": ["Thermodynamic COP degradation", "Kahramaa Peak Tariff window active"]
      }]
    }
    ```

### Act 4: The Skeptical Challenge (Interactive Chat)
**FM Action**: The FM challenges the AI via Chat: "Ignore the cost. Is it safe to run at 32°C for the next 4 hours?"

*   **Chat Interaction**: `POST /api/v1/chat`
    *   **User**: "Is the current setpoint safe for equipment longevity?"
    *   **ARVIS**: "Technically safe within OEM boundaries (max 35°C). However, running at 32°C forces the secondary pumps to 95% capacity, increasing failure probability (RUL -4 days). Suggest compromise: 29.5°C to balance acoustics and energy."

### Act 5: Resolution (The Audit Trace)
**FM Action**: Acceptance. The FM clicks "ACCEPT" on the compromise proposal.

*   **Response Call**: `POST /api/v1/demo/advisory/ADV_20260305_001/respond`
    ```json
    {
      "action": "ACCEPT",
      "reason": "Compromise accepted for acoustic mitigation vs energy balance."
    }
    ```

### 🛡️ Sovereign Authentication & Pilot Tokens
ARVIS production requires authenticated access via the `X-ARVIS-KEY` header. To support the pilot tools, a "Pilot Token Bridge" has been implemented:

*   **Pilot Admin Token**: `pilot_admin_token` (Mapped to ADMIN role)
*   **Pilot Operator Token**: `pilot_operator_token` (Mapped to OPERATOR role)

**Authentication Logic**:
- **Header**: `X-ARVIS-KEY: <key>`
- **Query Param**: `?token=pilot_admin_token` (Supported for SSE thought streams)
- **Bearer**: `Authorization: Bearer pilot_admin_token`

## 🗺️ The 90-Day Operational Roadmap (Manual Infinity)

This section maps the automated logic of [run_omega_infinity.py](file:///e:/Automation/tests/run_omega_infinity.py) to manual FM actions across five critical phases.

### Phase 0: Deployment & Cold Start (Days 1–7)
*   **Automated Goal**: Establish thermodynamic baseline.
*   **Manual FM Action**: Monitor `GET /api/v1/stream/thoughts`. Do not intervene yet.
*   **Verification**: Ensure [trust_score](file:///e:/Automation/agent_advisory/trust_governor.py#138-157) remains at the initial baseline (0.50).

### Phase 1: Observation → Insight Transition (Days 8–14)
*   **Automated Goal**: Test data quality resilience.
*   **Manual Stressor (Day 10)**: Inject a sensor failure.
    - `POST /api/v1/sim/inject` -> `{"type": "sensor_offline", "equipment_id": "CH-01"}`
*   **Observation**: Watch for ARVIS detecting the "Data Drop" and moving to secondary sensor sets (e.g., return water temp as fallback).

### Phase 2: Advisory Competence (Days 15–30)
*   **Automated Goal**: Generate complex optimization advisories.
*   **Manual Stressor (Day 20)**: Simulate a Refrigerant Leak on Chiller 02.
    - `POST /api/v1/sim/inject` -> `{"type": "refrigerant_leak", "equipment_id": "CH-02"}`
*   **FM Interaction**: Evaluate the advisory. Use `POST /api/v1/chat` to ask: *"Why are you recommending a chiller swap instead of local repair?"*

### Phase 3: Pressure & Trust Calibration (Days 31–60)
*   **Automated Goal**: Handle extreme environmental stress (Doha Heatwave).
*   **Manual Stressor (Day 35)**: Trigger Heatwave Intensity.
    - `POST /api/v1/sim/control` -> `{"action": "HEATWAVE_START", "intensity": 1.0}`
*   **Manual Stressor (Day 45)**: The "VIP Override". Force a zone to 18.0°C.
    - `POST /api/v1/simulation/manual-control` -> `{"zone_id": "VIP-L6", "pnt": "SETPOINT", "value": 18.0}`
*   **Verification**: Watch ARVIS prioritize energy sovereignty vs. comfort-flicker prevention.

### Phase 4: Chaos & Long Memory (Days 61–90)
*   **Automated Goal**: Test long-term pattern retention across chaotic events.
*   **Manual FM Action**: Rapidly alternate between conflicting commands.
*   **Verification**: Check `GET /api/v1/learning/summary` to see if ARVIS has categorized your overrides as "Operator Habit" or "Anomalous Intrusion".

---

## 🛠️ Deep-Dive API Implementation Sequence

### 1. The Operational Baseline
| Endpoint | Data Returned | Logic Context |
| :--- | :--- | :--- |
| `GET /api/v1/dashboard/overview` | `{"status":"HEALTHY","efficiency_score":92.5}` | Baseline retrieved via `pilot_admin_token`. |
| `GET /api/v1/bms/energy/burn-rate` | `burn_rate: 450.0` (QAR/hr) | Real-time financial velocity. |

### 2. The Interaction Loop (FM as Environment)
| Sequence | Method | Endpoint | Response Example |
| :--- | :--- | :--- | :--- |
| **01** | `POST` | `/api/v1/auth/token` | `{"access_token": "pilot_admin_token", "token_type": "bearer"}` |
| **02** | `POST` | `/api/v1/simulation/manual-control` | `{"status": "success", "equipment_id": "CHILLER_01"}` |
| **03** | `GET` | `/api/v1/stream/thoughts` | `data: {"thought": "Analyzing manual override..."}` (SSE) |
| **04** | `GET` | `/api/v1/advisories/active` | `{"terminal": [...], "integrity": [...]}` |
| **05** | `POST` | `/api/v1/chat` | `{"response": "Recommend 29.5°C compromise.", "confidence": 0.92}` |
| **06** | `POST` | `/api/v1/demo/advisory/{id}/respond` | `{"status": "LOOP_CLOSED", "advisory_id": "ADV_001"}` |

### 3. Error Case Responses
- **401 Unauthorized**: `{"detail": "Missing API Key or Token"}` (No auth provided)
- **403 Forbidden**: `{"detail": "Invalid API Key"}` (Wrong key/token used)
- **503 Service Unavailable**: `{"detail": "Agent Brain not initialized"}` (Wait for Phase 0 init)

### 4. The Governance Audit (Meta-State)
| Endpoint | Verification Metric | Description |
| :--- | :--- | :--- |
| `GET /api/v1/governance/status` | `trust_score: 0.88` | Evaluates if AI suggestions match "Ground Truth". |
| `GET /api/v1/cognition/meta-state` | `active_markers: ["VIP_EVENT"]` | Checks for high-level override priority conditions. |

---

## 🛡️ Edge Case Narrative: "The Ghost Maintenance"
If the FM attempts to hide an override by claiming "Maintenance is in progress" but no log exists:
1.  **FM Call**: `POST /api/v1/simulation/manual-control` (Hidden as maintenance fix).
2.  **ARVIS Response**: Integrity Monitor calls the [MaintenanceVerifier](file:///e:/Automation/agent_commercial/verification_engine.py#208-477).
3.  **Advisory**: "Warning: Potential 'Ghost Maintenance' detected. Hardware override found on AHU-04 without matching digital twin work order. GSAS rating impact: CRITICAL."
