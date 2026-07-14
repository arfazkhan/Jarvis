# Notifications — Frontend Engineer Brief

**Feature**: Cross-cutting notification system. Bell + drawer + toasts + banners + preferences UI. Backend handles email/SMS/pager dispatch.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS produces Advisories. Operators don't always have the UI focused. Notifications surface critical advisories via multiple channels. The UI owns the in-app channels (bell, toast, banner) + the preferences screen. Email/SMS/pager are dispatched server-side; UI only provides preference controls.

---

## What you're building

1. Bell + advisory drawer (in shell)
2. Toast renderer at app root
3. Banner stack at top of layout
4. Notification preferences screen (`/settings/notifications`)
5. SSE handler that wires events to in-app notifications

---

## Stack

Same as `shell/`. Toast: `sonner`. Time: `date-fns`.

---

## File layout

```
components/notifications/
  AlertBell.tsx                    — bell icon + count (lives in shell)
  AdvisoryDrawer.tsx               — slide-over from bell click
  AdvisoryDrawerCard.tsx
  ToastProvider.tsx                — wraps sonner with ARVIS theming
  BannerStack.tsx                  — top-of-page banners
  Banner.tsx
  PreferencesPanel.tsx             — Settings → Notifications
  PreferencesChannelRow.tsx
  PreferencesEventRow.tsx
  QuietHoursForm.tsx
  
lib/
  notifications/
    classify.ts                    — event → channels mapping
    drawer-state.ts                — Zustand
  hooks/
    useNotifications.ts            — subscribe + dispatch
    useNotificationPreferences.ts
```

---

## Data dependencies

### Endpoints

```
GET    /api/v1/notifications/preferences           → Preferences
PATCH  /api/v1/notifications/preferences           → Preferences
GET    /api/v1/notifications/unread?building_id=   → { advisories: AdvisorySummary[], alarms: AlarmSummary[], counts }
POST   /api/v1/notifications/mark-read             → { ids: string[] }
POST   /api/v1/notifications/dismiss               → { id }
```

### SSE topics

Already covered in `shell/engineer.md`. Bell subscribes to `advisories`, `alarms`, `system`. On each event: increment count + invalidate drawer cache.

### Cache keys

```
['notif-prefs']
['unread', buildingId]
```

---

## Components

### `<AlertBell>`

(Also referenced in `shell/engineer.md`. Implementation lives here.)

```tsx
const { count, hasCritical } = useUnreadCount(buildingId)
const open = useStore(s => s.drawerOpen)
const setOpen = useStore(s => s.setDrawerOpen)

<button onClick={() => setOpen(true)} aria-label={`${count} unread notifications`}>
  <BellIcon variant={count > 0 ? 'filled' : 'outline'} />
  {count > 0 && <Badge count={count} critical={hasCritical} />}
</button>
```

### `<AdvisoryDrawer>`

Right-side slide-over.

```tsx
<Drawer open={open} onOpenChange={setOpen} side="right">
  <DrawerHeader>
    <h2>Notifications</h2>
    <Button variant="ghost" onClick={markAllRead}>Mark all read</Button>
  </DrawerHeader>
  <DrawerBody>
    {unread.map(a => <AdvisoryDrawerCard key={a.id} advisory={a} />)}
    {read.length > 0 && <Section title="Earlier" items={read} />}
  </DrawerBody>
</Drawer>
```

Card click → navigates to Advisory Detail, marks read.

### `<ToastProvider>`

Wraps `sonner` with theme + accessibility config.

```tsx
<Toaster
  position="top-right"
  expand={false}
  visibleToasts={4}
  duration={10000}
  toastOptions={{ className: 'toast-arvis' }}
/>
```

Dispatched via `toast.success / toast.warning / toast.error` from hooks.

### `<BannerStack>`

Top of layout, between top bar and content.

Banner sources:
- Engine-down (from system topic)
- Active critical (from advisory topic when severity=critical, until acknowledged)
- Standard version drift (GSAS)
- Stale data warning

```tsx
const banners = useActiveBanners(buildingId)

<div className="banner-stack">
  {banners.map(b => <Banner key={b.id} {...b} />)}
</div>
```

### `<Banner>`

```tsx
<div className={cn("banner", `banner-${severity}`)} role="alert">
  <Icon kind={severity} />
  <span>{message}</span>
  {actionLabel && <Button variant="ghost" size="sm" onClick={action}>{actionLabel}</Button>}
  {dismissible && <CloseButton onClick={dismiss} />}
</div>
```

### `<PreferencesPanel>`

Form layout for `/settings/notifications`.

Sections:
- Channels (per-channel global toggle: bell / toast / email / SMS / pager)
- Events (per-event-type matrix: channel rows × event-type columns)
- Quiet hours (start/end/days picker)
- Vacation mode (P1)

Save on blur (debounced) or explicit Save button.

---

## State management

- Zustand for drawer open state
- React Query for preferences + unread list
- SSE for live updates

---

## Notification dispatch logic (client-side)

When SSE event arrives:

```ts
function classifyEvent(event): NotificationActions {
  const prefs = queryClient.getQueryData(['notif-prefs'])
  const inQuietHours = isQuietHours(prefs.quiet_hours)
  const severity = event.payload.severity ?? event.payload.risk_tier
  const overrideQuiet = severity === 'critical' || severity === 'T3'
  
  return {
    bell: prefs.channels.bell.enabled,
    toast: prefs.channels.toast.enabled 
      && prefs.events[event.event_type].toast 
      && (!inQuietHours || overrideQuiet),
    banner: severity === 'critical' && !alreadyBannered(event.advisory_id),
  }
}
```

Server-side dispatches email/SMS/pager based on same preferences. UI must NOT show "email sent" — that's server confirmed asynchronously.

---

## Performance budgets

| Operation | Target |
|---|---|
| Bell badge update on SSE event | <100ms |
| Drawer open animation | 200ms |
| Toast appear | <50ms after event |
| Banner appear | <100ms after event |
| Preferences save | <500ms |

---

## Testing

### Unit

- `classifyEvent` returns correct actions per pref combo
- Quiet hours override logic
- Banner deduplication

### Integration

- New T3 advisory → toast + bell badge increments + banner if critical
- Quiet hours active + T1 → bell only, no toast
- Preferences change → next event respects new prefs
- Mark all read → bell badge clears

### Visual

- Bell at 0, 1, 9, 9+, with critical pulse
- Toast variants (success, warning, error, with action)
- Banner severities
- Preferences panel

---

## Accessibility

- Bell button has descriptive aria-label
- Drawer: focus trap when open, ESC closes, focus returns
- Toast: `role="status"` for non-critical, `role="alert"` for critical
- Banner: `role="alert"`, content auto-announced
- Live regions for screen reader announcement

---

## Edge cases

- Multiple devices: one device opens drawer → others' bell clears (via SSE state event)
- Engine-down banner with no SSE: client polls `/system/status` every 30s as fallback
- Toast stack at 4: oldest auto-dismisses to make room
- Preferences load fails: defaults applied, retry banner
- Phone not provided: SMS toggle greyed with "Add phone in profile" link

---

## Integration points

- `shell/` — bell lives in TopBar
- `advisory_detail/` — opens from drawer card click, clears unread
- `live_view/` — advisory feed reflects same dataset
- `operator_actions/` — toasts dispatched from action success
- `settings_roles/` — preferences screen mounted as sub-route

---

## Open questions

1. **Drawer width**: 360px proposed; some screens compete for space.
2. **Toast queue overflow handling**: drop-oldest vs collapse-to-bell. P0 drop-oldest.
3. **Mark-all-read scope**: current building only or all? Building only.
4. **Preferences server sync**: write-through on every change vs explicit Save? Write-through (debounced).

## Changelog

- v1 2026-05-23: initial
