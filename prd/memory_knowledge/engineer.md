# Memory & Knowledge — Frontend Engineer Brief

**Feature**: `/memory` — search + browse memory entries (past incidents, patterns, skillbook, knowledge base).

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS keeps a memory layer of past incidents, recurring patterns, operator skillbook, and reference docs. Backend exposes it via REST. This screen is a search + browse + edit UI over those entries.

---

## What you're building

Route: `/memory`.

Layout: split-pane (results left, detail right) inside a tab-strip filtered list.

Capabilities:
- Full-text search via `q` query param
- Filter by tier, date range, equipment, source
- Detail pane shows full entry
- Mark useful / not useful
- Add new skillbook entry (P1)
- Edit existing skillbook entry (P1)

---

## Stack

Same as `shell/`. Markdown rendering: `react-markdown` + `rehype-sanitize` + `remark-gfm`.

---

## File layout

```
app/(authed)/memory/
  page.tsx                         — RSC, initial fetch
  loading.tsx

components/memory/
  MemoryBrowser.tsx
  SearchBar.tsx
  TierTabs.tsx
  FilterChips.tsx
  ResultsList.tsx
  ResultCard.tsx
  DetailPane.tsx
  LinkedAdvisories.tsx
  FeedbackButtons.tsx
  AddEntryModal.tsx                — P1
  EditEntryModal.tsx               — P1

lib/
  api/
    memory.ts
```

---

## Data dependencies

### Endpoints

```
GET  /api/v1/memory/search?q=&tier=&date_from=&date_to=&equipment=&limit=50&cursor=
     → { results: MemoryEntry[], next_cursor: string | null, total: number }

GET  /api/v1/memory/{id}
     → MemoryEntry (full body + linked advisories)

POST /api/v1/memory/feedback
     → { entry_id, useful: boolean, reason?: string }

POST /api/v1/memory                                  — P1 add
POST /api/v1/memory/{id}                             — P1 edit
```

### Cache keys

```
['memory-search', { q, tier, date_from, date_to, equipment }]
['memory-entry', id]
```

### URL state

Search query + filters bound to URL params for shareability:
```
/memory?q=refrigerant+migration&tier=incidents&date_from=2026-01-01
```

Use Next.js `useSearchParams` + `useRouter` to sync state.

---

## Components

### `<MemoryBrowser>`

Root client component. Renders search bar + tier tabs + filter chips + results + detail.

Manages selected entry id (local state, also URL param `id`).

### `<SearchBar>`

Debounced input (300ms) → updates URL → triggers new query.

Recent searches stored in localStorage (last 10).

### `<TierTabs>`

Tab strip. Each tab shows count from `total` per-tier (separate counts query, or returned in search response).

### `<FilterChips>`

Date range picker, equipment filter (uses `/buildings/{id}/topology` for equipment list).

### `<ResultsList>`

Virtualized list (`@tanstack/react-virtual`) if results > 50.

Sort selector: relevance (default) / date desc.

### `<ResultCard>`

Compact card. Click → updates selected entry id, scrolls into view.

```tsx
<button
  onClick={() => onSelect(entry.id)}
  className={cn("card", selected && "card-selected")}
>
  <div className="flex justify-between">
    <CategoryIcon tier={entry.tier} />
    <RelevanceChip value={entry.relevance} />
  </div>
  <h3 className="font-medium">{entry.title}</h3>
  <p className="text-sm text-muted line-clamp-2">{entry.snippet}</p>
  <div className="meta">{entry.date} · {entry.equipment ?? '—'}</div>
</button>
```

### `<DetailPane>`

Fetches full entry on selection change.

```tsx
const { data: entry } = useQuery({
  queryKey: ['memory-entry', selectedId],
  queryFn: () => fetchMemoryEntry(selectedId),
  enabled: !!selectedId,
})
```

Renders:
- Header (title, tier, date)
- Markdown body
- Tags (chips)
- Linked advisories list
- Author + updated
- Feedback buttons
- Tier-specific extras:
  - Pattern: occurrence chart
  - Skillbook: edit button if permitted

### `<FeedbackButtons>`

Two buttons: 👍 Useful / 👎 Not useful.

On click: POST `/api/v1/memory/feedback`. Optimistic UI: button highlights + thanks message.

Allow optional reason text (modal on Not useful).

### `<AddEntryModal>` / `<EditEntryModal>` (P1)

Form: title, body (markdown), tags (chip input), equipment scope (dropdown).

Markdown preview side-by-side or toggle.

---

## State management

- React Query for data
- URL params as source of truth for search state
- Zustand for: selected entry id (synced to URL too), modal open

---

## Performance budgets

| Operation | Target |
|---|---|
| Initial load | <800ms warm |
| Search submit → results | <500ms p95 |
| Tier tab switch | <200ms (cached) |
| Result click → detail | <300ms |
| Markdown render | <100ms |

For long markdown bodies: streaming render (P2) or lazy below-fold.

---

## Testing

### Unit

- Debounce works (search not firing on every keystroke)
- URL sync: change tab → URL updates; navigate to URL → tab restores
- Feedback optimistic UI

### Integration

- Search "refrigerant" → results appear
- Click result → detail loads
- Mark Not useful → feedback persisted

### Visual

- Empty / no results / loading states
- Detail pane for each tier type

---

## Accessibility

- Search input: `aria-label="Search memory"`
- Tab strip: keyboard navigable (arrow keys, home/end)
- Results: each card `role="article"`, button semantics for click
- Detail pane: `aria-live="polite"` on content change
- Markdown: ensure sanitized output (rehype-sanitize)

---

## Edge cases

- Empty search: list shows "Browse by category" suggestions instead of empty
- 0 results: helpful suggestions
- Result selected but deleted server-side: "This entry was removed" empty state in detail
- Markdown with embedded HTML: sanitize, never raw
- Concurrent edit (P1): show "Updated 5s ago by Layla" warning before save

---

## Integration points

- `advisory_detail/` — memory evidence chips link here with `?id=<entry_id>`
- `audit_replay/` — past incident memory entries link to original advisory
- `equipment_detail/` — equipment filter pre-populated when navigated from equipment

---

## Open questions

1. **Search backend**: keyword vs vector? `/memory/search` already exists — confirm shape.
2. **Markdown component customizations**: code block language hints? GFM tables?
3. **Add entry P0 or P1**: defer to P1, keep P0 read-only.
4. **Permissions on edit**: author + facility_manager? Engineer only? Per-tier?

## What engineer needs from product

- Search response shape (relevance % calibration source)
- Tier icon set (4 custom icons)
- Tag taxonomy decision

## Changelog

- v1 2026-05-23: initial
