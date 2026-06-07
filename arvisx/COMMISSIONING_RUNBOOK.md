# ArvisX — Building Commissioning Runbook

How a **non-engineer** (facility manager / supervisor) onboards a new building in
about **half a day**. Commissioning teaches ArvisX what this building has, what
its sensors mean, how its equipment depends on each other, and what "normal"
looks like — *before* it starts giving advice.

You do not need to write code. Every step is an API call (or a dashboard screen,
once the frontend exists). `BID` below = the building id returned in step 1.
Every call needs the header `X-API-Key: <your key>`.

---

## The gate (why you can't skip steps)

Commissioning is a **state machine**. You can't go OPERATIONAL until each gate is
satisfied — this is what keeps ArvisX from giving confident advice about a
building it doesn't understand.

```
DRAFT ─▶ ASSETS ─▶ SIGNALS ─▶ DEPENDENCIES ─▶ LEARNING ─▶ OPERATIONAL
  │         │          │            │             │            │
 name +   list the   map each    say what     watch live   live & giving
 services equipment  signal to   depends on   data until   advice
                     an asset    what         baselines
                                              settle
```

---

## Step 1 — Create the building  *(DRAFT)*

```
POST /api/v1/commission/building
{ "name": "Marina Heights Tower A", "services": ["water","power_backup","stp","pool","fire"] }
```
Returns the building record incl. **`BID`**. Pick only the services this building
actually has.

> **Shortcut — templates.** Instead of defining everything by hand, apply a
> service template that pre-loads the typical assets/signals for that service:
> `POST /api/v1/commission/building/{BID}/apply-template {"service":"water"}`
> Templates exist for water / power / stp / pool / fire. Apply, then edit.

---

## Step 2 — List the equipment  *(→ ASSETS)*

For each pump, tank, generator, blower, etc.:
```
POST /api/v1/commission/building/{BID}/assets
{ "asset_id":"booster_pump_a", "name":"Booster Pump A", "asset_type":"booster_pump",
  "service":"water", "design_attributes": { ... optional specs ... } }
```
**Design attributes matter** — rated power, tank capacity (litres), pump
flow-rate. They sharpen risk detection and the money math. Add what's on the
nameplate; skip what you don't know.

> **Discovery assist.** If sensors are already publishing, let ArvisX suggest the
> asset list from the live topic names:
> `POST /api/v1/commission/discover` → review the suggestions → accept/correct.

---

## Step 3 — Map the signals  *(→ SIGNALS)*

Tell ArvisX which incoming signal belongs to which asset and what it means
(power, runtime, level, pressure…):
```
POST /api/v1/commission/building/{BID}/signals
{ "asset_id":"booster_pump_a", "signal":"power_kw", "topic":"arvisx/booster_pump_a/power" }
```
This is the translation layer: raw telemetry → the operational language residents
see. Map every signal you want monitored.

---

## Step 4 — Declare dependencies  *(→ DEPENDENCIES)*

Tell ArvisX how equipment relates, so it can show downstream impact and lost
redundancy:
```
POST /api/v1/commission/building/{BID}/dependencies
{ "asset_id":"booster_pump_a", "depends_on":"underground_tank_1",
  "role":"primary", "redundancy":"booster_pump_b" }
```
Example: distribution depends on booster pumps, which depend on the tank. If a
tank issue appears, ArvisX can say "water distribution at risk, no backup tank."

---

## Step 5 — Learning mode  *(→ LEARNING)*

```
POST /api/v1/commission/building/{BID}/transition  { "to":"learning" }
```
Now ArvisX **watches live telemetry and learns each signal's normal range**
(robust median/MAD baselines). It does **not** alert yet — it's calibrating to
*this* building, not generic thresholds. Check progress:
```
GET /api/v1/commission/building/{BID}/learning
```
Let it run until baselines settle — typically a few days of representative
operation (covers daily on/off cycles). During this window ArvisX may raise
**validation questions** ("Is Booster Pump B a standby or always-on?"). Answer
them — they tune the model:
```
POST /api/v1/commission/building/{BID}/validations/{VAL_ID}/answer  { "answer":"standby" }
```

---

## Step 6 — Go live  *(→ OPERATIONAL)*

When learning progress is sufficient and validations are answered:
```
POST /api/v1/commission/building/{BID}/transition  { "to":"operational" }
```
ArvisX now produces readiness, risks, money estimates, work orders, the daily
digest, and answers WhatsApp questions. The gate blocks this until learning is
ready (override with `"force": true` only for demos/testing — never a real pilot).

---

## After go-live

- **Tuning happens automatically** — baselines keep adapting; drift is detected
  against the learned normal. No manual threshold-setting.
- **Close work orders with a cause** — `POST /workorders/{id}/close` with the real
  cause. This is the feedback loop: it trains the skillbook so repeat issues get
  recognised faster and with higher confidence.
- **Answer future validation prompts** as they appear.

---

## Checklist

- [ ] Building created, correct services selected
- [ ] All physical assets listed (+ design attributes where known)
- [ ] Every monitored signal mapped to an asset
- [ ] Dependencies + redundancy declared
- [ ] Learning mode run until baselines settled
- [ ] Validation questions answered
- [ ] Transitioned to OPERATIONAL (not forced)
- [ ] Owner/FM receiving the WhatsApp digest

Half a day of setup + a few days of passive learning = a building ArvisX
genuinely understands.
