# ARVIS Demo API — Full Reference

Router prefix: **`/api/v1/demo`** (FastAPI, tag `ARVIS Demo Capabilities`)
Source: `agent_commercial/api/routes_demo.py`
Base URL (sim): `http://localhost:8000`
OpenAPI/Swagger: `http://localhost:8000/api/docs`

> ARVIS is **read-only / advisory**. No endpoint here actuates equipment. "Actions" are recommendations only; the synthesis layer strips action verbs (`shut down`, `corrected`) before returning.

Conventions used below:
- **Auth**: demo router endpoints are unauthenticated in sim mode. (Core `/api/v1/*` routes use bearer tokens from `POST /api/v1/auth/token`.)
- All timestamps are ISO-8601 local (`datetime.now().isoformat()`), e.g. `2026-05-31T03:44:05.747000`.
- All bodies are JSON; all responses `application/json` unless noted (SSE / HTML / PNG).
- Common errors: `503` engine not wired, `404` resource not found, `422` request-body validation (FastAPI/Pydantic).

---

## Endpoint Index

| # | Method | Path | Group | Purpose |
|---|--------|------|-------|---------|
| 1 | GET | `/building/overview` | 1 Telemetry | Building snapshot, equipment grouped by type |
| 2 | GET | `/building/equipment/{equipment_id}` | 1 | Deep equipment detail + 60-min history |
| 3 | GET | `/building/alarms` | 1 | Active alarms enriched w/ equipment meta |
| 4 | GET | `/building/topology` | 1 | Floor/zone spatial tree |
| 5 | POST | `/calibrate/start` | 2 Calibration | Start baseline calibration (Marina preset) |
| 6 | GET | `/calibrate/status` | 2 | Calibration/sim status |
| 7 | GET | `/scenario/list` | 3 Scenarios | Fault scenario catalog |
| 8 | POST | `/scenario/inject` | 3 | Inject a curated fault |
| 9 | GET | `/scenario/active` | 3 | Currently active injected faults |
| 10 | POST | `/reasoning/trigger` | 4 Swarm | **Run the swarm**, returns `investigation_result` |
| 11 | GET | `/reasoning/latest` | 4 | Latest advisory |
| 12 | GET | `/advisories/history` | 4 | Advisory timeline |
| 13 | GET | `/explain/advisory/{advisory_id}` | 5 Explain | Causal chain, BFT votes, H4 status |
| 14 | GET | `/intelligence/summary` | 5 | Brain dashboard (trust, GSAS, patterns) |
| 15 | GET | `/stream/investigation` | Stream | **SSE** live investigation feed (Screen 3) |
| 16 | POST | `/workorder/create` | Work orders | Create follow-up work order |
| 17 | GET | `/workorder/list` | Work orders | List/filter work orders |
| 18 | POST | `/workorder/{work_order_id}/status` | Work orders | Update WO status |
| 19 | POST | `/artifacts/generate` | Artifacts | Generate report/roadmap/chart set |
| 20 | GET | `/artifacts/{artifact_set_id}` | Artifacts | Fetch a generated set |
| 21 | GET | `/artifacts/{artifact_set_id}/download/{artifact_type}` | Artifacts | Download one artifact (HTML/PNG/JSON) |

---

# GROUP 1 — Building Infrastructure (live telemetry)

## 1. `GET /building/overview`
Full building snapshot, equipment grouped by type with live point values.

**Request**: none.

**Response 200**
```json
{
  "building_id": "DOHA-TOWER-001",
  "timestamp": "2026-05-31T03:44:05.747000",
  "summary": {
    "total_equipment": 7,
    "active_alarms": 6,
    "outdoor_temp": 38.5,
    "energy_demand_kw": 49.6
  },
  "equipment": {
    "chiller":       [ { "...eq.to_dict()...": "...", "points": { "<param>": <value> } } ],
    "ahu":           [ ... ],
    "pump":          [ ... ],
    "cooling_tower": [ ... ],
    "other":         [ ... ]
  }
}
```
Field notes:
- `summary.outdoor_temp` ← `current_values["WEATHER_OAT"]`, default `38.5` if absent.
- `summary.energy_demand_kw` = sum of all `current_values` keyed `*_KW`.
- Each equipment object = `Equipment.to_dict()` plus a `points` map; point keys have the `"{equipment_id}_"` prefix stripped.
- Grouping key = `equipment_type.name.lower()`; unknown types fall into `other`.

**Errors**: `503` — `BMS State Engine not available`.

---

## 2. `GET /building/equipment/{equipment_id}`
Deep detail for one equipment incl. up to 60 most-recent history points per sensor.

**Path param**: `equipment_id` (e.g. `AHU-07`).

**Response 200**
```json
{
  "equipment_id": "AHU-07",
  "name": "AHU 07 — Floor 28",
  "type": "AHU",
  "location": "Floor 28",
  "status": "RUNNING",
  "points": [
    {
      "point_id": "AHU-07_MAT",
      "name": "MAT",
      "value": 30.8,
      "history": [ { "value": 24.1, "timestamp": "2026-05-31T03:10:00" }, "...up to 60..." ]
    }
  ]
}
```
Notes:
- `type` = `equipment_type.name`; `status` = `status.name`.
- `name` = point id with `"{equipment_id}_"` stripped.
- `history` = last 60 entries of `get_point_history(pid)`. If no history buffer, falls back to a single current-value point (sparkline-safe).

**Errors**: `503` engine; `404` `Equipment {id} not found`.

---

## 3. `GET /building/alarms`
Active alarms, each enriched with equipment name/location.

**Response 200**
```json
{
  "alarms": [
    {
      "...Alarm.to_dict()...": "...",
      "equipment_name": "AHU 07 — Floor 28",
      "location": "Floor 28"
    }
  ],
  "count": 6
}
```
`equipment_name`/`location` fall back to the raw `equipment_id` / `"Unknown"` if equipment lookup misses.

**Errors**: `503` engine.

---

## 4. `GET /building/topology`
Returns the building floor/zone spatial tree (`bms_state._topology`), or a default stub.

**Response 200** (shape is engine-defined)
```json
{ "building": "Marina Heights", "floors": { } }
```
**Errors**: `503` engine.

---

# GROUP 2 — Calibration (baseline learning)

## 5. `POST /calibrate/start`
Loads `MARINA_HEIGHTS_PRESET`, sets sim speed to 100 sim-min/tick, starts the orchestrator loop, and broadcasts progress on the SSE `system` channel (`20→100%` over ~10s).

**Request**: none.

**Response 200**
```json
{ "status": "calibrating", "estimated_seconds": 10, "preset_loaded": "MARINA_HEIGHTS" }
```
Side effect (SSE `system` channel): repeated `{ "message": "📊 Calibrating AI baseline: 40% complete...", "progress": 40 }` then a `progress: 100` "Baseline learning established" event.

---

## 6. `GET /calibrate/status`

**Response 200**
```json
{
  "baseline_established": true,
  "simulation_time": "2026-05-31T03:44:00",
  "simulation_day": 1,
  "speed": 100,
  "equipment_count": 7
}
```
`baseline_established` = orchestrator is running and has ≥0 advisories. `equipment_count` = `len(MARINA_HEIGHTS_PRESET["equipment"])`.

---

# GROUP 3 — Scenario Injection (faults)

## 7. `GET /scenario/list`
Returns `SCENARIO_CATALOG` (array of curated scenarios).

**Response 200**
```json
[
  {
    "id": "chiller_vibration",
    "name": "Chiller bearing vibration",
    "fault_payload": { "...injection spec...": "..." }
  }
]
```

## 8. `POST /scenario/inject`
**Request**
```json
{ "scenario_id": "chiller_vibration" }
```
Looks up the scenario by `id`, deep-copies its `fault_payload`, calls `demo.inject_fault(...)`.

**Response 200**
```json
{ "status": "success", "scenario_id": "chiller_vibration", "fault_id": "<id>", "message": "Injected: Chiller bearing vibration" }
```
**Errors**: `404` `Scenario {id} not found in catalog`.

## 9. `GET /scenario/active`
**Response 200**
```json
{ "active_faults": [ { "...": "..." } ], "count": 1 }
```

---

# GROUP 4 — Agent Reasoning (the swarm)

## 10. `POST /reasoning/trigger` ★ core endpoint
Runs the full multi-agent swarm against the live snapshot and returns the structured `investigation_result` (Screens 3 & 4).

**Request**
```json
{ "query": "AHU-07's OA damper is creeping to 85% open, supply air running hot — walk me through what's driving it and the downstream impact." }
```
| field | type | req | notes |
|-------|------|-----|-------|
| `query` | string | yes | natural-language investigation prompt |

Internally builds `context = { sim_day, sim_time, source: "api_manual_trigger", LIVE_BMS_SNAPSHOT: <snapshot> }` and calls `llm_agent.chat(query, context, channel="demo")`.

**Response 200**
```json
{
  "response": "<advisory text>",
  "confidence": 0.55,
  "advisories_generated": [ { "type": "advisory", "severity": "critical", "equipment_id": "AHU-07", "day": 1, "generated_at": "..." } ],
  "investigation_result": { /* full object — see schema below */ },
  "metadata": {
    "truth_score": 0.96,
    "answer_confidence": 0.9,
    "data_coverage": 1.0
  }
}
```
**Errors**: `503` `ARVIS LLM Agent not connected`.

> ⚠️ Latency: a real swarm pass is **~100–210 s** (multiple Bedrock round-trips: intent, depth-plan per node, tool loops, synthesis, H4/H2/H6 verification). Subscribe to the SSE stream first (endpoint 15) to render progress.

### `investigation_result` — full schema
Built by `_build_investigation_result()` in `bms_llm_agent.py`. `null` where not derivable.

```jsonc
{
  "equipment_id": "AHU-07",
  "status": "complete",                  // "complete" | "abstained"
  "abstained": false,                    // true if a verifier (e.g. H6 physics) could not reconcile
  "fully_grounded": true,                // (not abstained) AND no "[unverified]" markers survive
  "has_unverified_claims": false,        // any "[unverified]" token left in the advisory text

  "anomaly": {
    "type": "Mixed Air Temperature Drift",   // AHU* → MAT drift label, else null
    "z_score": 5.8,                          // REAL — watchdog rolling z, or computed inline from 24h history
    "anomaly_point": "Mixed Air Temp",       // which point drove it
    "severity": "critical"                   // watchdog severity, else "significant"/"normal"
  },

  "root_cause": {
    "label": "identified",                   // "identified" vs "probable — unconfirmed, inspection required"
    "statement": "Damper Actuator Blade Slip (physical opening significantly exceeds command)",
    "confidence_band": "Medium",             // Low | Medium | High  — DIAGNOSTIC band
    "confirmed": true                        // == fully_grounded AND band in {Medium,High}
  },

  "metrics": {
    "elapsed_seconds": 114.6,                // real monotonic clock
    "agents_investigated": 3,
    "agents_converged": 3,
    "tools_executed": 13,
    "data_points_analyzed": 45,              // snapshot points + tool results
    "evidence_count": 19,                    // entries in plan.evidence ledger
    "hypotheses_evaluated": 3,
    "confidence": 0.55,                      // DIAGNOSTIC confidence (band-derived; capped 0.45 if ungrounded)
    "truth_score": 0.96,                     // GROUNDEDNESS (separate from confidence — do not relabel)
    "data_coverage": 1.0
  },

  "agents": [ { "name": "Alarm_Agent", "...": "..." } ],     // per-agent participation
  "tool_activity": [ { "tool": "analyze_root_cause", "...": "..." } ],

  "key_evidence": [                          // grounded cards; falls back to live telemetry if claims stripped
    { "label": "Mixed Air Temp", "value": 30.8, "unit": "°C", "confidence": 0.95 },
    { "label": "OA Damper",      "value": 85.0, "unit": "%",  "confidence": null }
  ],

  "cost_impact": {                           // grounded QAR/month from derived:cost evidence; null if not derivable
    "monthly_savings_qar": 499.0,
    "excess_cooling_kw": 9.9,
    "excess_daily_kwh": 118.8,
    "tariff_qar_kwh": 0.14,
    "confidence": 0.6,                       // 0.6 if airflow assumed, 0.85 if measured
    "why": "Stuck-open OA damper pulls hot outdoor air past the commanded mix; the cooling coil burns extra chiller energy ... ~QAR 499/month at the Tier-3 rate.",
    "if_ignored": "Sustained energy waste continues every operating hour, the coil stays saturated ... until the damper actuator is repaired.",
    "assumption": "airflow estimated (nominal AHU)"   // or "airflow measured"
  },

  "hypotheses": [                            // ranked competing root causes (domain-agnostic differential)
    {
      "label": "Cooling-coil capacity / CHW flow restriction",
      "rationale": "CHW valve 99% yet SAT > setpoint; coil overwhelmed, not failed.",
      "supporting_evidence_ids": ["a31f628a-9bd", "0c80f001-163", "<derived:thermodynamics>"],
      "independent_sources": 2,              // # of DISTINCT CURRENT evidence source_tools (memory_recall excluded)
      "evidence_reliability": "Medium",      // Low(1) / Medium(2) / High(3+) | "Prior (uncorroborated)" if recall-only
      "recall_only": false,                  // true → supported ONLY by memory_recall; can never lead
      "mechanism_grounded": true,            // label keyword present in cited evidence content (else sunk)
      "precondition": "",                    // design/config assumption the mechanism rests on
      "precondition_grounded": true,         // false → unverified design precondition; cannot sit at top confidence
      "discriminating_test": "Clamp-on CHW flow + strainer ΔP at the AHU.",
      "probability": 0.34                    // normalized score (rank + corroboration, after all gates)
    },
    {
      "label": "OA damper position sensor / MAT sensor fault",
      "rationale": "MAT measured upstream of coil; a biased sensor mimics excess OA.",
      "supporting_evidence_ids": ["<live_snapshot:equipment>"],
      "independent_sources": 1,
      "evidence_reliability": "Low",
      "recall_only": false,
      "mechanism_grounded": true,
      "precondition": "",
      "precondition_grounded": true,
      "discriminating_test": "Handheld thermometer traverse in the mixing box.",
      "probability": 0.29
    },
    {
      "label": "Mechanical OA damper actuator slip",
      "rationale": "Damper physically open beyond command — possible but design-dependent.",
      "supporting_evidence_ids": ["<live_snapshot:equipment>", "<derived:thermodynamics>"],
      "independent_sources": 2,
      "evidence_reliability": "Medium",
      "recall_only": false,
      "mechanism_grounded": true,
      // DEMOTED: needs a motorized damper; Gulf commercial OA dampers are often FIXED →
      // precondition unverified → cannot lead until inspection confirms damper type.
      "precondition": "Assumes a MOTORIZED, free-to-travel damper — UNVERIFIED (often FIXED at minimum). Confirm on inspection.",
      "precondition_grounded": false,
      "discriminating_test": "Is the OA damper motorized or a bolted louver? Visual inspection.",
      "probability": 0.12
    }
    // ... up to 4
  ],
  "differential": {
    "dominance": 0.05,                       // probability gap, leader vs runner-up
    "leading_corroborated": true,            // leader backed by >=2 independent CURRENT sources
    "count": 4
  },

  "recommended_actions": [ "Schedule OA damper actuator inspection", "..." ],
  "investigation_flow": ["Detect", "Investigate", "Reason", "Synthesize", "Advise"],

  "suggested_questions": [                    // dynamically generated from THIS run's facts (Screen 5)
    "Explain in plain terms why damper actuator blade slip is the root cause for AHU-07.",
    "How confident is the Mixed Air Temp reading on AHU-07 given its z-score of 5.8?"
  ],

  "operator_summary": {                        // plain-language layer (deterministic, no LLM) — render as the headline card
    "headline":        "AHU-07: cooling coil fouling — most probable cause, inspection needed.",
    "whats_happening": "AHU-07 is showing an abnormal reading (Mixed Air Temperature Drift), flagged critical — about 6x its normal variation.",
    "how_sure":        "Most likely cause: ... — but NOT confirmed; 4 competing causes are still close. Treat it as a lead to check, not a verdict.",
    "do_this_first":   "Handheld thermometer traverse in the mixing box.",   // = leading hypothesis's discriminating_test
    "caveat":          "Caveat: Assumes a MOTORIZED, free-to-travel damper — UNVERIFIED (often FIXED). Confirm on inspection.",   // "" if none
    "cost_if_ignored": "Estimated waste if left unfixed: ~QAR 499/month (airflow estimated).",   // "" if no grounded cost
    "bottom_line":     "Unconfirmed — run the one check above before committing parts or labour."
  }
}
```

**Honesty invariants** (enforced in deterministic code at parse time, not by prompt or LLM judge):
- **Numbers** — a numeric value only appears if it traces to an evidence id (NumericAudit + telemetry rebind); un-traceable numbers → `[unverified]` + quarantined.
- **Event-history claims** — "recurring / documented N times / over the past …" with no historical evidence → `[unverified]` (`_enforce_claim_binding`).
- **Every assertive sentence (claim-first)** — any advisory sentence with ≥3 significant terms, NONE of which appear anywhere in the evidence ledger, is marked `[unverified]` (`_enforce_sentence_grounding`). Regardless of how the LLM wrote the prose, an unbacked sentence cannot reach the operator unmarked. H4 (LLM) is now only a backstop for semantic contradiction.
- **`confirmed`** is `true` **only** when `fully_grounded` AND band ∈ {Medium, High} AND the leading hypothesis is corroborated by **≥2 independent CURRENT evidence sources** AND it **dominates** the runner-up (`differential.dominance ≥ 0.15`). A single-sensor lead can never be `confirmed`.
- **`hypotheses[]`** is a ranked differential (2–4 competing causes), each with a `discriminating_test`. Scoring gates (all deterministic, domain-agnostic — no per-fault rules):
  - `recall_only=true` (supported only by `memory_recall:` evidence) → ×0.1, can never lead. Memory is prior context, not present proof.
  - `mechanism_grounded=false` (label keyword absent from cited evidence content, e.g. "damper" cited against a chiller snapshot) → ×0.05.
  - `precondition_grounded=false` (design precondition unverified — e.g. damper-slip needs a MOTORIZED damper; Gulf commercial dampers are often FIXED) → ×0.25, and the assumption is surfaced in `precondition`. Covers motorized damper, VFD, compressor unloader/staging.
- **Recall is equipment-scoped** at every channel (auto-recall, skillbook tools, scenario retriever): a fault learned on AHU-07 is not retrieved for a chiller or a different AHU.
- **`operator_summary`** is the plain-language layer (deterministic, no LLM, stable structure) — render it as the headline card and collapse `hypotheses[]` / `differential` / `metrics` behind a "details for engineers" toggle. It carries the same honesty into prose: never says "confirmed" unless `root_cause.confirmed` is true, surfaces the design `caveat`, and tags the cost as an estimate.
- `truth_score` (groundedness) is reported separately from `metrics.confidence` (diagnostic) — never merged.
- `cost_impact` is computed deterministically from telemetry (mixed-air balance → excess load → tariff), not authored by the LLM; assumptions are surfaced in `assumption`/`confidence`.

---

## 11. `GET /reasoning/latest`
**Response 200**
```json
{ "advisory": { "...latest advisory_history[-1]..." }, "history_count": 4 }
```
If none yet: `{ "advisory": null, "message": "No advisories generated yet" }`.

## 12. `GET /advisories/history`
**Response 200**
```json
{ "history": [ { "...": "..." } ], "count": 4 }
```

---

# GROUP 5 — Explainability & Brain Dashboard

## 13. `GET /explain/advisory/{advisory_id}`
Deep explainability for one advisory. **Real-data path**: if the advisory carries an `investigation_result` (it does when created via `POST /reasoning/trigger`), this returns the **actual ranked differential**, evidence-grounded verification metrics, and cost case — not defaults.

**Path param**: `advisory_id`.

**Response 200 — real path** (advisory has `investigation_result`)
```json
{
  "advisory_id": "ADV-20260531143805-A1B2",
  "title": "Damper Actuator Blade Slip (physical opening exceeds command)",
  "recommendation": "<advisory message>",
  "severity": "critical",
  "confidence": 0.55,
  "grounded": true,
  "confirmed": false,
  "explainability": {
    "causal_chain": [ { "step": 1, "description": "Detect" }, "...investigation_flow stages..." ],
    "differential_diagnosis": [
      {
        "rank": 1,
        "label": "Damper Actuator Blade Slip",
        "probability": 0.34,
        "evidence_reliability": "Medium",          // Low(1)/Medium(2)/High(3+) independent sources
        "independent_sources": 2,
        "rationale": "Actual OA damper 85% vs 15% command; MAT 30.8 > expected 26.7.",
        "discriminating_test": "Visual blade/linkage inspection vs the 15% command.",
        "supporting_evidence_ids": ["a31f628a-9bd", "0c80f001-163"]
      },
      {
        "rank": 2,
        "label": "Cooling-coil capacity / CHW flow restriction",
        "probability": 0.21,
        "evidence_reliability": "Low",
        "independent_sources": 1,
        "rationale": "Valve 99% yet SAT above setpoint; low coil ΔT.",
        "discriminating_test": "Clamp-on CHW flow + strainer ΔP at the AHU.",
        "supporting_evidence_ids": ["..."]
      }
      // ... up to 4
    ],
    "differential_summary": {
      "leading": "Damper Actuator Blade Slip",
      "dominance": 0.13,
      "leading_corroborated": true,
      "hypothesis_count": 4
    },
    "key_evidence": [ { "label": "Mixed Air Temp", "value": 30.8, "unit": "°C", "confidence": 0.95 } ],
    "financial_impact": {
      "monthly_savings_qar": 499.0,
      "excess_cooling_kw": 9.9,
      "basis": "Stuck-open OA damper ... ~QAR 499/month at the Tier-3 rate.",
      "if_ignored": "Sustained energy waste ... until the damper actuator is repaired.",
      "confidence": 0.6,
      "assumption": "airflow estimated (nominal AHU)"
    },
    "verification": {
      "truth_score": 0.96,
      "evidence_count": 19,
      "data_coverage": 1.0,
      "agents_converged": 3,
      "abstained": false,
      "has_unverified_claims": false,
      "synthesis_grounding": "Unconfirmed: competing hypotheses remain — run the discriminating test(s) before acting."
    }
  }
}
```

**Response 200 — fallback** (advisory has no `investigation_result`): a presentation-shaped block with representative defaults and `explainability.note: "presentation defaults — advisory carried no investigation_result"`.

**Errors**: `404` `Advisory {id} not found` (searches `advisory_history` then `pending_advisories`).

## 14. `GET /intelligence/summary`
**Response 200**
```json
{
  "dashboard": {
    "ai_trust_score": 0.95,
    "metacognition": { "verdict": "calibrated", "bounds": { "lower": 0.35, "upper": 0.95 }, "status": "nominal" },
    "gsas_compliance": { "status": "compliant", "ieq_rating": "5-Star", "energy_rating": "A-Grade", "water_rating": "Excellent" },
    "learned_patterns": [ { "pattern": "...", "action": "..." } ]
  }
}
```

---

# Live Investigation Stream (Screen 3)

## 15. `GET /stream/investigation` — Server-Sent Events
Long-lived SSE stream of swarm lifecycle events from the `monitor` channel. **Subscribe before** calling `POST /reasoning/trigger` to capture the whole run.

**Response 200** — `text/event-stream`
Headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.

Wire format (per event):
```
event: agent_tool_call
data: {"agent":"Alarm_Agent","tool":"analyze_root_cause","stage":"Investigate","ts":"..."}

```
Event types emitted (the `event:` line):
| event | when | typical `data` keys |
|-------|------|---------------------|
| `investigation_started` | swarm pass begins | `plan_id`, `query`, `stage:"Detect"` |
| `agents_dispatched` | nodes selected | `agents:[...]`, `stage:"Investigate"` |
| `agent_tool_call` | each tool invocation | `agent`, `tool`, `stage` |
| `plan_update` | depth/route change | `stage` |
| `investigation_complete` | synthesis+verify done | `stage:"Advise"` |
| `ping` | keep-alive heartbeat | — |

Client closes by disconnecting; the generator checks `request.is_disconnected()`.

---

# Work Orders (Screen 5)

## 16. `POST /workorder/create`
**Request** (`WorkOrderRequest`)
```json
{
  "equipment_id": "AHU-07",
  "title": "Inspect OA damper actuator",
  "actions": ["Verify actuator linkage", "Check feedback signal vs command"],
  "priority": "high",
  "source_investigation": "<investigation id or null>",
  "notes": "Driven by 85% vs 15% command gap"
}
```
| field | type | req | default |
|-------|------|-----|---------|
| `equipment_id` | string | yes | — |
| `title` | string | yes | — |
| `actions` | string[] | no | `[]` |
| `priority` | string | no | `"medium"` |
| `source_investigation` | string\|null | no | `null` |
| `notes` | string\|null | no | `null` |

**Response 200**
```json
{
  "created": true,
  "work_order": {
    "id": "WO-20260531-9077B6",
    "equipment_id": "AHU-07",
    "title": "Inspect OA damper actuator",
    "actions": ["..."],
    "priority": "high",
    "status": "open",
    "source_investigation": null,
    "notes": "...",
    "created_at": "2026-05-31T03:46:00.000000"
  }
}
```
ID format: `WO-YYYYMMDD-<6 hex upper>`. Store is **in-memory** (`_WORK_ORDERS`) — swap for DB in prod.

## 17. `GET /workorder/list`
**Query params**: `equipment_id` (optional, case-insensitive), `status` (optional, exact).
**Response 200**
```json
{ "count": 1, "work_orders": [ { "...": "..." } ] }
```

## 18. `POST /workorder/{work_order_id}/status`
**Query param**: `new_status` (e.g. `open` | `in_progress` | `closed`).
**Response 200**
```json
{ "updated": true, "work_order": { "...": "...", "status": "in_progress", "updated_at": "..." } }
```
**Errors**: `404` `Work order {id} not found`.

---

# Investigation Artifacts

## 19. `POST /artifacts/generate`
Generates a post-investigation artifact set from an `investigation_result`.

**Request** (`ArtifactGenerateRequest`)
```json
{ "investigation_result": { /* IR from endpoint 10 */ }, "investigation_id": "<optional>" }
```

**Always produced**: `summary_report` (HTML), `reasoning_roadmap` (causal steps), `trend_chart` (PNG/sparkline).
**Equipment-conditional**: `feedback_vs_command` (needs CMD+actual, e.g. `OA_DMPR` + `OA_DMPR_CMD`), `evidence_manifest` (full ledger w/ source attribution).

**Response 200** (artifact set)
```json
{
  "set_id": "ART-86FE48CFCB",
  "equipment_id": "AHU-07",
  "artifacts": [
    { "type": "summary_report",     "label": "Investigation Summary", "mime": "text/html",        "content": "<html>...</html>" },
    { "type": "reasoning_roadmap",  "label": "Reasoning Roadmap",     "mime": "application/json", "content": { "steps": [ ... ] } },
    { "type": "trend_chart",        "label": "Trend Chart",           "mime": "application/json", "content": { "format": "png_base64", "data": "<b64>" } },
    { "type": "feedback_vs_command","label": "Feedback vs Command",   "mime": "application/json", "content": { ... } },
    { "type": "evidence_manifest",  "label": "Evidence Manifest",     "mime": "application/json", "content": { ... } }
  ]
}
```
Server also fetches active alarms for `ir.equipment_id` to enrich the summary report.

## 20. `GET /artifacts/{artifact_set_id}`
Returns the full set (content inline). **Errors**: `404` `Artifact set {id} not found`.

## 21. `GET /artifacts/{artifact_set_id}/download/{artifact_type}`
Downloads ONE artifact by type. Content negotiation:
- `mime == "text/html"` → `HTMLResponse` (rendered report).
- `trend_chart` with `content.format == "png_base64"` → `image/png` (`Content-Disposition: attachment; filename="<label>.png"`).
- else → `JSONResponse` (`filename="<label>.json"`).

`artifact_type` ∈ `summary_report | reasoning_roadmap | trend_chart | feedback_vs_command | evidence_manifest`.
**Errors**: `404` set not found, or type not in set (lists available types in the message).

---

# Typical demo call sequence (5-screen flow)

```
# Screen 1 — calm baseline
GET  /api/v1/demo/building/overview

# Screen 2 — anomaly visible (faults injected out-of-band by the harness)
GET  /api/v1/demo/building/alarms

# Screen 3 — open the live stream, THEN run the swarm
GET  /api/v1/demo/stream/investigation        # keep open (SSE)
POST /api/v1/demo/reasoning/trigger           # { "query": "..." }  → investigation_result

# Screen 4 — render investigation_result.{root_cause, metrics, key_evidence, cost_impact}
POST /api/v1/demo/artifacts/generate          # { "investigation_result": {...} }
GET  /api/v1/demo/artifacts/{set_id}/download/summary_report

# Screen 5 — follow-up + work order
POST /api/v1/demo/reasoning/trigger           # follow-up query (context carried by agent)
POST /api/v1/demo/workorder/create            # { "equipment_id":"AHU-07", "title":"..." }
GET  /api/v1/demo/workorder/list?equipment_id=AHU-07
```

---

# Notes / gotchas

- **`reasoning/trigger` is slow** (100–210 s). Treat it as an async job from the UI; drive progress from the SSE stream.
- **Work orders are in-memory** — restarting the server clears them.
- **`/explain/advisory/{id}`** returns demo-presentation defaults; the per-run ground truth is in `investigation_result`.
- **`confirmed` is non-deterministic across runs**: if a query is classified `safety_critical` it can enter the BFT path; a BFT veto/timeout downgrades the advisory and can leave `confirmed=false band=Medium` even though the diagnosis is grounded. This is query-classification variance, not a grounding failure.
- **Core (non-demo) API** lives in `agent_commercial/api/routes.py` (~80 endpoints: `/api/v1/auth`, `/dashboard`, `/equipment`, `/chat`, `/maintenance`, `/energy`, `/gsas/*`, `/advisory/*`, `/goals`, `/memory`, `/cognition`, `/ml`, `/fleet`). Document separately if needed.
