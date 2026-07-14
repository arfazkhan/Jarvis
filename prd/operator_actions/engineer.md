# Operator Actions — Frontend Engineer Brief

**Feature**: Cross-cutting components and flows for Approve / Reject / Snooze / Feedback / Escalate / Undo on advisories. Used across Live View and Advisory Detail.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces Advisories that need operator action. Backend exposes `POST /advisories/{id}/{approve|reject|snooze}` + `POST /feedback`. These actions create T7 memory entries server-side and trigger downstream effects (notifications, optionally BACnet writes). FE must handle: confirm modals, optimistic UI, undo, escalation when permission insufficient, idempotency.

---

## What you're building

A set of **shared components + hooks** that any screen can drop in.

```
<ApproveButton advisoryId riskTier onSuccess />
<RejectButton advisoryId onSuccess />
<SnoozeDropdown advisoryId onSuccess />
<FeedbackButton advisoryId />
<EscalateButton advisoryId />
```

Plus shared hooks:
```ts
useApprove()
useReject()
useSnooze()
useFeedback()
useEscalate()
```

Plus a global `<ActionToastProvider>` that mounts at app root and handles toasts + undo.

---

## Stack

Same as `shell/`. Toast lib: `sonner` (recommended, supports actions). Modal: shadcn/ui Dialog.

---

## File layout

```
components/operator-actions/
  ApproveButton.tsx
  RejectButton.tsx
  RejectModal.tsx
  SnoozeDropdown.tsx
  FeedbackButton.tsx
  FeedbackModal.tsx
  EscalateButton.tsx
  EscalateModal.tsx
  ActionConfirmT3Modal.tsx
  ActionToastProvider.tsx

lib/
  api/
    actions.ts
  hooks/
    useApprove.ts
    useReject.ts
    useSnooze.ts
    useFeedback.ts
    useEscalate.ts
    useCanAct.ts                 — permission helper
```

---

## Data dependencies

### Endpoints

```
POST /api/v1/advisories/{id}/approve   { operator_id?, comment? }       → ActionResult
POST /api/v1/advisories/{id}/reject    { reason, freetext? }            → ActionResult
POST /api/v1/advisories/{id}/snooze    { until: iso8601 }               → ActionResult
POST /api/v1/feedback                  { advisory_id, label?, freetext } → FeedbackResult
POST /api/v1/advisories/{id}/escalate  { to_role, message? }            → EscalateResult
POST /api/v1/advisories/{id}/undo      { prior_action_id }              → ActionResult
```

All POSTs accept `Idempotency-Key` header. Generate UUID per click.

### Response shape

```ts
type ActionResult = {
  ok: boolean
  advisory_id: string
  operator_action_id: string
  t7_entry_created: boolean
  t7_entry_id: string?
  t7_bucket: 'primary' | 'shadow'
  shadow: boolean
  downstream_effects: string[]   // e.g., ['bacnet_writeback_dispatched', 'ticket_created:MNT-1284']
}
```

---

## Components

### `<ApproveButton>`

```tsx
type Props = {
  advisoryId: string
  riskTier: 'T1' | 'T2' | 'T3'
  targetSetpoint?: { point_id, value, unit }  // T3 only
  variant?: 'primary' | 'compact'
  onSuccess?: (result: ActionResult) => void
}
```

Logic:
```ts
const { mutate, isPending } = useApprove(advisoryId)
const canApprove = useCanAct('approve', riskTier)

const onClick = () => {
  if (!canApprove) return setShowEscalate(true)
  if (riskTier === 'T3') return setShowConfirm(true)
  if (riskTier === 'T2') return mutate({ comment: optional })
  mutate({})  // T1
}
```

### `<RejectButton>` + `<RejectModal>`

```tsx
type RejectFormData = {
  reason: 'false_positive' | 'wrong_equipment' | 'wrong_action' | 'bad_timing' | 'unsafe' | 'other'
  freetext?: string
}
```

Modal with radio buttons + textarea. Submit triggers mutation.

### `<SnoozeDropdown>`

```tsx
const options = [
  { label: '1 hour', delta: '1h' },
  { label: '4 hours', delta: '4h' },
  { label: 'End of shift', delta: () => computeShiftEnd(buildingId) },
  { label: '24 hours', delta: '24h' },
  { label: 'Custom…', delta: 'custom' },
]
```

On select: compute `until` datetime, fire mutation. Custom opens datetime picker.

### `<FeedbackButton>` + `<FeedbackModal>`

Always one-click to open modal. Textarea + optional tag picker.

Submission separate from approve/reject — does not change status.

### `<EscalateButton>` + `<EscalateModal>`

Appears when permission denied. Modal:
- "Notify [target_role] about this advisory?"
- Optional message textarea
- Confirm

Mutation fires, button shows "Escalated 2s ago" badge.

### `<ActionConfirmT3Modal>`

```tsx
<Dialog>
  <DialogTitle>Confirm T3 action</DialogTitle>
  <DialogDescription>
    ARVIS will write <code>{point_id}</code> = <code>{value}{unit}</code> on {equipment_id}.
  </DialogDescription>
  {counterfactual && <CounterfactualSummary cf={counterfactual} />}
  <DialogFooter>
    <Button variant="ghost" onClick={cancel}>Cancel</Button>
    <Button variant="primary" onClick={confirm}>Yes, write</Button>
  </DialogFooter>
</Dialog>
```

Focus trap, ESC closes, focus returns to trigger.

### `<ActionToastProvider>`

Mount at app root. Listens for action results.

For each success:
```ts
toast.success(`Advisory approved`, {
  action: hasUndoCapability(result) ? {
    label: 'Undo',
    onClick: () => undoMutation.mutate(result.operator_action_id),
  } : undefined,
  duration: 10000,  // 10s for undo grace
})
```

`hasUndoCapability` returns false if `downstream_effects` includes `bacnet_writeback_dispatched`.

---

## Hooks

### `useApprove`, `useReject`, `useSnooze`, `useFeedback`, `useEscalate`

All wrap React Query mutations.

```ts
export function useApprove(advisoryId: string) {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: ApproveData) => 
      fetch(`/api/v1/advisories/${advisoryId}/approve`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify(data),
      }).then(r => r.json()),
    
    onMutate: async (data) => {
      // optimistic: status → approved
      await queryClient.cancelQueries({ queryKey: ['advisory', advisoryId] })
      const prev = queryClient.getQueryData(['advisory', advisoryId])
      queryClient.setQueryData(['advisory', advisoryId], (old: any) => ({
        ...old,
        status: 'approved',
      }))
      return { prev }
    },
    
    onError: (err, data, context) => {
      // revert
      queryClient.setQueryData(['advisory', advisoryId], context?.prev)
      toast.error('Action failed', { description: err.message })
    },
    
    onSuccess: (result) => {
      toast.success('Approved', { 
        action: hasUndoCapability(result) ? { 
          label: 'Undo', 
          onClick: () => undoAction(result.operator_action_id),
        } : undefined,
      })
    },
    
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['advisory', advisoryId] })
      queryClient.invalidateQueries({ queryKey: ['advisories'] })
    },
  })
}
```

### `useCanAct`

```ts
export function useCanAct(action: 'approve' | 'reject' | 'snooze', riskTier?: RiskTier) {
  const { data: me } = useMe()
  if (!me) return false
  
  if (action === 'approve' && riskTier === 'T3') {
    return ['facility_manager'].includes(me.role)
  }
  if (['approve', 'reject', 'snooze'].includes(action)) {
    return ['operator', 'facility_manager', 'engineer'].includes(me.role)
  }
  return false
}
```

---

## State management

- Action state in React Query mutations
- Toast / undo via `sonner` API
- Modal state via local component state

---

## Idempotency

Always send `Idempotency-Key: <uuid>` header. Server deduplicates within 60s. Same key returns prior response.

If user double-clicks: second click hits same key → no double-write.

---

## Performance budgets

| Operation | Target |
|---|---|
| Approve T1 click → toast | <400ms (optimistic <100ms) |
| Reject modal open | <100ms |
| T3 confirm modal open | <100ms |
| Snooze dropdown render | <50ms |
| Undo click → reverted | <300ms |

---

## Testing

### Unit

- Idempotency-Key generated per click
- T3 always opens confirm modal
- T1 fires direct mutation
- Permission gating per role + tier

### Integration

- Approve → toast → optimistic UI → server confirm
- Undo within grace period → status reverts
- T3 with BACnet write → no Undo button
- Network failure → revert + error toast
- Conflict (already approved): modal explains

### Visual

- T1/T2/T3 button variants
- Modal open states (reject, confirm T3, feedback, escalate)
- Toast with and without undo
- Permission-denied disabled button

---

## Accessibility

- All buttons keyboard-activated
- Modals: focus trap, ESC close, focus return
- Toast announces via `role="status"`
- Disabled buttons explain why via tooltip + `aria-describedby`

---

## Edge cases

- Network drop mid-mutation: optimistic UI rolled back, retry banner
- Server returns 409 (conflict): explain in modal
- Idempotency key collision: extremely unlikely with UUIDv4
- T3 with bad counterfactual data: warn before commit
- Snooze custom time invalid: validation error, no submit

---

## Integration points

- `live_view/` — buttons in advisory cards
- `advisory_detail/` — sticky action bar
- `audit_replay/` — buttons disabled
- `notifications/` — escalations create notifications
- `memory_knowledge/` — T7 entries created server-side, surface there

---

## Open questions

1. **Undo grace period** — 10s default. Configurable per-user?
2. **Snoozed feed** — display under Live View as sub-tab? Defer to P1.
3. **Reject reason taxonomy** — final list (currently 6) or extensible?

## Changelog

- v1 2026-05-23: initial
