# AllGud — Frontend Integration Brief

Everything a frontend dev needs to build against the backend, cold. Pair with
`API_DOCS.md` (full request/response) and `ALLGUD_PRODUCT_FLOWS.md` (behaviour).

## 1. What it is
**AllGud** is a building-operations product for apartment associations + facility-management
companies. Phase 0 is **software-only (no sensors)**: technicians run digitised maintenance
checklists on their phone; managers assign/track them; an AI (**"Arvis"**) reasons over the
data. Naming: **AllGud = the product, Arvis = the AI assistant inside it.**

The core loop: *manager assigns a round → technician fills a timestamped checklist (photos) →
bad entries auto-open issues → issues escalate on an SLA clock → AI rolls up health, a
watchlist, a readiness score, and a shift handover.*

## 2. Run the backend
```
cd <repo>; set PYTHONPATH=<repo>
set ARVISX_API_PORT=8091
python -m arvisx.api          # http://127.0.0.1:8091
```
- REST under **`/api/v1/*`**. Interactive spec at **`GET /docs`** and **`GET /openapi.json`** (machine-readable types — generate your client from this).
- A reference mobile checklist page exists at **`GET /forms`** (vanilla JS) — use it as a behaviour reference; you're building the real UI.
- **CORS** is open by default (`ARVISX_CORS=*`).

### Get data to build against
- **Onboarded (clean) building:** `python scratch/onboard_one_anthem.py` → templates+roster+vendors+PPM, zero activity.
- **Populated (demo) building:** `python scratch/seed_one_anthem.py` → rounds, issues, watchlist, etc. (use this to develop screens with realistic data).
Point both at the same DB you run the API on (`ARVISX_DB`).

## 3. Auth
- **Dev mode:** if no users exist and `ARVISX_API_KEY` is unset, the API is **open** — build without auth first.
- **Real:** `POST /auth/login {username,password}` → `{token, role}`. Send `Authorization: Bearer <token>` on every call. `GET /auth/me` resolves the current user.
- **Roles:** `owner` / `fm` (can write) · `viewer` (read-only → **403 on any non-GET**). Account creation: `POST /auth/users` (owner only).
- Token = JWT-shaped, 24h TTL. Handle 401 (re-login) and 403 (insufficient role).

## 4. Building scope
Every endpoint is building-scoped via **`?building=<id>`** (default `one-anthem`). Build a
building switcher; thread the id through every call. A new building is onboarded with
`POST /forms/seed {building, from:"one-anthem"}` then `?building=` everywhere.

## 5. Screen → endpoint map
| Screen | Primary endpoints |
|---|---|
| **Overview** | `GET /analyzers/readiness` (score + band + contributors) · `GET /analyzers/watchlist` · `GET /agents/ask` (the Ask bar) |
| **Operations (list)** | `GET /forms/today` (runs: status, completion %, assignee) · `POST /forms/run` (assign) |
| **Round detail** | `GET /forms/run/{id}` (run+template+entries+summary+signoffs) · `GET /forms/run/{id}/review` (missing/anomalies/trends) · `POST .../submit` · `POST .../signoff` |
| **Check entry** | `POST /forms/run/{id}/entry` · `POST /forms/run/{id}/photo` (raw bytes) · `POST /vision/extract` (scan gauge) |
| **Issues** | `GET /issues` · `GET /issues/{id}` · `GET /issues/{id}/sla` · `POST /issues/{id}/transition` · `/visited` · `GET /agents/work-order?issue_id=` · `GET /agents/rca?asset=` |
| **Assets** | `GET /assets` · `GET /assets/{asset}/history` · `GET /analyzers/health` · `GET /ppm/schedule` |
| **People** | `GET /technicians` · `GET /vendors` · `GET /forms/assigned?technician=` · `GET /analyzers/vendors` (vendor performance) |
| **Intelligence** | `GET /agents/ask` · `/agents/handover` · `/agents/rca` · `/analyzers/watchlist` |
| **Setup/builder** | `GET/POST/DELETE /forms/templates*` · `POST /technicians` · `POST /vendors` · `GET/POST /sla/config` · `POST /ppm/schedule` |

## 6. Honesty conventions — NON-NEGOTIABLE (this is the product's credibility)
These are not style choices; the backend is built to honour them. Violating them in the UI
breaks the core promise.
1. **Confidence is a BAND — `Low` / `Medium` / `High` — NEVER a percentage.** RCA returns a
   band. Do not render "72%". (Bug seen in a mockup — don't ship it.)
2. **No fabricated probabilities.** The watchlist gives `concern: elevated|high` + evidence,
   **no "% failure risk"** (that needs sensors, Phase 1).
3. **Label the score "Maintenance Readiness"**, not "Readiness" — it's maintenance/inspection
   state, not live equipment condition. Keep the (i) tooltip.
4. **No "Online" on assets.** Phase 0 has no live connectivity — show **"Last checked <time>"**.
5. **No presence/"On Shift" yet.** We know "assigned a round today," not check-in. Use
   "Assigned today" / "Active round" until the Presence module ships.
6. **AI is advisory.** "Arvis suggests" / "Create work order?" — the human acts. Never imply
   the AI controls equipment or auto-resolves.
7. **Show provenance + evidence.** Agent responses include `"source": "agent"` (LLM, passed
   the grounding guard) or `"deterministic"`. Surface a badge; cite the data behind numbers.
8. **Abstain is a feature.** "Insufficient data — inspect on site" is a valid, good state.

## 7. Key enums / shapes
- **Run status:** `open` · `submitted` · `lapsed` (terminals: submitted, lapsed). Map UI states:
  Scheduled=future date · Open=open/0 entries · In Progress=open/some · Review=submitted, signoffs pending · Complete=submitted+signed.
- **Issue status:** `open → assigned → in_progress → resolved` (reopen allowed). `source`: `auto|manual`. `severity`: `critical|issue`. `priority`: `critical|high|medium|low`.
- **Item kinds:** `tick` (ok/issue) · `reading` (number+unit) · `state` (one of `options`; `alert_states` auto-raise an issue) · `note`.
- **Health band:** `good ≥85` · `watch ≥60` · `risk` (per-asset 0–100).
- **SLA escalation level:** 1 reminder(tech) · 2 supervisor · 3 facility-manager · 4 committee.
- **Photo upload:** raw image bytes in the body, `Content-Type: image/jpeg|png|webp`; served at `GET /api/v1/photos/{name}`.

## 8. Three roles, don't conflate
- **Auth role** (owner/fm/viewer) → API access.
- **Voice tier** (resident/manager/technician) → WhatsApp message phrasing (backend concern).
- **Roster** (technician/vendor) → who performs/owns work.

## 9. Not built yet (don't design as live)
- Vision model (Scan Gauge returns `available:false` until a key is set — label "Beta").
- Voice notes (only photo + text evidence exist).
- Operational Presence (check-in / GPS / "On Shift") — spec'd, parked.
- Per-asset warranty/AMC dates, supervisor registry, human issue IDs — net-new (see mockup feedback).

## 10. Pointers
- Full request/response: **`arvisx/API_DOCS.md`**
- Behaviour / every flow + terminals: **`arvisx/ALLGUD_PRODUCT_FLOWS.md`**
- Live types: **`GET /openapi.json`**
