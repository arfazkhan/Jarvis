# ARVIS Backend API Integration Guide (Exhaustive Reference)

This is the complete list of all backend endpoints available in the ARVIS framework, including standard dashboard operations, intelligent advisory endpoints, GSAS compliance, and the Omega Omega-Infinity simulation controls.

Unless noted, all endpoints are prefixed with `/api/v1`.

## 1. Authentication & Health
* **`POST /api/v1/auth/token`**
  * **Payload:** `{"query": "admin"}` (Uses [ChatRequest](file:///e:/Automation/agent_commercial/api/routes.py#42-46) schema as a placeholder in the demo)
  * **Response:** `{"access_token": "<jwt>", "token_type": "bearer"}`
* **`GET /api/health`**
  * **Response:** System status and boolean checks for engine initializations (`bms_state`, `alarm_engine`, `llm_agent`, etc.).

## 2. Dashboard & Overview
* **`GET /api/v1/dashboard/overview`**
    * **Response:** High-level metrics (`equipment_total`, `active_alarms_critical`, `energy_today_kwh`, `insights_pending`, etc.).
* **`GET /api/v1/dashboard/alarms/active`**
    * **Query Params:** `limit` (int, default 50), `severity` (string, optional)
    * **Response:** Array of active alarms, sorted by priority.
* **`POST /api/v1/alarms/{alarm_id}/acknowledge`**
    * **Auth:** Requires Operator/Admin JWT.
    * **Response:** `{"status": "acknowledged", "alarm_id": "ALM-001"}`

## 3. Equipment & Tracking
* **`GET /api/v1/equipment`**
    * **Query Params:** `equipment_type`, [status](file:///e:/Automation/tests/omega_stress_test/omega_test_runner.py#2339-2358), `location`
    * **Response:** Array of all equipment matching filters.
* **`GET /api/v1/equipment/{equipment_id}`**
    * **Response:** Detailed status, runtime hours, efficiency, and real-time data points (e.g., vibration, temp).
* **`GET /api/v1/equipment/{equipment_id}/history`**
    * **Query Params:** `point_id` (optional), `minutes` (int, default 60)
    * **Response:** Time-series arrays of historical sensor data.

## 4. Energy & Sustainability
* **`GET /api/v1/energy/consumption`**
    * **Query Params:** [period](file:///e:/Automation/agent_commercial/briefing_engine.py#412-420) ("today", "week", "month")
    * **Response:** Summary metrics (`total_kwh`, `deviation_percent`, peak usage).
* **`GET /api/v1/energy/anomalies`**
    * **Response:** Detected waste patterns and estimated financial impact.

## 5. GSAS Compliance (Greenwashing & Sustainability)
* **`GET /api/v1/gsas/status`**
    * **Response:** Current sustainability scores across energy, water, and indoor environment categories.
* **`GET /api/v1/gsas/improvement-priorities`**
    * **Response:** Top 10 actionable recommendations ranked by potential score gain.
* **`GET /api/v1/gsas/report`**
    * **Query Params:** `report_type` ("monthly", "quarterly", "annual")
* **`POST /api/v1/gsas/gord-report`**
    * **Purpose:** Triggers a background task to generate a formal PDF for GORD certification.
    * **Response:** `{"status": "success", "report_id": "...", "pdf_path": "..."}`
* **`GET /api/v1/reports/download/{filename}`**
    * **Response:** Returns the generated PDF file stream.

## 6. Predictive Maintenance
* **`GET /api/v1/maintenance/predictions`**
    * **Query Params:** `risk_level` ("low", "medium", "high", "critical")
    * **Response:** Array of predictive failure probabilities and Remaining Useful Life (RUL) days.
* **`GET /api/v1/maintenance/equipment/{equipment_id}/health`**
    * **Response:** Deep health analysis, risk factors, and maintenance recommendations for a specific machine.

## 7. AI Agent & Narrative
* **`POST /api/v1/chat`**
    * **Payload:** `{"query": "User message", "context": {"floor": 1}}`
    * **Response:** `{"response": "...", "confidence": 0.9, "sources": [], "suggested_actions": []}`
* **`GET /api/v1/insights/feed`**
    * **Query Params:** `limit` (int, default 20), `insight_type`
    * **Response:** AI-generated system insights feed.
* **`POST /api/v1/insights/{insight_id}/acknowledge`**

## 8. Feedback Loop (Operator Learning)
The system learns from what operators choose to do in response to AI suggestions.
* **`POST /api/v1/advisory/decision`**
    * **Payload:** `{"recommendation_id": "...", "chosen_option_index": 0, "operator_id": "..."}`
* **`POST /api/v1/advisory/outcome`**
    * **Payload:** `{"recommendation_id": "...", "actual_outcome": {}, "outcome_quality": "good"}`
* **`GET /api/v1/advisory/trust-metrics`**
    * **Response:** System trust metrics (Adoption rate, accuracy rate, calibration error).
* **`GET /api/v1/advisory/preference-insights`**
    * **Query Params:** `operator_id` (optional)
* **`GET /api/v1/advisory/recommendation-history`**
    * **Query Params:** `limit`, `operator_id`, `building_id`

## 9. Omega Inference Stream & Simulation Controls ("Glass Box" API)
These endpoints drive the Omega Infinity simulation UI.
* **`GET /api/v1/stream/thoughts`**
    * **Purpose:** The vital Server-Sent Events (SSE) stream pushing realtime AI `think`, `plan`, and `tool_use` JSON payloads to the UI.
* **`GET /api/v1/advisories/active`**
    * **Response:** Active "Terminal Rules" (Safety Vetoes) and "Integrity Alerts".
* **`GET /api/v1/governance/status`**
    * **Response:** The current Agent Trust Score Level and Autonomy Constraints.
* **`POST /api/v1/sim/control`**
    * **Payload:** `{"action": "PAUSE" | "RESUME" | "SET_SPEED" | "PULSE" | "NEXT_DAY", "speed": 1.0, "target_day": 5}`
* **`POST /api/v1/simulation/equipment/override`**
    * **Payload:** `{"equipment_id": "...", "value": "...", "intent": "Manual test"}`
* **`POST /api/v1/sim/rewind`**
    * **Purpose:** Restores simulation to the start of the current day.
* **`POST /api/v1/sim/scenario`**
    * **Payload:** `{"scenario_id": "hvac_failure"}`
* **`POST /api/v1/sim/persona`**
    * **Payload:** `{"persona_name": "skeptical_steve"}`
* **`POST /api/v1/config/setup`**
    * **Payload:** `{"provider": "groq", "model": "...", "api_key": "..."}`

## 10. Advanced Sovereign APIs (Cognition, Learning, ML, Logistics)

### 10.1 BMS Learning Engine (Pattern Extraction)
* **`GET /api/v1/learning/patterns`**
  * **Response:** Array of behavioral and environmental patterns.
    ```json
    [
      {
        "pattern_id": "PTRN-104",
        "type": "behavioral",
        "description": "Occupants in Zone 3 consistently override AC to 21°C between 14:00-16:00.",
        "confidence": 0.88
      }
    ]
    ```

### 10.2 Building Skillbook (Action Memory)
* **`GET /api/v1/skills/catalog`**
  * **Response:** Catalog of learned optimal actions.
    ```json
    [
      {
        "skill_id": "SK-042",
        "title": "Chiller 2 Surge Mitigation",
        "status": "verified",
        "confidence_score": 0.95
      }
    ]
    ```
* **`POST /api/v1/skills/{skill_id}/approve`**
  * **Payload:** `{"status": "approved", "operator_id": "admin"}`
  * **Response:** `{"status": "approved", "skill_id": "SK-042", "operator": "admin"}`

### 10.3 Agent Cognition (Episodic Memory & Graph)
* **`GET /api/v1/memory/episodic/{day}`**
  * **Response:** Specific timeline of events the AI remembers.
    ```json
    {
      "day": 12,
      "key_events": [{"time": "14:30", "memory": "Grid fluctuation. Sheeded load by 15%."}]
    }
    ```
* **`GET /api/v1/cognition/context-graph`**
  * **Response:** Node/Edge structure.
* **`GET /api/v1/cognition/meta-state`**
  * **Response:** Humility, overload, and internal doubt tracking.
    ```json
    {
      "cognitive_load": 0.75,
      "humility_index": 0.8,
      "state_assessment": "High uncertainty."
    }
    ```

### 10.4 What-If Simulator & Benchmarking
* **`POST /api/v1/ml/simulate`**
  * **Payload:** `{"action": "change_setpoint", "target": "Zone 2", "value": 24.0, "duration_hours": 4}`
  * **Response:** Prediction array (`energy_impact_kwh`, `cost_impact_qar`).
* **`GET /api/v1/fleet/benchmark/{building_id}`**
  * **Response:** Cross-building percentile score comparisons.

### 10.5 Maintenance & Logistics Engine
* **`GET /api/v1/logistics/queue`**
  * **Response:** Live tracking of dispatched physical contractors.
* **`GET /api/v1/logistics/verifications`**
  * **Response:** Checks if sensors proved the contractor fixed the unit.
    ```json
    [
      {
        "ticket_id": "WO-9912",
        "verification_status": "failed",
        "reason": "Vibration levels still identical."
      }
    ]
    ```

## 11. Financial, Operational & Safety Controls (Commercial Core)

* **`GET /api/v1/energy/burn-rate`**
  * **Query Params:** `current_load_kw` (float)
  * **Response:** Live Qatari Riyal electricity cost calculation based on tariffs.
* **`GET /api/v1/briefing/morning`**
  * **Query Params:** `user_id` (string, optional)
  * **Response:** Proactive executive summary of overnight anomalies, energy waste patterns, and weather context.
* **`POST /api/v1/safety/state`**
  * **Payload:** `{"state": "red" | "yellow" | "green"}`
  * **Purpose:** The ultimate "Kill Switch". Overrides AI autonomy level instantly.

## 12. Frontend Simulation Orchestrator (90-Day Stress Test)
Endpoints to allow UI to trigger and monitor the rigorous [OmegaTestRunner](file:///e:/Automation/tests/omega_stress_test/omega_test_runner.py#190-2358) within the background of the FastAPI server.

* **`POST /api/v1/omega/stress-test/start`**
  * **Payload:** `{"days": 90, "time_scale": 5000, "building_id": "DOHA-TOWER-001", "persona": "skeptical_steve"}`
  * **Purpose:** Triggers the background execution of the omega stress test.
* **`POST /api/v1/omega/stress-test/stop`**
  * **Purpose:** Aborts the currently running background simulation.
* **`GET /api/v1/omega/stress-test/status`**
  * **Response:** Progress tracking for the UI.
    ```json
    {
      "is_running": true,
      "current_day": 14,
      "total_days": 90,
      "building_id": "DOHA-TOWER-001",
      "status_message": "Starting Day 14"
    }
    ```
