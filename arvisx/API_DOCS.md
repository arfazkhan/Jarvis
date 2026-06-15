# ArvisX — Pilot API Documentation (Checklist + Agentic AI)

Phase-0, software-only (no edge hardware). Everything runs on the human-entered checklist
data. The agentic endpoints degrade to deterministic output when no LLM key is set, so the
pilot works with zero external dependencies.

---

## 1. Conventions

- **Base URL:** `http://<host>:8091/api/v1` (demo). The mobile checklist form is at `http://<host>:8091/forms`.
- **Auth:** if `ARVISX_API_KEY` is set, every `/api/v1/*` call must send it:
  `Authorization: Bearer <key>` **or** `X-API-Key: <key>`. Unset = open (dev/pilot on localhost only).
- **Content type:** JSON in / JSON out, except photo/vision uploads (raw image bytes).
- **`building`** — every endpoint is building-scoped; defaults to `one-anthem`. Pass `?building=` to scope.
- **Dates** — `YYYY-MM-DD`; timestamps are ISO-8601, server-generated (cannot be backdated).
- **Errors** — standard HTTP codes; body `{"detail": "<message>"}` (400 bad input, 404 not found,
  409 conflict, 422 validation).
- **Item kinds:** `tick` (done/issue), `reading` (number + unit), `state` (one of options), `note` (text).
- **Issue lifecycle:** `open → assigned → in_progress → resolved` (reopen allowed).
- **Grounding:** agent endpoints return `"source": "agent"` (LLM, passed the fabricated-number
  guard) or `"deterministic"` / `"deterministic-fallback"`. Numbers always trace to real data.

---

## 1b. Authentication & accounts

There are two auth modes; they coexist:
- **API key** (`ARVISX_API_KEY`) — server-to-server / the WhatsApp bot. Sent as
  `X-API-Key` or `Authorization: Bearer <key>`. Acts as role **`system`** (full write).
- **User accounts + tokens** — for the committee-facing frontend. Users have a role:
  **owner** / **fm** (can write) · **viewer** (read-only). Login mints an HMAC-signed token
  (JWT-shaped, 24 h TTL via `ARVISX_TOKEN_TTL`).

**When is auth enforced?** When at least one user exists **or** `ARVISX_API_KEY` is set.
With neither (local dev) the API is open and every request is role `system`.

**Write gating:** any non-GET request needs `owner` / `fm` / `system`; a `viewer` token gets
**403**. Reads need any valid identity (or open dev mode).

### Bootstrap the first admin
On first boot with no users, set `ARVISX_ADMIN_USER` + `ARVISX_ADMIN_PASSWORD` → an `owner`
account is created automatically.

### POST /auth/login   (exempt from auth)
```json
{ "username":"admin", "password":"secret" }
```
→ `{ "token":"<body>.<sig>", "role":"owner", "username":"admin" }`
Use it on every call: `Authorization: Bearer <token>`.

### GET /auth/me  → `{ "username":"admin", "role":"owner" }` (who the token/key resolves to).

### POST /auth/users   (owner / system only — this is account creation)
```json
{ "username":"rahul", "password":"pw", "role":"fm" }
```
→ `{ "username":"rahul", "role":"fm" }`  · roles: `owner` | `fm` | `viewer`.

> Note: these `auth` roles gate **API access** (read vs write). They are separate from the
> WhatsApp **voice tiers** (resident/manager/technician) and the **checklist roster**
> (who performs rounds) — different concepts, don't conflate.

---

## 2. Checklist templates (builder)

### GET /forms/templates
List the building's checklists (code defaults + custom).
```
curl "$B/forms/templates?building=one-anthem"
```
```json
{ "building": "one-anthem",
  "templates": [
    {"template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations",
     "cadence":"daily","timing":"12:00 AM – 08:15 PM","items":24,"per_asset":[]}
  ] }
```

### GET /forms/template/{template_id}
Full template (sections + items).
```json
{ "template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations","cadence":"daily",
  "timing":"12:00 AM – 08:15 PM","signoff_roles":["technician","supervisor","caretaker","engineer","president"],
  "per_asset":[],
  "sections":[
    {"name":"Water Treatment Plant","items":[
      {"item_id":"wtp_backwash","label":"WTP backwash","kind":"tick","unit":"","options":[],"alert_states":[],"asset":"WTP"},
      {"item_id":"wtp_leakage","label":"Leakage detected","kind":"state","unit":"","options":["NIL","DETECTED"],"alert_states":["DETECTED"],"asset":"WTP"}
    ]}
  ] }
```

### POST /forms/templates  (create / edit — the builder)
```json
{ "building":"one-anthem",
  "template":{
    "template_id":"CUSTOM-DG","name":"DG Quick Check","cadence":"daily",
    "signoff_roles":["technician","engineer"],
    "sections":[{"name":"DG","items":[
      {"item_id":"dg_oil_ok","label":"DG-1 oil level ok?","kind":"tick","asset":"DG-1"},
      {"item_id":"dg_v","label":"Battery voltage","kind":"reading","unit":"V","asset":"DG-1"}
    ]}]} }
```
→ `{"saved":true,"template_id":"CUSTOM-DG","building":"one-anthem"}`
Errors 400: missing `template_id`/`name`, no sections, duplicate `item_id`, bad `kind`.

### DELETE /forms/template/{template_id}?building=
→ `{"deleted":"CUSTOM-DG","building":"one-anthem"}` (404 if no custom template by that id).

### Seeds / onboarding a new building
Built-in checklists are **seed data** (`arvisx/seeds/*.json`), not code.
- `GET /forms/seeds` → `{"seeds":[{"building_id":"one-anthem","name":"One Anthem Apartments","templates":4}]}`
- `POST /forms/seed` `{"building":"green-meadows","from":"one-anthem"}` → clones a starter pack
  into a new building → `{"building":"green-meadows","seeded":["ANTHEM-SHIFT-1","..."]}`.
  (Or `{"building":..,"templates":[...]}` to bulk-import your own.) Onboarding building #2 = one
  call, no code change; thereafter pass `?building=green-meadows` everywhere.

---

## 3. Rounds (checklist runs)

### POST /forms/run  — start or resume today's run
```json
{ "template_id":"ANTHEM-SHIFT-2", "building":"one-anthem",
  "technician":"Ajith", "assignee":"Ajith", "date":"2026-06-14", "asset":"" }
```
`date`/`asset` optional (asset is for per-asset PPM runs). Resuming an open run for the same
template+date returns the existing one. Setting `assignee` queues a WhatsApp DM to that tech.
**Response (the run view, returned by most run endpoints):**
```json
{ "run":{"id":1,"building_id":"one-anthem","template_id":"ANTHEM-SHIFT-2","asset":"",
         "shift_date":"2026-06-14","technician":"Ajith","status":"open",
         "started_at":"2026-06-14T09:02:11","submitted_at":null,"assignee":"Ajith"},
  "template":{ ...full template... },
  "entries":{},
  "summary":{"total":24,"done":0,"completion_pct":0,"missing":["wtp_backwash", "..."],"issues":[]},
  "signoffs":[] }
```

### GET /forms/run/{rid}
Returns the same run view.

### POST /forms/run/{rid}/entry  — record one item (server-timestamped)
```json
{ "item_id":"g2_fire_alarm", "value":"OFF", "status":"", "note":"" }
```
For `tick`: `status` = `ok`|`issue`. For `state`/`reading`/`note`: put the value in `value`.
A value matching the item's `alert_states` (e.g. fire `OFF`) **auto-flags an issue**.
```json
{ "saved":true, "item_id":"g2_fire_alarm", "is_issue":true,
  "summary":{"total":24,"done":1,"completion_pct":4,"missing":["..."],
             "issues":[{"item_id":"g2_fire_alarm","label":"Fire alarm panel health (main ON / no fault)","value":"OFF","note":""}]} }
```
409 if the run is already submitted.

### POST /forms/run/{rid}/photo?item_id=<id>&filename=<name>  — attach photo
Body = **raw image bytes**, header `Content-Type: image/jpeg|png|webp` (max 8 MB).
```
curl -X POST "$B/forms/run/1/photo?item_id=g2_oh_tank&filename=tank.jpg" \
  -H "Content-Type: image/jpeg" --data-binary @tank.jpg
```
→ `{"saved":true,"item_id":"g2_oh_tank","photo":"<uuid>.jpg"}`  · view at `GET /photos/<uuid>.jpg`

### POST /forms/run/{rid}/assign  — manager assigns a technician
```json
{ "assignee":"Suresh" }
```
→ run view (with `run.assignee` updated); DMs the tech if they have a roster phone.

### POST /forms/run/{rid}/signoff
```json
{ "role":"supervisor", "by":"Athul" }
```
→ run view (with `signoffs` updated). Roles per the template's `signoff_roles`.

### POST /forms/run/{rid}/submit
Locks the run. → run view with `run.status":"submitted"`.

### GET /forms/run/{rid}/review  — AI supervisor (L2), no LLM
```json
{ "run_id":1,"completion_pct":58,
  "missing":[{"item_id":"el_room3","label":"Electrical room-3 inspection"}],
  "flagged_issues":[{"item_id":"g2_fire_alarm","label":"Fire alarm panel health (main ON / no fault)","value":"OFF"}],
  "anomalies":[{"item_id":"g2_oh_tank","label":"OH tank water level","flagged":true,"z":-3.4,"median":88,"low":80,"high":96,"latest":45,"direction":"below","n":12}],
  "trends":[{"item_id":"g2_gf_raw_tank","label":"GF raw tank water level","flagged":true,"direction":"declining","from":80,"to":40,"change_pct":50}] }
```

### GET /forms/today?building=&date=  — manager day view
```json
{ "building":"one-anthem","date":"2026-06-14",
  "runs":[{"run_id":1,"template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations",
           "status":"open","assignee":"Ajith","technician":"Ajith","asset":"",
           "completion_pct":58,"issues":[{"item_id":"g2_fire_alarm","label":"...","value":"OFF"}],
           "signoffs":["technician"]}] }
```

### GET /forms/assigned?technician=&building=&date=  — a tech's task list
```json
{ "technician":"Ajith","date":"2026-06-14",
  "assigned":[{"run_id":1,"name":"Shift II — Daily Operations","status":"open","asset":"",
               "completion_pct":58,"open_items":10,"issues":1}] }
```

### GET /forms/digest?building=&date=  — WhatsApp-ready manager summary
Includes today's rounds plus an **aged-open-issues** section (issues unresolved >2 days, so
a long-running issue can't fade after it tops the escalation ladder).
```json
{ "date":"2026-06-14",
  "text":"*Checklist summary — 2026-06-14*\n...\n\n*⏳ Aged open issues (>2d):*\n• STP blower FAULT — 3d [open] → ABC Power",
  "aged_open_issues":[{"id":3,"title":"STP blower FAULT","status":"open","age_days":3.0,"assignee":"","vendor":"ABC Power"}] }
```

---

## 4. Technician roster

### GET /technicians?building=&all=false
→ `{"building":"one-anthem","technicians":[{"id":1,"building_id":"one-anthem","name":"Ajith","phone":"9190...","active":1,"created_at":"..."}]}`

### POST /technicians  `{"name":"Ajith","phone":"9190...","building":"one-anthem"}` → `{"id":1,"name":"Ajith"}`
Re-adding an existing name reactivates it (no duplicate).

### POST /technicians/{id}/deactivate → `{"id":1,"active":false}`

---

## 5. Issues

### GET /issues?building=&status=&asset=
```json
{ "building":"one-anthem",
  "issues":[{"id":3,"building_id":"one-anthem","run_id":1,"item_id":"g2_fire_alarm","asset":"FIRE-PANEL",
             "title":"Fire alarm panel health (main ON / no fault): OFF","detail":"","status":"open",
             "severity":"issue","source":"auto","assignee":"","raised_by":"Ajith","photo":null,
             "created_at":"...","updated_at":"...",
             "history":[{"ts":"...","action":"opened","by":"Ajith","note":""}]}] }
```

### GET /issues/{id} → the issue object (as above).

### POST /issues  — log manually
```json
{ "building":"one-anthem","title":"STP blower noise","detail":"grinding sound","asset":"STP","severity":"issue","by":"Athul" }
```
→ the created issue object.

### POST /issues/{id}/transition  — lifecycle + assignment
```json
{ "status":"assigned", "assignee":"Suresh", "by":"Athul", "note":"please inspect today" }
```
`status` ∈ open/assigned/in_progress/resolved (validated; 409 on illegal jump). `assignee`/`note`
optional. → the updated issue object (history appended).

### POST /issues/{id}/photo  — raw image bytes (like the run photo). → `{"saved":true,"issue_id":3,"photo":"<uuid>.jpg"}`

---

## 6. PPM scheduling

### GET /ppm/schedule?building=
```json
{ "building":"one-anthem",
  "schedules":[{"asset":"DG-1","interval_days":90,"last_done":"2026-01-01","run_hours_limit":250,
                "latest_run_hours":243,"due_date":"2026-04-01","days_remaining":-74,
                "hours_remaining":7,"overdue":true,"status":"overdue"}] }
```
`status` ∈ ok / due_soon / overdue / unscheduled (date-based OR condition-based on run hours).

### POST /ppm/schedule  `{"asset":"DG-1","interval_days":90,"last_done":"2026-01-01","run_hours_limit":250,"building":"one-anthem"}`
Partial updates allowed (omitted fields keep current values). → `{"saved":true,"asset":"DG-1"}`

### POST /ppm/{asset}/done  `{"date":"2026-06-14","building":"one-anthem"}` → `{"asset":"DG-1","last_done":"2026-06-14"}`

---

## 7. Assets & history

### GET /assets?building= → `{"building":"one-anthem","assets":["BOREWELL","DG-1","DG-2","FIRE-PANEL","FIRE-PUMP","GF-FILTER-TANK","GF-RAW-TANK","LIFT","OH-TANK","POOL","STP","TRANSFORMER","WTP"]}`

### GET /assets/{asset}/history?building=&limit=100
```json
{ "building":"one-anthem","asset":"DG-1",
  "entries":[{"item_id":"dg_battery_v","value":"22.0","status":"","note":"","is_issue":false,
              "ts":"2026-06-14T20:11:03","photo":null,"shift_date":"2026-06-14","template_id":"ANTHEM-SHIFT-3"}],
  "issues":[ ...issue objects for this asset... ],
  "ppm":{ ...ppm_status for this asset, or null... } }
```

---

## 8. Analyzers (deterministic, no LLM)

### GET /analyzers/readings  — L1 anomalies vs each item's own band
```json
{ "building":"one-anthem",
  "anomalies":[{"item_id":"dg_battery_v","label":"Battery voltage","asset":"DG-1","unit":"V",
                "flagged":true,"z":-4.1,"median":24.9,"low":24.1,"high":25.7,"latest":21.7,"n":8,"direction":"below"}] }
```

### GET /analyzers/health  — L7 asset health (riskiest first)
```json
{ "building":"one-anthem",
  "assets":[{"asset":"DG-2","score":55,"band":"risk","reasons":["1 critical issue(s)","PPM overdue"],
             "open_issues":1,"overdue_ppm":true},
            {"asset":"DG-1","score":92,"band":"good","reasons":[],"open_issues":0,"overdue_ppm":false}] }
```
`band` ∈ good (≥85) / watch (≥60) / risk.

### GET /analyzers/readiness  — one building score (Maintenance Readiness)
0.7·(weighted asset health) + 0.3·(today's round completion) − PPM penalty. Maintenance/
inspection readiness from checklist data — **not** live equipment condition (sensors upgrade
the same score in Phase 1). A day with no completed rounds is capped at 60.
```json
{ "building":"one-anthem","label":"Maintenance Readiness","readiness":64,"band":"Attention Required",
  "components":{"asset_health_avg":87,"rounds_completion_avg":8,"overdue_ppm":0,"compliance_penalty":0},
  "contributors":["DG-2: 55/100 (1 critical issue(s))","rounds 8% complete today"],
  "assets_assessed":13,"note":"...not live equipment condition (sensors, Phase 1)..." }
```
`band`: Healthy ≥80 / Attention ≥50 / Critical.

### GET /analyzers/compliance  — L8
```json
{ "building":"one-anthem","compliance_risk":"high",
  "overdue_ppm":[{"asset":"MSB","days_overdue":17,"hours_over":null}],
  "due_soon_ppm":["DG-1"],
  "stale_assets":[{"asset":"LIFT","days_since_check":9}] }
```

### GET /analyzers/watchlist  — L6 failure watchlist (evidence + level, NO probability)
```json
{ "building":"one-anthem",
  "watchlist":[{"asset":"DG-2","concern":"high","signals":["1 open critical issue(s)","PPM overdue"],
                "note":"Concern level from corroborating signals — no failure probability/window (that needs continuous sensor data, Phase 1)."},
               {"asset":"DG-1","concern":"elevated","signals":["Battery voltage declining (25.0→22.0)"],"note":"..."}] }
```

---

## 9. Agents (LLM if `ARVISX_LLM_PROVIDER`/key set; deterministic fallback otherwise)

### GET /agents/handover?building=&notify=false&to=  — C-1 Shift Handover
```json
{ "text":"*Shift Handover*\n\n*Open Issues:*\n1. Fire alarm panel health: OFF [open] (→ Ajith)\n\n*Pending Tasks:*\n• Electrical room-3 inspection — Shift II — Daily Operations\n\n*Priority:* High",
  "source":"deterministic", "priority":"High" }
```
`notify=true` queues it to WhatsApp (DM `to`, else ops broadcast).

### GET /agents/rca?asset=DG-1&building=&notify=&to=  — C-2 Root-Cause
```json
{ "asset":"DG-1",
  "text":"*Root Cause — DG-1*\n\nObservations:\n• Battery voltage declining (25.0→22.0)\n• PPM overdue\n\nProbable cause: Battery deterioration — voltage trending down, PPM overdue (ageing / low utilization likely).\nRecommended: Battery load test; equalize charge; schedule periodic generator exercise runs.\nConfidence: Medium",
  "source":"deterministic","confidence":"Medium",
  "probable_cause":"Battery deterioration — voltage trending down, PPM overdue (ageing / low utilization likely)." }
```

### GET /agents/work-order?issue_id=3&building=  — C-3 Work-Order draft (deterministic)
```json
{ "issue_id":3,"asset":"FIRE-PANEL","observation":"Fire alarm panel health: OFF",
  "category":"Safety","required_team":"Fire-Safety","priority":"High",
  "suggested_action":"Verify the safety system and restore to normal; escalate if not resolved.",
  "text":"*Suggested Work Order — FIRE-PANEL*\n..." }
```

### GET /agents/ask?q=<question>&building=  — C-4 ask-the-building
```
curl "$B/agents/ask?q=what%20is%20the%20riskiest%20system"
```
```json
{ "text":"*Riskiest systems:*\n• DG-2: 55/100 (risk) — 1 critical issue(s), PPM overdue\n...","source":"deterministic" }
```

---

## 10. Vision (pipeline ready; model pluggable)

Without a vision model (`ARVISX_VISION_PROVIDER` unset) the pipeline still runs and reports
`available:false`; the photo is saved as evidence and the value is entered manually.

### POST /vision/extract?kind=gauge&run_id=&item_id=&building=&filename=
Body = raw image bytes. `kind` ∈ gauge/panel/level/condition/auto. Stores the photo + a
**pending** suggestion. **Never writes to the entry** — that needs confirm.
```json
{ "suggestion_id":5,"photo":"<uuid>.jpg","available":false,"reason":"vision model not configured",
  "kind":"gauge","extracted":{} }
```
With a model wired, `available:true` and e.g. `"extracted":{"readings":{"voltage":415,"current":118,"frequency":50},"confidence":0.9}`.

### GET /vision/suggestions?building=&status= → list of suggestions.

### POST /vision/suggestion/{id}/confirm  — operator confirms → writes the entry
```json
{ "value":"24.8", "run_id":1, "item_id":"dg_battery_v" }
```
(run_id/item_id optional if already on the suggestion). → the updated suggestion (status `confirmed`).

### POST /vision/suggestion/{id}/reject → `{"suggestion_id":5,"status":"rejected"}`

---

## 10b. SLA, escalation & vendor accountability

Every issue carries a **priority** → an SLA clock → a timed escalation ladder
(reminder → supervisor → facility manager → committee). Vendors can own the fix and have
their response/resolution measured. Deterministic; escalations ride the notification queue.

### Priority & SLA defaults (hours, per-building configurable)
| priority | response | resolution |
|---|---|---|
| critical | 1 | 4 |
| high | 4 | 24 |
| medium | 24 | 72 |
| low | 48 | 168 |
Escalation level by age: ≥response → reminder, ≥resolution → supervisor, ≥2× → facility
manager, ≥3× → committee. Issues with no `priority` fall back to severity (critical→critical, issue→medium).

### GET /sla/config?building=
```json
{ "building":"one-anthem","sla":{
    "critical":{"response_hours":1,"resolution_hours":4,"default":true},
    "high":{"response_hours":4,"resolution_hours":24,"default":true}, "...":{} } }
```
### POST /sla/config  `{"priority":"critical","response_hours":1,"resolution_hours":4,"building":"one-anthem"}` → `{"saved":true,"priority":"critical"}`

### GET /issues/{id}/sla
```json
{ "priority":"high","age_hours":30.0,"response_hours":4,"resolution_hours":24,
  "breached_resolution":true,"escalation_level":2,"target":"supervisor" }
```

### POST /escalations/run?building=  — ISSUE SLA sweep (bot calls each poll)
Escalates any open issue past its SLA, one notification per new level. → `{"building":"one-anthem","fired":[{"issue_id":3,"level":2,"target":"supervisor"}]}`

### POST /forms/reminders/run?building=  — ROUND sweep + lapse (bot calls each poll)
Two things in one sweep:
1. **Reminders** — assigned-but-unfinished rounds today: after `ARVISX_ROUND_REMIND_H`
   (default 6) DM the technician; after `ARVISX_ROUND_ESCALATE_H` (default 10) escalate to
   the manager. One notification per level; submitted/complete skipped; unassigned → manager.
2. **Lapse** — any still-`open` run from a **prior day** is closed to terminal status
   `lapsed` (with its completion %) + a manager notice, so incomplete rounds never hang open.
```json
{ "building":"one-anthem",
  "lapsed":[{"run_id":1,"shift_date":"2026-06-13","completion_pct":40}],
  "fired":[{"run_id":7,"level":1,"assignee":"Ajith"}] }
```
`level` 1 = technician nudged, 2 = manager escalated. **Run terminal states: `submitted` | `lapsed`.**

### Vendors
- `GET /vendors?building=&all=false` → `{"building":"one-anthem","vendors":[{"id":1,"name":"ABC Power","category":"DG","contact":"98xx","active":1}]}`
- `POST /vendors` `{"name":"ABC Power","category":"DG","contact":"98xx","building":"one-anthem"}` → `{"id":1,"name":"ABC Power"}`
- `POST /vendors/{id}/deactivate`

### Assigning a vendor / priority to an issue
Via `POST /issues/{id}/transition` (section 5) with extra fields:
```json
{ "status":"assigned", "assignee":"ABC Power", "vendor":"ABC Power", "priority":"high", "by":"Athul" }
```

### POST /issues/{id}/visited  `{"by":"Athul"}` — vendor site-visit milestone (feeds response-time analytics) → the issue object.

### GET /analyzers/vendors?building=  — vendor performance (slowest resolution first)
```json
{ "building":"one-anthem",
  "vendors":[{"vendor":"SlowCo","jobs":4,"resolved":3,"escalations":2,
              "avg_response_hours":18.0,"avg_resolution_hours":52.0},
             {"vendor":"ABC Power","jobs":6,"resolved":6,"escalations":0,
              "avg_response_hours":2.5,"avg_resolution_hours":9.0}] }
```

---

## 11. WhatsApp integration queue (for the bot)

The bot polls these; you usually don't call them directly.
- `GET /whatsapp/notifications` → `{"notifications":[{"id":1,"building_id":"one-anthem","to_number":"9190...","kind":"assignment","text":"..."}]}` (to_number set = DM; blank = ops broadcast).
- `POST /whatsapp/notifications/ack` `{"ids":[1,2]}` → marks delivered (at-least-once).
- `GET /resident-requests?status=` / `POST /resident-requests/ack` — resident maintenance requests.

---

## 12. Typical pilot flow (request order)

1. `POST /technicians` (build the roster) · `POST /forms/templates` (optional custom checklists)
2. `POST /forms/run` with `assignee` → tech gets a WhatsApp DM
3. tech: `POST /forms/run/{rid}/entry` (+ `/photo`) per item — `fire=OFF` auto-opens an issue (manager alerted)
4. `GET /forms/run/{rid}/review` (supervisor) · `GET /issues` · `GET /agents/work-order?issue_id=`
5. `POST /issues/{id}/transition` (assign → resolve) · `POST /forms/run/{rid}/signoff` · `/submit`
6. roll-ups: `GET /analyzers/health|compliance|watchlist`, `GET /agents/handover`, `GET /agents/ask`

All Phase-0, no hardware. Edge sensors (later) feed the same `reading` items + light up
vision/verification — the API surface does not change for the pilot→hardware upgrade.

---

## 13. Scope note — endpoints NOT in this doc

This document covers the **checklist + agentic AI pilot** surface only. The running API also
exposes **legacy ArvisX platform endpoints** that are NOT part of the Phase-0 checklist
product and are out of scope here: `/commission/*` (building commissioning), `/community/*`,
`/workorders/*`, `/water`, `/topology`, `/impact`, `/heartbeat/*`, `/watches`,
`/investigations`, `/investigate`, `/monitor`, `/incident/*`, `/reason/*`, `/ask` (legacy),
`/skillbook`, `/signal-quality`, `/events/stream`, `/scenario/*`, `/gas/billing`,
and the older `/checklist/*` (telemetry checklist, superseded by `/forms/*`). They belong to
the sensor/commercial path; ignore them for the pilot. Everything a checklist pilot needs is
in sections 2–12 above.

Machine-readable spec: FastAPI serves the live OpenAPI at `GET /openapi.json` and Swagger UI
at `GET /docs` — but those list ALL routes (including the legacy ones above); this doc is the
curated pilot subset.
