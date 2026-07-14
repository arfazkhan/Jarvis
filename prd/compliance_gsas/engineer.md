# Compliance / GSAS — Frontend Engineer Brief

**Feature**: `/compliance` — GSAS module (dashboard, categories, criterion detail, deductions, surveys, evidence library, audit package).

**Audience**: Frontend engineer, no ARVIS or GSAS context.

---

## 30-second ARVIS primer

ARVIS is a Next.js operator console. This module computes Qatar's GSAS sustainability rating continuously and produces an annual audit package. Score = 1-6 Star. Backend: REST + SSE.

## 30-second GSAS primer

GSAS = Global Sustainability Assessment System (Qatar's LEED equivalent). GSAS-OP = Operations flavor, annual renewal. ~8 categories, ~50-80 criteria total. Each criterion has a benchmark + earned points. Sum → Star rating.

---

## What you're building

Sub-routes under `/compliance/`:
- `/` — Dashboard
- `/categories` — Categories overview
- `/categories/{category_id}` — Category detail
- `/criterion/{criterion_id}` — Criterion detail
- `/deductions` — Deductions list
- `/audit-package` — Generate + history
- `/surveys` (P1)
- `/evidence` (P1)
- `/settings` (P1)

---

## Stack

Same as `shell/`. Add: PDF viewer for audit package preview — `react-pdf` (P1).

---

## File layout

```
app/(authed)/compliance/
  layout.tsx                       — sub-nav for GSAS module
  page.tsx                         — dashboard
  categories/page.tsx
  categories/[id]/page.tsx
  criterion/[id]/page.tsx
  deductions/page.tsx
  audit-package/page.tsx
  surveys/page.tsx                 — P1
  evidence/page.tsx                — P1
  settings/page.tsx                — P1

components/gsas/
  ScoreCard.tsx
  TrajectoryChart.tsx
  CategoryGrid.tsx
  CategoryCard.tsx
  CriteriaTable.tsx
  CriterionDetail.tsx
  CalculationTrail.tsx
  EvidencePanel.tsx
  RecoveryActions.tsx
  AuditNotes.tsx
  DeductionsTable.tsx
  AuditPackagePanel.tsx
  PreSubmissionChecklist.tsx

lib/
  api/
    gsas.ts
```

---

## Data dependencies

### Endpoints (REST)

```
GET  /api/v1/compliance/gsas/{building_id}                       → GSASScore
GET  /api/v1/compliance/gsas/{building_id}/categories            → GSASCategory[]
GET  /api/v1/compliance/gsas/{building_id}/categories/{cat_id}   → GSASCategory + criteria
GET  /api/v1/compliance/gsas/{building_id}/criterion/{id}        → GSASCriterion (full)
GET  /api/v1/compliance/gsas/{building_id}/deductions            → Deduction[]
POST /api/v1/compliance/gsas/{building_id}/evidence              → upload doc
GET  /api/v1/compliance/gsas/{building_id}/audit-package         → kicks off generation
GET  /api/v1/compliance/gsas/{building_id}/audit-package/{job}   → status / download URL
POST /api/v1/compliance/gsas/{building_id}/criterion/{id}/recover → accept recovery action
POST /api/v1/compliance/gsas/{building_id}/criterion/{id}/notes  → save audit notes
```

### SSE updates

Topic: `gsas`. Events:
- `gsas_score_update` — total score changed
- `gsas_deduction_new` — new deduction
- `gsas_deduction_recovered` — points restored

### Cache keys

```
['gsas-score', buildingId]                — refresh on SSE + on focus
['gsas-categories', buildingId]
['gsas-category', buildingId, categoryId]
['gsas-criterion', criterionId]
['gsas-deductions', buildingId, filters]
['gsas-audit-jobs', buildingId]
```

---

## Components

### `<ScoreCard>`

Big score card on dashboard.

```tsx
<div className="score-card">
  <StarRating filled={score.star_rating} total={6} />
  <div className="text-3xl font-mono">{score.total_points}</div>
  <div className="text-sm text-muted">of {score.total_max} points</div>
  <ProjectedRating projected={score.star_projected} />
  <DeltaIndicator delta={score.delta_vs_last_week} />
  <span className="text-xs text-muted">ARVIS-estimated · {timeAgo(score.last_calculated)}</span>
</div>
```

### `<TrajectoryChart>`

ECharts line chart.

X: months in rating period. Y: cumulative points.

Series:
- Actual (solid line)
- Projected (dotted line beyond today)
- Star bands (background shaded areas at thresholds)

Vertical marker for today. Hover → tooltip with score + events.

### `<CategoryCard>`

Grid item. Status chip + score + sparkline.

```tsx
<button onClick={() => router.push(`/compliance/categories/${cat.id}`)}>
  <div className="flex justify-between">
    <CategoryIcon kind={cat.kind} />
    <StatusChip status={cat.status} />
  </div>
  <h3>{cat.name}</h3>
  <ProgressBar value={cat.earned} max={cat.max} />
  <span>{cat.earned} / {cat.max}</span>
  <Sparkline data={cat.trend} />
  <span className="text-xs">{cat.open_deductions} open deductions</span>
</button>
```

### `<CriteriaTable>`

Sortable table inside Category Detail.

Columns: ID, Name, Status, Points (earned/max), Last Evidence, Auto-tracked, Actions.

Inline filter: at-risk only, deducted only.

Row click → `/compliance/criterion/{id}`.

### `<CriterionDetail>`

Most complex screen in module.

Sections:
- Header (id, name, benchmark vs current, status, points)
- Plain-English explainer (markdown)
- Evidence panel (chips, drill modal)
- Calculation trail (formula + numbers)
- History chart
- Recovery actions (ranked list with Accept/Reject)
- Audit notes (auto-save textarea)

### `<CalculationTrail>`

```
Building floor area: 50,000 m²
2026 YTD electricity: 7.2 GWh
→ 144 kWh/m²/yr
Benchmark: ≤ 180 kWh/m²/yr
Status: Met (20% below benchmark)
```

Renders as a vertical step list with the final result highlighted.

### `<RecoveryActions>`

Ranked list. Each action:

```tsx
<div className="recovery-action">
  <h4>{action.title}</h4>
  <div className="metadata">
    <Chip>+{action.points_recovered} pts</Chip>
    <Chip>{action.effort_hours}h work</Chip>
    {action.cost_qar > 0 && <Chip>{action.cost_qar} QAR</Chip>}
  </div>
  <p>{action.description}</p>
  <div className="actions">
    <Button onClick={onAccept}>Accept</Button>
    <Button variant="ghost" onClick={onSnooze}>Snooze</Button>
    <Button variant="ghost" onClick={onReject}>Reject</Button>
  </div>
</div>
```

Accept → POST → creates linked advisory in main Live View feed → task with deadline.

### `<DeductionsTable>`

Flat table. Filterable. Sortable.

Bulk actions: select rows → "Assign to me", "Snooze all 7d", "Export CSV".

### `<AuditPackagePanel>`

Two states:
1. **Generate**: button → POST kicks off job → progress bar → completion → download link
2. **Past packages**: list with submission status, GORD outcome, downloadable

### `<PreSubmissionChecklist>`

4 mandatory checkboxes:
- [ ] Reviewed every category summary
- [ ] Reviewed all deduction recovery evidence
- [ ] Confirmed survey response rates meet minimums
- [ ] Confirmed all policy documents current-period signed

Submit button greyed until all checked. Submit → external link modal (not API call).

---

## State management

- React Query for all data
- SSE updates cache
- Zustand for: filter state on deductions table, expanded sections on criterion detail, checklist boxes (persisted to localStorage)

---

## Performance budgets

| Operation | Target |
|---|---|
| Dashboard first paint | <1000ms |
| Trajectory chart render | <200ms |
| Category Detail load | <800ms |
| Criterion Detail load | <1000ms |
| Recovery action Accept | <500ms (creates downstream task) |
| Audit package generation | server async (5-10 min); client polls every 5s |

---

## Testing

### Unit

- Score formatting (1-6 star, rounding rules)
- Delta indicator (▲ ▼ →)
- Recovery action accept → creates advisory mock
- Checklist enables submit only when all checked

### Integration

- Dashboard load → all categories rendered
- Criterion detail → accept recovery → linked advisory id returned
- Audit package generate → poll → download
- SSE deduction_new → top deduction risks list updates

### Visual

- All Star ratings (1-6)
- Status chips: Met / At Risk / Failed
- Shadow mode banner
- Standard version drift banner

---

## Accessibility

- Stars rendered as filled/outlined with `aria-label="4 of 6 stars"`
- Trajectory chart `aria-label` describes overall direction
- Deductions table fully keyboard navigable
- Calculation trail uses ordered list semantics

---

## Edge cases

- Criterion locked (period closed): readonly badge, action buttons hidden
- Recovery action requires data not yet available: disabled with reason
- Audit package generation fails: show error + retry
- Pre-submission checklist boxes lost on refresh: persist to localStorage

---

## Integration points

- `live_view/` — recovery actions create advisories that surface there
- `advisory_detail/` — linked back from criterion via "linked advisories" section
- `notifications/` — score drops trigger notifications

---

## Open questions

1. **Trajectory chart implementation**: ECharts (recommended) or Recharts?
2. **Audit package preview**: in-browser PDF render or download-only? P1 stretch in-browser.
3. **Deductions bulk export**: CSV / XLSX? P0 CSV.
4. **Recovery action / advisory bridge**: does Accept create an advisory immediately or queue? Confirm.

## What engineer needs from product

- Final criteria list (or schema)
- Star icon assets (per GORD brand)
- Submission portal URL (GSASgate)
- Standard version metadata

## Changelog

- v1 2026-05-23: initial
