# Equipment Detail — Frontend Engineer Brief

**Feature**: `/equipment/{id}` — live readings + 24h trend with physics prediction overlay + related advisories + maintenance.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is a Next.js console for building operators. This screen renders per-equipment state: a header, live tiles, a multi-series chart with physics-predicted lines overlaid on observed sensor data, related advisories, maintenance history, and gated override actions. Chart rendering is the hardest part — keep it smooth under live point updates.

---

## What you're building

Route: `/equipment/{id}`.

Sections:
1. Header
2. Live readings (grid of tiles)
3. 24h trend chart with predicted overlay
4. Related advisories
5. Maintenance history table
6. Actions bar

---

## Stack

Same as `shell/`. Charts: **ECharts** preferred (handles dense multi-series well). Fallback: Recharts for simpler charts.

---

## File layout

```
app/(authed)/equipment/
  [id]/page.tsx
  loading.tsx

components/equipment-detail/
  EquipmentDetail.tsx
  EquipmentHeader.tsx
  LiveReadings.tsx
  ReadingTile.tsx
  TrendChart.tsx
  TrendChartLegend.tsx
  RelatedAdvisories.tsx
  MaintenanceHistory.tsx
  ActionsBar.tsx
  OverrideModal.tsx

lib/
  api/
    equipment.ts                   — GET /equipment/{id}, /points, /trends, /physics-prediction
  charts/
    echart-theme.ts                — ARVIS dark theme for ECharts
```

---

## Data dependencies

### Initial fetch

```ts
const [equipment, points, trends, prediction, advisories, maintenance] = await Promise.all([
  fetchEquipment(id),
  fetchEquipmentPoints(id),
  fetchEquipmentTrends(id, '24h'),
  fetchPhysicsPrediction(id),
  fetchRelatedAdvisories(id),
  fetchMaintenanceHistory(id),
])
```

### Live updates (SSE)

Subscribe to `point_update` events filtered to this equipment.

Server batches on 100ms window. Client further throttles via `requestAnimationFrame`.

### Chart data merge

```ts
type TrendSeries = {
  point_id: string
  label: string
  unit: string
  observed: { ts: iso8601, value: number }[]
  predicted: { ts: iso8601, value: number }[]  // empty if no physics model
  threshold_pct?: number                        // deviation threshold for shading
}
```

---

## Components

### `<EquipmentDetail>`

Root client component.

### `<EquipmentHeader>`

Pure component. Renders metadata: id, model, capacity, install year, runtime hours, status, MTBF, last service.

### `<LiveReadings>`

Grid layout (CSS grid, auto-fit, min 200px columns).

Renders array of `<ReadingTile>` from current point values.

### `<ReadingTile>`

```tsx
<div className="tile">
  <span className="label">{label}</span>
  <span className="value font-mono text-2xl">{formatValue(value, unit)}</span>
  <TrendArrow direction={trend} />
  <span className="delta">{delta != null ? `${delta > 0 ? '+' : ''}${delta}% vs design` : null}</span>
  <Sparkline data={lastHour} className="h-6 mt-1" />
</div>
```

### `<TrendChart>` — the important one

ECharts setup:

```tsx
const option = useMemo(() => ({
  animation: false,         // disable for live updates
  grid: { top: 20, right: 20, bottom: 40, left: 60 },
  tooltip: { trigger: 'axis' },
  legend: { show: false },  // we use external legend
  xAxis: { type: 'time' },
  yAxis: visibleSeries.map((s, i) => ({
    type: 'value',
    name: s.unit,
    position: i === 0 ? 'left' : 'right',
  })),
  series: visibleSeries.flatMap(s => [
    {
      name: s.label,
      type: 'line',
      data: s.observed.map(d => [d.ts, d.value]),
      lineStyle: { width: 2 },
      smooth: false,
    },
    s.predicted.length > 0 && {
      name: `${s.label} (predicted)`,
      type: 'line',
      data: s.predicted.map(d => [d.ts, d.value]),
      lineStyle: { type: 'dashed', color: 'rgb(168 85 247)' /* purple */ },
      smooth: false,
    },
    s.predicted.length > 0 && {
      name: `${s.label} delta`,
      type: 'line',
      stack: 'shade',
      data: computeDeltaShade(s.observed, s.predicted, s.threshold_pct),
      areaStyle: { color: 'rgba(168, 85, 247, 0.15)' },
      lineStyle: { width: 0 },
      symbol: 'none',
      showInLegend: false,
    },
  ].filter(Boolean)),
}), [visibleSeries])

return <ReactECharts option={option} style={{ height: 320 }} />
```

### Live update path

```ts
useLiveStream(buildingId, {
  onPointUpdate: (batch) => {
    const relevant = batch.filter(p => p.equipment_id === equipmentId)
    if (relevant.length === 0) return
    
    queryClient.setQueryData(['equipment-points', equipmentId], (prev) => 
      mergePointUpdates(prev, relevant)
    )
    
    // Append to chart series too
    queryClient.setQueryData(['trends', equipmentId, '24h'], (prev) => 
      appendToTrends(prev, relevant)
    )
  },
})
```

Throttle chart re-render:

```ts
const throttledSeries = useThrottledMemo(trends, 250)  // re-derive every 250ms max
```

### `<TrendChartLegend>`

Custom legend below chart with checkboxes. Toggles `visibleSeries`.

### `<RelatedAdvisories>`

List, similar to AdvisoryCard but more compact.

### `<MaintenanceHistory>`

Table with sort + expandable row.

### `<ActionsBar>`

Buttons. Override gated by role.

### `<OverrideModal>`

Form: point picker, new value, duration, reason.

POST to `/api/v1/equipment/{id}/override` (TBD — endpoint may not exist yet for P0; gate the feature).

---

## State management

- React Query for all server data
- SSE updates merged into trend + points caches
- Zustand for chart series visibility, modal open

---

## Performance budgets

| Operation | Target |
|---|---|
| First paint | <1500ms cold |
| Chart render with 4 series × 96 points (24h @ 15min) | <100ms |
| Live update batch → chart repaint | <50ms (throttled 250ms max) |
| Series toggle | <100ms |
| Maintenance history table sort | <50ms |

### Chart perf tips

- Disable animations (`animation: false`)
- Throttle live update merges
- Use ECharts `appendData` for incremental updates instead of full re-render
- Virtualize if >1000 points (24h × 1Hz polling). Default 15min interval = 96 points, fine.

---

## Testing

### Unit

- `mergePointUpdates` correctness with out-of-order timestamps
- `computeDeltaShade` shades only where deviation > threshold
- `formatValue` handles all units (°C, kPa, kW, bool)

### Integration

- Live point update → tile value changes within 500ms
- Series toggle persists per-equipment in localStorage
- Override modal opens for facility_manager, disabled for operator

### Visual

- Chart with all series, predicted vs observed clearly distinct
- Chart with no predicted (fallback)
- Equipment stopped / offline / faulted variants

---

## Accessibility

- Chart has fallback `<table>` rendering for screen readers (ECharts supports this via `aria-label`)
- Live regions announce critical point changes
- Tile values: each `aria-label` includes label + value + unit + delta

---

## Edge cases

- Equipment not found: 404 page
- No physics prediction (equipment kind doesn't have model): chart renders observed only, banner "Physics prediction unavailable"
- Stale data: tile + chart timestamps show staleness, refresh button
- Equipment has 100+ points: live tiles cap at 8 most-relevant (defined per equipment kind), full point list in collapsible

---

## Integration points

- `live_view/` — schematic click navigates here
- `advisory_detail/` — equipment chip in advisory links here
- `audit_replay/` — replay mode shows historical state

---

## Open questions

1. **Chart library**: ECharts (recommended for density) or Recharts (simpler API)? P0 ECharts.
2. **Trend window**: 24h default, configurable to 8h / 7d / custom?
3. **Sparkline in tile**: ECharts inline or separate lightweight SVG? Lightweight SVG to avoid chart-instance overhead per tile.
4. **Override endpoint**: not in `_shared/api_contracts.md` — may not exist for P0. Gate feature behind feature flag if so.
5. **Equipment family page** (chiller plant view across CH-1..CH-4): P0 separate per-equipment screens; P2 family view?

## What engineer needs from product

- Equipment kind → default tile point list
- Equipment kind → default chart series
- Physics model coverage matrix
- Override permission matrix

## Changelog

- v1 2026-05-23: initial
