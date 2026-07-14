# Audit & Replay — Frontend Engineer Brief

**Feature**: `/audit` — list past advisories, replay any one of them in read-only "frozen at timestamp" mode.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces Advisories backed by an investigation plan + evidence + agent votes + verifier outcomes — all persisted. Backend exposes a `/audit/replay/{plan_id}` endpoint that returns the event stream that produced the advisory. This screen lets engineers debug past advisories without rerunning the engine.

---

## What you're building

Route: `/audit`.

Layout: split-pane.
- Left: filtered list of past advisories
- Right: replay pane — embeds `<AdvisoryDetail>` in replay mode

Plus URL deep-linking: `/audit?advisory_id=...` loads the specified advisory.

---

## Stack

Same as `shell/`. Reuse `<AdvisoryDetail>` from `advisory_detail/`.

---

## File layout

```
app/(authed)/audit/
  page.tsx                         — RSC, initial advisory list
  loading.tsx

components/audit-replay/
  AuditBrowser.tsx
  FilterPanel.tsx
  DateRangePicker.tsx
  PastAdvisoryList.tsx
  PastAdvisoryCard.tsx
  ReplayPane.tsx
  ReplayBanner.tsx
  PlaybackControls.tsx             — P1

lib/
  api/
    audit.ts
```

---

## Data dependencies

### Endpoints

```
GET  /api/v1/advisories?since=&until=&risk_tier=&equipment=&status=&verifier_failed=&building=
     → { results: AdvisorySummary[], next_cursor: string | null }

GET  /api/v1/advisories/{id}?replay=true
     → Advisory (full, with replay mode metadata)

GET  /api/v1/audit/replay/{plan_id}
     → { events: ReplayEvent[] }   // for P1 scrub
```

### Cache keys

```
['audit-list', { since, until, risk_tier, equipment, status, verifier_failed }]
['advisory-replay', advisoryId]
['replay-events', planId]
```

---

## Components

### `<AuditBrowser>`

Root client component. Manages URL state for filters + selected advisory id.

URL params:
- `since`, `until` — date range (ISO date strings)
- `risk_tier` — comma-separated
- `equipment` — equipment id
- `status` — outcome
- `verifier_failed` — boolean
- `advisory_id` — selected

### `<FilterPanel>`

Top bar with date range picker + filter chips + reset.

```tsx
<div className="filter-panel">
  <DateRangePicker value={range} onChange={setRange} />
  <FilterChip label="Risk Tier" options={['T1','T2','T3']} value={filters.risk_tier} />
  <FilterChip label="Equipment" options={equipmentList} value={filters.equipment} />
  <FilterChip label="Status" options={['approved','rejected','snoozed','auto_withdrawn']} value={filters.status} />
  <Toggle label="Verifier failed only" checked={filters.verifier_failed} />
  <Button variant="ghost" onClick={resetFilters}>Reset</Button>
</div>
```

### `<PastAdvisoryList>`

Virtualized list (`@tanstack/react-virtual`) if >50 results.

Pagination: infinite scroll with cursor.

### `<PastAdvisoryCard>`

Compact card:

```tsx
<button onClick={() => onSelect(adv.id)} className={cn("card", selected && "card-selected")}>
  <div className="flex justify-between">
    <span className="font-mono text-xs">{formatDate(adv.created_at)}</span>
    <RiskTierChip tier={adv.risk_tier} />
  </div>
  <p className="font-medium line-clamp-1">{adv.summary}</p>
  <div className="flex justify-between mt-1">
    <EquipmentChip ids={adv.equipment_ids} />
    <OutcomeChip status={adv.status} />
  </div>
  <VerifierGateStrip gates={adv.verifier_gates_summary} />
</button>
```

### `<ReplayPane>`

Renders `<ReplayBanner>` above embedded `<AdvisoryDetail>` in replay mode.

```tsx
<div className="replay-pane">
  <ReplayBanner frozenAt={advisory.created_at} />
  <AdvisoryDetail advisory={advisory} mode="replay" me={me} />
  <div className="cross-links">
    <Link href={`/advisories/${advisory.id}`}>Open current state</Link>
    <Link href={`/equipment/${advisory.equipment_ids[0]}`}>Open equipment</Link>
  </div>
</div>
```

### `<ReplayBanner>`

```tsx
<div className="replay-banner bg-purple-500/20 text-purple-300 border-purple-500 px-4 py-2">
  🕰 Replay — frozen at {formatTimestamp(frozenAt)} UTC
</div>
```

### `<PlaybackControls>` (P1)

Scrub bar across the investigation window. Step buttons. Plays trace events in order.

Reads from `GET /audit/replay/{plan_id}`.

```ts
type ReplayEvent = {
  t_offset_ms: number
  event_type: 'plan_created' | 'evidence_appended' | 'agent_vote' | 'verifier_h4_pass' | ...
  payload: object
}
```

Renders progressive UI:
- t=0: empty advisory shell
- t=142ms: first evidence chip appears
- t=1820ms: first agent vote appears
- ...

---

## Reusing `<AdvisoryDetail>` in replay mode

`<AdvisoryDetail>` accepts a `mode` prop:
- `mode="live"` (default) — SSE subscription active, action bar enabled
- `mode="replay"` — no SSE, action bar disabled

In replay mode:
- `<ActionBar>` renders disabled with tooltip "Replay mode — actions unavailable"
- No SSE subscription mounted
- Evidence drill modals show historical state (already what they always show — evidence is immutable)

---

## State management

- URL params drive filter + selection state
- React Query for advisory list + selected advisory
- Zustand for: filter panel collapse state

---

## Performance budgets

| Operation | Target |
|---|---|
| Initial list load (50 results) | <800ms |
| Filter change → list reload | <500ms |
| Card click → replay pane load | <500ms |
| Replay pane render | <800ms |
| Infinite scroll page load | <400ms |

---

## Testing

### Unit

- URL sync: filters → URL → restore on reload
- Empty state shown when 0 results
- Pagination cursor handling

### Integration

- Date range change → list updates
- Click card → replay banner appears + AdvisoryDetail renders
- "Open current state" link navigates correctly
- Verifier-failed filter shows only those advisories

### Visual

- Filter chips in default + active states
- Past advisory cards with all outcome types
- Replay banner

---

## Accessibility

- Date range picker keyboard navigable
- Past advisory cards: `role="button"`, full ARIA labels
- Replay banner: `role="status"`, `aria-live="polite"`

---

## Edge cases

- Advisory archived past retention: card shows "Replay unavailable, summary only"
- Selected advisory deleted between sessions: clear `advisory_id` param, show "Selected advisory no longer available"
- 0 results: helpful empty state with "Reset filters" button
- Stress test: 10,000 past advisories — pagination must not lag

---

## Integration points

- `advisory_detail/` — embedded in replay mode
- `equipment_detail/` — cross-link from replay pane
- `live_view/` — "open current state" navigates back

---

## Open questions

1. **Playback / scrub** P0 vs P1? Recommendation: P1 — static replay first.
2. **Annotations on past advisory** (engineer notes)? P1.
3. **Data retention** — how far back can we replay? Affects empty state copy.
4. **Cross-building audit** for engineer role: should engineer see across buildings? Likely yes.

## What engineer needs from product

- Sample dataset of 50+ past advisories with varied outcomes
- Retention policy
- Engineer cross-building access rule

## Changelog

- v1 2026-05-23: initial
