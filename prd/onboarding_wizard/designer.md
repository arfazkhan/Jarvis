# Onboarding Wizard — Product Designer Brief

**Feature**: New building setup. Upload spec, map BACnet points to ARVIS ontology, set baselines, enable shadow mode, go live.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. To monitor a new building, ARVIS needs:
1. A **building spec** (YAML or guided form) describing equipment + topology
2. A **point mapping** — connecting the building's BMS (Building Management System) points to ARVIS's canonical names ("MAIN/HVAC/CH-1/EVAP_LWT" → "CH-1.chilled_water_supply_temp")
3. **Coverage validation** — % of expected points actually mapped
4. **Shadow mode** for first 30 days (advisories render, no notifications, no writes)
5. **Go-live** — explicit human gate flip from shadow to live

Onboarding is a multi-step wizard inside the Simulation Cockpit (for SIM building creation) or accessed via Settings (for real building onboarding by a facility manager / engineer).

---

## Why this exists

Without onboarding, each new building requires hand-editing config files and a manual integration handoff. With the wizard, a facility manager can onboard a building in <4 hours.

---

## Users

- **Facility manager** — primary, owns the onboarding
- **AI engineer** — co-pilot for complex mappings
- **Sales** — preview the experience for prospective customers

---

## Scope

**In**:
- Step 1: Building spec (upload YAML or guided form)
- Step 2: BACnet point mapping with coverage %
- Step 3: Baselines (energy intensity benchmark, occupancy, schedules)
- Step 4: Compliance setup (GSAS version, rating period)
- Step 5: Shadow mode confirmation
- Step 6: Go-live (explicit gate, requires confirmations)

**Out**:
- Initial BMS integration setup (out-of-band engineering work)
- Auth/role configuration (separate Settings flow)
- Tenant survey configuration (separate within GSAS)

---

## Layout — wizard pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│ Onboarding Wizard — Marina Heights Tower                            │
│ Step 2 of 6: Map BMS Points                                         │
│ ●●○○○○                                                              │
├─────────────────────────────────────────────────────────────────────┤
│ Map BMS Points                                                      │
│ ARVIS needs to know which of your BMS points correspond to which   │
│ equipment readings.                                                 │
│                                                                     │
│ Coverage: 8,247 / 12,386 points mapped (67%)                        │
│ ████████████████░░░░░░░  Need ≥80% to proceed                       │
│                                                                     │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Search points: [             ]   Filter: [✓Mapped ✓Unmapped]   │ │
│ │                                                                  │ │
│ │ BMS Point                       ARVIS Mapping       Confidence  │ │
│ │ MAIN/HVAC/CH-1/EVAP_LWT_C       CH-1.chwst         ✓ Auto       │ │
│ │ MAIN/HVAC/CH-1/COND_EWT_C       CH-1.ecwt          ✓ Auto       │ │
│ │ MAIN/HVAC/CH-1/POWER_KW         CH-1.power_kw      ✓ Auto       │ │
│ │ MAIN/HVAC/CH-1/UNKNOWN_PT_47    [Pick mapping ▾]   ⚠ Unmapped   │ │
│ │ ...                                                              │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│ [Back]                                       [Skip] [Next: Baselines] │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Steps

### Step 1: Building spec

- Two options: Upload YAML or Guided form
- Guided form fields: building name, floor area, occupancy, equipment counts per type, BMS vendor (Desigo CC / Niagara / other)
- Validation: must have ≥1 chiller, ≥1 AHU
- Preview: parsed building summary

### Step 2: BACnet point mapping

- Table with all BMS points
- Auto-mapped (high confidence) shown ✓ with confidence indicator
- Unmapped flagged ⚠ — click → dropdown with ARVIS canonical names
- Filter: mapped / unmapped / by equipment
- Search by point name
- Coverage % live updates as user maps
- ≥80% required to proceed (blocks Next button below threshold)
- "Skip and finalize later" link → saves draft, returns to it from Settings

### Step 3: Baselines

- Energy intensity benchmark (kWh/m²/yr) — required for GSAS scoring
- Occupancy schedule (per day-of-week)
- Setpoint defaults (CHWST, zone temp ranges)
- Comfort thresholds
- Quick-fill: "Use standard office defaults"

### Step 4: Compliance setup

- GSAS version (auto-selected if Doha building)
- Rating period start date
- Building category (Commercial Office / Retail / Mixed Use)
- Owner-of-record (for audit package)

### Step 5: Shadow mode confirmation

- Big explainer: "Shadow mode means ARVIS observes and advises but doesn't act for the first 30 days. This builds trust before going live."
- Visual diff: shadow vs live (what fires vs what doesn't)
- Required acknowledgments (checkboxes):
  - [ ] I understand shadow mode means no BMS writes, no notifications
  - [ ] I will review shadow advisories before flipping to live
  - [ ] Date target for go-live (informational, not enforced)

### Step 6: Go-live decision

- Defaults to "Start in shadow mode" (Recommended)
- Alternative: "Go live immediately" — requires explicit checkbox + confirm modal (intended for engineers re-onboarding after a config change)
- "Onboard" button → kicks off integration verification → progress → success / failure detail

---

## States

- **Pre-wizard**: launch from Settings or Sim Cockpit
- **In-progress**: step indicator, back navigation
- **Draft saved**: banner "Resuming from step 2 — last saved 2h ago"
- **Validation failure on a step**: error chip + scroll to first error
- **Coverage <80%**: Next button disabled + tooltip "Reach 80% to proceed"
- **Integration verification failed**: detail panel with errors + retry / cancel
- **Onboarding complete**: success screen → "Open Live View" CTA

---

## Flows

### Flow A — Facility manager onboards a new building

1. Engineering finishes BMS integration plumbing offline
2. FM opens Onboarding Wizard
3. Step 1: uploads building.yaml from architect
4. Step 2: 78% auto-mapped, FM manually maps 20 more points, hits 87%
5. Step 3: enters baselines from utility bill
6. Step 4: GSAS-OP v2.1, period starts today
7. Step 5: acknowledges shadow rules
8. Step 6: defaults to shadow → Onboard
9. Building appears in selector, ARVIS observing

Total time: ~3h with breaks.

### Flow B — Engineer re-onboards after config change

1. Engineer needs to swap building.yaml v1.0 → v2.0
2. Opens Settings → "Re-onboard building"
3. Uploads new YAML
4. Wizard prefilled where possible, asks confirmation on changes
5. Step 6: chooses "Skip shadow — already validated"
6. Confirms

### Flow C — Wizard interrupted

1. FM starts wizard, completes 3 steps
2. Power outage / browser crash
3. Reopens → "Resume onboarding for Marina Heights" prompt
4. Picks up at Step 4

---

## Design principles

1. **Big visible coverage %**. The ≥80% gate is the most important UX element.
2. **Auto-map shown with confidence**. Operator can trust or override.
3. **Shadow is the default**. Skipping shadow is a deliberate, explicit choice.
4. **Save drafts aggressively**. Onboarding is multi-hour; never lose progress.
5. **Validation messages are actionable**. "Floor area required" not "Field invalid".
6. **Wizard is exit-able**. User can leave and return without losing state.

---

## Edge cases

- BMS reports 30,000 points where 12,000 expected: pagination + virtualization
- Auto-mapper confidence universally low: warn "Auto-mapping confidence low — manual review required"
- User uploads YAML for wrong building type: schema validation error
- User tries to go-live but coverage drops back to <80% on validation: block
- Concurrent onboarding (two users): lock building, show "Locked by X"

---

## Open questions

1. **Where wizard lives** — under Settings or top-level nav? Recommendation: top-level for first-deploy, then under Settings for reconfig.
2. **Auto-map confidence threshold** for auto-acceptance — 0.8? 0.9?
3. **Skip shadow** flow — engineer-only? Or facility_manager with extra warning?
4. **Building.yaml editor in-browser** vs IDE-only? Recommendation: P2 in-browser.
5. **Multi-building portfolio onboarding** — bulk import? P3.

---

## Success criteria

- Non-engineer FM completes onboarding solo
- Coverage ≥80% in ≤3 hours for a typical 10k-point building
- Wizard recovers from interruption without loss
- 30-day shadow lifts to live cleanly

## What designer needs from product

- BACnet point name format examples (vendor-specific)
- ARVIS canonical point ontology
- Confidence calibration for auto-mapper
- Sample building.yaml for Marina Heights

## Changelog

- v1 2026-05-23: initial
