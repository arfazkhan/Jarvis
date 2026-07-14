# Shell (Chrome) — Product Designer Brief

**Feature**: The persistent UI frame that wraps every screen — top bar, navigation, mode badge, building selector, clock, alert bell, user menu.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial building operators. It watches large chiller plants (Marina Heights Tower, Doha: 32 floors, 4 chillers, 142 air handlers) 24/7, spots problems, explains them, and recommends fixes. Operators (Bilal types) sit at a BMS desk; managers (Ahmed types) check in weekly; owners (Noor types) quarterly. ARVIS is **read-only advisory** — it observes and recommends, doesn't actuate equipment. The operator decides what to do.

Same UI, three modes:
- **SIM** (gray badge) — synthetic data, sales demos
- **PILOT** (amber badge) — real building, shadow mode (no notifications, no writes)
- **PROD** (green badge) — real building, live

The shell is the part of the screen that doesn't change when you navigate.

---

## Why this exists

Every screen needs:
- A way to switch between top-level views (Live View, Advisory Detail, Equipment, Memory, Compliance, Audit, Sim Cockpit)
- A constant reminder of which **mode** the user is in (SIM/PILOT/PROD) — clicking changes the building, not the building
- The current **building** if multi-building (P3)
- The current **time** (wall clock or sim clock)
- An **alert bell** for new advisories
- A **user menu** with role + sign-out

Without persistent chrome users get lost, click wrong buttons, miss alerts.

---

## Users

All five personas (operator, facility manager, exec, engineer, sales) see this constantly. **Operator** sees it most — must not annoy.

---

## Scope

**In**:
- Top bar
- Left rail or top-tab nav (designer picks)
- Mode badge with strong visual difference per mode
- Building selector (single building P0; multi-select P3)
- Clock (wall / sim)
- Alert bell with unread count
- User avatar / menu / sign-out
- Role indicator (small chip next to avatar)

**Out**:
- Page content (each feature owns its own)
- Footer (none — operator console, no marketing footer)
- Mobile-specific drawer (P1 — phone is read-only anyway)

---

## Layout

**Top bar** (h: 56px desktop, 64px tablet):

```
[Logo] [BuildingName ▾]            [ModeBadge] [Clock] [🔔3] [Avatar ▾]
```

- Left: ARVIS logo (24px monogram), building name with dropdown (P0 single building only, dropdown disabled state)
- Center: mode badge — pill-shape, color-filled, label + status ("SIM" / "PILOT — Shadow" / "LIVE")
- Right: clock (HH:MM, building local time), bell, avatar dropdown

**Nav** — designer picks:
- **Option A**: Top tabs below top bar — Live View / Advisories / Equipment / Memory / Compliance / Audit / Sim
- **Option B**: Left rail collapsible — 56px collapsed, 240px expanded
- **Recommendation**: Left rail. More items will land in P2. Top tabs run out of width.

Active nav item indicated by accent bar + filled icon + bold label.

---

## States

- **Mode badge states**:
  - SIM: gray, neutral
  - PILOT shadow: amber, "PILOT — Shadow" label
  - PILOT graduated to live: green, "PILOT — Live"
  - PROD: green, "LIVE"
  - PROD with active critical: red pulse, "LIVE — 1 critical"
- **Alert bell**:
  - 0 unread: outline icon, no badge
  - 1-9 unread: filled icon, numeric badge
  - 10+ unread: filled icon, "9+" badge
  - Active critical alarm: red dot pulse on bell
- **Building selector** (P0): single building locked, no chevron
- **Building selector** (P3): chevron, dropdown with search, recent buildings, all buildings
- **Clock**:
  - PROD/PILOT: wall clock, building local TZ shown in tooltip
  - SIM: sim clock, with speed indicator (1x, 6x, 60x), small "SIM" prefix
- **Loading**: shell renders immediately on first paint, content below skeletons
- **Offline / connection lost**: amber banner replaces clock area: "Reconnecting — last update 14:32"

---

## Flows

### Flow A — Operator signs in
1. Lands on login (Cognito/Auth0 hosted)
2. Returns to ARVIS with token
3. Shell renders, defaults to Live View
4. Mode badge confirms PROD
5. Bell shows unread count
6. Operator clicks bell → advisory feed slides over

### Flow B — Switch building (P3)
1. Click building name → dropdown
2. Search or select
3. All screens reload with new building's data
4. Mode badge may change if different building is in different mode
5. Confirm modal if leaving uncommitted operator action

### Flow C — Sign out
1. Click avatar → menu → Sign out
2. Confirm modal if pending operator actions
3. Cookie cleared, redirect to login

---

## Design principles

1. **Mode badge is the single most important UI element** after the advisory feed. Visible in every screen. Color-coded. Color + label, never color alone.
2. **Shell never blocks content**. If shell data takes longer, content renders first.
3. **Bell is always one click from advisory feed**. Don't bury behind tabs.
4. **Building name + mode together** answer "where am I?" in one glance.
5. **Avatar dropdown contains role, building access, sign-out**. Nothing destructive primary-positioned.

---

## Edge cases

- User signed in, no buildings: empty state — "No buildings assigned. Contact your administrator."
- User with multiple roles per building: show primary role only, full list in menu
- Token expired during long session: silent refresh; if fails, redirect to login with return URL
- New advisory arrives while bell hidden by scroll: bell stays visible (sticky top bar)
- Demo screen recording: hide bell numeric badge optionally (clean shot)

---

## Open questions

1. **Top tabs vs left rail** — final call after P1 IA stabilizes.
2. **Building selector behavior with cross-building advisories** — when on Building A, do you see Building B advisories? P0: no. P3: combined view possible.
3. **Mode badge clickable?** Could open mode-switch modal for engineers. Or read-only display only.
4. **Clock format** — 24h (operator preference) or 12h (default)? Setting in user prefs.
5. **Brand co-branding** — customer logo slot in left chrome? P1.

---

## Success criteria

- Operator never asks "what mode am I in?" — answered by badge
- New user reaches any top-level screen within 1 click from login
- Shell renders <100ms on cached load, <500ms on cold

---

## What designer needs from engineering

- Confirmed list of top-level views for P0 (this PRD assumes 7)
- Final auth provider (Cognito vs Auth0) — affects login screen
- Building list shape for selector (likely just one in P0)
- Mode toggle source of truth — comes from `GET /me`
