# Operator Actions — Product Designer Brief

**Feature**: Cross-cutting flows for Approve / Reject / Snooze / Feedback on advisories.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces Advisories (recommendations) for building operators. Every advisory has a status: pending / approved / rejected / snoozed / auto-withdrawn. The operator decides outcome by clicking action buttons across multiple screens (Live View feed, Advisory Detail). Operator actions feed back into ARVIS's memory (T7 = Resolution memory) and tune future recommendations.

---

## Why this exists

Without consistent operator action UX:
- Approve/reject buttons inconsistent across screens
- Operator unsure if action was recorded
- T7 memory misses freetext context
- No reversal path
- No escalation path for permissions

This feature defines the contract for all action surfaces.

---

## Users

- **Operator** — primary actor on T1/T2
- **Facility manager** — adds T3 approval
- **AI engineer / auditor** — reviews action history

---

## Scope

**In**:
- Approve (with optional comment)
- Reject (with required reason + optional freetext)
- Snooze (with duration picker)
- Provide feedback (separate path, freetext)
- Escalate (when permission insufficient)
- Reverse / undo (within grace period)

**Out**:
- Manual BMS override (lives in Equipment Detail)
- Alarm acknowledgment (separate)

---

## Action surfaces

These flows are reused in:
- Live View advisory feed (quick action buttons on cards)
- Advisory Detail sticky bottom action bar
- Audit Replay (disabled, view-only)

---

## Flow A — Approve

### Trigger
- "Approve" button on advisory card (Live View) or sticky bar (Advisory Detail)

### Behavior by risk tier
- **T1 (info)**: one-click, no confirm. Toast "Approved".
- **T2 (diagnostic)**: optional comment field appears briefly (3s) before commit. Toast on commit.
- **T3 (actionable)**: required confirm modal.
  - Modal shows: "ARVIS will write `CH-4/CWST = 28°C`. Confirm?"
  - Cancel + "Yes, write" buttons
  - If recommendation has counterfactual: shows impact summary in modal
  - Toast on commit + downstream effect indicator ("Setpoint written")

### Side effects
- Status → approved
- T7 memory entry created (auto)
- Audit log entry
- If T3: BACnet write dispatched
- Card disappears from Live View feed within 500ms
- Advisory Detail header updates: "Approved by Bilal at 14:35"

### Permissions
- T1/T2: operator + facility_manager + engineer
- T3: facility_manager only (default; can be delegated)

---

## Flow B — Reject

### Trigger
- "Reject" button

### Modal
- Required reason picker (radio buttons):
  - False positive
  - Wrong equipment
  - Wrong action
  - Bad timing
  - Unsafe
  - Other
- Optional freetext (max 500 chars)
- Submit button

### Side effects
- Status → rejected
- T7 memory entry created with outcome_label=operator_rejected
- Audit log entry
- Card disappears from feed
- Advisory Detail header updates

---

## Flow C — Snooze

### Trigger
- "Snooze" button → dropdown

### Dropdown options
- 1 hour
- 4 hours
- Until end of shift (calculated based on building schedule)
- 24 hours
- Custom… (datetime picker)

### Side effects
- Status → snoozed (until ts)
- Card moved to "Snoozed" sub-feed (P1)
- Re-emerges as pending at snooze expiry
- Audit log entry

### Permissions
- All operator+ roles

---

## Flow D — Feedback

### Trigger
- "Provide feedback" link in Advisory Detail (separate from approve/reject)

### Modal
- Freetext only (no required reason)
- Tag picker (P1: useful, fast, slow, confusing, accurate, wrong-context, …)
- Submit

### Side effects
- T7 memory entry created/updated (merged on advisory_id if approve/reject already happened)
- Audit log entry
- No status change

---

## Flow E — Escalate

### Trigger
- Operator clicks Approve/Reject on action they lack permission for (e.g., operator on T3)

### Behavior
- Button shows disabled state with permission tooltip
- "Escalate to facility_manager" button appears
- Click → modal: "Notify Ahmed about CH-4 T3 advisory?" + optional message
- On confirm: notification dispatched to facility_manager via configured channel (in-app + email)
- Advisory remains pending; operator card shows "Escalated to Ahmed 2 min ago" badge

### Side effects
- Notification persisted
- Audit log entry

---

## Flow F — Reverse / Undo (grace period)

### Trigger
- Toast after Approve/Reject has "Undo" link
- Active for 10 seconds

### Behavior
- Click Undo → revert status to pending
- Toast updates: "Undone"

### Side effects
- T7 entry deleted (or marked rolled-back)
- Audit log retains both entries

### Limitations
- T3 BACnet writes are NOT reversible by Undo (write already dispatched). Show different toast: "Approved + write dispatched. To reverse, manually adjust setpoint."

---

## States

- **Action in progress**: button shows spinner, disabled
- **Action succeeded**: toast + status change
- **Action failed (network)**: toast with retry button
- **Action conflicted** (already approved by someone else): modal "Already approved by Layla 2s ago"
- **Permission denied**: disabled button + escalate option
- **Idempotent retry**: second click within 60s deduplicates (no double-write)

---

## Design principles

1. **T1 light, T3 heavy**. Confirmation friction proportional to blast radius.
2. **Toast always confirms**. Operator should never wonder "did that work?"
3. **Undo where possible**. Not for BACnet writes.
4. **Escalation is one-click**. Don't make operator navigate elsewhere.
5. **Reason picker on Reject is required**. Drives memory + product improvement.
6. **Feedback is separate path**. Don't bury under reject (some advisories are valuable but not actionable).

---

## Edge cases

- Operator approves while advisory was auto-withdrawn: "This advisory was withdrawn 5s ago" modal, no action taken
- Two operators approve simultaneously: first wins, second sees conflict modal
- T3 approve but BACnet adapter offline: pre-commit check; modal warns "BMS write unavailable, accept as recommendation only?"
- Snooze custom time in past: validation error
- Network down: optimistic UI + queued for retry on reconnect

---

## Open questions

1. **Undo grace period length** — 10s (proposed) or 30s?
2. **Snoozed feed** P0 or P1? Recommendation: P1.
3. **Feedback tag taxonomy** — fixed set or freetext only?
4. **Escalate channels** — in-app only or also email/SMS/Slack?
5. **Reason picker localization** — Arabic translation needed for Doha?

---

## Success criteria

- Action commit <500ms from click to toast
- ≥85% of advisories receive an action (approve / reject / snooze) within 1h
- ≥40% of approve/reject actions include freetext

## What designer needs from engineering

- Final permission matrix per risk tier
- BACnet write dispatch semantics (sync vs async)
- Notification channels available for escalation

## Changelog

- v1 2026-05-23: initial
