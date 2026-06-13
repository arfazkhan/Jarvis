# ArvisX — Live Pilot Onboarding & Test Runbook

How to bring ArvisX up against a building (real or the digital-twin demo) and verify every tier
behaves. Written for the person running the pilot. Follow top to bottom the first time.

> **Demo vs real building:** the only difference is the data source. The demo uses the digital
> twin (`scratch/demo_mode.py`); a real building uses the edge gateway publishing MQTT. Everything
> below — bot, roles, commissioning, learning, the test matrix — is identical.

---

## 0. The three numbers (decide these first)

| Role | Number | What it does | Who holds it |
|---|---|---|---|
| **BOT** | `…885707` | ArvisX's WhatsApp identity. Scans the QR. You never text *from* it. | Reserved/spare SIM |
| **OWNER** | `…057376` | You. Tech voice, all alerts, daily digest, checklist pings, `.auth*` admin commands. | The pilot operator |
| **RESIDENT** | *3rd number* | A real resident. Resident voice (outcome only), can log requests, no work orders. | A test phone / a willing resident |

You need **all three** to test the full system. Bot + owner alone only exercises the tech tier.
(Optional 4th surface: a **group** the bot is added to → manager voice for the committee.)

---

## 1. Prerequisites (Day 0)

- [ ] Laptop/always-on box, kept awake (`powercfg` or plugged in) for the run length.
- [ ] Python env at `E:\Automation\venv`, Node/npm for the bot.
- [ ] Port **8091** free (8090 is squatted by Wondershare `WsToastNotification` on this machine — we use 8091).
- [ ] Bot `.env` filled (already done): `ARVIS_API_URL=http://127.0.0.1:8091`, `BOT_NUMBER`, `OWNER_NUMBER`,
      `TECHNICIAN_NUMBER`, `AUTH_REQUIRED=true`.
- [ ] Bot's WhatsApp logged out elsewhere (a fresh QR scan links it here).

---

## 2. Bring up the building (Terminal 1)

**Rehearsal (16 min — do this first, every time, to check wiring):**
```powershell
cd E:\Automation
$env:PYTHONPATH="E:\Automation"
$env:DEMO_API_PORT="8091"
$env:DEMO_TOTAL_MIN="16"; $env:DEMO_FAULT_AT_MIN="6"; $env:DEMO_CADENCE_S="8"; $env:DEMO_CREEP_PCT_PER_MIN="1.5"
.\venv\Scripts\python -u scratch\demo_mode.py
```

**Full 48h pilot run (realistic slow degradation):**
```powershell
cd E:\Automation
$env:PYTHONPATH="E:\Automation"
$env:DEMO_API_PORT="8091"
.\venv\Scripts\python -u scratch\demo_mode.py
```

You'll see the lifecycle in the log: `infra_up` → commissioned → **LEARNING** → **OPERATIONAL**
(readiness gate approves on evidence, ~20 min full / ~4–5 min rehearsal) → quiet healthy operation →
degradation at the fault minute → `INCIDENT_CAUGHT`. Timeline written to `scratch/demo_timeline.jsonl`.

Health check (any time, separate shell):
```powershell
curl http://127.0.0.1:8091/api/v1/whatsapp/digest
```

---

## 3. Bring up the bot (Terminal 2)

```powershell
cd E:\Automation\arvisx\bot
npm start
```

- First run prints a **QR** → scan with the **BOT** number's WhatsApp.
- On connect it verifies the linked account matches `BOT_NUMBER` and warns if not.
- Watch for: `🔔 Notifier started …` — the alert poller + digest/checklist schedulers are live.

---

## 4. Authorize people (owner runs these, from the OWNER phone)

The owner is auto-trusted. Everyone else must be added. **Pick the right command per role:**

| Command | Adds them as | Voice they get | Run from |
|---|---|---|---|
| `.auth <number>` | FM / technician | **tech** (asset IDs, σ, actions) + can raise work orders | DM or group |
| `.authresident <number>` | resident | **resident** (outcome only) — no work orders | DM or group |
| `.authgroup` | the whole group | **manager** (softened) | inside that group |

All three also accept a **reply** to the person's message or an **@mention** instead of typing the number.

> For the test: from the OWNER phone, send `.authresident <3rd number>`. That 3rd number is now a
> resident. Without this it would be silently ignored (auth on) — the resident voice has no other route.

To switch a number from FM→resident, just `.authresident` it (it's removed from the FM list automatically).

---

## 5. Test matrix — verify every tier

| # | From | Send | Expect |
|---|---|---|---|
| 1 | OWNER | `any issues?` | Tech voice: `[XFER-PUMP-01] … power creep (3.2σ…) → action [High]` |
| 2 | OWNER | `water status` | Raw service line, asset detail |
| 3 | RESIDENT | `is the pool open?` | `🏊 Pool operational` — **no** IDs / % / σ / confidence |
| 4 | RESIDENT | `any issues?` | Outcome summary; warnings invisible, only CRITICAL shows as "disruption" |
| 5 | RESIDENT | `create work order` | `✅ Noted … ref RR-1` **and** within 60s OWNER gets `📩 Resident request RR-1 from +91…` |
| 6 | GROUP (if set) | `arvis any issues?` | Manager voice: "working harder than usual" — **not** "power creep (3.2σ)" |
| 7 | — wait for fault — | (auto) | OWNER gets `⚠️ Water … Risk` alert + money line + "create work order?" |
| 8 | OWNER | `create work order` | `✅ WO created` — loop closed |

**Anti-ban behaviour to watch (Phase A):**
- The digest header / alert CTA **wording changes** between sends (not identical every time).
- A burst of alerts arrives **spaced out** (seconds apart), not all in the same instant.
- The numbers, asset names, and `RR-n` refs are **always exact** inside the varied wrapper.

**Honesty checks:**
- Resident `create work order` must NOT claim "noted" unless RR-n actually comes back (it's recorded first).
- If the bot drops the WhatsApp connection and reconnects, alerts must keep arriving (no stale-socket loss),
  and a resident request must still reach the owner (re-delivered until acked).

---

## 6. Daily rhythm (what the building feels)

| When | What happens |
|---|---|
| 08:00 (`DIGEST_HOUR`) | Daily digest to owner + groups: readiness, service tiles, issue count |
| 09:00 (`CHECKLIST_HOUR`) | Checklist pings to the technician: "pump room visual? reply: ok pump_room_visual" |
| 17:00 (`CHECKLIST_REMINDER_HOUR`) | Reminder for still-pending checklist items |
| every 60s (`ALERT_POLL_MS`) | New alerts + resident-request relays pushed (deduped, rate-capped) |
| any time | Anyone authorized can text questions; residents get the resident voice |

Reply to a checklist ping: `ok pump_room_visual` or `issue pump_room_visual <note>` → logged with timestamp.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `bind: address already in use` on 8090 | Wondershare. We use 8091 — set `DEMO_API_PORT=8091`, `.env` already on 8091. |
| Bot can't reach API | Terminal 1 not up, or URL not 8091. `curl …8091/api/v1/whatsapp/digest`. |
| QR won't scan / wrong account | Bot's WhatsApp linked elsewhere; the bot warns if linked account ≠ `BOT_NUMBER`. Re-link. |
| Resident gets tech voice | They're in the FM list — re-run `.authresident <number>` (auto-moves them). |
| Resident message ignored entirely | Not authorized. `.authresident` them. |
| No alerts ever | Building still LEARNING (by design — won't cry wolf), or no fault yet. Check `demo_timeline.jsonl`. |
| Alerts stopped after reconnect | Should be fixed (single rebound socket). If seen, capture bot logs — regression. |

---

## 8. Fresh start vs warm resume

- **Resume warm:** Ctrl+C, rerun. `scratch/demo_mode.db` keeps baselines, work orders, commissioning,
  and resident requests — the building picks up where it left off.
- **Clean slate:** delete `scratch/demo_mode.db` (and the bot's `data/authorized_*.json` to reset who's
  authorized) before rerunning.

---

## 9. What changes for a REAL building (not the demo)

- **Data source:** edge gateway publishes real MQTT instead of the twin. Point ArvisX at the real broker
  (`ARVISX_SOURCE=mqtt`, `ARVISX_MQTT_BROKER/PORT`). Everything else is the same.
- **Commissioning:** import the building's real assets/zones/specs instead of the demo fleet.
- **API security:** set an API key (not open localhost), don't port-forward.
- **WhatsApp:** Baileys + anti-ban Phase A is the PILOT posture. A paying building should move to the
  official **WhatsApp Business API** (Meta-approved templates, no ban risk) — cost it into the pilot→production plan.
- **Fire:** advisory only, alongside the certified panel — never the monitoring system of record.

---
*Pairs with `DISCOVERY_QUESTIONNAIRE.md` (pre-sale), `PILOT_AGREEMENT.md`, `PILOT_LAUNCH_ROADMAP.md`.
Demo internals: `scratch/DEMO_MODE_HOWTO.md`.*
