# Compliance / GSAS — Product Designer Brief

**Feature**: Qatar GSAS sustainability score module — dashboard, categories, criterion detail, deductions, surveys, evidence library, audit package.

**Audience**: Product designer, no ARVIS context, no GSAS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. One module produces a continuous **GSAS score** for the building (Qatar's annual green-building rating, similar to LEED). Score is computed daily from live sensor + operator inputs. The output: a 1-6 Star rating renewed yearly via an audit by GORD (the Qatari assessor).

## 30-second GSAS primer

**GSAS-OP** = GSAS for Operations. Annual certification. ~8 categories (Energy, Water, Indoor Environment, Materials, Waste, Site, Management, Cultural/Economic). Each has criteria (~50-80 total). Each criterion has a benchmark + earned points. Total points → Star rating (1-6, 6 best).

ARVIS's bet: replace the annual scramble (operator hunts evidence in binders) with a live score that's always up to date, with an audit package one click away.

---

## Why this exists

Today the sustainability officer (Layla) collects evidence by hand for 3 months before each annual audit. ARVIS makes the score visible every day, evidence collected continuously, recovery actions surfaced proactively.

---

## Users

- **Sustainability officer (Layla)** — primary user, daily check-in
- **Facility manager (Ahmed)** — weekly review, approves recovery budgets
- **Owner (Noor)** — quarterly snapshot
- **GORD auditor** — annual walk-through (P2 auditor mode)

---

## Scope

**In (P0)**:
- Dashboard (score, trajectory, top risks)
- Categories overview
- Category detail
- Criterion detail (focus surface)
- Deductions (work queue)
- Audit Package generation

**In (P1)**:
- Surveys (send, monitor, results)
- Evidence Library (search archive)
- Settings (rating period, baselines, GSAS version)

**Deferred**:
- Auditor mode (read-only external)
- Predictive end-of-period score
- Peer-building benchmarking
- Other standards (LEED, BREEAM)

---

## Key automation table

Show this on screen as inline chips:

| Task | ARVIS | Human |
|---|---|---|
| Read meters | 🔄 | — |
| Compute kWh/m²/yr | 🔄 | — |
| Compare to benchmark | 🔄 | — |
| Flag deduction risk | 🔄 | review |
| Suggest recovery action | 🤖 | pick + execute |
| Send tenant survey | 🤖 | review send list |
| Upload policy PDF | — | ✋ |
| Compile audit package | 🔄 | review |
| Submit to GSASgate | — | ✋ |

(🔄 auto · 🤖 suggest · ✋ manual)

---

## Things users must be mindful of (surface in UI)

1. Score is **provisional until audit**. Label "ARVIS-estimated".
2. Some criteria need physical inspection — ARVIS can't verify landscaping was planted.
3. Surveys must meet response rate threshold (~30%) — ARVIS suggests, operator owns.
4. Policy docs need human signatures.
5. Deduction recovery has deadlines. After period close = locked.
6. GSAS standard version drift — warn when newer version released.
7. ARVIS does NOT submit on operator's behalf — human owns final submission.

---

## Layout — main views

### Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│ ★ ★ ★ ★ ☆ ☆       Trajectory Chart                                  │
│ 4 Star                                                              │
│ Projected: 4 Star    [chart: score vs months, with star bands]      │
│ ARVIS-estimated · 2 min ago                                         │
├─────────────────────────────────────────────────────────────────────┤
│ Categories (8 cards)                                                │
│ [Energy 87%] [Water 92%] [IndoorEnv 78%] [Materials 95%] ...        │
├─────────────────────────────────────────────────────────────────────┤
│ Top Deduction Risks            │ Recent Activity                    │
│ • Chiller plant -2pts          │ • Survey sent floor 12, 2h ago     │
│ • IAQ survey response low      │ • +2pts Energy recovered, today    │
│ • Lighting LPD high            │ • Evidence uploaded Mgmt-3         │
└─────────────────────────────────────────────────────────────────────┘
```

### Category Detail (drill from a card)

Criteria table for that category. Sortable. Row click → Criterion Detail.

### Criterion Detail — the work surface

Most important screen for Layla.

- Big benchmark vs current side-by-side
- Status chip: Met / At Risk / Failed
- Plain-English explainer
- Evidence panel (chips, click to drill)
- Calculation trail (show the math)
- History chart
- Recovery actions (if deducted)
- Audit notes (freetext)

### Deductions

Flat table. Filterable by category, status, deadline. Sort by deadline asc by default.

### Audit Package

- Generate button (kicks off job)
- Pre-submission checklist (4 mandatory checkboxes)
- Past packages list

---

## States

- **First-time setup** (new building, <30d data): "ARVIS needs 30 days of data. 7 / 30 days complete."
- **Rating period rollover**: dual-period view briefly
- **Standard version drift**: yellow banner across module
- **Permanently lost points**: row faded, "Locked" badge
- **Shadow mode**: submit / generate disabled, banner "GSAS in shadow — not for submission"

---

## Flows

### Flow A — Monthly Layla check-in (target ≤4 min)

1. Dashboard → Score 4 Star, -2pts vs last week
2. Energy card amber → click → Category Detail
3. Sort criteria by points lost → top row → click → Criterion Detail
4. Read calc trail, accept recovery action
5. Done

### Flow B — Annual audit prep (Flow B from earlier docs)

1. Audit Package → Generate
2. Read PDF (UI tracks pages read)
3. Tick 4 checkboxes
4. Submit button enables → modal "ARVIS does not submit. Log in to GSASgate."
5. External submission
6. Mark "Submitted" in ARVIS

### Flow C — Recovery action closed loop

1. Layla accepts "Recommission CH-4 reset schedule"
2. Advisory appears in main Live View
3. Operator (Bilal) sees + executes
4. Advisory closed → evidence auto-attached to criterion
5. Criterion recomputes → Layla sees +2pts next visit

---

## Design principles

1. **Score is a story, not a number**. Trajectory chart over big number.
2. **Always label "ARVIS-estimated"**. Auditor decides.
3. **Recovery actions are the work**. Surface them prominently.
4. **Audit walk readiness**. Every screen presentable to GORD over Layla's shoulder.
5. **Calculation transparency**. Every number has "show math" affordance.
6. **Defer to human at last mile**. Submit, sign, attest — always human-confirmed.

---

## Edge cases

- Criterion with no data: "No data — manual entry required" + upload button
- Survey under-response: warning before close, override with explanation
- Auditor disputes ARVIS score: Audit Notes captures
- Shadow mode: submit/generate disabled with explanation

---

## Open questions

1. Star icons: gold filled vs GSAS-branded? Need GORD brand pack.
2. Trajectory chart density: always annotated or hover-annotated?
3. Treemap variant for category overview?
4. Audit package preview: in-browser PDF or download-only?
5. Recovery action ranking: points / speed / cost? Default = points.

---

## Success criteria

- "Are we on track?" answered in <30s on Dashboard
- Monthly check-in ≤4 min
- Audit package generated by non-engineer
- Surveys ≥30% response rate
- Auditor walk: ARVIS evidence accepted

## What designer needs from product

- GSAS-OP standard PDF (skim for category list)
- Sample old audit binder (replace with this)
- Shadow with real sustainability officer (1 hr)
- GORD star brand pack
- Sample data: full rating period mock

## Changelog

- v1 2026-05-23: initial
