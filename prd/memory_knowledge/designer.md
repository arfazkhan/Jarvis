# Memory & Knowledge — Product Designer Brief

**Feature**: Searchable archive of past incidents, recurring building patterns, operator skillbook, and reference docs.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. When an advisory is generated, ARVIS draws on a memory layer to recall past incidents ("we saw this in March, here's what worked"). The memory layer has multiple tiers:
- **Past Incidents** — resolved advisories with operator outcomes
- **Building Patterns** — recurring rhythms (e.g., afternoon thermal lag on south face)
- **Operator Skillbook** — procedures, tribal knowledge, vendor contacts
- **Knowledge Base** — equipment manuals, standards, GSAS criteria

Operators access this directly to look up "what did we do last time?"

---

## Why this exists

Two needs:
1. **Engineers debugging an ARVIS recommendation** want to see what memory was recalled and verify it was appropriate
2. **Operators on a tricky alarm** want to search "has this happened before?" without waiting for ARVIS to recall it for them

Memory is also where ARVIS's institutional knowledge accumulates across years.

---

## Users

- **Operator** — search past incidents, look up procedures
- **Engineer / facility manager** — audit memory recall quality
- **Vendor** — pilot read-only access to vendor-specific patterns (P2)

---

## Scope

**In**:
- Full-text + tag search across all 4 memory categories
- Result list with snippets
- Detail panel for each result
- Filter by category, date, equipment, source
- Add manual entry (operator skillbook only)
- Mark useful / not useful (feedback signal)

**Out**:
- Memory training UI (engine internal)
- Direct embedding manipulation
- Cross-building memory share (P3)

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Search bar                                                          │
│ [🔍 "refrigerant migration"                          ] [Search]    │
├─────────────────────────────────────────────────────────────────────┤
│ Filters (tab strip)                                                 │
│ [ All ] [ Past Incidents ] [ Building Patterns ]                    │
│ [ Operator Skillbook ] [ Knowledge Base ]                           │
├─────────────────────────────────────────────────────────────────────┤
│ Results                                       │ Detail              │
│ ┌─────────────────────────────────────────┐  │ ┌─────────────────┐  │
│ │ 🩺 Past Incident · 2026-03-04           │  │ │ Selected item   │  │
│ │ CH-4 refrigerant migration              │  │ │                 │  │
│ │ Resolved by 8lb R134a top-up by ACME    │  │ │ Full body here  │  │
│ │ Relevance: 92%                          │  │ │                 │  │
│ └─────────────────────────────────────────┘  │ │ Linked          │  │
│ ┌─────────────────────────────────────────┐  │ │ advisories: 3   │  │
│ │ 🔁 Building Pattern                     │  │ │                 │  │
│ │ Afternoon south-face thermal lag        │  │ │ [Useful?]       │  │
│ │ Repeated 14× this year                  │  │ │ [Not useful?]   │  │
│ │ Relevance: 78%                          │  │ │                 │  │
│ └─────────────────────────────────────────┘  │ │ Tags: chiller,  │  │
│ ┌─────────────────────────────────────────┐  │ │ refrigerant     │  │
│ │ 📖 Skillbook                            │  │ └─────────────────┘  │
│ │ R134a top-up procedure (ACME)           │  │                      │
│ │ Author: Layla · Updated 2025-09-12      │  │                      │
│ │ Relevance: 65%                          │  │                      │
│ └─────────────────────────────────────────┘  │                      │
└──────────────────────────────────────────────┴──────────────────────┘
```

---

## Component details

### Search bar

- Full-text input
- Submit on enter or button
- Recent searches dropdown
- Saved searches (P1)

### Filter tab strip

- All / Past Incidents / Building Patterns / Operator Skillbook / Knowledge Base
- Counts shown per tab ("Past Incidents (47)")
- Filter chips below tabs for: date range, equipment, source author

### Results list

- Each card: category icon, title, snippet, relevance %, metadata (date, equipment, linked advisory count)
- Sort: relevance desc default; date desc as toggle
- Click card → fills Detail panel

### Detail panel (right)

- Title + category
- Full body (markdown rendered)
- Tags (clickable to filter)
- Linked advisories list (clickable)
- Author + last updated
- **Useful / Not useful** feedback buttons → improves recall ranking
- For Past Incidents: link to original advisory in Audit & Replay
- For Patterns: time-series chart showing pattern occurrence
- For Skillbook: edit button (if author or facility_manager)
- For Knowledge Base: download / view source link

### Add entry (P1)

- Only for Operator Skillbook
- Form: title, body (markdown), tags, equipment scope
- Save → indexed for future recall

---

## States

- **Empty search**: show "Browse by category" with curated highlights
- **No results**: "No results. Try broader terms or check filters." With clear filter button
- **Loading**: skeleton with shape hints
- **Item with no linked advisories**: section hidden
- **Useful feedback submitted**: green check + "Thanks — this improves future recall"
- **Item locked (vendor entry, P2)**: read-only badge

---

## Flows

### Flow A — Operator looks up past incident

1. Alarm fires on CH-4
2. Operator opens Memory & Knowledge from nav
3. Searches "CH-4 refrigerant"
4. Top result: past incident from March 2026
5. Reads resolution, follows linked advisory
6. Closes Memory, executes same fix

Time: <2 min.

### Flow B — Engineer audits ARVIS memory recall

1. Engineer notes ARVIS recalled "afternoon thermal lag" for an unrelated alarm
2. Opens Memory & Knowledge
3. Filters Building Patterns
4. Finds entry, reviews body + linked advisories
5. Marks "Not useful" with reason
6. ARVIS down-weights this pattern's recall for similar queries

### Flow C — Operator adds skillbook entry

1. Operator just resolved a tricky one
2. Opens Memory, clicks "Add to Skillbook"
3. Writes procedure
4. Tags: CH-4, refrigerant, ACME
5. Saves
6. Future similar alarm: ARVIS may recall this entry

---

## Design principles

1. **Search is the primary affordance**. Browse secondary.
2. **Category icons must be distinguishable** — at a glance know "this is an incident vs a pattern vs a procedure"
3. **Relevance % is exposed** — operators learn to calibrate trust
4. **Useful/Not useful is one click**. Lower friction = more signal.
5. **Detail panel beside list, not modal**. Allows multi-result comparison without navigation churn.
6. **Markdown bodies render with code blocks**. Operators paste BMS commands.

---

## Edge cases

- 0 search results: helpful suggestions
- 500+ results: paginate, default first 50
- Entry deleted while in detail panel: "This entry was removed"
- Cross-building memory access attempt: filtered out at backend (403 if direct URL)
- Skillbook entry by ex-employee: keep, mark "Author no longer at building"

---

## Open questions

1. **Category icons**: which icon set conveys "incident vs pattern vs procedure vs reference"? Custom needed.
2. **Search syntax**: support advanced (tag:chiller, date:>2026-01)? P1 stretch.
3. **Tag taxonomy**: free-form or controlled? P0 free-form; P1 suggest from existing.
4. **Pattern visualization**: line chart of occurrence count over time, or timeline? P0 line chart.
5. **Add entry permissions**: operator can add skillbook, facility_manager can edit any, engineer can mark vendor entries?

---

## Success criteria

- Operator finds relevant past incident in <2 min
- Memory entries get useful/not-useful feedback on ≥30% of opens
- Engineer audits memory recall fast enough to file fixes weekly

## What designer needs from engineering

- Memory entry shape (already in `_shared/data_model.md`)
- Tag list extracted from existing memory
- Relevance score calibration (what's a "good" 80% vs 60%?)

## Changelog

- v1 2026-05-23: initial
