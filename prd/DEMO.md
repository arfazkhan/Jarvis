# ARVIS 2-Minute Demo — Build PRD

**Goal**: Single scripted 2-minute demo. Sales rep loads Marina Heights, hits play, watches all 6 ARVIS moats land on screen. Closes the meeting.

**Status**: v1
**Date**: 2026-05-23
**Audience**: Product designer + Frontend engineer + Backend engineer (all read this; sections labeled)

This PRD **collapses 13 feature PRDs into 5 features and one scripted scenario**. Everything not in this doc is deferred.

---

## 1. The Demo

### 1.1 What the customer sees (timed)

```
0:00 — ARVIS open on Live View. Marina Heights schematic visible. SIM badge top-right.
       Sales rep: "This is Marina Heights, Doha. 32 floors, 4 Carrier chillers,
                   142 air handlers. ARVIS is watching."

0:15 — Sim Cockpit pre-loaded with "AHU-7 cascade" scenario. Hits Play (off-screen).
       Sim clock 6x speed.

0:20 — Schematic: AHU-7 icon shifts amber → red over 5 seconds.
       Alarm strip populates: 4 cascade alarms.
       Advisory card slides into feed: "T2 · AHU-7 supply temp cascade"
       Sales rep: "ARVIS just caught a cascade fault without me asking."

0:30 — Sales rep clicks advisory card. Advisory Detail opens.

0:35 — Header visible:
       "AHU-7 supply temp 2.4°C above setpoint. Coil saturated.
        Recommend technician dispatch within 48h."
       Sales rep: "It tells me what's wrong, what to do, and how confident it is."

0:45 — Counterfactual block expanded by default:
       ┌─ With action ──────┐ ┌─ Without action ───┐
       │ 30d failure: 4%    │ │ 30d failure: 34%   │
       │ kWh waste: 0       │ │ kWh waste: 1,240   │
       │ Cost: $0           │ │ Cost: $1,240       │
       └────────────────────┘ └────────────────────┘
       Sales rep: "Here's what it costs to ignore this. $1,240 in 30 days."
       ← MOAT 1: Counterfactual + dollar value

1:00 — Sales rep expands Agent Trace (single click on collapsible).
       Maintenance_Agent · APPROVE · 86% · "Matches OA damper signature"
       Energy_Agent · APPROVE_WITH_CONDITION · 71% · "Verify ambient driving"
       Comfort_Agent · APPROVE · 80% · "Zone 12 above setpoint confirmed"
       Memory_Agent · ABSTAIN · — · "Transient model failure, excluded"
       Sales rep: "Four AI specialists debated. They didn't all agree.
                   ARVIS shows you who said what."
       ← MOAT 2: Multi-agent debate

1:15 — Sales rep clicks an evidence chip "Physics: COP -12.4%"
       Modal opens. Chart: dotted purple predicted COP line vs solid observed.
       Shaded delta where they diverge starting 14:00 today.
       Sales rep: "Here's where physics expected COP to be vs where it is.
                   Twelve percent gap. That's the smoking gun."
       ← MOAT 3: Physics prediction overlay

1:30 — Sales rep closes modal. Points at Verifier Gates strip:
       Claim ✓  Faithfulness ✓  Physics ✓
       Sales rep: "Before this advisory reached me, ARVIS ran three
                   automated checks. Every claim grounded. No hallucinations."
       ← MOAT 4: Verifier gates

1:40 — Sales rep clicks memory evidence chip "Past incident 2026-03-04"
       Modal: prior AHU-7 incident resolved by OA damper actuator replacement.
       Sales rep: "ARVIS remembers. Same fault three months ago.
                   This is what worked then."
       ← MOAT 5: Cross-incident memory

1:50 — Sales rep closes modal. Sticky action bar visible.
       Clicks Approve. Optional comment skipped.
       Toast: "Approved · Maintenance task created · Linked to vendor ACME"
       Sales rep: "I approve. ARVIS opens a ticket. Loop closed."
       ← MOAT 6: Decision-coupled (operator → action → memory)

2:00 — End. Customer asks first question.
```

### 1.2 What customer must take away

- ARVIS works **on its own**, not via chat
- Recommendations have **dollar value attached**
- Multiple **AI agents debate**, no single black box
- **Physics**, not just statistics
- **Memory** across incidents
- **Verifier gates** prevent hallucination
- One-click decision closes the loop

If they don't say "wait, show me again" by 2:30, the demo failed.

---

## 2. In-Scope Features (5)

Other 8 features (Equipment Detail, Memory Knowledge full screen, Compliance, Audit Replay, Exec KPI, Notifications, Onboarding, Settings) are **deferred** for this demo.

### 2.1 Shell (chrome only, minimal)

What's needed:
- Top bar with ARVIS logo (left)
- Building name "Marina Heights Tower" (left)
- Mode badge "SIM" (center-right, gray pill)
- Wall/sim clock (right) — shows current sim time
- Bell icon (right) — badge increments when advisory arrives
- Side nav — collapsed to icons. Only 3 items lit: Live View / Sim Cockpit / placeholder others greyed
- User avatar (right) — does not need to open dropdown

What's NOT needed:
- Building selector dropdown (locked single building)
- Theme toggle
- Multi-mode color states (only SIM needed; others stub)
- Functional sign-out
- Notification preferences

See: `prd/shell/designer.md` + `prd/shell/engineer.md` for full version. Subset only.

### 2.2 Live View (schematic + advisory feed only)

What's needed:
- 2D SVG schematic of Marina Heights chiller plant + 1 AHU floor
  - Equipment shown: CH-1, CH-2, CH-3, CH-4, AHU-7, AHU-8, AHU-9 (any 7 pieces is enough)
  - Equipment color per status (green / amber / red / gray)
- Alarm strip top (renders 4 cascade alarms when scenario fires)
- Advisory feed right column (renders the one demo advisory)
- KPI strip bottom — optional, can stub or omit

What's NOT needed:
- P&ID toggle
- Equipment hover tooltips (nice but not required)
- Equipment click-to-navigate (schematic is decorative for this demo)
- Sparklines in KPI tiles (omit KPI strip if tight)
- Empty / loading polish

See: `prd/live_view/` for full version.

### 2.3 Advisory Detail (FULL — hero screen)

This is the demo. Build it richest.

What's needed (all):
- Header (risk tier T2 chip, summary, equipment chip, time, no SHADOW for demo)
- Recommendation block (action + predicted savings + confidence bar)
- Counterfactual block (two cards, with/without action, all 4 numbers per side)
- Verifier Gates strip (3 green badges + click expand details)
- Agent Trace collapsible (4 agents with vote chip + confidence + reasoning)
- Evidence Ledger chip cloud (~6 chips covering 5 source types)
- Evidence drill modals (physics, memory at minimum; others stub OK)
- Sticky action bar (Approve / Reject / Snooze)

What's NOT needed:
- Reject reason picker modal (button can fire success toast directly)
- Snooze duration picker (button can be cosmetic)
- T3 confirm modal (demo uses T2)
- Operator action attribution block (no operator action in scenario)
- Replay mode variant
- Undo

See: `prd/advisory_detail/` for full version. Build the full hero per that PRD.

### 2.4 Sim Cockpit (minimal control surface)

What's needed:
- Single scenario card "AHU-7 cascade" — selected by default
- Single building loaded "marina_heights.yaml" — locked
- Play / Pause button
- Speed selector (1x / 6x default / 60x)
- Sim clock display
- "Reset scenario" button

What's NOT needed:
- Multiple scenarios
- Building loader
- Persona toggles (run with default persona set, or none)
- Judge panel
- Jump-to-event
- Custom scenarios

See: `prd/simulation_cockpit/` for full version. Subset only.

### 2.5 Operator Actions (Approve only, minimal)

What's needed:
- Approve button works → optimistic UI + toast "Approved · task created"
- Toast shows downstream_effects from response

What's NOT needed:
- Reject modal
- Snooze flow
- Feedback flow
- Escalate flow
- Undo
- T3 confirm
- Idempotency-Key generation (nice but not demo-critical)

See: `prd/operator_actions/` for full version.

---

## 3. Out of Scope (Explicit)

Cut for demo:
- All notifications other than bell badge increment
- All cross-screen navigation other than schematic-decorative + advisory feed → detail
- Equipment Detail screen entirely
- Memory & Knowledge browser (one chip drill modal is enough)
- GSAS Compliance entirely
- Audit & Replay entirely
- Exec KPI entirely
- Onboarding Wizard entirely
- Settings & Roles entirely
- Auth (use a static dev token; sign in is decorative)
- Real BACnet integration (Sim event generator only)
- Mobile / responsive layout (demo runs on 1920×1080 sales laptop)
- Print stylesheets
- Internationalization (English only)
- Dark mode toggle (dark default; no light)
- Accessibility deep work (basic ARIA only; full pass deferred)

---

## 4. Required Demo Scenario (Engine + Data)

### 4.1 Scenario script: `ahu7_cascade`

Defined in `scratch/scenarios/ahu7_cascade.yaml` (TBD path). Driven by Sim engine.

**Trigger sequence** (driven by sim clock):
- T+0: scenario starts
- T+5s: AHU-7 OA_DMPR position drifts 15% → 80% (synthetic point update injected)
- T+8s: MAT rises 4.2°C above expected
- T+12s: CHW valve saturates at 100% command
- T+15s: SAT deviation alarm fires (ALM-AHU7-001 critical)
- T+18s: 3 additional cascade alarms fire (ALM-AHU7-002 through -004)
- T+20s: ARVIS engine generates advisory (autonomous, not user-triggered)
- T+22s: Advisory published via SSE
- T+25s: Advisory card visible in FE feed

The advisory generation must take 2-5 seconds on screen — enough to feel "thinking" but not so long the demo stalls.

### 4.2 Advisory contract for demo

The single demo advisory must have:

```yaml
id: <uuid>
risk_tier: T2
summary: "AHU-7 supply temp 2.4°C above setpoint. Coil saturated. Recommend technician dispatch within 48h."
equipment_ids: ["AHU-7"]
recommendation:
  action: "schedule_inspection"
  target_equipment_id: "AHU-7"
  target_window_hours: 48
  expected_savings_kwh_per_day: 41
  expected_mtbf_delta_days: 12

counterfactual:
  with_action:
    horizon_hours: 720
    predicted_failure_probability: 0.04
    predicted_kwh_overage: 0
  without_action:
    horizon_hours: 720
    predicted_failure_probability: 0.34
    predicted_kwh_overage: 1240

swarm_votes:
  - agent: "Maintenance_Agent"
    verdict: "APPROVE"
    confidence: 0.86
    reasoning_summary: "OA damper drift signature confirmed by 15% position deviation"
  - agent: "Energy_Agent"
    verdict: "APPROVE_WITH_CONDITION"
    confidence: 0.71
    conditions: ["Verify ambient temperature not primary driver"]
    reasoning_summary: "Could be ambient-driven at 49°C OAT"
  - agent: "Comfort_Agent"
    verdict: "APPROVE"
    confidence: 0.80
    reasoning_summary: "Zone 12 confirmed above setpoint 25.1°C"
  - agent: "Memory_Agent"
    verdict: "ABSTAIN"
    confidence: null
    reasoning_summary: "Transient model failure, excluded from quorum"

verifier_gates:
  h2_claim: { status: "pass", score: 0.94, blocked_claims: [] }
  h4_faithfulness: { status: "pass", score: 0.91, contradictions: [], regen_attempts: 0 }
  h6_physics: { status: "pass", deviation_pct: 12.4, threshold_pct: 15.0 }
  abstention_gate: { fired: false, signals: { data_coverage: 0.93, truth_score: 0.91, ml_fallback_ratio: 0.0, max_drift: 0.08 } }

evidence_ledger:
  - source_type: "live_sensor"
    source_ref: "AHU-7/OA_DMPR_POS"
    value_summary: "OA damper position: 80% (expected 65%)"
  - source_type: "historian"
    source_ref: "AHU-7/SAT 24h history"
    value_summary: "SAT min 14.2°C, max 16.8°C, deviation onset 14:00"
  - source_type: "physics_simulator"
    source_ref: "coil model AHU-7 NTU-effectiveness"
    value_summary: "COP predicted 4.12 vs observed 3.61 (-12.4%)"
  - source_type: "memory"
    source_ref: "Past incident 2026-03-04"
    value_summary: "Same fault, resolved by OA damper actuator replacement, 4h labor, ACME"
  - source_type: "live_sensor"
    source_ref: "AHU-7/CHW_VLV_CMD"
    value_summary: "CHW valve at 100% command, saturated"
  - source_type: "ml_model"
    source_ref: "alarm cluster 3ad7bc2d"
    value_summary: "4-alarm cluster, root cause confidence 0.80"
```

Backend must produce this exact shape. Hand-author the YAML + canned response if needed for demo. Live engine generation is **nice-to-have**, scripted response is **must-have**.

### 4.3 Physics overlay data (for drill modal)

```yaml
chart_series:
  predicted:
    points: [{ts: "T-24h", value: 4.10}, ..., {ts: "T-2h", value: 4.12}, {ts: "now", value: 4.11}]
  observed:
    points: [{ts: "T-24h", value: 4.08}, ..., {ts: "T-2h", value: 4.10}, {ts: "now", value: 3.61}]
  threshold_pct: 5.0
  deviation_onset_ts: "T-2h"
```

---

## 5. Build Order

```
Step 1 (parallel):
  - Backend: scenario engine + canned advisory generator
  - Frontend: shell + Sim Cockpit minimal
  - Designer: Advisory Detail high-fidelity

Step 2:
  - Frontend: Live View schematic + advisory feed
  - Backend: SSE wired up
  - Designer: Live View + Sim Cockpit minimal

Step 3:
  - Frontend: Advisory Detail full build
  - Frontend: Operator Action approve flow

Step 4 (integration):
  - End-to-end: hit play → advisory appears → click → all moats visible → approve

Step 5 (polish):
  - Timing tuning (5s alarm cascade, 2-5s advisory delay)
  - Schematic equipment color animations
  - Toast styling
  - Final demo dry-runs
```

No timeline given — depends on team. Estimated 3-4 weeks of focused work.

---

## 6. Acceptance Test

Demo is ready when:

- [ ] Sales rep with 30 min training runs full 2-min demo solo without engineer
- [ ] Scenario fires same way 10 times in a row, no flakiness
- [ ] Advisory appears within 20-25s of scenario start (consistent)
- [ ] All 6 moats visibly land within 2 min
- [ ] Approve button works and shows downstream effects
- [ ] Reset button cleanly returns to baseline for next demo
- [ ] Runs on 1920×1080 sales laptop in browser (no install)
- [ ] No browser console errors during demo
- [ ] No network errors during demo (canned responses OK)
- [ ] Sub-2-second navigation between schematic click and Advisory Detail
- [ ] Physics chart renders in <300ms

If any fail: not demo-ready.

---

## 7. Designer Deliverables

For 2-min demo:

1. **Shell** mockup at high-fidelity for top bar + side nav (collapsed state only)
2. **Live View** mockup with:
   - Marina Heights schematic (7-10 equipment pieces, hand-drawn layout)
   - Alarm strip with 4 cascade alarms shown
   - Advisory feed with 1 demo card
3. **Advisory Detail** mockup at high-fidelity, all sections:
   - Header
   - Recommendation
   - Counterfactual (most attention)
   - Verifier Gates
   - Agent Trace expanded
   - Evidence Ledger chip cloud (~6 chips)
   - Evidence Drill Modal (physics overlay + memory variants)
   - Sticky action bar
4. **Sim Cockpit** mockup minimal (play / pause / speed / reset)
5. **Color tokens** finalized (dark theme only for demo)
6. **Custom icons**: chiller, AHU, valve (custom SVGs)
7. **Approve toast** styling

Skip:
- Light theme
- Mobile / tablet layouts
- Empty states / error states beyond loading skeletons
- Settings screens
- Print stylesheets

---

## 8. Frontend Engineer Deliverables

1. Next.js app with shell + 4 routes:
   - `/live-view` (the home)
   - `/advisories/{id}` (Advisory Detail)
   - `/sim` (Sim Cockpit)
   - `/login` (decorative — dev token bypass)
2. SSE subscription wired
3. Static demo-fixture mode: if `NEXT_PUBLIC_DEMO_MODE=true`, use canned advisory + canned point updates instead of real backend
4. Scenario auto-play timing tuned to 20-25s alarm-to-advisory
5. Advisory Detail full implementation per `prd/advisory_detail/engineer.md`
6. Physics chart in evidence drill modal (ECharts)
7. Approve button with toast
8. Bell badge increment on SSE event

Skip:
- All other routes
- Auth integration (use mock `useMe()` returning demo user)
- Permissions enforcement
- Audit log writes
- React Query devtools in demo build

---

## 9. Backend Engineer Deliverables

Two options. Pick A for safety, B for credibility.

### Option A — Canned response demo backend (lower risk, recommended for first demo)

- Static REST endpoint `GET /api/v1/advisories/{id}` returns the YAML from §4.2 verbatim
- SSE endpoint publishes hand-scripted events on timer when Sim Cockpit `/start` called
- Sim Cockpit endpoints return success without doing real work
- No real ARVIS engine in loop

Pros: zero risk, deterministic
Cons: customer asks "is this real?" — answer is "scripted scenario, same engine"

### Option B — Real engine in scripted scenario mode (higher credibility, higher risk)

- Real ARVIS engine reads Marina building.yaml + scenario.yaml
- Engine fires real alarms when scenario clock advances
- Real swarm vote, real verifier gates, real evidence ledger
- Engine returns advisory matching demo expectations (because scenario constructed to)

Pros: real ARVIS reasoning, post-demo customer can ask follow-up
Cons: engine variability — needs Marina pass rate ≥90% to be safe (currently 33%)

**Recommendation**: ship Option A for first sales rotation. Migrate to Option B when Marina hits 90%.

Either way, deliver:
- Scenario file: `ahu7_cascade.yaml`
- Marina building topology file: `marina_heights.yaml` (already exists)
- SSE event publisher with timing controls
- Reset endpoint that flushes state

---

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Engine variability ships wrong advisory shape | High (today) | Demo fails | Use Option A canned backend until Marina ≥90% |
| Physics chart renders slow | Low | Demo hiccup | Disable animations, pre-warm chart on Sim Cockpit load |
| Network drop during demo | Low | Demo fails | Run with `NEXT_PUBLIC_DEMO_MODE=true` + local SSE simulator |
| Designer scope creep into deferred features | Medium | Late demo | Hard cut at acceptance test; defer enthusiastically |
| Customer asks for live BMS integration mid-demo | Medium | Demo derails | Sales script: "This is SIM mode — same UI as PROD. SIM is for demos." |
| Sales rep can't pace 2:00 | Medium | Demo runs 3-4 min | Sales training + sim clock 6x ensures 2:00 budget |

---

## 11. What This Demo Does NOT Cover

- Long-form conversation (Q&A bonus 30s only)
- Multiple buildings
- Multi-tenant
- GSAS compliance story (separate demo)
- Operator UX deep dive (separate demo)
- Owner KPI story (separate demo for exec audiences)

This demo wins **technical buyers** (CTO, CIO, head of facilities). For owner / CEO audience, build the Exec KPI demo separately.

---

## 12. Open Questions

1. **Sales script**: who writes the verbal narration? Recommendation: sales team writes, product reviews.
2. **Demo recording**: should we record a backup video for offline meetings? Yes — 2-min loop video as fallback.
3. **Localization**: Arabic version needed for Doha sales? P1 — English ships first.
4. **Branding**: customer logo top-left for prospect-specific demos? P1.
5. **Multiple scenarios**: do we ship only `ahu7_cascade` or also `refrigerant_migration` for variety? P0 just one. P1 add second.

---

## 13. Success Criteria for the Demo Itself

Beyond technical acceptance test, the demo succeeds when:

- ≥50% of customer meetings result in technical deep-dive follow-up
- ≥30% of meetings result in pilot RFP
- Customers verbatim reference moats ("the trace", "the gates", "the physics overlay") in follow-up emails
- Sales cycle from first meeting to signed pilot ≤90 days (industry benchmark: 180+)
- Repeatable across at least 3 sales reps

---

## 14. Beyond the Demo

After this demo lands:
- **Next sprint**: Equipment Detail (deepen the physics moat story)
- **Sprint after**: GSAS Compliance (deepen the value moat story)
- **Sprint after**: Onboarding Wizard (close the pilot loop)
- **Sprint after**: Exec KPI (open the C-level loop)

This demo PRD is the wedge. Everything else widens it.

---

## Changelog

- v1 2026-05-23: initial — collapses 13 feature PRDs into 5-feature demo build spec
