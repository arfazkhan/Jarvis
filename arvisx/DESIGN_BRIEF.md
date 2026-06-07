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

Actions (creating work orders, commissioning) are **role-gated**. Owners see money & readiness; FMs see and act on the detailed queue.

---

## 3. The core concepts the UI must express

These are the nouns the whole product is built around. Every screen is a view onto one of these.

1. **Community Readiness** — a single 0–100% score for the whole community, with a band: **Healthy / Attention Required / Critical**. This is the hero number. It's a weighted roll-up of all services (water & fire weighted highest).

2. **Services** — the 6 things ArvisX watches, each with its own health band and score:
   - 💧 **Water Availability** (the hero service — "do we have water and for how long")
   - 🔌 **Power Backup** (generators, batteries)
   - 🏊 **Pool**
   - ♻️ **STP** (sewage treatment)
   - 🔥 **Fire Readiness** (*supplementary visibility only — NEVER presented as the certified fire system of record. Design must avoid implying it replaces the legal fire panel.*)
   - ⚡ **Energy** (efficiency / waste)

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

**Currency is configurable** — default QAR (Qatar), but the same product runs in India (₹). Design currency as a token, not hardcoded.

---

## 5. Screens to design (suggested set)

Priority order. The first three are the MVP.

### MVP
1. **Home / Community Readiness dashboard**
   - Hero: readiness % + band (color-coded).
   - 6 service tiles (icon, name, band, score) — tappable into detail.
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
4. **Service detail** (one template, 6 instances) — band, score, the assets in that service, their risks, history sparkline.
5. **Work order queue** — Open / In Progress / Closed tabs; create + close-with-cause flow.
6. **"What is this costing us"** — full economic breakdown (the committee money page).
7. **Asset detail + impact** — one asset, its dependencies, "if this fails, X loses redundancy."

### Phase 3
8. **Commissioning wizard** — multi-step, gated (Assets → Signals → Dependencies → Learning → Go live). Non-engineer audience; progress + validation states matter most here.
9. **WhatsApp surface** — *(see §6, mostly text, but you may design message card templates / a digest layout.)*

---

## 6. WhatsApp is a first-class channel (not an afterthought)

Most residential users live in **WhatsApp**, not a dashboard. ArvisX already speaks WhatsApp:
- **Daily digest** (morning summary: readiness + services + issue count)
- **Sparse alerts** (only Critical/Warning, deduped — anti-fatigue is a hard rule)
- **Q&A** ("any issues?", "water status?", "why is readiness down?", "what is this costing us?", "create work order")

Design implication: the dashboard and WhatsApp must feel like **one product**. Same language, same icons/emoji vocabulary (✅ ⚠️ 🚨 🔧 💧 🔌 🏊 ♻️ 🔥 💸), same operational tone. A user who reads the WhatsApp digest then opens the app should see the same words. You may design WhatsApp message templates as part of the system.

---

## 7. Voice & tone rules (these are non-negotiable — bake into the design system)

1. **Operational language, never raw telemetry.** Say "Transfer Pump A runtime up 43%, inspect bearings" — never "12.4A" or "current draw 12.4 amps." If a number appears, it's a *consequence* (hours of water, money, %), not a sensor reading.
2. **Money is the committee's language.** Lead with cost wherever a committee/owner is the audience. Risk → money is the conversion that gets budgets approved.
3. **Honesty / no false confidence.** Confidence (Low/Med/High) is always shown, never hidden. Low-confidence items are visible but de-emphasized. Never imply certainty ArvisX doesn't have.
4. **Advisory, never controlling.** No toggle, slider, or button that implies the app operates equipment. The only actions are *create/close work order* and *commission*. CTA verbs: "Create work order," "Mark done," not "Turn off," "Restart."
5. **Fire = visibility only.** Never design fire UI that looks like a certified fire-alarm control panel. Add a persistent disclaimer near fire content.
6. **Anti-fatigue.** Alerts are precious. The design should reinforce scarcity — a clean inbox is the goal state, not an empty one to fill.

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

Services: 💧 water · 🔌 power · 🏊 pool · ♻️ STP · 🔥 fire · ⚡ energy.

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

*Backend status: 16 build phases complete, REST API live (all data above is real API output), WhatsApp bot working. Frontend is the missing layer — that's what you're designing.*
