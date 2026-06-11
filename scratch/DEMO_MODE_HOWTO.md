# ArvisX 48-Hour WhatsApp Demo — personal run

Two terminals + your phone. The building lives on your machine; ArvisX talks to you on
WhatsApp like a deployed pilot.

## Terminal 1 — the building (broker + API + digital twin)

```powershell
cd E:\Automation
$env:PYTHONPATH="E:\Automation"
.\venv\Scripts\python -u scratch\demo_mode.py
```

What you'll see: infra up → building commissioned → LEARNING → `OPERATIONAL` (the
readiness gate approves on evidence, usually within ~20 minutes) → quiet healthy
operation → at **hour 30** the booster starts degrading in real time → `INCIDENT_CAUGHT`
within ~45 minutes of onset. Timeline: `scratch/demo_timeline.jsonl`.

Ctrl+C stops it; restarting resumes warm (same `scratch/demo_mode.db` — baselines, WOs,
commissioning survive). Delete that file for a fresh demo.

## Terminal 2 — the WhatsApp bot

```powershell
cd E:\Automation\arvisx\bot
# .env (create/edit):
#   ARVIS_API_URL=http://127.0.0.1:8090
#   OWNER_NUMBER=<your number, country code, no +>   e.g. 9745xxxxxxx
#   TECHNICIAN_NUMBER=<same number — you get the checklist pings too>
#   RESPONSE_IN_DMS=true
#   AUTH_REQUIRED=true
#   DIGEST_HOUR=8
#   CHECKLIST_HOUR=9
npm start
```

First run prints a QR — scan with the **bot's** WhatsApp (a spare number/second phone is
ideal; it's a normal WhatsApp-Web link). Your own number is the OWNER and receives
everything.

## What your phone experiences (the script)

| When | What lands on your phone |
|---|---|
| ~20 min in | nothing — and that's the point. The building is learning; ArvisX won't cry wolf. |
| 08:00 daily | 📊 daily digest: readiness, 7 service tiles, issue count |
| 09:00 daily | 🔧 checklist pings: "pump room visual check? Reply: ok pump_room_visual" — reply and watch it log |
| any time | text it: "any issues?", "water status?", "gas status?", "what is this costing us?" |
| **hour 30** | the booster starts wearing (real-time physical drip on the twin) |
| **~hour 30.7** | ⚠️ *Water Availability Risk — Booster Pump 1 power creep (Nσ above its own normal)* 💸 money line, "Create work order?" |
| you reply | "create work order" → ✅ WO created. Loop closed. |

## Try a compressed rehearsal first (15 minutes instead of 48h)

```powershell
$env:DEMO_TOTAL_MIN="16"; $env:DEMO_FAULT_AT_MIN="6"; $env:DEMO_CADENCE_S="8"; $env:DEMO_CREEP_PCT_PER_MIN="1.5"
.\venv\Scripts\python -u scratch\demo_mode.py
```

Gate approves ~minute 4–5, incident at minute 6 (faster drip so it's catchable in the
window), caught ~minute 10–13. Same script, fast-forwarded — good for checking your
bot wiring before committing to the 48h run. (The 48h run uses the default slow drip,
+0.2%/min — a realistic hour-long degradation.)

## Notes
- Keep the laptop awake for the 48h run (power settings / `powercfg`), or run it on any
  always-on box — everything is localhost.
- The API runs **open** (no API key) on localhost for this demo. Don't port-forward it.
- To demo to a prospect later: same setup, add their number via the bot's `.auth` command
  (owner-only) — they become a viewer and receive the digest/alerts.
