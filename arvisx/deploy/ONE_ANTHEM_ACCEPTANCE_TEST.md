# One Anthem — Manual Acceptance Test (on-site)

Run this in the building once the stack is deployed, onboarded, and the bot is paired.
You need: a laptop/phone on the **console** (owner login) + a **technician phone** with
WhatsApp whose number is in the roster. Tick PASS/FAIL as you go.

---

## 0. Pre-flight
- [ ] Open `https://<your-domain>` — loads with a **padlock** (HTTPS).
- [ ] Owner logs in (the `ARVISX_ADMIN_USER` / password).
- [ ] Bot is paired — `docker compose logs bot` shows it connected (scan the QR from the logs first if not).
- [ ] People shows the real roster, each tech "PIN set".

## 1. Assign a round (manager, console)
- [ ] Operations → **Assign Round** → pick a template (e.g. Shift I) + a real technician (one with a phone).
- [ ] The round appears in Operations as **Open / assigned**.

## 2. Technician receives + opens it (the adoption test)
- [ ] Within ~30s the tech's **WhatsApp** gets a DM from the bot with the round link.
- [ ] Tap the link → AllGud opens and drops **straight into the round** (no login).
- [ ] *Fallback if no DM:* open `https://<domain>/field`, building `one-anthem`, enter the tech's **PIN** → same round.

## 3. Fill the round (technician phone)
- [ ] A **tick** item → tap OK (auto-advances).
- [ ] A **reading** item → type a real number → Save.
- [ ] One item → tap **Issue** (it should pause, let you note it).
- [ ] **Add photo** → camera opens → take a photo → it attaches.
- [ ] Tap through to the end → **Submit round** → "Round submitted" screen.

## 4. Manager sees it (console)
- [ ] Overview → **"What changed today"** shows *round submitted* + *issue opened*.
- [ ] Operations → the round shows **Review/Complete**; open it → entries + the **photo** are visible.
- [ ] Issues → the flagged item is listed with its detail.
- [ ] Apply a **supervisor sign-off** on the round.

## 5. Issue lifecycle
- [ ] Open the issue → **assign** to a technician or vendor → mark **In Progress** → **Resolve**.
- [ ] Status + SLA timer behave (resolved closes it; reopening resets escalation).

## 6. WhatsApp Q&A + digest (owner phone)
- [ ] Message the bot: **"how is the building?"** → sensible deterministic reply.
- [ ] Ask **"any issues?"** → reflects the issue you raised.
- [ ] Confirm the **daily digest** arrives to the owner (or trigger via Intelligence → sweeps).

## 7. Offline resilience (the honest stress test)
- [ ] Start a new round on the tech phone.
- [ ] Put the phone in **airplane mode** mid-round; keep answering checks → they show **"saved on this phone — will sync"**.
- [ ] Turn network back on → the queued entries **sync**; Submit succeeds (no lost taps).

## 8. Second technician / sharing access
- [ ] People → **Set/Reset PIN** for another tech.
- [ ] People → **Field link** (copy) → open on a different phone → lands authed in that tech's rounds.

## 9. Honesty / correctness spot-checks (these must hold)
- [ ] Confidence shown as **Low / Medium / High** bands — **never a %**.
- [ ] Assets show **"last checked"**, never "Online" (no live sensors in Phase 0).
- [ ] AI/advisory text carries a **source badge**; no invented numbers.
- [ ] Header says **"Maintenance Readiness"** (not live equipment condition).

## 10. Missed-round behaviour (optional, next day)
- [ ] A round left unsubmitted past its window shows **Lapsed** (console) / **Missed** (field, read-only) — not a silent disappearance.

---

### If something fails
- Bot DM didn't arrive → check the tech has a **phone** in the roster + bot card = Connected.
  The **Field link** / PIN path still works regardless.
- Field link hits a login wall → confirm `ARVISX_PUBLIC_URL` = the SPA origin (HTTPS).
- Photo/clipboard fails → must be **HTTPS** (secure context), not plain HTTP.

### What this proves
The full loop a building actually lives: assign → tech fills on the phone → issue raised →
manager sees it → signed off → owner informed on WhatsApp — with no lost data on flaky signal.
