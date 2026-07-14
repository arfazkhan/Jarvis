# Settings & Roles — Product Designer Brief

**Feature**: Configuration screens for building settings, user roles, integrations, audit log.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for commercial chiller plants. Like any SaaS, it needs an administration surface: who has access, building-level configuration (rating period, GSAS version, baselines), integration credentials (BMS, email, SMS providers), notification preferences (per-user), and an audit log of administrative changes.

---

## Why this exists

Without Settings:
- Onboarding edits require engineering
- Role changes need backend access
- Integration tokens scattered
- No audit trail for "who changed what"
- No way to see vacation mode / on-call rotation

---

## Users

- **Facility manager** — primary admin, runs most settings
- **AI engineer** — integration setup, debug
- **Operator** — only sees own profile + notification prefs
- **Owner / exec** — read-only for many settings

---

## Scope

**In**:
- Profile (personal settings: name, email, phone, avatar, password)
- Notification preferences (per-user)
- Building settings (rating period, GSAS version, baselines, schedules)
- Roles & permissions (who has what access)
- Integrations (BMS, email, SMS providers; OAuth + API keys)
- Audit log (admin changes)
- Re-onboarding (re-run wizard)

**Out**:
- Billing / subscription (P2)
- Tenant data privacy controls (P2)
- API key management for third-party access (P2)

---

## Information architecture

```
/settings
  /profile                  — own user
  /notifications            — own notification prefs (cross-ref notifications PRD)
  /building                 — building config (per building)
  /roles                    — user list + role assignments
  /integrations             — connections
  /audit-log                — admin change history
```

Sub-nav inside Settings (left rail or top tabs).

Permissions:
- Profile + notifications: all roles
- Building, roles, integrations: facility_manager + engineer
- Audit log: facility_manager + engineer
- Re-onboarding: facility_manager + engineer

---

## Layouts

### Profile

Form: name, email, phone, avatar upload, password change.

### Building settings

- Rating period dates (start / end)
- GSAS version selector (locked or override)
- Building category (commercial / mixed-use / etc.)
- Owner-of-record (for audit packages)
- Baselines (energy intensity, occupancy schedule, setpoint defaults)
- Equipment registry (table — view/edit equipment metadata; full add/remove via re-onboarding)
- Time zone
- Re-onboard building button

### Roles & permissions

- User list table: name, email, role, status (active / invited / suspended)
- Add user (invite by email)
- Per-row: change role, suspend, remove
- Role definitions (read-only display of what each role can do — links to permission matrix)
- Delegated permissions (P1): grant specific role-bypass per user per advisory tier

### Integrations

- BMS connector card: provider name, status (connected / disconnected), point count, last sync
- Email provider card: SendGrid/SES with API key (masked)
- SMS provider card: Twilio with phone number
- Pager / Slack (P2)
- GSASgate submission link (informational — submission still manual)

### Audit log

- Table of admin actions
- Columns: ts, actor, action, target, before, after
- Filter by actor, action type, date range
- Export to CSV

---

## States

- **Profile saved**: toast confirms
- **Integration disconnected**: card shows error chip + reconnect button
- **Role change requires confirmation**: modal "Changing Bilal from operator to facility_manager — confirm"
- **Suspended user**: row faded, "Suspended" chip
- **Re-onboarding** in progress: building locked from edits, banner explains
- **Read-only for current user role**: form fields disabled with tooltip

---

## Flows

### Flow A — Facility manager invites new operator

1. Settings → Roles → Add user
2. Email + role pick → invite sent
3. New user lands in "Invited" state
4. They accept invite, set password
5. Status → Active, can sign in

### Flow B — Engineer rotates SMS API key

1. Settings → Integrations
2. SMS card → click reveal/rotate
3. Modal confirms; new key generated, old key deactivated
4. Audit log records change

### Flow C — Manager edits baselines after meter upgrade

1. Building Settings → Baselines
2. Edits energy intensity benchmark (after new sub-meters added)
3. Save → confirm impact ("This affects GSAS scoring from this date forward")
4. Save → audit log entry

### Flow D — Auditor walk-through reviewing changes

1. GORD auditor asks "what was changed since last year's audit?"
2. Facility manager opens Audit Log
3. Filters by date range = last 12 months
4. Exports CSV
5. Hands to auditor

---

## Design principles

1. **Defaults work**. Settings rarely need touching after initial setup.
2. **Audit log is sacred**. Every admin action persisted with diff.
3. **Permissions enforced server-side**. UI only hints at what's possible.
4. **Confirmation on destructive actions**. Suspend user, rotate keys, delete integration.
5. **Read-only graceful**. Operators see what they cannot edit, with explanation.
6. **Mobile / tablet**: forms reflow; complex flows require desktop.

---

## Edge cases

- Last facility_manager attempts to demote self: blocked, "Cannot remove last administrator"
- Integration disconnected → ARVIS still runs in degraded mode (no SMS, no audit package submission)
- Re-onboarding aborted mid-flow: building remains on prior config
- Role change for currently signed-in user: forces re-login

---

## Open questions

1. **Self-serve role changes** vs request-and-approve? P0 self-serve for facility_manager.
2. **Per-user notification prefs** lived here or in dedicated `/notifications` settings? Cross-link both directions.
3. **Audit log retention** — indefinite or N years? Legal Q.
4. **Integration setup wizards** — guided or raw form fields?

---

## Success criteria

- Facility manager onboards a new user in <2 min
- All admin actions appear in audit log within 1s
- Settings screens unmistakably indicate permission state

## What designer needs from product

- Final permission matrix
- List of integrations supported P0
- Audit log retention policy

## Changelog

- v1 2026-05-23: initial
