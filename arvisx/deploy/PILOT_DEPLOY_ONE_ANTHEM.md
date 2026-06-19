# AllGud — One Anthem Pilot Deployment Runbook

The **checklist product** (no sensors): manager console + phone-first field app +
WhatsApp bot, behind one HTTPS origin. Deterministic engine, SQLite, single VPS.

```
            https://oneanthem.<domain>     (Caddy: auto-TLS)
                 │  /api/* → api:8090   ·   /* → SPA (deep-link fallback)
        ┌─────────┴─────────┐
       api (engine, SQLite)  └─ internal ─ bot (WhatsApp, Baileys)
```

---

## 0. Prerequisites

- **VPS**: 1 vCPU / 2 GB RAM / 20 GB disk, Ubuntu 22.04+. Docker Engine + Compose plugin.
- **Domain**: a subdomain (e.g. `oneanthem.allgud.app`) with an **A-record → VPS public IP**.
- **Firewall**: inbound **80** and **443** open (Caddy needs 80 for the ACME challenge).
- **WhatsApp**: a dedicated phone/number for the bot (see the channel note in §6).

> Why HTTPS is non-negotiable: WhatsApp deep-links, the camera capture, and the
> "Field link" clipboard copy all require a secure context. Plain HTTP won't do for
> the real pilot.

---

## 1. Get the code (with the bot submodule)

```sh
git clone --recurse-submodules <main-repo-url> /opt/allgud
cd /opt/allgud/arvisx/deploy
# If you cloned without --recurse-submodules:
git submodule update --init --recursive
```

The bot lives at `arvisx/bot` (submodule → github.com/arfazkhan/wa_bot).

---

## 2. Configure

```sh
cp .env.pilot.example .env
# generate two secrets:
openssl rand -hex 32   # -> ARVISX_API_KEY
openssl rand -hex 32   # -> ARVISX_AUTH_SECRET
nano .env
```

Set at minimum: `DOMAIN`, `ARVISX_API_KEY`, `ARVISX_AUTH_SECRET`,
`ARVISX_ADMIN_USER`, `ARVISX_ADMIN_PASSWORD`, `OWNER_NUMBER`.
(`ARVIS_API_KEY` for the bot is derived from `ARVISX_API_KEY` automatically.)

---

## 3. Bring up the stack

```sh
docker compose -f docker-compose.pilot.yml up -d --build api web
```

Verify:
```sh
curl -sI https://$DOMAIN | head -1                 # 200 (SPA loads, cert issued)
curl -s  https://$DOMAIN/api/v1/auth/me            # {"username":null,"role":null} or 401
```
If the cert doesn't issue: confirm the A-record resolves and 80/443 are open.

---

## 4. Onboard One Anthem (real data)

```sh
cp onboard.one-anthem.example.json onboard.json
nano onboard.json     # REAL roster + DISTINCT field PINs, vendors, real PPM dates
docker compose -f docker-compose.pilot.yml cp onboard.json api:/data/onboard.json
docker compose -f docker-compose.pilot.yml exec api python -m arvisx.onboard /data/onboard.json
```

Expected: `technicians: N (N with a field PIN)`. The 4 checklist templates
(Shift I/II/III + PPM) seed automatically from `seeds/one-anthem.json`.

> PINs are hashed at rest. Distribute them to each technician privately (not in a group).

---

## 5. Verify the console + field flow

**Console** — open `https://$DOMAIN`, log in as the owner:
- Overview renders Maintenance Readiness + "What changed today".
- Operations lists today's runs; People shows the roster with "PIN set".

**Field, on a real phone** (the step never tested on-device before — do it):
1. In People, tap **Field link** for a technician → paste it in the phone browser →
   it should land directly in the field app (deep-link token auto-auths).
2. Or open `https://$DOMAIN/field` → enter building `one-anthem` + the tech's PIN.
3. Assign a round (Operations → Assign), fill it: tick/reading/photo, flag one issue, submit.
4. Back in the console: the round shows submitted, the issue appears, the activity feed updates.

---

## 6. WhatsApp bot — first run (QR pairing)

> **Channel decision (do this consciously):** the bot uses **Baileys** (unofficial
> WhatsApp-Web). It works and is fast to stand up, but carries a **ban risk** for the
> number. For a short design-partner pilot it's acceptable; for anything longer, plan
> a move to the WhatsApp Business API. Use a dedicated number either way.

Pair once (interactive — the bot prints a QR to its logs; scan it with WhatsApp →
Linked devices → Link a device). Pairing is a deployer step, kept separate from the
AllGud console on purpose.
```sh
docker compose -f docker-compose.pilot.yml up -d --build bot
docker compose -f docker-compose.pilot.yml logs -f bot     # scan the ASCII QR
```
The session persists in the `bot-session` volume — no re-scan on restart.

Smoke: from the owner number, message the bot "how is the building?" → it replies
from live state. Assign a round in the console → the assigned tech gets a DM with a
deep-link straight into `/field/run/...`.

---

## 7. Daily operations

- Manager: assign rounds, watch completion, triage issues, request sign-off.
- Owner: receives the daily WhatsApp digest + critical alerts.
- Everything degrades to deterministic text if no LLM key is set (advisory still works).

---

## 8. Backups (do not skip)

The whole pilot is one SQLite file in the `api-data` volume. No backup = data loss.
```sh
chmod +x backup.sh
crontab -e
# nightly at 02:00:
0 2 * * * cd /opt/allgud/arvisx/deploy && ./backup.sh >> backup.log 2>&1
```
Restore: stop the stack, `docker compose cp backups/arvisx_<stamp>.db api:/data/arvisx.db`, start.

---

## 9. Security checklist (before handing the URL out)

- [ ] `ARVISX_ADMIN_PASSWORD` is strong and was changed from any default.
- [ ] `ARVISX_API_KEY` + `ARVISX_AUTH_SECRET` are random 32-byte hex, not placeholders.
- [ ] `.env` is not committed and is `chmod 600`.
- [ ] HTTPS confirmed (padlock); plain-HTTP `DOMAIN=:80` is staging only.
- [ ] Field PINs are distinct and were sent privately.
- [ ] Note: the field **PIN has no rate-limit** — fine for one trusted building; revisit
      before multi-tenant. The deep-link token is the primary path; PIN is the fallback.

---

## 10. Operate, troubleshoot, roll back

```sh
docker compose -f docker-compose.pilot.yml ps
docker compose -f docker-compose.pilot.yml logs -f api          # or web / bot
docker compose -f docker-compose.pilot.yml restart api
git pull --recurse-submodules && \
  docker compose -f docker-compose.pilot.yml up -d --build       # redeploy
docker compose -f docker-compose.pilot.yml down                  # stop (volumes kept)
```

---

## Known limits (set expectations with the committee)

- **Single-process / single-tenant** — sized for One Anthem; don't add building #2 to
  this instance.
- **No sensors (Phase 0)** — "Maintenance Readiness" reflects checklist/inspection
  state, not live equipment condition. Confidence is a band, never a %.
- **Baileys ban risk** — see §6.
- **First building = the proof** — no prior track record; manage expectations.
