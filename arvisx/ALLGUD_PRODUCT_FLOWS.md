# AllGud — End-to-End Product Flows (with endpoints, requests & responses)

A complete, zero-context walkthrough of the AllGud Phase-0 product (software only, no
hardware). Read top to bottom — it follows ONE real day at "One Anthem Apartments": manager
**Meera** runs the building, technician **Ajith** does Shift II, and the **fire panel reads
OFF**. Every step shows the exact API call, what to send, and what comes back.

---

## 0. Before you start (applies to every call)

- **Base URL:** `http://<host>:8091/api/v1` — written `$B` below.
- **Format:** JSON in, JSON out (except photo uploads = raw image bytes).
- **Building scope:** every call takes `?building=` (defaults to `one-anthem`).
- **Auth:** if the server has accounts or an API key, send a token on every call:
  `Authorization: Bearer <token>`. Get one by logging in (step 1). In local dev with no
  users + no key, auth is off and you can skip the header.
- **Roles:** `owner`/`fm` can write (POST/DELETE); `viewer` is read-only (gets 403 on writes).

---

## 1. Log in (get a token)

**What:** Meera signs in; the API returns a token she sends on every later call.

```
POST $B/auth/login
{ "username": "meera", "password": "secret" }
```
**Response**
```json
{ "token": "eyJzdWIiOiJ...<signed>...", "role": "owner", "username": "meera" }
```
Use it: `Authorization: Bearer eyJzdWIiOiJ...`.
- `GET $B/auth/me` → `{ "username":"meera","role":"owner" }` (who am I).
- Create a teammate (owner only): `POST $B/auth/users` `{ "username":"athul","password":"pw","role":"fm" }`.
- Branch: wrong password → **401**. Viewer tries to create a user → **403**.

---

## 2. One-time setup

### 2.1 Add technicians (the roster)
```
POST $B/technicians
{ "name": "Ajith", "phone": "919000000001" }
```
**Response** `{ "id": 1, "name": "Ajith" }`
- List: `GET $B/technicians` → `{ "building":"one-anthem","technicians":[{"id":1,"name":"Ajith","phone":"919000000001","active":1,...}] }`
- Remove: `POST $B/technicians/1/deactivate`. Re-adding the same name reactivates it (no duplicate).

### 2.2 Add vendors (AMC companies)
```
POST $B/vendors
{ "name": "ABC Power", "category": "DG", "contact": "9812345678" }
```
**Response** `{ "id": 1, "name": "ABC Power" }` · list with `GET $B/vendors`.

### 2.3 Set SLA targets (optional — defaults exist)
```
POST $B/sla/config
{ "priority": "critical", "response_hours": 1, "resolution_hours": 4 }
```
**Response** `{ "saved": true, "priority": "critical" }`
- See all: `GET $B/sla/config` →
```json
{ "building":"one-anthem","sla":{
  "critical":{"response_hours":1,"resolution_hours":4,"default":false},
  "high":{"response_hours":4,"resolution_hours":24,"default":true}, "...":{} } }
```

### 2.4 Checklists — use built-ins or build your own
List what exists:
```
GET $B/forms/templates
```
**Response**
```json
{ "building":"one-anthem","templates":[
  {"template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations","cadence":"daily",
   "timing":"12:00 AM – 08:15 PM","items":24,"per_asset":[]} ] }
```
Full detail of one: `GET $B/forms/template/ANTHEM-SHIFT-2` →
```json
{ "template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations","cadence":"daily",
  "signoff_roles":["technician","supervisor","caretaker","engineer","president"],"per_asset":[],
  "sections":[{"name":"General Operations","items":[
    {"item_id":"g2_fire_alarm","label":"Fire alarm panel health (main ON / no fault)",
     "kind":"state","unit":"","options":["ON","OFF","FAULT"],"alert_states":["OFF","FAULT"],"asset":"FIRE-PANEL"},
    {"item_id":"g2_oh_tank","label":"OH tank water level","kind":"reading","unit":"%","options":[],
     "alert_states":[],"asset":"OH-TANK"} ]}] }
```
Build a custom one:
```
POST $B/forms/templates
{ "building":"one-anthem",
  "template":{ "template_id":"DG-QUICK","name":"DG Quick Check","cadence":"daily",
    "signoff_roles":["technician","engineer"],
    "sections":[{"name":"DG","items":[
      {"item_id":"dg_oil_ok","label":"DG-1 oil ok?","kind":"tick","asset":"DG-1"},
      {"item_id":"dg_v","label":"Battery voltage","kind":"reading","unit":"V","asset":"DG-1"} ]}]} }
```
**Response** `{ "saved":true,"template_id":"DG-QUICK","building":"one-anthem" }`
- Delete: `DELETE $B/forms/template/DG-QUICK`.
- Branch (validation): missing id/name, no sections, duplicate item_id, or bad `kind` → **400**, nothing saved.

> **Item kinds** the technician will fill: `tick` (Done/Issue), `reading` (a number + unit),
> `state` (pick from `options`), `note` (free text). `alert_states` = values that auto-raise an
> issue (e.g. fire `OFF`).

### 2.5 The four built-in checklists at One Anthem
A real building runs **three daily shifts + one quarterly PPM**. All are returned by
`GET /forms/templates`. The flow in steps 3–8 is **identical for every shift** — you only
change `template_id`. Here's what each contains:

| template_id | name | timing | sections (key items) |
|---|---|---|---|
| `ANTHEM-SHIFT-1` | Shift I — Daily Operations | 08:00 AM – 04:15 PM | **Fire Pump Room** (diesel fuel, coolant, oil, main/standby/jockey pump) · **Swimming Pool** (vacuum, pH, backwash, filtration, chlorination) · **General** (electrical status, fire alarm, MyGate, OH tank, borewell) |
| `ANTHEM-SHIFT-2` | Shift II — Daily Operations | 12:00 AM – 08:15 PM | **WTP** (backwash, chemical, filtration, leakage) · **Electrical** (transformer, room 1/2/3 inspections, MSB×3, SSB×3, DG-1/DG-2 panel) · **General** (fire alarm, MyGate, lift, GF raw/filter tank, OH tank, Japan water, borewell) |
| `ANTHEM-SHIFT-3` | Shift III — Daily Operations | 08:00 PM – 08:15 AM | **Diesel Generators** (DG-1, DG-2, run hours, battery V, oil, coolant, fuel) · **STP** (PSF/ACF backwash, chemical dosing, blower, sludge, leakage, overflow) · **Night** (duct, server room, amenities, fire, water) |
| `ANTHEM-PPM` | Quarterly Preventive Maintenance | every 3 months | 10 sections per asset (safety/prep, cleaning, mechanical tightness, thermal, electrical components, earthing, wiring, metering, documentation, corrective actions) — run **once per panel** (transformer/MSB/SSB/DG/distribution) |

Fetch any one in full: `GET /forms/template/ANTHEM-SHIFT-1` (same shape as 2.4) → its exact
sections, item kinds, units, `alert_states`, and asset tags. Examples of the alert-states that
auto-raise issues across shifts: Shift I `fp_main_pump=FAULT`, `pool_filtration=OFF`; Shift III
`stp_leakage=DETECTED`, `dg1_status=FAULT`, `night_fire=FAULT`.

> Asset tags link items to assets so they roll up into health/history/RCA — e.g. Shift III's
> `dg_battery_v` and Shift II's `el_dg1_panel` both feed asset **DG-1**.

---

## 3. Assign the round (manager)

**What:** Meera assigns Shift II to Ajith. He gets a WhatsApp message.

```
POST $B/forms/run
{ "template_id":"ANTHEM-SHIFT-2", "technician":"Ajith", "assignee":"Ajith" }
```
**Response (the "run view" — returned by most round calls)**
```json
{ "run": { "id":1, "building_id":"one-anthem", "template_id":"ANTHEM-SHIFT-2", "asset":"",
           "shift_date":"2026-06-14", "technician":"Ajith", "status":"open",
           "started_at":"2026-06-14T09:02:11", "submitted_at":null, "assignee":"Ajith" },
  "template": { "...full template as in 2.4..." },
  "entries": {},
  "summary": { "total":24, "done":0, "completion_pct":0, "missing":["g2_fire_alarm","..."], "issues":[] },
  "signoffs": [] }
```
**Side effect:** because `assignee` has a roster phone, a WhatsApp DM is queued for Ajith:
*"📋 You've been assigned Shift II — 24 items. Open: <form link>."*
- Re-assign later: `POST $B/forms/run/1/assign` `{ "assignee":"Suresh" }` → run view, re-DMs Suresh.
- Branch: unknown `template_id` → **400**. Same template+date again → returns the SAME open run (resume).
- **Other shifts — identical call, different id:** `{"template_id":"ANTHEM-SHIFT-1","assignee":"Ramesh"}`
  starts the morning round; `"ANTHEM-SHIFT-3"` starts the night round. Each is its own run with
  its own completion, sign-off, reminders and lapse.
- **Quarterly PPM — one run per panel:** pass `asset` so each panel gets its own sheet:
  ```
  POST $B/forms/run
  { "template_id":"ANTHEM-PPM", "asset":"MSB", "assignee":"ABC Power", "date":"2026-06-14" }
  ```
  Repeat with `"asset":"DG Panel"`, `"SSB"`, etc. Everything else (fill, submit, sign-off,
  reminders) works the same; the PPM also feeds `GET /ppm/schedule` (mark done via `POST /ppm/MSB/done`).

---

## 4. Technician fills the checklist (Ajith, on his phone)

He opens `http://<host>:8091/forms` (the mobile page) — or the app calls these directly.
Each item is one call, **time-stamped by the server** (he can't back-date it).

### 4.1 A normal reading
```
POST $B/forms/run/1/entry
{ "item_id":"g2_oh_tank", "value":"90", "status":"ok" }
```
**Response**
```json
{ "saved":true, "item_id":"g2_oh_tank", "is_issue":false,
  "summary":{ "total":24, "done":1, "completion_pct":4, "missing":["g2_fire_alarm","..."], "issues":[] } }
```

### 4.2 The fire panel is OFF → auto-raises an issue
```
POST $B/forms/run/1/entry
{ "item_id":"g2_fire_alarm", "value":"OFF" }
```
**Response** (`OFF` is an alert-state → `is_issue:true`)
```json
{ "saved":true, "item_id":"g2_fire_alarm", "is_issue":true,
  "summary":{ "total":24, "done":2, "completion_pct":8, "missing":["..."],
    "issues":[ { "item_id":"g2_fire_alarm",
      "label":"Fire alarm panel health (main ON / no fault)", "value":"OFF", "note":"" } ] } }
```
**Side effects:** a tracked **issue is auto-created** (see step 6) and a **manager alert** is
queued: *"⚠️ Checklist flagged an issue: Fire alarm panel health: OFF."*
- Branch: if he later corrects it (`value":"ON"`) → the auto-issue **auto-resolves**.

### 4.3 Attach a photo to an item (raw image bytes)
```
POST $B/forms/run/1/photo?item_id=g2_oh_tank&filename=tank.jpg
Content-Type: image/jpeg
<binary image bytes in the body>
```
**Response** `{ "saved":true, "item_id":"g2_oh_tank", "photo":"7f3c9a...e1.jpg" }`
View it: `GET $B/photos/7f3c9a...e1.jpg`.

### 4.4 (Optional) scan a gauge instead of typing — see step 9 (Vision).

---

## 5. Supervisor reviews the round (the AI checks the work)

```
GET $B/forms/run/1/review
```
**Response**
```json
{ "run_id":1, "completion_pct":58,
  "missing":[ {"item_id":"el_room3","label":"Electrical room-3 inspection"} ],
  "flagged_issues":[ {"item_id":"g2_fire_alarm","label":"Fire alarm panel health...","value":"OFF"} ],
  "anomalies":[ {"item_id":"g2_oh_tank","label":"OH tank water level","flagged":true,
                 "z":-3.4,"median":88,"low":80,"high":96,"latest":45,"direction":"below","n":12} ],
  "trends":[ {"item_id":"g2_gf_raw_tank","label":"GF raw tank water level","flagged":true,
              "direction":"declining","from":80,"to":40,"change_pct":50} ] }
```
Plain meaning: 58% done, Electrical room-3 not checked, fire panel flagged, OH-tank reading is
far below its own normal, and the raw-tank has been steadily dropping. None of this needs a
human to spot.

---

## 6. The issue lifecycle (the fire-panel issue)

### 6.1 See it
```
GET $B/issues?status=open
```
**Response**
```json
{ "building":"one-anthem","issues":[
  { "id":3,"building_id":"one-anthem","run_id":1,"item_id":"g2_fire_alarm","asset":"FIRE-PANEL",
    "title":"Fire alarm panel health (main ON / no fault): OFF","detail":"","status":"open",
    "severity":"issue","priority":null,"vendor":null,"escalated_level":0,"source":"auto",
    "assignee":"","raised_by":"Ajith","photo":null,"created_at":"2026-06-14T09:31:02",
    "updated_at":"2026-06-14T09:31:02",
    "history":[ {"ts":"2026-06-14T09:31:02","action":"opened","by":"Ajith","note":""} ] } ] }
```
One issue: `GET $B/issues/3`. Log one manually: `POST $B/issues` `{ "title":"STP blower noise","asset":"STP","priority":"high","by":"Athul" }`.

### 6.2 Assign it (to staff or a vendor) + set priority
```
POST $B/issues/3/transition
{ "status":"assigned", "assignee":"ABC Power", "vendor":"ABC Power", "priority":"critical", "by":"Meera" }
```
**Response** = the updated issue object (status `assigned`, vendor set, history appended).
- Valid path: `open → assigned → in_progress → resolved` (and `resolved → open` reopen).
- Branch: illegal jump (e.g. `resolved → assigned`) → **409**.

### 6.3 Vendor visits site (milestone — feeds vendor scoring)
```
POST $B/issues/3/visited
{ "by":"ABC Power" }
```
**Response** = issue object with a `"vendor visited"` history entry.

### 6.4 Resolve it
```
POST $B/issues/3/transition
{ "status":"resolved", "by":"ABC Power", "note":"panel reset, normal" }
```
**Response** = issue object, status `resolved` (TERMINAL ✓).
- Reopen if it recurs: `POST $B/issues/3/transition {"status":"open","by":"Meera"}` → escalation clock **resets**.
- Attach photo proof: `POST $B/issues/3/photo` (raw bytes).

### 6.5 Where is this issue against its SLA?
```
GET $B/issues/3/sla
```
**Response**
```json
{ "priority":"critical","age_hours":5.0,"response_hours":1,"resolution_hours":4,
  "breached_resolution":true,"escalation_level":2,"target":"supervisor" }
```

---

## 7. Automatic escalation (issues + rounds) — the bot runs these each minute

### 7.1 Issue SLA sweep
```
POST $B/escalations/run
```
**Response** `{ "building":"one-anthem","fired":[ {"issue_id":3,"level":2,"target":"supervisor"} ] }`
Meaning: issue 3 passed its resolution SLA → a notification to the supervisor was queued. Levels
climb by age: **1 reminder → 2 supervisor → 3 facility manager → 4 committee**, one message per
level (never repeats, never auto-closes).

### 7.2 Round sweep + lapse
```
POST $B/forms/reminders/run
```
**Response**
```json
{ "building":"one-anthem",
  "lapsed":[ {"run_id":0,"shift_date":"2026-06-13","completion_pct":40} ],
  "fired":[ {"run_id":1,"level":1,"assignee":"Ajith"} ] }
```
Meaning: Ajith's round is still unfinished after the reminder cutoff → he's DM'd (level 1; level
2 would escalate to Meera). Yesterday's unfinished round was **closed to `lapsed`** so it can't
hang open. (Cutoffs: `ARVISX_ROUND_REMIND_H`=6, `ARVISX_ROUND_ESCALATE_H`=10.)

---

## 8. Close the shift + roll-ups (manager view)

### 8.1 Submit + sign off the round
```
POST $B/forms/run/1/signoff   { "role":"supervisor", "by":"Athul" }
POST $B/forms/run/1/submit
```
Submit response = run view with `"status":"submitted"` (TERMINAL ✓).

### 8.2 Today across all shifts
```
GET $B/forms/today
```
**Response**
```json
{ "building":"one-anthem","date":"2026-06-14","runs":[
  { "run_id":1,"template_id":"ANTHEM-SHIFT-2","name":"Shift II — Daily Operations",
    "status":"submitted","assignee":"Ajith","technician":"Ajith","asset":"",
    "completion_pct":100,"issues":[],"signoffs":["technician","supervisor"] } ] }
```

### 8.3 Manager digest (WhatsApp-ready, includes aged issues)
```
GET $B/forms/digest
```
**Response**
```json
{ "date":"2026-06-14",
  "text":"*Checklist summary — 2026-06-14*\n\n✅ Shift II: 100% (submitted) · 👤 Ajith · 2 sign-off(s)\n\n*⏳ Aged open issues (>2d):*\n• STP blower FAULT — 3d [open] → ABC Power",
  "aged_open_issues":[ {"id":9,"title":"STP blower FAULT","status":"open","age_days":3.0,"assignee":"","vendor":"ABC Power"} ] }
```

### 8.4 Maintenance readiness (one building score)
```
GET $B/analyzers/readiness
```
**Response**
```json
{ "building":"one-anthem","label":"Maintenance Readiness","readiness":64,"band":"Attention Required",
  "components":{"asset_health_avg":87,"rounds_completion_avg":58,"overdue_ppm":0,"compliance_penalty":0},
  "contributors":["FIRE-PANEL: 55/100 (1 critical issue(s))","rounds 58% complete today"],
  "assets_assessed":13,
  "note":"Maintenance/inspection readiness from checklist data — not live equipment condition." }
```

### 8.5 The rest of the dashboards
- `GET $B/analyzers/health` → per-asset 0–100 (riskiest first) + reasons.
- `GET $B/analyzers/compliance` → overdue PPM + stale assets + risk level.
- `GET $B/analyzers/watchlist` → rising-concern assets with evidence (no fake %).
- `GET $B/analyzers/vendors` → vendor jobs / avg response / avg resolution / escalations (slowest first).
- `GET $B/assets` → asset list · `GET $B/assets/FIRE-PANEL/history` → that asset's entries + issues + PPM.
- `GET $B/ppm/schedule` → due/overdue per asset · `POST $B/ppm/schedule` / `POST $B/ppm/DG-1/done`.

---

## 9. Vision (photo → reading) — pluggable model, never auto-trusted

```
POST $B/vision/extract?kind=gauge&run_id=1&item_id=dg_v&filename=dg.jpg
Content-Type: image/jpeg
<binary image bytes>
```
**Response (no model wired yet)**
```json
{ "suggestion_id":5,"photo":"a1b2...jpg","available":false,"reason":"vision model not configured",
  "kind":"gauge","extracted":{} }
```
**Response (model wired)** → `"available":true,"extracted":{"readings":{"voltage":415,"current":118,"frequency":50},"confidence":0.9}`.
The reading is a **proposal** — it is NOT written to the checklist until the operator confirms:
```
POST $B/vision/suggestion/5/confirm   { "value":"24.8", "run_id":1, "item_id":"dg_v" }
```
→ now the entry is written (+ the photo attached). Or `POST $B/vision/suggestion/5/reject`.

---

## 10. AI agents (grounded; fall back to deterministic if no LLM key)

Every agent answer carries `"source"`: `agent` (LLM, passed the no-made-up-numbers guard) or
`deterministic` (rules). Numbers always trace to real data.

- **Shift handover** `GET $B/agents/handover` →
```json
{ "text":"*Shift Handover*\n\n*Open Issues:*\n1. STP blower FAULT [open] (→ ABC Power)\n\n*Pending Tasks:*\n• Electrical room-3 inspection — Shift II\n\n*Priority:* High",
  "source":"deterministic","priority":"High" }
```
- **Root cause** `GET $B/agents/rca?asset=DG-1` →
```json
{ "asset":"DG-1",
  "text":"*Root Cause — DG-1*\nObservations:\n• Battery voltage declining (25.0→22.0)\n• PPM overdue\nProbable cause: Battery deterioration...\nRecommended: Battery load test...\nConfidence: Medium",
  "source":"deterministic","confidence":"Medium","probable_cause":"Battery deterioration..." }
```
- **Work-order draft** `GET $B/agents/work-order?issue_id=3` →
```json
{ "issue_id":3,"asset":"FIRE-PANEL","observation":"Fire alarm panel health: OFF",
  "category":"Safety","required_team":"Fire-Safety","priority":"High",
  "suggested_action":"Verify the safety system and restore to normal; escalate if not resolved.",
  "text":"*Suggested Work Order — FIRE-PANEL*\n..." }
```
- **Ask the building** `GET $B/agents/ask?q=what is the riskiest system` →
```json
{ "text":"*Riskiest systems:*\n• FIRE-PANEL: 55/100 (risk) — 1 critical issue(s)\n...","source":"deterministic" }
```

---

## 11. Resident flows (read-only voice)

A resident texts the bot. They get plain outcomes, never asset jargon. To raise a request the
bot calls (with the resident's number as `by`):
```
POST $B/whatsapp/ask
{ "question":"create work order: pool light broken", "role":"resident", "by":"919496836948" }
```
**Response** `{ "intent":"create_work_order","text":"✅ Noted — your request has been logged for the building team (ref RR-1)..." }`
The note is sent ONLY after it's saved. Team sees it on the next poll. `GET $B/resident-requests` lists them.

---

## 12. How WhatsApp delivery works (behind every "is queued" above)

AllGud never sends directly from the API — it queues, and the bot delivers and confirms:
```
GET  $B/whatsapp/notifications   → [ {"id":1,"to_number":"919000000001","kind":"assignment","text":"..."} ]
POST $B/whatsapp/notifications/ack   { "ids":[1] }
```
`to_number` set = DM that person (technician); blank = broadcast to the manager + committee
groups. **At-least-once:** a message stays queued until acked, so a bot restart never loses it
(worst case: a duplicate). Same for resident requests (`/resident-requests/ack`).

---

## 12b. A full day across all three shifts (the rhythm)

Each shift is the same loop (assign → fill → review → submit → handover). The **handover
chains them** — every shift starts informed by the last.

```
08:00  Shift I  (Ramesh)  ── fill fire-pump/pool/general ──┐
                                                           ▼  at 16:15 close →
                          GET /agents/handover  →  open issues + pending → broadcast to Shift II
00:00  Shift II (Ajith)   ── fill WTP/electrical/general ──┐   (overlaps; the long shift)
                                                           ▼  at 20:15 close →
                          GET /agents/handover  →  carries the fire-panel issue → Shift III
20:00  Shift III (Suresh) ── fill DG/STP/night ───────────┐
                                                           ▼  at 08:15 close →
                          GET /agents/handover  →  back to Shift I next morning
Quarterly: PPM runs (one per panel) ride alongside, not daily.
```
- Each shift = its own `POST /forms/run` (step 3) with that shift's `template_id`.
- The bot broadcasts the handover at `FORMS_DIGEST_HOUR` (and you can pull it anytime via
  `GET /agents/handover`).
- Open issues + lapsed/incomplete rounds **carry across shifts** — an unresolved fire-panel
  issue raised in Shift II is still open (and escalating) when Shift III and next-day Shift I
  begin, and shows in their handover + the aged-issues digest until resolved.
- `GET /forms/today` shows **all three shifts'** runs side by side with each one's completion,
  assignee, and issues.

---

## 13. Terminal states (proof nothing hangs / loops)

| Thing | Ends at | Why it can't loop |
|---|---|---|
| Round | `submitted` or `lapsed` | reminders cap at level 2; prior-day open → lapsed |
| Issue | `resolved` (reopen allowed) | escalation caps at committee; resets on reopen |
| Vision suggestion | `confirmed` / `rejected` | single decision |
| Notification | acked (`sent`) | leaves the queue on ack |
| Resident request | `notified` | at-least-once, acked |
| Roll-ups | once/day | day-flag guard |

---

## 14. The whole day in one paragraph

Meera logs in, sets up the roster/vendors/SLA/checklists once, then **assigns Shift II to
Ajith** (`POST /forms/run`) — he's messaged on WhatsApp. He opens the form and **fills it**
(`POST .../entry`), each entry time-stamped; the **fire panel OFF auto-raises an issue**
(`/issues`) and pings Meera. The **AI review** (`/forms/run/{id}/review`) flags a missing
inspection and an off-normal tank. Meera **assigns the issue to ABC Power**
(`/issues/{id}/transition`), who **visit** (`/visited`) and **resolve** it. If anything stalls,
the **sweeps** (`/escalations/run`, `/forms/reminders/run`) chase the technician then the
manager, and yesterday's unfinished round **lapses**. At shift close Meera reads the **digest**,
**readiness score**, **health/compliance/watchlist/vendor** dashboards, and the **AI handover**
for the next shift — and can just **ask "what's the riskiest system?"**. Every WhatsApp message
is delivered at-least-once, and every path ends in a clean terminal.
