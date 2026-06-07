# ArvisX — Pilot Deployment Runbook

How to stand up ArvisX for a real residential community. ~30 minutes to a running
stack; commissioning the building is a separate half-day (see
`COMMISSIONING_RUNBOOK.md`).

The pilot runs on the **deterministic floor** — no LLM, no cloud dependency, no
hallucination. It needs only Docker.

---

## 0. What gets deployed

```
┌──────────┐   MQTT    ┌──────────────┐   REST    ┌──────────────┐
│ sensors/ │ ────────▶ │   broker     │ ◀──────── │   api        │
│ gateway  │  :1883    │ (mosquitto)  │           │ (ArvisX)     │
└──────────┘           └──────────────┘           └──────┬───────┘
                                                          │ REST :8090
                                                   ┌──────┴───────┐
                                                   │   bot        │
                                                   │ (WhatsApp)   │
                                                   └──────────────┘
```

Three containers, one network: **broker** (MQTT in), **api** (engine + REST),
**bot** (WhatsApp out). State is on Docker volumes (DB, broker data, WhatsApp
session) so restarts are safe.

---

## 1. Prerequisites

- Docker + Docker Compose v2 (`docker compose version`).
- A dedicated WhatsApp number for the bot (a spare SIM / second phone). The bot
  logs in by scanning a QR with that phone, like WhatsApp Web.
- The building's owner/FM phone numbers (country code, no `+`).
- A host on the **building LAN** the sensors/gateway can reach on port 1883.

---

## 2. Configure

```bash
cd arvisx

cp .env.example .env
cp bot/.env.example bot/.env
```

Edit **`.env`** (the API):
- `ARVISX_API_KEY` — generate one:
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `ARVISX_TARIFF` / `ARVISX_CURRENCY` — `0.11` / `QAR` for Qatar; `8` / `INR` for India.
- `ARVISX_CORS` — set to your dashboard URL once a frontend exists (leave `*` for now).

Edit **`bot/.env`** (the WhatsApp bridge):
- `ARVIS_API_KEY` — **paste the exact same key** as the API.
- `OWNER_NUMBER` — owner's number, e.g. `9745xxxxxxx`.
- Leave `ARVIS_API_URL=http://api:8090` (compose networking; the bot adds `/api/v1`).

---

## 3. Bring it up

```bash
# broker + api first
docker compose up -d broker api

# verify the API is alive (401 = up & secured, that's expected without the key)
curl -s -H "X-API-Key: $YOUR_KEY" http://localhost:8090/api/v1/community/overview | head

# bot — run ATTACHED the first time to scan the WhatsApp QR
docker compose up bot
#   → a QR code prints in the terminal. Open WhatsApp on the bot phone →
#     Settings → Linked Devices → Link a Device → scan it.
#   → once "connected" appears, Ctrl-C and restart detached:
docker compose up -d bot
```

The WhatsApp session is saved on the `bot-session` volume — you scan **once**.

Smoke test: from the owner's phone, WhatsApp the bot **"how is the building?"** —
you should get the daily-summary card.

---

## 4. Point sensors at the broker

Each sensor / gateway publishes JSON to the broker on `:1883`. Topic and payload
shape are handled by `arvisx/ingest/topics.py`. Typical:

```
topic:   arvisx/<asset_id>/<signal>
payload: {"value": 12.4, "ts": "2026-06-07T10:00:00Z"}
```

No hardware yet? Run with the simulator instead — set `ARVISX_SOURCE=sim` in
`.env` and restart `api`. The full engine runs on simulated telemetry so the
committee can see real screens/answers before devices arrive. You can also drive
demo scenarios: `POST /api/v1/scenario/{name}`.

After devices are live, **commission the building** → `COMMISSIONING_RUNBOOK.md`.

---

## 5. Securing the broker (before anything leaves the LAN)

The default `mosquitto.conf` allows anonymous connections — fine only on an
isolated building LAN. For anything routable:

1. In `mosquitto/mosquitto.conf` set `allow_anonymous false` and add
   `password_file /mosquitto/config/passwd`.
2. Create the file:
   `docker compose exec broker mosquitto_passwd -c /mosquitto/config/passwd arvisx`
3. Put the same user/pass on every sensor/gateway and (if needed) in the API's
   MQTT settings. Restart `broker` then `api`.
4. **Never** publish port `1883` to the internet. Bind it to the LAN interface
   in `docker-compose.yml` (`"192.168.x.x:1883:1883"`) or drop the `ports:`
   mapping entirely and keep it on the Docker network.

API auth (`ARVISX_API_KEY`) is mandatory the moment the API is reachable beyond
localhost. The app logs a warning if it's blank.

---

## 6. Operate

| Task | Command |
|------|---------|
| Logs | `docker compose logs -f api` (or `bot`, `broker`) |
| Restart a service | `docker compose restart api` |
| Update after code change | `docker compose up -d --build api` |
| Stop all | `docker compose down` (volumes/data preserved) |
| Reset all data | `docker compose down -v` ⚠️ wipes DB + WhatsApp session |
| Back up | copy the `api-data` volume (the SQLite DB is the source of truth) |

**Backups:** the SQLite DB on `api-data` holds events, learned baselines, work
orders, and the skillbook. Snapshot it periodically:
`docker compose cp api:/data/arvisx.db ./backup-$(date +%F).db`

---

## 7. Health & troubleshooting

- **API container unhealthy** → `docker compose logs api`. Healthcheck only needs
  the port to answer; a crash loop is usually a bad `.env`.
- **Bot won't connect / QR expired** → `docker compose run --rm bot` to rescan;
  if the session is corrupt, `docker volume rm arvisx_bot-session` and re-link.
- **Bot replies "unauthorized"** → `ARVIS_API_KEY` mismatch between `.env` files.
- **No data / everything "not monitored"** → no telemetry arriving. Check the
  broker (`docker compose logs broker`), sensor connectivity, and that the
  building has been commissioned to OPERATIONAL.
- **Money looks wrong** → check `ARVISX_TARIFF`/`ARVISX_CURRENCY`.

---

## 8. Pilot acceptance checklist

- [ ] `docker compose up -d` brings up all three, all healthy.
- [ ] API rejects requests without the key, accepts with it.
- [ ] Broker is LAN-only / anonymous disabled (if networked).
- [ ] Owner gets the daily digest on WhatsApp.
- [ ] "any issues?" / "water status?" / "what is this costing us?" answer correctly.
- [ ] Building commissioned to OPERATIONAL (`COMMISSIONING_RUNBOOK.md`).
- [ ] DB backup job in place.
- [ ] LLM stays OFF (`ARVIS_X_LLM=0`) — deterministic floor only.

---

*ArvisX is read-only / advisory. It never controls equipment. Fire signals are
supplementary visibility only — never the certified fire system of record.*
