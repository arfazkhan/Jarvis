# Exec KPI Roll-up — Frontend Engineer Brief

**Feature**: `/exec` — owner / executive dashboard with KPIs, trends, GSAS, top wins/concerns, PDF export.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces operational data. This screen rolls it into an executive view. Read-only. Designed for low-frequency, high-context use. Must export cleanly to PDF.

---

## What you're building

Route: `/exec`.

Sections:
- Header (building name + period selector)
- Hero KPI strip (5 tiles)
- Energy trend chart
- GSAS trajectory chart
- Top Wins list
- Top Concerns list
- Export PDF button

---

## Stack

Same as `shell/`. PDF export: server-side (preferred) via `GET /exec/{building_id}/export.pdf` — backend renders with headless browser.

Alternative client-side: `@react-pdf/renderer` (heavy, but possible).

---

## File layout

```
app/(authed)/exec/
  page.tsx
  loading.tsx

components/exec/
  ExecKPI.tsx
  PeriodSelector.tsx
  HeroKPIStrip.tsx
  KPITile.tsx
  EnergyTrendChart.tsx
  GSASTrajectoryChart.tsx
  TopWinsList.tsx
  TopConcernsList.tsx
  ExportButton.tsx

lib/
  api/
    exec.ts
```

---

## Data dependencies

### Endpoints

```
GET  /api/v1/exec/{building_id}?period=Q2-2026
     → ExecRollup

GET  /api/v1/exec/{building_id}/export.pdf?period=Q2-2026
     → application/pdf
```

`ExecRollup` shape:
```ts
type ExecRollup = {
  building_id: string
  period: { id: string, label: string, start: iso8601, end: iso8601 }
  hero_kpis: {
    money_saved: { value: number, currency: 'QAR' | 'USD', delta_yoy_pct: number | null, sparkline: number[] }
    kwh_avoided: { value: number, delta_yoy_pct: number | null, sparkline: number[] }
    gsas: { points: number, star: number, projected_star: number, delta_yoy_stars: number | null }
    mtbf_hours: { value: number, delta_yoy_pct: number | null }
    approval_rate: { value: number, delta_yoy_pct: number | null }
  }
  energy_trend: { months: { ts: string, actual: number, baseline: number }[] }
  gsas_trajectory: { years: { year: number, points: number, star: number, projected?: boolean }[] }
  top_wins: ExecWin[]
  top_concerns: ExecConcern[]
}
```

### Cache keys

```
['exec', buildingId, periodId]
```

Stale time: 1 hour (this is low-freq data).

---

## Components

### `<PeriodSelector>`

Dropdown: Q1/Q2/Q3/Q4/Full year for last 3 years.

URL param: `?period=Q2-2026`.

### `<HeroKPIStrip>`

5-column grid (responsive: 5 → 3 → 1).

```tsx
<HeroKPIStrip>
  <KPITile label="$ Saved" value={fmt(kpis.money_saved.value, 'currency')} delta={kpis.money_saved.delta_yoy_pct} sparkline={kpis.money_saved.sparkline} />
  <KPITile label="kWh Avoided" value={fmt(kpis.kwh_avoided.value, 'kwh')} delta={kpis.kwh_avoided.delta_yoy_pct} sparkline={kpis.kwh_avoided.sparkline} />
  <KPITile label="GSAS Score" value={`${kpis.gsas.star}★`} subValue={`${kpis.gsas.points} pts`} delta={kpis.gsas.delta_yoy_stars} sparkline={null} />
  <KPITile label="MTBF" value={fmt(kpis.mtbf_hours.value, 'hours')} delta={kpis.mtbf_hours.delta_yoy_pct} />
  <KPITile label="Approval Rate" value={`${kpis.approval_rate.value}%`} delta={kpis.approval_rate.delta_yoy_pct} />
</HeroKPIStrip>
```

### `<KPITile>`

```tsx
<div className="kpi-tile">
  <span className="label">{label}</span>
  <div className="value font-mono text-3xl">{value}</div>
  {subValue && <span className="sub">{subValue}</span>}
  <DeltaIndicator delta={delta} />
  {sparkline && <Sparkline data={sparkline} />}
</div>
```

### `<EnergyTrendChart>`

ECharts line + area.

X: months (12). Y: kWh.

Series:
- Baseline (dashed)
- Actual (solid)
- Savings (filled area below baseline where actual < baseline)

Annotations: events from rollup (heatwave, outage).

### `<GSASTrajectoryChart>`

ECharts bar + line.

X: years. Y: points.

Bars colored by star rating achieved. Forward year as lighter shade (projected).

### `<TopWinsList>` / `<TopConcernsList>`

Each item: short description + impact value + linked advisory id.

```tsx
{wins.map(w => (
  <li key={w.id}>
    <p>{w.description}</p>
    <span className="impact">{w.impact_value} {w.impact_unit}</span>
    {w.linked_advisory_id && (
      <Link href={`/audit?advisory_id=${w.linked_advisory_id}`}>View</Link>
    )}
  </li>
))}
```

P1: editable list with manager curation (drag-reorder, edit text).

### `<ExportButton>`

```tsx
<Button onClick={async () => {
  setExporting(true)
  const res = await fetch(`/api/v1/exec/${buildingId}/export.pdf?period=${period}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  triggerDownload(url, `arvis-exec-${buildingId}-${period}.pdf`)
  setExporting(false)
}}>
  Export PDF
</Button>
```

Server-side PDF preferred. If server-side unavailable, fallback to printable view + browser print.

---

## State management

- React Query for rollup data
- URL param drives period
- Zustand for: export in progress

---

## Print stylesheet

If browser-print fallback used:

```css
@media print {
  .shell, .sidenav, .topbar { display: none; }
  .exec-kpi { padding: 1in; }
  .chart { page-break-inside: avoid; }
  @page { size: letter; margin: 0.5in; }
}
```

---

## Performance budgets

| Operation | Target |
|---|---|
| Initial load | <1500ms |
| Period change | <500ms (cached) |
| Chart render | <300ms |
| PDF export | <10s (server-side) |

---

## Testing

### Unit

- Number formatting (currency, kWh, hours)
- Delta indicator sign + color
- Period selector URL sync

### Integration

- Load → all sections render
- Period change → data refreshes
- Export → PDF downloaded (or browser print dialog)

### Visual

- Default Q2 2026 view
- Negative delta variant
- Insufficient data state
- Print preview

---

## Accessibility

- Tile values use mono font for screen reader number consistency
- Charts have `aria-label` summary
- Period selector keyboard navigable
- Export button announces progress

---

## Edge cases

- New building, <12 months: hide YoY, show MoM with caveat banner
- GSAS not yet audited: show ARVIS-estimated with prominent caveat
- Multi-building portfolio (P3): roll-up across selected buildings
- PDF gen fails: show error toast + fallback to browser print

---

## Integration points

- `compliance_gsas/` — GSAS data sourced from there
- `audit_replay/` — Top Wins link to original advisories
- `shell/` — Exec KPI is a top-level nav item for facility_manager + exec roles

---

## Open questions

1. **Currency** — QAR for Doha, USD for sales demo? Configurable per-building.
2. **PDF server-side** — confirm endpoint exists for P0.
3. **Top Wins/Concerns curation** — P0 algorithmic, P1 editable?
4. **Carbon KPI** — P0 or P1?

## Changelog

- v1 2026-05-23: initial
