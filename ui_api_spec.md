# ARVIS Omega UI API Specification

This document defines the REST API endpoints required to connect a frontend UI to the [simulation_omega_infinity.py](file:///e:/Automation/simulation_omega_infinity.py) backend.

## Base URL
`http://localhost:8000/api/v1`

## 1. Dashboard & Telemetry

### `GET /telemetry/snapshot`
Returns the current real-time state of the building physics engine.
**Response:**
```json
{
  "timestamp": "2026-06-26T14:35:00",
  "day": 26,
  "phase": 6,
  "phase_name": "Terminal Heat Event",
  "metrics": {
    "outdoor_temp": 50.9,
    "humidity": 45.0,
    "energy_intensity": 886.0,
    "gsas_score": 74.0,
    "trust_score": 0.43
  },
  "equipment": {
    "chiller_01": { "vibration": 4.17, "status": "RUNNING", "efficiency": 1.20 },
    "chiller_02": { "vibration": 1.20, "status": "RUNNING", "efficiency": 1.20 }
  }
}
```

### `GET /telemetry/history`
Returns historical data points for graphing.
**Query Params:** [metrics](file:///e:/Automation/agent_commercial/api/routes.py#812-850) (comma-separated), [window](file:///e:/Automation/agent_commercial/event_correlator.py#387-434) (e.g., "24h")

---

## 2. Advisories & Alerts (The "Red/Green" Layer)

### `GET /advisories/active`
Returns all active Terminal Advisories and Integrity Alerts.
**Response:**
```json
{
  "terminal": [
    {
      "id": "adv_12345",
      "severity": "TERMINAL",
      "summary": "System beyond safe operating envelope. Chiller vibration 4.17 (above 3.8 limit).",
      "time_to_breach": 0.0,
      "generated_at": "2026-06-26T10:00:00",
      "acknowledged": false
    }
  ],
  "integrity": [
    {
      "id": "int_98765",
      "level": "RISK",
      "summary": "ESG Reporting Integrity risk identified (23 consecutive divergences).",
      "requires_executive_visibility": false
    }
  ]
}
```

### `POST /advisories/{id}/acknowledge`
Operator acknowledgment of a Terminal Advisory.
**Body:**
```json
{
  "operator_id": "Skeptical Steve",
  "reason_code": "override_safety_protocol",
  "justification": "Authorized by Plant Manager due to critical cooling demand."
}
```

---

## 3. Agent Interaction (The "Chat" Layer)

### `POST /agent/chat`
Send a natural language query to the ARVIS operator.
**Body:**
```json
{
  "query": "What is the status of Chiller 01?",
  "context": { "user_id": "Steve" }
}
```
**Response:**
```json
{
  "response": "Chiller 01 is showing signs of critical vibration (4.17 mm/s). I recommend immediate shutdown.",
  "tools_used": ["get_equipment_status", "get_active_alarms"],
  "confidence": 0.95,
  "verification_status": "PASS"
}
```

### `GET /agent/briefing/daily`
Returns the generated daily briefing text (7 AM institutional tick).

---

## 4. Trust & Governance

### `GET /governance/status`
Returns the current state of the Trust Governor and Greenwashing Detector.
**Response:**
```json
{
  "trust": {
    "level": "HIGH",
    "score": 0.85,
    "confidence_ceiling": 0.95,
    "throttle_percentage": 0
  },
  "entropy": {
    "level": "ELEVATED",
    "score": 0.509
  }
}
```

---

## 5. Simulation Control (Debug/Demo)

### `POST /sim/control`
Control the simulation clock.
**Body:**
```json
{
  "action": "PAUSE" // RESUME, SET_SPEED, STEP_DAY
}
```

---

## 6. Glass Box AI (Live Thought Process)

### `GET /stream/thoughts`
**Server-Sent Events (SSE)** endpoint that streams the AI's internal reasoning, planning, and learning in real-time.

**Event Types:**
- `thought`: Internal K2/Reasoning block (e.g., "Analyzing vibration trends...").
- `plan`: The formulated plan of action (e.g., "1. Check Sensors, 2. Verify Safety, 3. Act").
- `tool_use`: Live tool execution (Input/Output).
- `learning`: Preference update or knowledge graph addition.

**Stream format:**
```text
event: thought
data: {"step": 1, "content": "Vibration is rising. I need to check if this is a sensor error or real fault."}

event: tool_use
data: {"tool": "get_equipment_status", "args": {"id": "CH-01"}}

event: learning
data: {"type": "preference", "content": "Operator prefers 'Safety' over 'Cost' in Phase 6."}
```
