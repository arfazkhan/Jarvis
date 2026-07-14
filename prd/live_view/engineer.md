# Live View — Frontend Engineer Brief

**Feature**: Home screen — building schematic, alarms strip, advisories feed, KPI strip.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is a Next.js operator console for commercial building advisories. Backend exposes REST + SSE. Live View is the highest-traffic screen — must render fast and stay live. Advisories are the central artifact. SSE streams updates: new alarms, new advisories, point updates.

---

## What you're building

A page at `/live-view` with four zones:
- Active alarms strip (top)
- Building schematic (canvas, 60% width)
- Open advisories feed (right column, 360px)
- KPI strip (bottom)

All four zones live-update via SSE. Page must render fast (<500ms warm) and remain interactive even when SSE is bursting events.

---

## Stack assumptions

Same as `shell/engineer.md`: Next.js 14 App Router, TypeScript, Tailwind, shadcn/ui, React Query, Zustand. SVG for schematic (P0). Consider react-flow for interactive equipment graph (P1 if topology is graph-shaped).

---

## File layout

```
app/(authed)/live-view/
  page.tsx                         — RSC, prefetches data, passes to client
  loading.tsx                      — skeleton

components/live-view/
  LiveView.tsx                     — top-level client component
  AlarmsStrip.tsx
  AlarmCard.tsx
  BuildingSchematic.tsx
  SchematicEquipment.tsx
  EquipmentTooltip.tsx
  AdvisoryFeed.tsx
  AdvisoryCard.tsx
  KPIStrip.tsx
  KPITile.tsx

lib/
  api/
    alarms.ts
    advisories.ts
    topology.ts
    kpis.ts
  stream/
    useLiveStream.ts               — wraps SSE for this page
  schematic/
    layout.ts                      — building.yaml → SVG positions
    icons.tsx                      — custom equipment SVGs
```

---

## Data dependencies

### Initial load (RSC)

Parallel fetches in `page.tsx`:

```ts
const [topology, alarms, advisories, kpis] = await Promise.all([
  fetchTopology(buildingId),
  fetchActiveAlarms(buildingId),
  fetchOpenAdvisories(buildingId),
  fetchKPISnapshot(buildingId),
])
```

Pass as props to `<LiveView>`.

### Endpoints

- `GET /api/v1/buildings/{id}/topology` → equipment + edges
- `GET /api/v1/alarms?building={id}&active=true` → active alarms
- `GET /api/v1/advisories?building={id}&status=pending&limit=50` → open advisories
- `GET /api/v1/buildings/{id}/kpis` → KPI snapshot (custom endpoint, P0 simple)

### Live updates (SSE)

Topics: `alarms`, `advisories`, `points`, `kpis` (TBD or computed client-side from points)

```ts
useLiveStream(buildingId, {
  onAlarmNew: (alarm) => queryClient.setQueryData(['alarms', buildingId], addAlarm(alarm)),
  onAlarmCleared: (id) => queryClient.setQueryData(['alarms', buildingId], removeAlarm(id)),
  onAdvisoryPublished: (adv) => queryClient.setQueryData(['advisories', buildingId], addAdvisory(adv)),
  onAdvisoryStateChange: (adv) => queryClient.setQueryData(['advisories', buildingId], updateAdvisory(adv)),
  onPointUpdate: (batch) => updateSchematicPoints(batch),
  onKpiUpdate: (kpis) => queryClient.setQueryData(['kpis', buildingId], kpis),
})
```

Point updates are heavy (potentially many per second). Server batches them on 100ms window, max 20/frame. Client further throttles paint via `requestAnimationFrame`.

---

## Components

### `<LiveView>`

Client component. Root layout grid (CSS Grid).

```css
grid-template-rows: 80px 1fr 60px;
grid-template-columns: 1fr 360px;
grid-template-areas:
  "alarms alarms"
  "schematic advisories"
  "kpis kpis";
```

Owns `useLiveStream` subscription.

### `<AlarmsStrip>`

Horizontal scroll. Renders array of `<AlarmCard>`.

Virtualization: not needed for <30 alarms; if >30, switch to virtualized list.

Sort: severity (critical → warning → info), then `raised_at` desc.

### `<AlarmCard>`

Compact card (160×64). Severity color border. Time-since chip (uses `date-fns/formatDistance`).

Click → opens modal with full alarm + linked advisory link.

### `<BuildingSchematic>`

SVG canvas. Renders equipment from topology.

```tsx
<svg viewBox="0 0 1200 800" className="w-full h-full">
  {topology.equipment.map(eq => (
    <SchematicEquipment
      key={eq.id}
      equipment={eq}
      x={schematicLayout[eq.id].x}
      y={schematicLayout[eq.id].y}
      status={equipmentStatus[eq.id]}
      onHover={setHoveredId}
      onClick={() => router.push(`/equipment/${eq.id}`)}
    />
  ))}
  {topology.edges.map(edge => <SchematicEdge key={edge.id} {...edge} />)}
</svg>
```

`schematicLayout` is a deterministic position map computed from building.yaml. For P0 Marina Heights, can be hand-tuned in a static file. P2: auto-layout via dagre or elkjs.

`equipmentStatus` derived from current point values + alarms. Use a `useMemo` to recompute when either changes.

### `<EquipmentTooltip>`

Renders on hover. Shows equipment id, status, key live values (2-3 most relevant points).

Position: follows mouse, 12px offset, clamped to viewport.

### `<AdvisoryFeed>`

Vertical list. Virtualized if >50 cards (use `@tanstack/react-virtual`).

Sort: by `created_at` desc by default. Toggle for risk-tier-desc.

### `<AdvisoryCard>`

```tsx
<div className="card">
  <div className="flex justify-between">
    <RiskTierChip tier={advisory.risk_tier} />
    <TimeSinceChip ts={advisory.created_at} />
  </div>
  {advisory.shadow && <ShadowBadge />}
  <p className="text-base mt-2">{advisory.summary}</p>
  <EquipmentChip id={advisory.equipment_ids[0]} />
  <div className="flex gap-2 mt-3">
    <ApproveButton advisoryId={advisory.id} />
    <RejectButton advisoryId={advisory.id} />
    <ViewButton advisoryId={advisory.id} />
  </div>
</div>
```

Approve / Reject / View handlers — see `operator_actions/engineer.md`.

### `<KPIStrip>` + `<KPITile>`

4 tiles. Each tile:
- Label (top)
- Big value (mono, center)
- Sparkline (bottom)
- Delta indicator

Sparkline: lightweight SVG line, no library needed. Or recharts `<Sparkline>`.

---

## State management

- React Query for server state
- `useLiveStream` mutates query cache on SSE events
- Zustand for UI-only: alarm modal open, schematic view mode (iconographic vs P&ID)

### Cache keys

```
['topology', buildingId]
['alarms', buildingId]            
['advisories', buildingId, 'pending']
['kpis', buildingId]
['equipment-points', equipmentId] — used by tooltip on hover
```

Stale times:
- topology: 1 hour (rarely changes)
- alarms: kept fresh by SSE; staleTime: 30s as backup
- advisories: same pattern
- kpis: SSE-driven; staleTime: 30s

---

## Performance budgets

| Operation | Target |
|---|---|
| First paint (warm) | <500ms |
| TTI (warm) | <1000ms |
| New advisory SSE → card painted | <300ms |
| New alarm SSE → strip updated | <200ms |
| Point update batch → schematic re-render | <100ms |
| Schematic with 100 equipment | <16ms per frame |

### Schematic perf

- Use `React.memo` per equipment
- Avoid re-rendering all equipment on any point update
- Subscribe equipment-by-equipment via selector pattern:

```ts
const eqStatus = usePointStore((s) => s.equipmentStatus[eqId])
```

- For 100+ equipment, consider canvas rendering (P2) instead of SVG

---

## Testing

### Unit (vitest)

- Sort order in `<AlarmsStrip>` correct
- `<AdvisoryCard>` renders shadow badge in shadow mode
- `<KPITile>` formats delta correctly (+ / − / →)

### Integration (Playwright)

- Click equipment in schematic → routes to `/equipment/{id}`
- Approve advisory from card → toast appears, card disappears
- New advisory SSE → card appears in feed within 500ms
- Disconnect SSE → reconnect → state restored

### Visual

- Schematic in 3 building states (all green / one critical / all gray-offline)
- Advisory feed empty + populated states
- KPI strip with delta arrows in all directions

---

## Accessibility

- Schematic equipment: each has `role="button"`, `aria-label="Chiller 1, status: running"`
- Alarm cards: `role="article"`, severity in label
- Advisory cards: `role="article"`, action buttons properly labeled
- Live region for new advisory announcements: "New T2 advisory: AHU-7 cascade"
- Tab order: alarms → schematic equipment (left-right, top-bottom) → advisory feed → KPI strip

---

## Edge cases

- Topology fails to load: render alarm strip + advisory feed + KPI strip, show "Building schematic unavailable" placeholder
- SSE permanently disconnected: switch to 10s polling for alarms + advisories; mark "Live updates paused"
- Building has 200 equipment: schematic scrolls or zooms (pan/zoom controls)
- Mobile / phone: schematic hidden, alarms + advisories stacked vertically, KPI horizontal

---

## Integration points

- `shell/` — bell count incremented when new advisory arrives even if user is elsewhere
- `advisory_detail/` — View button navigates here
- `equipment_detail/` — schematic equipment click navigates here
- `operator_actions/` — Approve/Reject buttons call into this feature

---

## Open questions

1. **Schematic source of truth**: building.yaml static layout vs auto-layout from topology? P0: static hand-tuned.
2. **Sparkline data source**: separate KPI endpoint or computed client-side from point history?
3. **Schematic interaction model**: pan/zoom needed for P0 or P1?
4. **Point update aggregation**: client-side throttle window — 100ms or 250ms?

## What engineer needs from product

- Marina Heights equipment layout (positions for schematic)
- KPI definitions: exactly which 4 + their formulas
- Schematic icon set (custom SVGs — designer ships)

## Changelog

- v1 2026-05-23: initial
