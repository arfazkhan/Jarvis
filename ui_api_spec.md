# ARVIS Omega UI API Specification (Swarm Updated)

This document defines the REST API endpoints required to connect a frontend UI to the ARVIS Swarm backend for real-time interactive demos.

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
  "metrics": {
    "outdoor_temp": 50.9,
    "energy_intensity": 886.0,
    "trust_score": 0.43
  },
  "equipment": {
    "chiller_01": { "vibration": 4.17, "status": "RUNNING" }
  },
  "agent_state": "MONITORING" // MONITORING, ANALYZING, INTERVENING
}
```

---

## 2. Swarm & Advisories

### `GET /advisories/active`
Returns active Terminal Advisories with Swarm consensus data.

---

## 3. Interactive Controls

### `POST /sim/inject`
Inject a manual fault or condition for interactive demos.
**Body:**
```json
{
  "type": "EQUIPMENT_FAULT", // WEATHER_EVENT, VIP_OVERRIDE, DATA_CORRUPTION
  "target": "chiller_01",
  "parameter": "vibration",
  "value": 5.5,
  "duration_hours": 2
}
```

### `POST /advisories/{id}/acknowledge`
Manual human intervention to accept/reject swarm advice.

---

## 4. Glass Box SSE (Live Thought Stream)

### `GET /stream/thoughts`
**Server-Sent Events (SSE)** endpoint streaming background reasoning.

**Event Types:**
- [thought](file:///e:/Automation/tests/omega_stress_test/omega_test_runner.py#2219-2251): "Ambient Thinking" processed by the Swarm in the background.
- `swarm_event`: BFT consensus updates (e.g., "Comfort Agent vetoed Energy proposal").
- `truth_score`: Real-time validation results for emergent reasoning.
- `tool_use`: Live tool execution by specialized agents.
- `learning`: Dynamic updates to the Institutional Memory.
