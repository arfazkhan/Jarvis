# ArvisX — Product Design Brief

*For the product designer. Everything you need to design the screens without reading code.*

---

## 1. What ArvisX is (in one paragraph)

ArvisX is an **operations-intelligence layer for residential communities** (apartment complexes, gated communities, towers). These buildings have fragmented infrastructure — water tanks & pumps, diesel generators, sewage treatment (STP), swimming pool systems, fire pumps, common-area AC — but **no unified building management system**. Today a facilities manager (FM) tracks all of it on WhatsApp, paper checklists, and memory. ArvisX sits on top of whatever sensors exist, learns what "normal" looks like, and tells the community **what's at risk, why, and what it's costing them** — in plain operational language, not raw telemetry.

**Critical product principle:** ArvisX is **read-only / advisory**. It never controls equipment. It observes, reasons, and recommends. A human always acts.

---

## 2. Who uses it (roles → what they need to see)

| Role | Who | Primary need | Access |
|------|-----|--------------|--------|
| **Owner / Committee member** | Building owner, HOA committee, board | "Is my community OK? What is this costing us?" High-level, money-framed, trust. | Read-only, summary-level |
| **Facility Manager (FM)** | On-site manager / supervisor | "What's broken, what do I do, create the work order." Operational detail + actions. | Read + actions (create/close work orders) |
| **Viewer / Resident rep** | Resident, watchman, vendor | "Is water/power OK right now?" Status only. | Read-only, minimal |
| **Technician** | On-site maintenance staff | Receives daily checklist prompts on WhatsApp, submits readings/physical checks. Mostly lives in WhatsApp, not the dashboard. | WhatsApp replies; dashboard read-only if any |

Actions (creating work orders, commissioning) are **role-gated**. Owners see money & readiness; FMs see and act on the detailed queue. Technicians interact via WhatsApp prompts.

---

## 3. The core concepts the UI must express

These are the nouns the whole product is built around. Every screen is a view onto one of these.

1. **Community Readiness** — a single 0–100% score for the whole community, with a band: **Healthy / Attention Required / Critical**. This is the hero number. It's a weighted roll-up of all services (water & fire weighted highest).

2. **Services** — the 7 things ArvisX watches, each with its own health band and score:
   - 💧 **Water Availability** (the hero service — "do we have water and for how long")
   - 🔌 **Power Backup** (generators, batteries)
   - 🏊 **Pool**
   - ♻️ **STP** (sewage treatment)
   - 🔥 **Fire Readiness** (*supplementary visibility only — NEVER presented as the certified fire system of record. Design must avoid implying it replaces the legal fire panel.*)
   - ⚡ **Energy** (efficiency / waste)
   - 🔥🍳 **Gas Safety & Supply** (basement gas plant + per-apartment lines — *same disclaimer discipline as fire: supplementary visibility; the certified gas-safety system stays authoritative*)

3. **Risks** — individual issues ArvisX has detected. Each risk has:
   - a **severity**: 🚨 Critical / ⚠️ Warning / 🔧 Maintenance / ℹ️ Info
   - a **confidence**: Low / Medium / High (= how many independent signals corroborate it)
   - an **operational message** ("Transfer Pump A runtime +43%, inspect bearings") — *never* raw numbers like "12.4A"
   - an optional **money line** ("💸 Potential failure cost: QAR 3,000–10,000")

4. **Work Orders** — the action layer. A risk becomes a work order (ticket) with status: Open → In Progress → Closed. Closing requires a cause (this feeds learning).

5. **Money / Economic view** — every risk can be translated to currency: recurring **energy waste** (per month) or one-time **failure exposure** (a range). Plus a community-wide "what is this costing us" total.

6. **Water Status** (special, hero) — current stored volume, draw rate, **hours of water remaining**, whether it can refill in time, and a forecast.

7. **Asset Dependency / Impact** — assets depend on each other (tank → booster pump → distribution). If one fails, ArvisX shows the downstream impact and which redundancy is lost.

8. **Commissioning** — the one-time setup wizard a non-engineer runs to onboard a new building (define assets, map signals, set dependencies, then go live). Goal: a non-engineer commissions a building in **half a day**.

9. **Gas Billing Statement** — ArvisX records every apartment's gas meter continuously, so the month-end statement computes itself (consumption per flat + CSV export). Kills the manual meter round. Honesty states matter in the UI: a meter can be **ok**, **no_data** (no readings — never an invented number), or **flagged** (index decreased — tamper/rollover, human review). *ArvisX measures and reports; the society applies the tariff and bills.*

10. **Daily Checklist (the self-writing logbook)** — two halves:
   - **Auto-filled items** — telemetry-backed checks (tank %, runtimes, battery V, gas pressure) recorded automatically: timestamped, tamper-proof.
   - **Physical items** — human-only checks (visual leak, noise, odour) prompted to the technician over WhatsApp; replies land in the same log.
   - **Reading verification** — a human-submitted reading is checked against the sensor at the claimed time → **matched / mismatch (flagged) / no-data**. The mismatch state is the headline feature: pencil-whipped numbers are caught. The UI must show flags prominently but neutrally ("doesn't match the sensor — review"), not as accusations.

---

## 4. Real data shapes (so mockups use realistic content)

These are the actual API responses the screens will bind to. Use these as your content placeholders — don't invent telemetry.

**Community overview**
```
Community Readiness: 78%  →  band: "Attention Required"
Services:
  💧 Water Availability     — Healthy (94%)
  🔌 Power Backup           — Attention Required (61%)
  🏊 Pool                   — Healthy (88%)
  ♻️ STP                    — Healthy (90%)
  🔥 Fire Readiness         — Critical (40%)
  ⚡ Energy                 — Attention Required (72%)
Active issues: 4
```

**A single risk (as shown to user)**
```
⚠️ Power Backup Risk
Diesel Generator 1 — weekly test overdue, battery voltage trending down
Confidence: Medium
💸 Potential failure cost: QAR 8,000–25,000
[Create work order]
```

**Water status (hero card)**
```
Stored: 48,000 L of 60,000 L
Current draw: ~2,400 L/hr
Hours remaining: 20 hrs
Can refill in time: Yes
Forecast: stable through tomorrow
```

**"What is this costing us" (committee view)**
```
What this is costing you
💸 Ongoing waste: ~QAR 12 / month
⚠️ At-risk (deferred maintenance): QAR 12,200 – 39,000

Top contributors:
  • Diesel Generator 1   QAR 8,000–25,000
  • Fire Pump 1          QAR 3,000–10,000
  • Booster Pump A       ~QAR 9 / mo
```

**Work order**
```
#WO-014  Inspect Transfer Pump A bearings
Status: Open   Priority: High   Asset: Transfer Pump A
Opened: 2 days ago
```

**Gas billing statement (month)**
```
Month: 2026-06        Total: 148.2 m³   Billable meters: 11 / Flagged: 1 / No data: 0
  APT-101   ok        12.5 m³   (index 100.0 → 112.5)
  APT-102   flagged   — index decreased: meter rollover/replacement/tamper, review manually
  APT-103   ok        9.8 m³
  …
[Download CSV]   Note: measured by ArvisX — society applies tariff and bills.
```

**Daily checklist (today)**
```
Auto-recorded (telemetry, tamper-proof):  9/9 ✓
  UG tank level 78%  ·  Booster power 3.1 kW  ·  Gen battery 12.8 V  ·  Gas pressure 0.5 bar …
Physical checks:  3/4 done
  ✅ Pump room visual — ok (tech1, 09:14)
  ✅ Gas plant odour — ok (tech1, 09:16)
  ⚠️ Generator room — ISSUE: "oil seep near base" (tech1, 09:21)
  ⏳ Pool area — pending
Submitted readings:  1 flagged ⚠
  UG tank: submitted 75% — sensor recorded 40% at that time → doesn't match, review
```

**Currency is configurable** — default QAR (Qatar), but the same product runs in India (₹). Design currency as a token, not hardcoded.

---

## 5. Screens to design (suggested set)

Priority order. The first three are the MVP.

### MVP
1. **Home / Community Readiness dashboard**
   - Hero: readiness % + band (color-coded).
   - 7 service tiles (icon, name, band, score) — tappable into detail.
   - "Active issues" count + top 2–3 risks preview.
   - A money strip ("This month: ~QAR 12 waste · QAR 39k at risk").
   - Audience: owner/committee first glance.

2. **Issues / Risk list**
   - List of risks sorted by severity then confidence.
   - Each row: severity icon, operational message, confidence chip, money line, [Create work order] (role-gated).
   - Filter by service / severity.

3. **Water Status (hero detail)**
   - Big "hours remaining" number + can-refill state.
   - Stored vs capacity gauge, draw rate, forecast line.
   - Any water risks listed below.

### Phase 2
4. **Service detail** (one template, 7 instances) — band, score, the assets in that service, their risks, history sparkline.
5. **Work order queue** — Open / In Progress / Closed tabs; create + close-with-cause flow.
6. **"What is this costing us"** — full economic breakdown (the committee money page).
7. **Asset detail + impact** — one asset, its dependencies, "if this fails, X loses redundancy."
8. **Daily Checklist** — the self-writing logbook (auto-recorded items + physical-check statuses + flagged readings). Two audiences: FM sees today's completion + flags; committee sees the weekly compliance trend ("rounds actually happened"). The ⚠ mismatch state is the star — visible, neutral wording.
9. **Gas Billing** — month picker → per-apartment statement table (ok / no_data / flagged states) + total + [Download CSV]. The "this used to be a manual meter round" screen — design it boring and trustworthy, like a bank statement.

### Phase 3
10. **Commissioning wizard** — multi-step, gated (Assets → Signals → Dependencies → Learning → Go live). Non-engineer audience; progress + validation states matter most here.
11. **WhatsApp surface** — *(see §6, mostly text, but you may design message card templates / a digest layout.)*

---

## 5.5 BE LITERAL: build this / do not build this

This section is blunt on purpose. Every widget below either has a live endpoint today
(**BUILD**) or does not (**DON'T**). If a widget is not in the BUILD table and not
explicitly approved, assume DON'T and ask.

### ✅ BUILD — every widget here binds to a real endpoint, today

| Widget | Endpoint | Notes |
|---|---|---|
| Login form | `POST /api/v1/auth/login` → `{token, role}` | store JWT; send as `Authorization: Bearer` |
| Who am I / role gate | `GET /api/v1/auth/me` | hide write-actions for `viewer` |
| Readiness hero (% + band) | `GET /api/v1/community/overview` | `community_readiness`, `readiness_band` |
| 7 service tiles | same response → `services[]` | band + score per service |
| Money strip | `GET /api/v1/costs` | `monthly_waste`, `exposure_low/high`, `currency` |
| Risk list (severity, confidence, money) | `GET /api/v1/community/risks` | paginated `?limit=&offset=` |
| "Create work order" button on a risk | `POST /api/v1/workorders/from-risk {asset_id}` | one click = one WO, deduped server-side |
| Work-order queue + detail | `GET /api/v1/workorders`, `GET /workorders/{id}` | |
| WO status change | `POST /workorders/{id}/status/{status}` | open/ack/in_progress/done |
| WO close-with-cause (the root-cause field) | `POST /workorders/{id}/close {actual_cause, action}` | REQUIRED — this feeds learning |
| Water hero (hours remaining, fill, refill-ok, forecast string) | `GET /api/v1/water` | forecast is a STRING, not a series |
| Asset detail (live signals + its risks) | `GET /api/v1/asset/{id}` | |
| Asset advisory (cause + action + institutional memory) | `GET /api/v1/asset/{id}/advisory` | |
| Asset fault history | `GET /api/v1/asset/{id}/history` | |
| Dependency tree / cascade impact | `GET /api/v1/topology`, `GET /api/v1/impact` | impact = ranked, with readiness delta |
| Daily checklist screen | `GET /api/v1/checklist/today` | auto + physical + flagged readings |
| Submit a manual reading (with verdict) | `POST /api/v1/checklist/submit-reading` | shows matched / mismatch / no_data |
| Gas billing statement + CSV | `GET /api/v1/gas/billing?month=YYYY-MM` (`&format=csv`) | ok / no_data / flagged rows |
| Live updates | `GET /api/v1/events/stream` (SSE, `?token=`) | else poll overview every 30–60s |
| Commissioning wizard (Phase 3 only) | `POST /api/v1/commission/building/...` chain | gated steps; readiness gate decides go-live |

### ❌ DO NOT BUILD — these have no backend, and some break the product's honesty rules

| Don't build | Why |
|---|---|
| **"Similar issues in other communities"** (peer incidents, costs at other buildings) | No fleet data exists — single-tenant. Showing it = fabricated content. **Hard no.** |
| **"Insights" / "Recommendations" cards with generated prose** ("you used 8% less water", "stagger gardening") | The backend does not produce these sentences. Frontend MUST NOT invent advisory text — every sentence on screen comes from an API response. |
| **Time-series charts** (24-h water forecast curve, signal sparklines, trend graphs) | No series endpoint yet. `forecast` is a string. If you want charts, request the endpoint first — don't fake the curve. |
| **"Best time to act: within N days"** | Not computed by the engine. |
| **Per-WO "estimated time 2–3 hrs" / technician directory with avatars** | Not in the data model. `assignee` is a plain string; render it as text only. |
| **3D isometric building map with asset positions** | No coordinates exist in commissioning data. Park until the wizard collects positions. A flat dependency-graph view (from `/topology`) is fine. |
| **"What changed today" activity feed** | No endpoint yet (derivable from events — request it if needed). |
| **Anything that controls equipment** (start/stop/restart buttons, setpoint sliders, toggles) | ArvisX is read-only. Forbidden, permanently. |
| **Raw telemetry dashboards** (amps/volts gauges, sensor value tables) | Violates voice rule #1. Numbers shown must be consequences (hours, %, money), not sensor readings. |
| **Payment/billing execution** (collect money, mark paid, invoices) | Gas billing screen ENDS at the statement + CSV. Society bills; we never touch money. |
| **A fire- or gas-panel look-alike** | Legal exposure. Persistent "supplementary view" disclaimer instead. |
| **Confidence hidden behind a tooltip** | Confidence chips are first-class, always visible on every risk. |

### Rules of engagement
1. **If the data isn't in an endpoint response, it doesn't go on screen.** No placeholder prose that "the backend will produce later."
2. **Missing endpoint you genuinely need?** Ask for it (e.g. signal-history for sparklines, events-today for a feed) — small additions are cheap; faked data is not.
3. **Empty/no-data states are designed, not hidden.** "No readings — cannot bill from data" is a feature.
4. **Build order:** Login → Home → Issues → Work Orders → Asset detail. Then Water, Checklist, Gas Billing. Everything else after pilot.

---

## 6. WhatsApp is a first-class channel (not an afterthought)

Most residential users live in **WhatsApp**, not a dashboard. ArvisX already speaks WhatsApp:
- **Daily digest** (morning summary: readiness + services + issue count)
- **Sparse alerts** (only Critical/Warning, deduped — anti-fatigue is a hard rule)
- **Q&A** ("any issues?", "water status?", "gas status?", "why is readiness down?", "what is this costing us?", "create work order")
- **Technician checklist prompts** (9:00 daily + 17:00 reminder for still-pending):
  > 🔧 Daily check: pump room visual — leaks, unusual noise/vibration? Reply: ok pump_room_visual / issue pump_room_visual \<note\>
  The reply is confirmed ("✅ Logged: pump_room_visual → ok") and lands timestamped in the same daily log the dashboard shows.

Design implication: the dashboard and WhatsApp must feel like **one product**. Same language, same icons/emoji vocabulary (✅ ⚠️ 🚨 🔧 💧 🔌 🏊 ♻️ 🔥 💸), same operational tone. A user who reads the WhatsApp digest then opens the app should see the same words. You may design WhatsApp message templates as part of the system.

---

## 7. Voice & tone rules (these are non-negotiable — bake into the design system)

1. **Operational language, never raw telemetry.** Say "Transfer Pump A runtime up 43%, inspect bearings" — never "12.4A" or "current draw 12.4 amps." If a number appears, it's a *consequence* (hours of water, money, %), not a sensor reading.
2. **Money is the committee's language.** Lead with cost wherever a committee/owner is the audience. Risk → money is the conversion that gets budgets approved.
3. **Honesty / no false confidence.** Confidence (Low/Med/High) is always shown, never hidden. Low-confidence items are visible but de-emphasized. Never imply certainty ArvisX doesn't have.
4. **Advisory, never controlling.** No toggle, slider, or button that implies the app operates equipment. The only actions are *create/close work order* and *commission*. CTA verbs: "Create work order," "Mark done," not "Turn off," "Restart."
5. **Fire & gas = visibility only.** Never design fire or gas UI that looks like a certified safety panel. Add a persistent disclaimer near fire AND gas content ("supplementary view — the certified system stays authoritative").
6. **Anti-fatigue.** Alerts are precious. The design should reinforce scarcity — a clean inbox is the goal state, not an empty one to fill.
7. **Flags are neutral, never accusations.** A mismatched checklist reading says "doesn't match the sensor — review", not "the technician lied." A flagged gas meter says "index decreased — review manually." ArvisX presents evidence; humans judge.
8. **Honest empty states.** A meter with no readings shows "no data — cannot bill from data", never a guessed number. The no_data / abstain state deserves real design attention — it's the trust feature.

---

## 8. Color / state mapping (starting point — refine in design)

| Band / severity | Suggested color | Emoji |
|-----------------|-----------------|-------|
| Healthy | green | ✅ |
| Attention Required / Warning | amber | ⚠️ |
| Critical | red | 🚨 |
| Maintenance | blue/grey | 🔧 |
| Info | grey | ℹ️ |
| Money / cost | — | 💸 |

Services: 💧 water · 🔌 power · 🏊 pool · ♻️ STP · 🔥 fire · ⚡ energy · 🍳 gas.
Checklist states: ✅ done/matched · ⚠ mismatch (flagged) · ⏳ pending · ∅ no-data (honest abstain).

---

## 9. Context the designer should keep in mind

- **Primary market:** Gulf (Qatar — Marina Heights is the reference community) + India. Mobile-first. Likely English primary, Arabic/Hindi possible later (design for RTL-friendliness).
- **Users are not engineers.** FMs are practical operators; owners are non-technical. Clarity > density.
- **Trust is the product.** It competes with "the FM's gut feel + WhatsApp." If the UI feels uncertain, noisy, or wrong once, they revert to WhatsApp. Calm, sparse, confident, money-aware.
- **The win metric:** *action rate* — what fraction of alerts get acted on. Design should make acting (create work order) frictionless and make ignored alerts feel like a cost.

---

## 10. Out of scope (don't design these)

- Any equipment control UI (it's read-only).
- A certified fire-alarm panel.
- Raw sensor dashboards / graphs of amps & volts (engineers' tool, not this product).
- Resident-facing billing or payments.

---

*Backend status: 17 build phases complete (incl. Gas Safety & Supply + per-apartment gas billing + the self-writing daily checklist with reading verification), REST API live (all data above is real API output), WhatsApp bot working incl. technician checklist prompts, deployment proven on a digital twin (45-min real-time soak, adversarial suite). Frontend is the missing layer — that's what you're designing.*
