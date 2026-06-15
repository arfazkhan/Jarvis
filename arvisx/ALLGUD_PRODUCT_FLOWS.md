# AllGud — End-to-End Product Flows (Phase 0, software-only)

Every feature, every actor, every branch — including terminal/edge states. Built on the
ArvisX engine. No hardware. Endpoints in `API_DOCS.md`; this is the behaviour map.

## Actors
- **Owner / Committee** — top authority; accounts, SLA config, sees everything, escalation tip.
- **Manager / Supervisor** — assigns rounds, reviews, approves, resolves issues.
- **Technician** — performs rounds on the mobile form.
- **Vendor (AMC)** — external; owns some fixes; performance is measured.
- **Resident** — asks status, raises requests (read-only voice).
- **The bot** — WhatsApp delivery + polling sweeps.
- **The AI agents** — handover / RCA / work-order / ask (grounded, advisory only).

Three separate "role" concepts (don't conflate): **auth roles** (owner/fm/viewer → API
read/write) · **voice tiers** (resident/manager/technician → message phrasing) · **roster**
(who performs rounds).

---

## 0. Setup / onboarding (one-time per building)
1. **Create accounts** — bootstrap owner via env, then `POST /auth/users` (owner/fm/viewer). → login mints token.
2. **Build the roster** — `POST /technicians` (name + phone). Re-add reactivates (no dup).
3. **Register vendors** — `POST /vendors` (name, category, contact).
4. **Configure SLA (optional)** — `POST /sla/config` per priority; else defaults (critical 1/4h … low 48/168h).
5. **Templates** — use the built-in One Anthem checklists, or **build custom** (`POST /forms/templates`, validated) — sections + items (tick/reading/state/note, alert-states, asset tag). Delete via `DELETE /forms/template/{id}`.
   - Branch: invalid template (no id/name/sections, dup item, bad kind) → **400**, nothing saved.

---

## 1. The core daily loop (happy path)
```
Manager assigns round → tech DM'd → tech fills form → submits → supervisor signs off
                                   ↘ bad entry → issue → resolved
End of shift → digest + handover + readiness
```
Step by step with every branch below.

### 1.1 Assign a round
- `POST /forms/run` with `template_id` + `assignee` (+ date/asset). Creates or **resumes** today's open run.
- **If assignee set + has roster phone** → WhatsApp DM: *"Assigned Shift II, 18 items, open: <link>"*.
- Branch — **unknown template** → 400. **Reassign later** → `POST /forms/run/{id}/assign` (re-DMs). **No phone** → assignment still recorded, no DM (shows in app).
- Branch — **PPM per-asset run** → pass `asset` (one run-block per panel).

### 1.2 Technician fills the form (`GET /forms` mobile page)
- Opens link → sees sections + items. Each entry `POST /forms/run/{id}/entry`, **server-timestamped** (cannot backfill).
- Item kinds: **tick** (ok/issue) · **reading** (number+unit) · **state** (dropdown) · **note**.
- **Photo** per item — `POST .../photo` (raw bytes). **Vision scan** on readings — see §6.
- Branch — **entry value ∈ alert-states** (fire `OFF`, leak `DETECTED`) → **auto-opens an issue** (§3) + manager alerted. Idempotent per run+item.
- Branch — **correct a bad entry back to OK** → the auto-issue **auto-resolves**.
- Branch — **run already submitted** → entry returns **409** (locked).

### 1.3 Close the round — terminals
- **Submit** `POST /forms/run/{id}/submit` → status **`submitted`** ✓ (terminal). Optionally `signoff` (technician→supervisor→caretaker→engineer→president).
- **Not submitted + incomplete** → reminder/lapse path (§2).
- Two and only two run terminals: **`submitted`** or **`lapsed`**.

---

## 2. Round not done → escalation (the "if not done, alert" loop)
Bot calls `POST /forms/reminders/run` each poll.
- Run **open, <100%, assigned**:
  - after `ARVISX_ROUND_REMIND_H` (6h) → **DM the technician** (L1): "Shift II 40%, 11 pending".
  - after `ARVISX_ROUND_ESCALATE_H` (10h) still incomplete → **escalate to manager** (L2, ops broadcast).
  - One notice per level (`reminded_level` guard). **Unassigned** incomplete → straight to manager.
- Prior-day run still open → **LAPSED** ✓ (terminal) + manager notice with completion %. (No orphan rounds.)
- Branch — submitted/100% before cutoff → no reminder. Branch — bot down → sweep just runs next poll.

---

## 3. Issue lifecycle (every path)
States: **open → assigned → in_progress → resolved** (reopen allowed). Source: **auto** (alert-state) or **manual** (`POST /issues`).
- **Open** — auto (from §1.2) or manual. Carries asset, severity, priority, optional vendor.
- **Assign** — `POST /issues/{id}/transition` {status:assigned, assignee, vendor?, priority?}. Assign to a tech OR a vendor.
- **In progress / vendor visited** — transition to in_progress; `POST /issues/{id}/visited` records the vendor site-visit milestone (feeds vendor analytics).
- **Resolve** — transition to resolved → **RESOLVED** ✓ (terminal).
- **Auto-resolve** — auto-issue whose entry is corrected to OK → **RESOLVED** ✓.
- **Reopen** — resolved→open → escalation clock **resets** (escalated_level=0, 'reopened' logged) so it re-chases.
- **Photo evidence** — `POST /issues/{id}/photo`.
- Branch — **illegal transition** (e.g. resolved→assigned) → **409**. **Unknown issue** → 404.
- Every issue ends at **resolved** (only terminal); an unresolved one stays visible (digest aged-list + escalation).

### 3.1 Issue SLA escalation
Bot calls `POST /escalations/run` each poll. For each unresolved issue by age vs its priority SLA:
- ≥response → **reminder** (DM assigned tech) · ≥resolution → **supervisor** · ≥2× → **facility manager** · ≥3× → **committee**.
- One notification per level (`escalated_level` guard, capped at committee). Never auto-closes.
- `GET /issues/{id}/sla` → current age/level/breach.

---

## 4. Vendor accountability
- Issue owned by a vendor (transition with `vendor`) → visited milestone → resolved.
- `GET /analyzers/vendors` → per-vendor **jobs, avg response (opened→visited), avg resolution, escalations** — slowest first. (AGM/billing leverage: which AMC is slow / causes escalations.)

---

## 5. AI validation + roll-ups (deterministic; no LLM)
- **L1 anomaly** `GET /analyzers/readings` — a reading off its own learned band (battery 21.7 vs 25). Abstains under thin history.
- **L2 supervisor** `GET /forms/run/{id}/review` — missing items + anomalies + declining-trend contradictions.
- **L7 asset health** `GET /analyzers/health` — 0–100 per asset (issues/anomalies/overdue PPM/staleness), riskiest first.
- **L8 compliance** `GET /analyzers/compliance` — overdue PPM + stale assets → risk level.
- **L6 watchlist** `GET /analyzers/watchlist` — rising-concern with evidence + level (elevated/high), **no fabricated %**.
- **Maintenance readiness** `GET /analyzers/readiness` — one building score (weighted health + completion − PPM penalty); no-rounds-today capped at 60; honest = maintenance, not live condition.
- **PPM** `GET/POST /ppm/schedule`, `POST /ppm/{asset}/done`, status ok/due_soon/overdue (date + run-hours).
- **Manager digest** `GET /forms/digest` — completion per shift + assignees + **aged-open issues (>2d)**.
- **Asset history** `GET /assets/{asset}/history` — timeline of entries + issues + PPM.

---

## 6. Vision (model-pluggable; verify pattern)
1. Tech scans a gauge → `POST /vision/extract` (raw bytes) → stores photo + a **pending suggestion**. **Never writes the entry.**
2. **Model wired** → extracted reading shown → operator **confirms** (`/confirm`) → **now** written to the entry (+ photo attached). Or **reject** (`/reject`).
3. **No model** → `available:false`, photo saved, enter manually.
- Branch — bad image (type/size) → 400. Reused photo (future pHash) → flagged for review.

---

## 7. AI agents (LLM if configured; deterministic fallback always)
Each: gather facts deterministically → optional LLM narrative → **grounding guard** (every number must trace to a tool output) → ship `source:agent`, else `source:deterministic`.
- **Handover** `GET /agents/handover` — open issues + pending + priority; bot broadcasts at shift close.
- **RCA** `GET /agents/rca?asset=` — observations → probable cause → recommended action → evidence-derived confidence; abstains to "inspect on site".
- **Work-order** `GET /agents/work-order?issue_id=` — category/team/priority (rules) + action from RCA; human raises it.
- **Ask-the-building** `GET /agents/ask?q=` — "riskiest system?", "what's open?" — answered over the tools.
- Branch — fabricated number in LLM output → guard rejects → **deterministic fallback** (proven by tests).

---

## 8. Resident flows
- Resident texts the bot → **resident voice** (outcome only, no jargon): "is the pool open?" → "🏊 Pool operational".
- **Raise a request** ("create work order") → recorded → "✅ Noted, ref RR-n" (only after the save) → team notified on the next poll. `GET /resident-requests`.
- Critical service disruption → resident gets a plain disruption push (CRITICAL only, deduped per service).

---

## 9. WhatsApp delivery (cross-cutting)
- **Notification queue** — assignment DMs, issue alerts, escalations, round reminders/lapse, resident-request relays. `GET /whatsapp/notifications` → bot delivers → `POST .../ack`. **At-least-once** (pending until acked; bot crash → re-delivers, never lost).
- **Tiered**: technician DM (roster phone) vs ops broadcast (owner + groups) vs resident groups.
- **Anti-ban (Phase A)**: hand-written phrasing variants + send jitter + per-recipient hourly cap. Facts always verbatim.

---

## 10. Terminal-state summary (no hanging nodes, no loops)
| Entity | Terminals | Loop guard |
|---|---|---|
| Round | submitted · lapsed | reminded_level ≤ 2; lapse closes prior-day |
| Issue | resolved (reopen allowed) | escalated_level ≤ 4 (committee); reset on reopen |
| Vision suggestion | confirmed · rejected | one decision |
| Notification | sent (acked) | ack removes from queue |
| Resident request | notified | ack-based, at-least-once |
| Roll-ups | once/day | day-flag guard |

---

## 11. The complete narrative (one read-through)
Manager sets up the building (accounts, roster, vendors, templates, SLA). Each shift she
**assigns** rounds; the technician gets a **WhatsApp link**, walks the building filling a
**timestamped** checklist with **photos** (and, later, vision-scanned readings). A bad reading
**auto-opens an issue** and pings the manager. If the round stalls, the technician is
**nudged**, then the manager; an unfinished prior-day round **lapses** so nothing hangs. Issues
are **assigned** (to staff or a **vendor**), tracked, and **escalate on their SLA clock**
(reminder→supervisor→FM→committee) until **resolved** — vendors' response times are scored.
The deterministic AI **validates** entries and rolls up **health, compliance, a watchlist, and
a maintenance-readiness score**; the LLM agents (grounded, fallback-safe) write the **shift
handover**, **root cause**, **work-order drafts**, and answer **"what's the riskiest system?"**.
Residents get plain-language status and can raise requests. Everything is delivered over
WhatsApp **at-least-once**, and every path ends in a clean terminal.
