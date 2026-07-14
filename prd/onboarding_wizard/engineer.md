# Onboarding Wizard — Frontend Engineer Brief

**Feature**: `/onboarding` — multi-step wizard for new building setup.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS monitors commercial chiller plants. To onboard a new building it needs: spec, BACnet point mapping (≥80% coverage), baselines, compliance setup, shadow-mode acknowledgment, go-live gate. Backend exposes these as multi-call wizard endpoints. Frontend persists drafts as user moves through steps.

---

## What you're building

Route: `/onboarding/[buildingId]/[step]`.

6 steps, sequential with back/forward nav. Drafts persisted server-side after each step. Resumable mid-flow.

---

## Stack

Same as `shell/`. Form lib: `react-hook-form` + `zod` for validation. File upload: native input + drag-drop overlay.

---

## File layout

```
app/(authed)/onboarding/
  [buildingId]/
    [step]/page.tsx              — dynamic step routing
    layout.tsx                   — wizard chrome (progress, nav)
  page.tsx                       — entry: start new or resume

components/onboarding/
  WizardLayout.tsx
  StepProgress.tsx
  StepNav.tsx                    — back/next/skip
  
  Step1Spec.tsx
  YAMLUpload.tsx
  GuidedSpecForm.tsx
  
  Step2Mapping.tsx
  PointMappingTable.tsx
  CoverageGauge.tsx
  MappingDropdown.tsx
  
  Step3Baselines.tsx
  BaselineForm.tsx
  
  Step4Compliance.tsx
  ComplianceForm.tsx
  
  Step5Shadow.tsx
  ShadowAcknowledgment.tsx
  
  Step6GoLive.tsx
  IntegrationVerificationPanel.tsx

lib/
  api/
    onboarding.ts
  schemas/
    onboarding.ts                — zod schemas per step
```

---

## Data dependencies

### Endpoints

```
POST   /api/v1/onboarding/start                          → { building_id, draft_id }
POST   /api/v1/onboarding/{building_id}/spec             → BuildingSpec
POST   /api/v1/onboarding/{building_id}/spec/parse-yaml  → { ok, errors? }
POST   /api/v1/onboarding/{building_id}/mapping          → BulkMappingResult
GET    /api/v1/onboarding/{building_id}/mapping/auto     → { mappings, confidences }
GET    /api/v1/onboarding/{building_id}/coverage         → { mapped, total, percent }
POST   /api/v1/onboarding/{building_id}/baselines        → Baselines
POST   /api/v1/onboarding/{building_id}/compliance       → ComplianceSetup
POST   /api/v1/onboarding/{building_id}/acknowledge      → { shadow_acknowledged: true }
POST   /api/v1/onboarding/{building_id}/finalize         → { mode: 'PILOT' | 'PROD', verification: Status }
GET    /api/v1/onboarding/{building_id}/draft            → CurrentDraft
```

### Cache keys

```
['onboarding-draft', buildingId]
['onboarding-coverage', buildingId]
```

### Form state

`react-hook-form` per step. Save on Next click. Failure halts navigation.

---

## Components

### `<WizardLayout>`

Renders progress + nav + step content slot.

```tsx
<div className="wizard">
  <StepProgress current={step} total={6} />
  <h1>{stepTitles[step]}</h1>
  <div className="step-content">{children}</div>
  <StepNav 
    onBack={prevStep}
    onNext={nextStep}
    nextDisabled={!stepValid}
    nextLabel={step === 6 ? 'Onboard' : 'Next'}
  />
</div>
```

### `<StepProgress>`

6 dots, filled to current step. Click filled dot to revisit (no jumping forward).

### Step 1 — `<Step1Spec>`

Toggle between Upload YAML vs Guided Form.

YAML upload:
- Drag-drop area + file picker
- POST to `/spec/parse-yaml`
- Show parse result: success → preview parsed building; error → inline error
- Edit-after-upload available via "Edit YAML" textarea

Guided form: react-hook-form fields. Validation via zod.

### Step 2 — `<Step2Mapping>`

Core complexity.

Workflow:
1. On mount: trigger `GET /mapping/auto` (auto-map all points)
2. Render table with auto-mapped rows pre-filled
3. User reviews/overrides
4. On override: optimistic UI + debounced POST to `/mapping`
5. Coverage % live-recomputes

Table virtualization (`@tanstack/react-virtual`) — buildings have 10k+ points.

```tsx
<CoverageGauge percent={coverage.percent} target={80} />

<PointMappingTable
  bmsPoints={bmsPoints}
  mappings={mappings}
  onChange={(pointId, mapping) => updateMapping(pointId, mapping)}
  filters={filters}
/>
```

`<MappingDropdown>`:
- Async-loaded list of ARVIS canonical names
- Search-as-you-type
- Confidence indicator next to suggestions

### Step 3 — `<Step3Baselines>`

Form with energy intensity, occupancy schedule (per day-of-week with time bins), setpoint defaults.

Quick-fill button: "Use standard office defaults" pre-populates.

### Step 4 — `<Step4Compliance>`

Form. Pre-selects GSAS-OP v2.1 for Doha building.

### Step 5 — `<Step5Shadow>`

Read-heavy screen. Three checkboxes to enable Next button:

```tsx
const allAcknowledged = ack1 && ack2 && ack3
<Button disabled={!allAcknowledged} onClick={next}>Next</Button>
```

### Step 6 — `<Step6GoLive>`

Two-choice cards: Shadow (recommended) or Live.

Choosing Live requires extra checkbox + confirm modal.

On Onboard click: POST to `/finalize`. Returns verification status, which the `<IntegrationVerificationPanel>` shows in detail (progress + checks).

Success → success page with "Open Live View" CTA. Failure → error detail + retry button.

---

## State management

- Form state via `react-hook-form` per step
- Server draft state via React Query
- URL drives step
- Zustand for: YAML editor open state, mapping filters, verification panel state

---

## Performance budgets

| Operation | Target |
|---|---|
| Step transition | <300ms |
| YAML parse | <1s |
| Auto-map 10k points | <5s (server side; FE shows progress) |
| Mapping table render | <500ms with virtualization |
| Coverage % update | <100ms |
| Finalize | <10s (verification takes time) |

---

## Testing

### Unit

- Zod schemas validate correctly
- Coverage gauge math
- Step nav disabled state

### Integration

- Full happy path: start → 6 steps → finalize → success
- Interruption: refresh mid-flow → resume from same step
- Mapping override propagates to coverage %
- Coverage <80% blocks Next on step 2

---

## Edge cases

- YAML parse fails: show errors inline, allow edit-and-retry
- Auto-map service down: render unmapped only, manual mode
- Concurrent onboarding: backend lock; UI shows "Onboarding by another user — view only"
- Building already onboarded (re-onboarding): wizard prefilled, "Replace existing" warning
- Browser crash: server-side draft preserved, prompt to resume on next visit

---

## Integration points

- `settings_roles/` — re-onboarding triggered from Settings
- `simulation_cockpit/` — building load reuses onboarding for SIM buildings
- After finalize: `live_view/` becomes accessible

---

## Open questions

1. **Building.yaml schema** — published or proprietary? Need engineering reference.
2. **Auto-mapper confidence display** — number, bar, or chip?
3. **In-browser YAML editor** — P2; just text area for P0?
4. **Wizard state machine library** — Xstate or hand-rolled? P0 hand-rolled.

## What engineer needs from product

- ARVIS canonical point ontology (full list of standard names)
- Building.yaml example
- Validation rules per step
- Integration verification checks list

## Changelog

- v1 2026-05-23: initial
