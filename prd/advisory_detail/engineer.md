# Advisory Detail — Frontend Engineer Brief

**Feature**: Full advisory view at `/advisories/{id}`. Most complex screen in the product.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces Advisories (recommendations to building operators) backed by multi-agent reasoning + evidence + automated verifier checks. Backend stores: investigation plan, evidence ledger, swarm votes, verifier gate outcomes, counterfactual projections. This screen renders all of it.

---

## What you're building

Route: `/advisories/{id}` — full advisory view.

Sections (top-down):
1. Header (risk tier, summary, equipment, timestamps, shadow)
2. Recommendation (action + predicted outcome + confidence)
3. Why (collapsible explainer)
4. Counterfactual (two-card with/without)
5. Verifier gates (3 badges + details)
6. Agent trace (vertical timeline, collapsible)
7. Evidence ledger (chip cloud + filters, click to drill)
8. Recent operator actions (conditional)
9. Sticky action bar (approve/reject/snooze)

Plus replay mode variant (same screen, frozen timestamp).

---

## Stack

Same as `shell/engineer.md`. Use shadcn/ui for collapsibles, dialogs, dropdowns.

---

## File layout

```
app/(authed)/advisories/
  [id]/
    page.tsx                       — RSC, fetches advisory, passes to client
    loading.tsx

components/advisory-detail/
  AdvisoryDetail.tsx
  AdvisoryHeader.tsx
  RecommendationBlock.tsx
  WhyBlock.tsx
  CounterfactualBlock.tsx
  VerifierGates.tsx
  VerifierGateBadge.tsx
  AgentTrace.tsx
  AgentVoteRow.tsx
  EvidenceLedger.tsx
  EvidenceChip.tsx
  EvidenceDrillModal.tsx
  OperatorActionsContext.tsx
  ActionBar.tsx
  ConfirmModal.tsx
  ShadowBadge.tsx

lib/
  api/
    advisory.ts                    — GET /advisories/{id}
    actions.ts                     — approve/reject/snooze
```

---

## Data dependencies

### Initial fetch (RSC)

```ts
const advisory = await fetchAdvisory(id)
// Returns full Advisory (see _shared/data_model.md)
```

Cache key: `['advisory', id]`. staleTime: 30s. Refetch on focus.

### Live updates (SSE)

Subscribe to `advisory_state_change` events. If `event.payload.id === advisoryId`, update cache.

Used for: two operators on same advisory, one approves, the other sees state change.

### Action endpoints

```ts
POST /api/v1/advisories/{id}/approve { operator_id, comment? }
POST /api/v1/advisories/{id}/reject  { operator_id, reason, freetext? }
POST /api/v1/advisories/{id}/snooze  { until: iso8601 }
```

All accept `Idempotency-Key` header. Use UUID per click.

Response: `ActionResult` with `t7_entry_created` flag, `downstream_effects[]`.

---

## Components

### `<AdvisoryDetail>`

Root client component. Props: `advisory: Advisory`, `me: Me`.

Manages local UI state (expanded sections, modal open).

Mounts SSE subscription for this advisory's state changes.

### `<AdvisoryHeader>`

Pure component. Renders risk tier chip, summary, equipment chips, timestamps, shadow badge.

### `<RecommendationBlock>`

Renders action + predicted outcome + confidence bar.

Confidence bar:
```tsx
<div className="h-2 rounded bg-neutral-bg-2">
  <div className="h-full rounded bg-accent-primary" style={{ width: `${confidence * 100}%` }} />
</div>
```

### `<WhyBlock>`

Collapsible (default open). Renders prose explainer + bullet chips that scroll to evidence ledger.

Click chip → smooth scroll to corresponding evidence id in ledger + 1s highlight.

### `<CounterfactualBlock>`

Two-card layout. Side-by-side on desktop, stacked on mobile.

Numbers formatted: failure prob as percentage, kWh as integer with comma separator.

If `counterfactual === null` (engine couldn't compute): render placeholder card "Counterfactual not computed — reason: <missing physics curves>".

### `<VerifierGates>`

3 badges in a row. Each badge:
- Green check + label if pass
- Red X + label if fail
- Gray dash + label if skipped

Below: abstention gate row with 4 signal values.

Click any badge → expands detail panel below row.

```tsx
const gates = [
  { key: 'h2_claim', label: 'Claim', state: advisory.verifier_gates.h2_claim.status },
  { key: 'h4_faithfulness', label: 'Faithfulness', state: advisory.verifier_gates.h4_faithfulness.status },
  { key: 'h6_physics', label: 'Physics', state: advisory.verifier_gates.h6_physics.status },
]
```

If any failed but advisory shipped: render red banner above gates section.

### `<AgentTrace>`

Collapsible (default closed for operator role, default open for engineer role).

Renders array of `<AgentVoteRow>` sorted by `confidence` desc, with ABSTAIN agents at bottom.

```tsx
const sortedVotes = useMemo(() => sortVotes(advisory.swarm_votes), [advisory.swarm_votes])
```

### `<AgentVoteRow>`

```tsx
<div className="flex items-start gap-3 py-2">
  <AgentIcon name={vote.agent} />
  <div className="flex-1">
    <div className="flex items-center gap-2">
      <span className="font-medium">{vote.agent}</span>
      <VerdictChip verdict={vote.verdict} />
      {vote.confidence !== null && <ConfidenceBar value={vote.confidence} />}
    </div>
    <p className="text-sm text-muted mt-1">{vote.reasoning_summary}</p>
    {vote.conditions.length > 0 && (
      <ul className="mt-1">
        {vote.conditions.map(c => <li key={c} className="text-xs">⚠ {c}</li>)}
      </ul>
    )}
  </div>
</div>
```

### `<EvidenceLedger>`

Default view: chip cloud. Toggle to table.

Filter chips at top: All / Live / History / Physics / Memory / ML / Operator / Doc.

Each evidence chip:
```tsx
<button
  onClick={() => openDrillModal(evidence)}
  className="evidence-chip"
>
  <SourceIcon type={evidence.source_type} />
  <span>{evidence.value_summary}</span>
  {evidence.is_ml_fallback && <FallbackBadge />}
</button>
```

### `<EvidenceDrillModal>`

Switches content based on `source_type`:
- `historian` → trend chart for the queried point + range
- `physics_simulator` → inputs / outputs / curves source
- `memory` → memory entry preview + link to full memory screen
- `ml_model` → model id + lineage + confidence + training date
- `operator_input` → audit log entry
- `external_doc` → embedded PDF viewer

### `<OperatorActionsContext>`

Renders only if `advisory.operator_context.attributed_to_operator === true`.

```tsx
{advisory.operator_context.recent_actions_5min.map(action => (
  <ActionRow key={action.ts} action={action} />
))}
```

### `<ActionBar>`

Sticky bottom (CSS `position: sticky; bottom: 0`).

```tsx
<div className="sticky bottom-0 border-t bg-neutral-bg-1 px-4 py-3 flex gap-2">
  <ApproveButton 
    advisoryId={advisory.id}
    riskTier={advisory.risk_tier}
    requiresConfirm={advisory.risk_tier === 'T3'}
    disabled={!canApprove(me.role, advisory.risk_tier)}
  />
  <RejectButton advisoryId={advisory.id} />
  <SnoozeDropdown advisoryId={advisory.id} />
</div>
```

Permission gating:
```ts
function canApprove(role: Role, tier: RiskTier): boolean {
  if (tier === 'T3') return ['facility_manager'].includes(role)
  return ['operator', 'facility_manager', 'engineer'].includes(role)
}
```

If disabled: render tooltip "Requires Facility Manager. [Escalate]".

### `<ConfirmModal>`

For T3 approve. Shows: "ARVIS will write `point_id` = `new_value`. This affects equipment X. Confirm?"

Two buttons: Cancel + "Yes, write".

---

## Replay mode

URL param: `?replay=<timestamp>` enables replay mode.

When replay mode on:
- Header banner: "Replay — frozen at 2026-05-23 14:51 UTC"
- All "as of now" indicators replaced with "as of T"
- Action bar disabled (replay is view-only)
- Evidence drill modals show historical state

Fetched via `GET /api/v1/audit/replay/{plan_id}` instead of `GET /api/v1/advisories/{id}`.

---

## State management

- React Query for advisory data
- Zustand for local UI: expanded sections, drill modal, confirm modal
- SSE subscription updates query cache for live state changes

---

## Performance budgets

| Operation | Target |
|---|---|
| First paint | <1500ms cold, <500ms warm |
| Section expand/collapse | <100ms |
| Evidence chip click → modal open | <200ms |
| Approve click → toast | <400ms (API <300ms p95) |
| Replay mode load | <1000ms |

Heavy section: Agent Trace + Evidence Ledger if many items. Virtualize if >50 in either.

---

## Testing

### Unit

- Permission gating: operator cannot approve T3
- Sort order: votes by confidence desc, ABSTAIN at bottom
- Counterfactual renders placeholder when null
- Shadow badge renders only in shadow mode

### Integration

- Approve flow end-to-end: click → confirm (T3) → API → toast → header updates
- Reject flow with reason picker
- Replay mode: action bar disabled, banner visible
- Evidence chip click → modal with correct source content

### Visual

- All risk tiers (T1/T2/T3)
- Verifier gates: all pass, one failed, all failed
- Shadow mode variant
- Operator-attributed advisory
- Replay mode

---

## Accessibility

- Sticky action bar must not obscure focus when tabbing
- Collapsibles use `<details>` or `aria-expanded`
- Evidence chips: each `button` with `aria-label="Evidence: <source_type>, <value_summary>"`
- Agent trace: vote rows are `role="article"` with proper headings
- Confirm modal: focus trapped, ESC closes, focus returns to trigger

---

## Edge cases

- Advisory not found (404): "Advisory not found or you don't have access"
- Advisory in another building user lacks: 403 → "Access denied"
- Concurrent state change (other operator approved): inline notice "This advisory was approved by Layla 2s ago"
- Network down during approve: optimistic UI + retry; persistent failure → revert + error toast
- T3 with no `target_setpoint`: render warning "Recommendation incomplete — refusing to enable approve"

---

## Integration points

- `live_view/` — clicked from advisory feed
- `audit_replay/` — clicked from replay timeline (replay mode)
- `equipment_detail/` — equipment chip in header links here
- `memory_knowledge/` — memory evidence chips link to memory screen
- `operator_actions/` — approve/reject/snooze flows
- `notifications/` — bell badge cleared when advisory opened

---

## Open questions

1. **Optimistic UI on approve**: instant state update or wait for API? Recommendation: optimistic, revert on failure.
2. **Evidence drill modal vs sidebar**: modal blocks focus, sidebar allows comparison. P0: modal. P1: sidebar option.
3. **Concurrent edit conflict UI**: inline notice (proposed) or toast?
4. **Replay mode action bar**: fully disabled or shows "Replay mode — actions unavailable" tooltip?

## What engineer needs from product

- Final permission matrix (currently in `_shared/api_contracts.md`)
- Sample advisories with all edge cases (verifier failed, abstention, operator-attributed)
- Agent icon set

## Changelog

- v1 2026-05-23: initial
