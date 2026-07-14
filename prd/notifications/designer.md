# Notifications — Product Designer Brief

**Feature**: Bell, toasts, banners, email, SMS, and pager rules. How ARVIS reaches the operator without them looking at the screen.

**Audience**: Product designer, no ARVIS context.

---

## 30-second ARVIS primer

ARVIS is an AI advisor for building operators. It produces Advisories. Operators don't always have the UI open — they might be walking the building, at a desk doing other work, or off-shift. Notifications are how ARVIS pulls operator attention back to the UI when something needs human action.

---

## Why this exists

Without notifications:
- Critical advisories sit unseen for hours
- Operators wake up to disasters
- Pager / SMS / email patterns inconsistent
- Fatigue from over-notification leads to ignored notifications (false-alarm tolerance)

This feature defines:
- What gets notified
- Where (bell / toast / email / SMS / pager)
- When (immediate / digest / scheduled)
- To whom (role-based + on-call rotation)

---

## Users

- **Operator** — receives most notifications
- **Facility manager** — receives T3 escalations + weekly digest
- **Owner** — opt-in to critical incidents only
- **AI engineer** — receives system-health notifications

---

## Scope

**In**:
- In-app bell with unread count
- Toast (transient, in-app)
- Banner (persistent, in-app) for critical
- Email digests + immediate
- SMS for critical (P1)
- Pager / Slack / Teams (P2)
- Per-user notification preferences
- Quiet hours
- Snooze category (e.g., "no T1 notifications until 09:00")

**Out**:
- BACnet alarm notifications (separate BMS responsibility)
- Marketing / product updates
- Phone calls (out of scope)

---

## Notification triggers (default mapping)

| Event | In-app bell | Toast | Banner | Email | SMS | Pager |
|---|---|---|---|---|---|---|
| New T1 advisory | yes | no | no | digest only | no | no |
| New T2 advisory | yes | yes | no | digest | no | no |
| New T3 advisory | yes | yes | no | immediate | yes | yes (on-call) |
| Critical fault (engine-level) | yes | yes | yes | immediate | yes | yes |
| Verifier gate failed | yes | yes | no | digest | no | no |
| Operator action expected (snooze expired) | yes | yes | no | no | no | no |
| Weekly briefing | no | no | no | scheduled | no | no |
| GSAS score drop | yes | yes | no | digest | no | no |
| System status (ARVIS down) | yes | yes | yes (engineer only) | immediate | no | no |

Pilot tunes per building.

---

## Layout

### In-app bell (lives in shell)

- Outline icon (no unread) / filled icon (unread) / red dot (active critical)
- Numeric badge for 1-9 unread, "9+" for higher
- Click → opens advisory drawer

### Toast

- Top-right corner, 480px max width
- Auto-dismiss 10s (T1/T2), 30s (T3), 60s (critical)
- "Undo" / "View" / "Dismiss" action buttons
- Stack up to 4; older auto-dismiss
- Live region for screen reader

### Banner

- Top of screen below shell top bar
- Red (critical) / amber (warning) / blue (info)
- Persistent until acknowledged
- Dismiss button + "View advisory" action

### Email digest

- Daily (default 07:00 building time)
- Weekly (Sunday 18:00) for managers
- Subject line: "ARVIS — Marina Heights — 3 new advisories, 1 critical"
- Body: prioritized list, click-through to specific advisory in UI

### Notification preferences screen

Accessed from user menu → Settings → Notifications.

- Per-channel preferences (enable/disable each: bell, toast, email, SMS)
- Per-event-type preferences (T1/T2/T3, GSAS, system, etc.)
- Quiet hours (start / end / days)
- Vacation mode (silence all for N days, opt-in)
- On-call schedule (P2 — for facilities team rotation)

---

## States

- **No notifications**: bell outline, empty drawer
- **All read**: bell outline, but drawer has history
- **Active critical**: bell red pulse + banner active
- **In quiet hours**: bell still updates but no toast/email
- **Vacation mode**: all notifications routed to backup contact (P2)
- **System down**: persistent banner "ARVIS engine offline, contact support"

---

## Flows

### Flow A — Critical advisory raised at 3am

1. Engine raises T3 critical
2. Operator (on-shift) gets: toast + banner + SMS + bell badge
3. Operator clicks any → opens Advisory Detail
4. Reviews, takes action

### Flow B — Operator on quiet hours

1. T1 advisory raised
2. Bell badge increments silently
3. No toast, no email
4. Operator opens UI at shift start, sees badge

### Flow C — Operator off-shift, T3 raised

1. Pager fires to on-call manager (per rotation)
2. Manager opens UI, takes action
3. Operator returns, sees action taken in audit history

### Flow D — Customizing preferences

1. Operator dislikes SMS frequency
2. Settings → Notifications → SMS toggle off for T2
3. Saves
4. Next T2: no SMS, but bell + toast still fire

---

## Design principles

1. **Severity-proportional intensity**. T1 quiet, T3 loud.
2. **Never silently lose a critical**. T3 + critical bypass quiet hours.
3. **Operator owns their preferences**. Defaults sensible, customizable freely.
4. **One source of truth in-app**. Bell is canonical; toast / email are amplifications.
5. **Avoid fatigue**. Cap toasts to 4 visible; collapse to bell at higher rate.
6. **Banner is rare**. Reserve for engine-down or active critical only.

---

## Edge cases

- 50 advisories raised at once (engine restart, alarm flood): collapse to single bell entry "27 new advisories raised" with link to feed; no toasts
- Email delivery fails: queue + retry; surface failure in Settings
- SMS opt-in not provided: greyed in prefs with "Add phone number" CTA
- Quiet hours + critical: critical overrides, banner explains "Bypassed quiet hours due to critical"
- User signed in on multiple devices: notification deduped per advisory, all devices clear when one device opens

---

## Open questions

1. **Default delivery channels per role** — operator gets SMS by default? Facility manager?
2. **Email digest timing** — building local time vs server time?
3. **Banner dismissal** — auto when condition clears or always manual?
4. **Snooze category UX** — global snooze button, or per-event-type? Per-event-type proposed.
5. **Pager integration** — which providers? Twilio? PagerDuty?
6. **Operator off-boarding** — what happens to their preferences + on-call rotation?

---

## Success criteria

- T3 critical reaches on-shift operator <60s p95
- Off-shift critical reaches on-call <5 min p95
- ≥90% operators customize prefs within first 2 weeks
- Bell badge consistency: never out of sync with feed

## What designer needs from engineering

- Final default channel mapping per event type
- SMS provider + format constraints (160 char limit)
- Email template constraints (HTML support level)
- On-call rotation schema (P2)

## Changelog

- v1 2026-05-23: initial
