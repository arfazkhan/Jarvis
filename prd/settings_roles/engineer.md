# Settings & Roles — Frontend Engineer Brief

**Feature**: `/settings` — admin surface for profile, building settings, roles, integrations, audit log.

**Audience**: Frontend engineer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is a Next.js SaaS for building operators. Settings is the admin sub-app. Backed by REST endpoints. Permission-gated per route. Audit log captures every change. Multi-tenant data isolation enforced server-side; UI hides irrelevant controls.

---

## What you're building

Sub-routes under `/settings/`:
- `/profile` — own user
- `/notifications` — own notification prefs (delegated to `notifications/` feature)
- `/building` — building config
- `/roles` — user list + role assignments
- `/integrations` — connectors
- `/audit-log` — admin history

Plus permission gating at the layout level.

---

## Stack

Same as `shell/`. Forms: `react-hook-form` + `zod`. Tables: `@tanstack/react-table`.

---

## File layout

```
app/(authed)/settings/
  layout.tsx                       — sub-nav + permission guard
  profile/page.tsx
  notifications/page.tsx           — imported from notifications/
  building/page.tsx
  roles/page.tsx
  integrations/page.tsx
  audit-log/page.tsx

components/settings/
  SettingsSubNav.tsx
  ProfileForm.tsx
  BuildingConfigForm.tsx
  BaselinesForm.tsx
  EquipmentRegistryTable.tsx
  RolesTable.tsx
  InviteUserModal.tsx
  RoleEditModal.tsx
  IntegrationCard.tsx
  IntegrationSetupModal.tsx
  AuditLogTable.tsx
  AuditLogFilters.tsx

lib/
  api/
    settings.ts
    integrations.ts
    audit.ts
```

---

## Data dependencies

### Endpoints

```
GET   /api/v1/settings/profile                       → Profile
PATCH /api/v1/settings/profile                       → Profile

GET   /api/v1/settings/{building_id}                 → BuildingSettings
PATCH /api/v1/settings/{building_id}                 → BuildingSettings

GET   /api/v1/settings/{building_id}/roles           → UserRole[]
POST  /api/v1/settings/{building_id}/roles/invite    → { invite_token }
PATCH /api/v1/settings/{building_id}/roles/{user_id} → UserRole
DELETE /api/v1/settings/{building_id}/roles/{user_id} → 204

GET   /api/v1/settings/{building_id}/integrations            → Integration[]
PATCH /api/v1/settings/{building_id}/integrations/{provider} → Integration

GET   /api/v1/settings/{building_id}/audit-log?...   → AuditEntry[]
```

---

## Components

### `<SettingsSubNav>`

Left rail or top tabs.

Items conditionally rendered based on role:
- Profile + Notifications: all roles
- Building, Roles, Integrations: facility_manager + engineer
- Audit Log: facility_manager + engineer

### `<ProfileForm>`

Form with: name, email (read-only post-signup), phone, avatar upload, password change.

### `<BuildingConfigForm>`

Sectioned form:
- General (name, timezone, building category)
- Rating Period (start, end dates)
- GSAS (version, locked status)
- Owner-of-record
- Baselines (sub-form: energy intensity, occupancy schedule, setpoints, comfort thresholds)
- Equipment Registry (table with view/edit metadata; add/remove triggers re-onboarding)

Auto-save with debounce, OR explicit Save button. Recommendation: explicit Save with confirm if change affects scoring.

### `<RolesTable>`

`@tanstack/react-table` with columns: user, email, role, status, last sign-in, actions.

Actions menu: change role, suspend / reinstate, remove.

```tsx
<DropdownMenu>
  <DropdownMenuItem onClick={() => openRoleEdit(user)}>Change role</DropdownMenuItem>
  <DropdownMenuItem onClick={() => suspendUser(user)}>Suspend</DropdownMenuItem>
  <DropdownMenuItem onClick={() => removeUser(user)} className="destructive">Remove</DropdownMenuItem>
</DropdownMenu>
```

### `<InviteUserModal>`

Form: email + role.

Submit → backend sends invite email with `invite_token`. Modal closes with success toast.

### `<IntegrationCard>`

Per integration:
- Provider name + logo
- Status chip (connected / disconnected / error)
- Last sync timestamp
- Action: Configure / Reconnect / Rotate Key / Test

### `<IntegrationSetupModal>`

Provider-specific form. Examples:
- Email (SendGrid): API key, from address
- SMS (Twilio): account SID, auth token, phone number
- BMS connector: connection string, point namespace prefix

API keys masked; reveal-on-click with auth challenge.

### `<AuditLogTable>`

Paginated table with: ts, actor, action, target, before, after.

Filter by actor, action type, date range. Export CSV.

Click row → expanded JSON diff modal.

---

## State management

- React Query for all server data
- `react-hook-form` for form state
- URL params for audit log filters

---

## Permission enforcement

UI hides controls user lacks permission for. Backend enforces independently — UI is hint, not gate.

Use `useMe()` from shell to check role; render conditionally.

For mutations: backend returns 403 if forbidden. Surface as toast: "You don't have permission for this action."

---

## Performance budgets

| Operation | Target |
|---|---|
| Settings load | <800ms |
| Profile save | <500ms |
| Role change | <500ms |
| Integration test | <3s (real network call) |
| Audit log pagination | <500ms |

---

## Testing

### Unit

- Permission gating: operator can't see Roles tab
- Form validation per section
- Audit diff renderer handles nested object diffs

### Integration

- Invite user → invite token returned → email sent (mock)
- Role change → audit log entry created
- Integration disconnect → status updates immediately
- Audit log filter persists in URL

### Visual

- All sub-pages in default + read-only states
- Modal forms (invite, role edit, integration setup)
- Audit diff expanded view

---

## Accessibility

- Forms use proper `<label>` + `aria-describedby` for errors
- Tables: row selection via keyboard, sortable headers announce sort state
- Modals: focus trap, ESC close
- Destructive actions: extra confirm + clear language

---

## Edge cases

- Last admin attempts to demote self: backend 409 → UI explains
- Concurrent edits: optimistic + revert + warn
- Integration disconnected mid-action: defer + retry
- Invite email bounces: status changes to "Invite failed" with retry

---

## Integration points

- `shell/` — me data + role determines visible sub-nav
- `onboarding_wizard/` — re-onboarding entry point
- `notifications/` — preferences sub-page lives here
- `compliance_gsas/` — settings affect scoring; warn on save

---

## Open questions

1. **Settings auto-save vs explicit Save**: per-section policy?
2. **Equipment registry edit scope**: metadata only, or includes BACnet mapping (which sits in onboarding)?
3. **Invite token expiry**: 7 days? 24h?
4. **Audit log retention**: indefinite or N years?

## Changelog

- v1 2026-05-23: initial
