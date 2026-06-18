# AllGud — frontend

Building-operations console + field app for the AllGud product (React 19 + Vite + Tailwind 4).
Two faces of one app:
- **Console** (manager) — sidebar, dashboards: `/`, `/operations`, `/issues` (+ Assets/People/Intelligence under "More").
- **Field app** (technician) — full-screen, phone-first round runner: `/field`, `/field/run/:rid`. The WhatsApp assignment link drops the technician straight into `/field/run/:rid`.

## Run locally
1. Start the backend (see `arvisx/FRONTEND_BRIEF.md`): `python -m arvisx.api` on port 8091.
2. `cp .env.example .env` and set `VITE_API_BASE=http://localhost:8091/api/v1`.
3. `npm install && npm run dev` → open the printed URL.

Seed demo data first so screens render: `python scratch/seed_one_anthem.py` (against the same `ARVISX_DB` the API uses).

## Auth
- If the backend has no users and no API key, it runs **open** — the app skips login.
- Otherwise users **sign in** (`/auth/login`); the token is stored and sent as `Bearer`.
  `viewer` role is read-only (write controls hidden). Create users on the backend
  (`POST /auth/users`, owner only) or bootstrap an owner via `ARVISX_ADMIN_USER` / `ARVISX_ADMIN_PASSWORD`.

## Build & deploy (pilot)
```
npm run build                      # → dist/ (static)
```
Serve `dist/` from any static host **with SPA fallback to index.html** (deep links like
`/field/run/42` must resolve client-side). Set `VITE_API_BASE` to the deployed API URL (HTTPS)
at build time.

### Docker (nginx, SPA fallback included)
```
docker build --build-arg VITE_API_BASE=https://api.yourhost/api/v1 -t allgud-web .
docker run -p 8080:80 allgud-web
```

## Conventions (do not break)
Icons only (lucide), **no emojis**. Confidence is a band (Low/Med/High), never a %. AI output
carries a source badge. See `arvisx/FRONTEND_BRIEF.md` §6 for the full honesty rules.
