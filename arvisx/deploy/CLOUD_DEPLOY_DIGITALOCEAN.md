# AllGud — Cloud Deploy to DigitalOcean (fully remote, from your machine)

Deploy the One Anthem pilot to a DigitalOcean Droplet without going on-site.
Model: **build images on your machine → push to GHCR → the Droplet pulls them.**
No source code on the server. Pair the WhatsApp bot remotely via the console QR.

```
your machine ──build+push──▶ GHCR ──pull──▶ DO Droplet (Ubuntu + Docker)
                                              caddy(HTTPS) + api + bot
   you scan the bot QR from the console (Intelligence ▸ WhatsApp Bot)
```

---

## 0. Prerequisites (one-time)
- DigitalOcean account (your $200 credit).
- A domain (or subdomain) you can add a DNS record to, e.g. `oneanthem.<yourdomain>`.
- On your machine: Docker Desktop (you have it) + the repo.
- A GitHub Personal Access Token (classic) with **`write:packages`** (to push) — and
  the Droplet will use one with **`read:packages`** (to pull).

---

## 1. Build + push the images (your machine)
```sh
cd arvisx/deploy
echo <YOUR_PAT> | docker login ghcr.io -u arfazkhan --password-stdin
REGISTRY=ghcr.io/arfazkhan TAG=latest ./build-and-push.sh
```
This builds `allgud-api`, `allgud-web` (with `VITE_API_BASE=/api/v1`), `allgud-bot`
for `linux/amd64` and pushes all three.

> Make the 3 GHCR packages **private** (default) — the Droplet authenticates to pull.

---

## 2. Create the Droplet
- Create → Droplets → **Ubuntu 22.04 LTS**.
- Plan: **Basic, Regular — 2 GB RAM / 1–2 vCPU** ($12–18/mo; builds happen on your
  machine, so the server is light). $200 credit ≈ a year+.
- Region: closest to the building (e.g. **BLR1 / Bangalore** for India).
- Auth: add your **SSH key**.
- Note the **public IP**.

---

## 3. DNS
- Point `oneanthem.<yourdomain>` **A-record → the Droplet IP**.
  (If your domain's DNS is on DigitalOcean: Networking → Domains.)
- Wait until `ping oneanthem.<yourdomain>` resolves to the IP (TTL).

---

## 4. Install Docker on the Droplet
```sh
ssh root@<droplet-ip> 'bash -s' < bootstrap-droplet.sh
```
Installs Docker + compose, opens 80/443, keeps SSH.

---

## 5. Ship the 3 small config files (NOT the source)
On your machine, prepare `.env` and `onboard.json` locally first:
```sh
cp .env.pilot.example .env       # fill DOMAIN, secrets (openssl rand -hex 32),
                                 # ARVISX_ADMIN_*, OWNER_NUMBER, REGISTRY=ghcr.io/arfazkhan
cp onboard.one-anthem.example.json onboard.json   # real roster + DISTINCT PINs, vendors, PPM
```
Copy them up:
```sh
ssh root@<droplet-ip> 'mkdir -p /opt/allgud'
scp docker-compose.cloud.yml .env onboard.json root@<droplet-ip>:/opt/allgud/
```

---

## 6. Pull + start (on the Droplet)
```sh
ssh root@<droplet-ip>
cd /opt/allgud
echo <READ_PAT> | docker login ghcr.io -u arfazkhan --password-stdin
docker compose -f docker-compose.cloud.yml pull
docker compose -f docker-compose.cloud.yml up -d
```
Verify:
```sh
curl -sI https://oneanthem.<yourdomain> | head -1     # 200, cert auto-issued by Caddy
```

---

## 7. Onboard One Anthem (real data)
```sh
docker compose -f docker-compose.cloud.yml cp onboard.json api:/data/onboard.json
docker compose -f docker-compose.cloud.yml exec api python -m arvisx.onboard /data/onboard.json
```

---

## 8. Pair the WhatsApp bot — remotely (deployer step, separate from AllGud)
On the Droplet, watch the bot logs for the QR and scan it:
```sh
docker compose -f docker-compose.cloud.yml logs -f bot     # ASCII QR prints here
```
Scan with the **building-owned WhatsApp number's phone** (dedicated SIM — not your
personal/dev number; one number per bot). The session persists in `bot-session`.
Pairing is intentionally a deployer/CLI step, not part of the AllGud console.

---

## 9. Hand it over
- Give the manager the URL + their login.
- Give each technician their **PIN** (privately) — or the **Field link** from People.
- Run `ONE_ANTHEM_ACCEPTANCE_TEST.md` end-to-end.

---

## Updating later (new build)
```sh
# your machine:
REGISTRY=ghcr.io/arfazkhan TAG=latest ./build-and-push.sh
# droplet:
cd /opt/allgud && docker compose -f docker-compose.cloud.yml pull && \
  docker compose -f docker-compose.cloud.yml up -d
```

## Backups
Put `backup.sh` on the Droplet and cron it (see PILOT_DEPLOY_ONE_ANTHEM.md §8),
pointing at `docker-compose.cloud.yml`. Or snapshot the Droplet from the DO panel.

## Costs (with $200 credit)
- Droplet 2 GB: ~$12–18/mo → credit lasts ~12 months.
- GHCR: free for your usage. DO bandwidth: negligible for a pilot.

## Honest notes
- **One WhatsApp number = one bot.** Use a dedicated, building-owned number; unlinking
  it from that phone kills the bot.
- **Single Droplet, single building.** Don't add building #2 to this instance (no
  multi-tenant yet).
- **Backups are on you** — the SQLite volume is the whole pilot.
