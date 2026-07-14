# Audit & Replay — Product Designer Brief

**Feature**: Pick any past advisory, walk through it as if it just happened.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS generates Advisories (AI recommendations) for building operators. Every advisory has an investigation plan, evidence ledger, agent votes, and verifier gate outcomes — all stored. Audit & Replay lets engineers and managers reconstruct any past advisory exactly as it shipped, to debug or verify.

---

## Why this exists

When an operator says "ARVIS got this wrong yesterday," engineers need to:
- Find that specific advisory
- See exactly what data ARVIS had at the time
- See the agent votes and verifier outcomes as of then
- Form a hypothesis about why it went wrong

Without replay, debugging is guesswork.

---

## Users

- **AI engineer** — primary, debugs daily
- **Facility manager** — occasionally for QA
- **GORD auditor (P2)** — could verify ARVIS reasoning post-hoc

---

## Scope

**In (P0)**:
- Timeline picker (calendar + advisory list)
- Filter by date, risk tier, equipment, outcome
- Selected advisory opens in Advisory Detail (replay mode)
- Playback controls: jump, ±1min, ±10s (P1 — P0 is static replay)
- Cross-link to live equipment state ("Open in current state")

**Out (deferred)**:
- "What if" re-execution (P2): "if Memory_Agent hadn't crashed, what would have happened?"
- Diff view across multiple advisories (P2)
- Time-lapse animation of building state (P3)

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│ Date range picker · Filters                                         │
│ [📅 2026-05-01 → 2026-05-23] [T2] [CH-4] [Rejected]                 │
├─────────────────────────────────────────────────────────────────────┤
│ Past advisories                          │ Replay pane              │
│ ┌─────────────────────────────────────┐ │ ┌──────────────────────┐ │
│ │ 2026-05-22 14:51 · T2 · CH-4        │ │ │ Replay banner:       │ │
│ │ Refrigerant migration               │ │ │ Frozen at 14:51 UTC  │ │
│ │ Outcome: Approved                   │ │ │                      │ │
│ │ Verifier: ✓ ✓ ✓                     │ │ │ Advisory Detail      │ │
│ └─────────────────────────────────────┘ │ │ (in replay mode)     │ │
│ ┌─────────────────────────────────────┐ │ │                      │ │
│ │ 2026-05-22 09:14 · T1 · AHU-7       │ │ │ All sections render  │ │
│ │ Outcome: Rejected (false positive)  │ │ │ as of frozen time    │ │
│ │ Verifier: ✓ ✓ ✗                     │ │ │                      │ │
│ └─────────────────────────────────────┘ │ │ [Open in current]    │ │
│ ...                                     │ └──────────────────────┘ │
└─────────────────────────────────────────┴──────────────────────────┘
```

---

## Component details

### Date range picker

- Calendar with start/end dates
- Quick presets: Today / Yesterday / Last 7d / Last 30d / Custom
- Updates URL

### Filter chips

- Risk tier (T1/T2/T3)
- Equipment (chip with autocomplete)
- Outcome (Approved / Rejected / Snoozed / Auto-withdrawn / Pending)
- Verifier failed (toggle: show only advisories where any gate failed)
- Reset filters button

### Advisory list (left)

- Compact cards: timestamp, risk tier, equipment, summary, outcome chip, verifier gate strip
- Sort: timestamp desc default
- Click → load in replay pane

### Replay pane (right)

- Persistent banner: "Replay — frozen at YYYY-MM-DD HH:MM UTC"
- Embedded Advisory Detail (read-only)
- Action bar replaced with: "Open in current state" + "Open original alarm" + "View linked equipment"
- Operator action history shown if any (approve/reject events with operator + timestamp)

### Playback (P1 stretch)

- Scrub bar across the advisory's investigation window
- Step backward / forward through trace events
- See evidence ledger populate over time
- See verifier gates pass/fail in sequence

---

## States

- **No selection**: replay pane shows "Pick an advisory from the list"
- **Loading advisory**: skeleton
- **Advisory deleted (data retention expired)**: "This advisory's full replay is no longer available. Summary only."
- **Filter returns 0**: helpful empty state
- **Pending advisory selected**: "This advisory is still active — view in Live View instead"

---

## Flows

### Flow A — Engineer debugs a false positive

1. Operator: "ARVIS gave bad advisory yesterday on CH-4"
2. Engineer opens Audit & Replay
3. Filters: date=yesterday, equipment=CH-4, outcome=Rejected
4. Finds 3 results, clicks the one with "false_positive" reason
5. Replay pane opens, expands evidence ledger
6. Sees one evidence chip "physics_prediction" flagged ml_fallback=true
7. Opens that chip → physics model was missing curves for CH-4
8. Files internal bug

Time: <5 min.

### Flow B — Facility manager weekly QA

1. Ahmed opens Audit & Replay
2. Filters: last 7d, outcome=Rejected
3. Reviews each rejected advisory
4. Marks recurring false-positive patterns in shared memory
5. Reports to engineer

### Flow C — Auditor verifies a decision (P2)

1. GORD auditor with time-bounded login
2. Opens Audit & Replay
3. Navigates to specific advisory engineer pointed them to
4. Reviews evidence and verifier gates
5. Satisfied → records assent

---

## Design principles

1. **Replay mode is explicit and unmissable**. Banner across top, distinct color (purple).
2. **Replay shows truth of that moment**. No "current state" leakage in replay.
3. **Cross-link to current state** for diff thinking ("then this point read X, now it reads Y").
4. **Filters are the primary affordance**. Engineers come with a hypothesis, filter narrows.
5. **No editing in replay**. Read-only. Comments / annotations live separately.

---

## Edge cases

- Advisory was rejected but reason corrupted: show "Reason unavailable"
- Replay across rating period rollover (P0 ignore; P1 supports)
- Replay of currently-active advisory: redirect to Live View
- Replay of advisory in a different building: 403, "Not authorized"

---

## Open questions

1. **Date range default**: last 7d or last 24h? Recommendation: last 7d.
2. **Filter persistence**: per-session (URL) or per-user (localStorage)? URL default, save as named filter P1.
3. **Replay scrub**: P0 static or P1 timeline scrub? Defer P1.
4. **Mobile / tablet**: read-only review on tablet acceptable; phone too cramped — desktop-first.
5. **Annotations** in replay (engineer leaves a note for next reviewer): P1.

---

## Success criteria

- Engineer finds + opens a specific advisory in <2 min
- Replay opens in <1 sec from list click
- Past advisory data preserved indefinitely (or per retention policy)

## What designer needs from engineering

- Sample 50+ past advisories with all outcome types
- Replay event shape (for P1 scrub feature)
- Data retention policy (how far back is replay available?)

## Changelog

- v1 2026-05-23: initial
