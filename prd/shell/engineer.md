# Shell (Chrome) — Frontend Engineer Brief

**Feature**: Persistent UI frame (top bar, navigation, mode badge, building selector, clock, alert bell, user menu).

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor SaaS for commercial building operators. Frontend is Next.js (App Router) + React Server Components + Tailwind + shadcn/ui. State via React Query for server data, light Zustand store for shell-level UI state. Stream via SSE. Auth via Cognito or Auth0 (TBD — code defensively).

Three runtime modes per user session: SIM, PILOT, PROD. The mode comes from `GET /me`; shell must render this prominently. Cross-cutting concern: every screen lives inside this shell.

---

## What you're building

A persistent layout component that:

- Renders on every authenticated route
- Owns top-bar, side-nav, mode badge, building selector, clock, alert bell, avatar menu
- Provides a slot for page content
- Subscribes to SSE for advisory + alarm count updates (for the bell)
- Handles auth refresh transparently
- Handles offline / reconnect UI

---

## Stack assumptions

- Next.js 14+ App Router
- React 18+ (Suspense, RSC)
- TypeScript strict
- Tailwind CSS + shadcn/ui
- React Query (TanStack Query v5)
- Zustand for UI-only state (modal open, drawer open, etc.)
- SSE via native EventSource or `@microsoft/fetch-event-source`
- date-fns for time formatting

---

## File layout

```
app/
  layout.tsx                       — root layout, theme provider, query client
  (authed)/
    layout.tsx                     — shell layout, side nav + top bar
    live-view/page.tsx
    advisories/[id]/page.tsx
    equipment/[id]/page.tsx
    ...
  login/page.tsx
  
components/
  shell/
    Shell.tsx                      — layout shell
    TopBar.tsx
    SideNav.tsx
    ModeBadge.tsx
    BuildingSelector.tsx
    Clock.tsx
    AlertBell.tsx
    UserMenu.tsx
    OfflineBanner.tsx
  
lib/
  api/
    client.ts                      — fetch wrapper, auth header, error handling
    me.ts                          — GET /me
  stream/
    sse.ts                         — SSE subscription hook
  auth/
    session.ts                     — JWT cookie + refresh
  state/
    shellStore.ts                  — Zustand store
```

---

## Data dependencies

### `GET /me`

Server component fetch at shell mount. Cached per-session.

```ts
type Me = {
  user_id: string
  email: string
  role: "operator" | "facility_manager" | "exec" | "engineer" | "sales_demo"
  building_ids: string[]
  mode: "SIM" | "PILOT" | "PROD"
  shadow_mode: boolean
}
```

### `GET /buildings`

For building selector. Cached. Refetch on focus.

### SSE subscription

Topics: `alarms`, `advisories`. Used only for unread count.

Endpoint: `GET /stream/events?building_id={id}&topics=alarms,advisories`

```ts
// useUnreadCount.ts
const { advisoryCount, alarmCount } = useUnreadCount(buildingId)
// counts cleared when user opens corresponding panel
```

---

## Component contracts

### `<Shell>`

Root layout component. Renders nav + bar + outlet.

```tsx
<Shell>
  {children}
</Shell>
```

Server component. Wraps client-side TopBar + SideNav.

### `<TopBar>`

Client component. Sticky.

Props: `me: Me`, `buildings: Building[]`.

Renders left section (logo + building), center (mode badge), right (clock, bell, user menu).

Height: 56px desktop, 64px tablet.

### `<SideNav>`

Client component. Collapsible (collapsed: 56px, expanded: 240px).

Items hardcoded for P0:
```ts
const NAV_ITEMS = [
  { path: '/live-view', label: 'Live View', icon: 'home' },
  { path: '/advisories', label: 'Advisories', icon: 'alert' },
  { path: '/equipment', label: 'Equipment', icon: 'cpu' },
  { path: '/memory', label: 'Memory', icon: 'book' },
  { path: '/compliance', label: 'Compliance', icon: 'shield' },
  { path: '/audit', label: 'Audit & Replay', icon: 'history' },
  { path: '/sim', label: 'Sim Cockpit', icon: 'flask', simOnly: true },
]
```

`simOnly` items hidden when `mode !== 'SIM'`.

Active state from `usePathname()`.

### `<ModeBadge>`

Pure component. Props: `mode: "SIM" | "PILOT" | "PROD"`, `shadow: boolean`, `activeCritical: boolean`.

Color tokens:
- SIM → `bg-neutral-bg-2 text-neutral-text-primary`
- PILOT shadow → `bg-amber-500/20 text-amber-300 border-amber-500`
- PROD → `bg-green-500/20 text-green-300 border-green-500`
- PROD critical → `bg-red-500/20 text-red-300 border-red-500 animate-pulse`

ARIA: `role="status"`, `aria-live="polite"`.

### `<Clock>`

Client component. Renders building-local time. Polls system clock every second (cheap setInterval).

For SIM mode, reads `sim_time` from `useSimClock()` hook which polls `/sim/clock` every 1s, or subscribes to clock stream.

### `<AlertBell>`

Client component. Subscribes to `useUnreadCount(buildingId)`.

Click → opens advisory drawer (renders to a portal, separate component owned by advisory feed feature).

### `<UserMenu>`

Avatar (initials fallback) + dropdown:
- Email + role
- Building access
- Theme toggle
- Sign out

Sign out → POST /auth/logout → redirect to /login.

### `<OfflineBanner>`

Mounted at top of shell. Visibility tied to SSE connection state.

When SSE disconnected > 5s: shows "Reconnecting — last update HH:MM".
Auto-hides when reconnected.

---

## State management

### Zustand store (`shellStore.ts`)

```ts
type ShellState = {
  sideNavCollapsed: boolean
  setSideNavCollapsed: (v: boolean) => void
  advisoryDrawerOpen: boolean
  setAdvisoryDrawerOpen: (v: boolean) => void
  theme: 'dark' | 'light' | 'system'
  setTheme: (t: 'dark' | 'light' | 'system') => void
}
```

Persist `sideNavCollapsed` + `theme` to localStorage.

### React Query

- `['me']` — staleTime: 5min
- `['buildings']` — staleTime: 1min, refetchOnFocus: true
- `['unread-count', buildingId]` — kept in sync via SSE side-effect

---

## Auth

### Request flow

1. RSC `(authed)/layout.tsx` reads JWT from HTTP-only cookie via server-side helper
2. If missing or expired → redirect to /login
3. If present → fetch `GET /me` server-side, pass to `<Shell>`
4. Client mounts, reads `me` from props

### Refresh

Silent refresh:
- Cookie has short-lived access token + long-lived refresh token
- Middleware refreshes on every request if access token within 60s of expiry
- If refresh fails: client receives 401 → redirect to /login with `returnUrl`

### Logout

POST /auth/logout → cookies cleared server-side → redirect to /login.

---

## SSE subscription

Single SSE connection at shell mount. Multiplexed via topics.

```ts
// hooks/useShellStream.ts
export function useShellStream(buildingId: string) {
  useEffect(() => {
    const source = new EventSource(
      `/api/v1/stream/events?building_id=${buildingId}&topics=alarms,advisories`,
      { withCredentials: true }
    )
    
    source.addEventListener('advisory_published', (e) => {
      queryClient.setQueryData(['unread-count', buildingId], (prev) => ({
        ...prev,
        advisoryCount: (prev?.advisoryCount ?? 0) + 1,
      }))
    })
    
    source.addEventListener('alarm_new', (e) => {
      // similar
    })
    
    source.onerror = () => {
      // mark offline; SSE auto-reconnects
    }
    
    return () => source.close()
  }, [buildingId])
}
```

Reconnect: native EventSource handles. On reconnect, server replays from `Last-Event-ID`.

Beyond 5-min reconnect gap: full refresh via `queryClient.invalidateQueries()`.

---

## Performance budgets

| Operation | Target |
|---|---|
| Shell first paint | <500ms cold, <100ms warm |
| Time to interactive | <1500ms cold |
| Mode badge re-render on mode change | <16ms |
| Bell badge update on new advisory | <100ms from SSE event to paint |
| Side nav collapse/expand animation | 200ms ease-out |

---

## Testing

### Unit (vitest)

- `<ModeBadge>` renders correct color per mode
- `<Clock>` renders building-local time
- `useUnreadCount` increments on advisory_published event

### Integration (Playwright)

- Auth flow: redirect when not logged in, restore after login
- Mode badge persists across navigation
- Bell count updates on simulated SSE event
- Offline banner appears + disappears on stream interruption

### Visual regression (Chromatic / Percy)

- TopBar in all 3 modes
- SideNav collapsed + expanded
- ModeBadge for SIM/PILOT-shadow/PILOT-live/PROD/PROD-critical

---

## Accessibility

- Tab order: logo → building selector → nav items → mode badge → clock → bell → avatar
- ARIA landmarks: `<header>` for top bar, `<nav>` for side nav
- Skip to content link (visually hidden until focused)
- Bell announces new advisories via aria-live region
- ModeBadge has explicit `aria-label="Mode: PILOT (shadow)"`
- Color contrast: all states ≥ 4.5:1

---

## Mobile / responsive

- Desktop (≥1024px): full shell
- Tablet (768-1023px): side nav collapses to icons by default
- Phone (<768px): side nav becomes bottom tab bar; top bar reduces to logo + mode + bell + avatar; building selector moves to menu

Operator actions disabled on phone (read-only).

---

## Integration points

- Advisory feed drawer (owned by `live_view` feature) — bell triggers drawer open
- Notification system (owned by `notifications` feature) — bell ties into notification preferences
- Building list (P3 multi-building) — building selector queries `/buildings`

---

## Open questions

1. **Auth provider**: Cognito vs Auth0 final pick? Affects login page + SDK choice.
2. **SSE library**: native EventSource (no auth headers) vs `@microsoft/fetch-event-source` (custom headers). Recommendation: native + cookie auth.
3. **Theme persistence**: per-user (server) or per-device (localStorage)? P0: localStorage. P1: server-side preference.
4. **Building selector behavior in P0**: single building, dropdown disabled or hidden? Recommendation: visible but disabled, hover tooltip "Single building in P0".

---

## What engineer needs from product

- Final nav item list (locked)
- Final mode label strings (in case marketing rewrites "PILOT — Shadow" to something else)
- Brand assets (logo, monogram)

## Changelog

- v1 2026-05-23: initial
