# ARVIS API Contracts

REST + streaming endpoint specs. Engineer reference; designer skim for context.

## Base

- Base URL: `/api/v1`
- Auth: `Authorization: Bearer <jwt>` (Cognito or Auth0 — TBD)
- Content type: `application/json`
- Building scope: every read endpoint checks `claims.building_ids ∋ <building_id>`. Returns 403 if not authorized.
- Versioning: URL path. Breaking changes bump to `/api/v2`.

## REST endpoints

### Buildings

```
GET  /buildings                          → Building[]
GET  /buildings/{id}                     → Building
GET  /buildings/{id}/topology            → { equipment: Equipment[], edges: TopologyEdge[] }
```

### Equipment

```
GET  /equipment/{id}                     → Equipment + current state
GET  /equipment/{id}/points              → Point[]
GET  /equipment/{id}/trends?range=24h    → { point_id, series: [{ts, value}] }[]
GET  /equipment/{id}/physics-prediction  → PhysicsPrediction
GET  /equipment/{id}/advisories          → Advisory[] (recent)
```

### Advisories

```
GET  /advisories?since=&risk_tier=&building=&status=  → Advisory[] (paginated)
GET  /advisories/{id}                                  → Advisory (full, with plan + ledger + verifier + counterfactual)
POST /advisories/{id}/approve                          → ActionResult
POST /advisories/{id}/reject                           → ActionResult
POST /advisories/{id}/snooze                           → ActionResult
POST /feedback                                         → FeedbackResult
```

### Memory

```
GET  /memory/search?q=&tier=&limit=      → MemoryEntry[]
GET  /memory/{id}                        → MemoryEntry (full)
POST /memory/feedback                    → mark useful / not useful
```

### Alarms

```
GET  /alarms?building=&active=true       → Alarm[]
POST /alarms/{id}/ack                    → AckResult
```

### Compliance / GSAS

```
GET  /compliance/gsas/{building_id}                       → GSASScore
GET  /compliance/gsas/{building_id}/categories            → GSASCategory[]
GET  /compliance/gsas/{building_id}/criterion/{id}        → GSASCriterion (full)
GET  /compliance/gsas/{building_id}/deductions            → Deduction[]
POST /compliance/gsas/{building_id}/evidence              → upload doc
GET  /compliance/gsas/{building_id}/audit-package         → kicks off generation
GET  /compliance/gsas/{building_id}/audit-package/{job}   → status / download URL
```

### Surveys

```
GET  /surveys/templates                  → SurveyTemplate[]
POST /surveys/send                       → SendResult
GET  /surveys/active                     → ActiveSurvey[]
GET  /surveys/{id}/results               → SurveyResults
```

### Audit Replay

```
GET  /audit/replay/{plan_id}             → { events: ReplayEvent[] }
```

### Simulation (SIM only)

```
POST /sim/scenario/start                 → { run_id }
POST /sim/scenario/pause
POST /sim/scenario/resume
POST /sim/scenario/reset
POST /sim/persona/{name}/enable
POST /sim/persona/{name}/disable
POST /sim/clock/set                      → { sim_time, speed }
GET  /sim/judge-verdicts/{run_id}        → JudgeVerdicts
```

### Onboarding

```
POST /onboarding/upload-yaml             → BuildingSpec
POST /onboarding/map-points              → PointMapping
GET  /onboarding/coverage                → { mapped, total, percent }
POST /onboarding/go-live                 → flips PILOT → PROD (gated, audit-logged)
```

### Settings + roles

```
GET  /me                                 → { user_id, role, building_ids, mode }
GET  /settings/{building_id}             → BuildingSettings
PATCH /settings/{building_id}            → BuildingSettings
GET  /roles                              → RolePermissions[]
```

### Telemetry (FE → BE)

```
POST /telemetry/ui                       → { event_type, payload, ts } — for FE perf metrics
```

## Streaming

### SSE (Server-Sent Events)

Endpoint: `GET /stream/events?building_id=&topics=`

Topics: `alarms`, `advisories`, `points`, `trace`, `gsas`

Envelope (all events):
```
data: { "event_type": "...", "event_id": "...", "ts": "...", "building_id": "...", "payload": {...} }
```

Client supports `Last-Event-ID` header for reconnect. Server holds 5-minute event buffer. Beyond that, client must full-refresh via REST.

### Event types

- `advisory_published` — new advisory available
- `advisory_state_change` — advisory approved / rejected / snoozed / withdrawn
- `alarm_new` — new alarm raised
- `alarm_cleared` — alarm cleared
- `point_update` — point value changed (batched on 100ms window, max 20 events/frame)
- `trace_event` — agent trace event during active investigation
- `gsas_score_update` — GSAS score changed

### Aggregation

Server-side coalescing rules:
- `point_update`: 100ms window, drop-oldest if buffer > 20
- `trace_event`: 100ms window, no drop (must be complete)
- Other events: no coalescing

## Pagination

Cursor-based:
```
GET /advisories?cursor=eyJpZCI6...&limit=50
→ { data: [...], next_cursor: "..." | null }
```

Limits: default 50, max 200.

## Errors

```
HTTP 400 → { error: "validation", details: {...} }
HTTP 401 → { error: "unauthenticated" }
HTTP 403 → { error: "forbidden", required_role: "..." }
HTTP 404 → { error: "not_found" }
HTTP 409 → { error: "conflict", reason: "..." } — e.g., approving already-approved advisory
HTTP 429 → { error: "rate_limit", retry_after: 60 }
HTTP 500 → { error: "internal" }
```

## Idempotency

`POST /advisories/{id}/approve` etc. accept `Idempotency-Key` header. Same key within 60 seconds returns prior response without re-executing.

## Performance budgets

| Endpoint | p50 | p95 |
|---|---|---|
| GET /advisories (list) | <100ms | <300ms |
| GET /advisories/{id} (full) | <200ms | <500ms |
| GET /equipment/{id}/trends?range=24h | <300ms | <800ms |
| POST /advisories/{id}/approve | <150ms | <400ms |
| SSE first event after connect | <500ms | <1500ms |
| Trace event end-to-end (engine → FE paint) | <300ms | <1000ms |

## Auth flows

- Login: redirect to Cognito/Auth0 hosted UI
- Callback: receive code, exchange for JWT, store in HTTP-only cookie + short-lived access token
- Refresh: silent in iframe (Cognito) or refresh token (Auth0)
- Logout: clear cookie + revoke session
- Role: claims include `role` and `building_ids[]`

## CORS

Same-origin in production (FE proxied through BE). Dev: allow localhost:3000.
