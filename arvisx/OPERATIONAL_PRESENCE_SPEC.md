# ArvisX — Operational Presence (proof layer) — SPEC

Status: SPEC ONLY (not built). The foundational trust layer beneath the checklist + agents.

## Why
Before anyone trusts the AI's conclusions, they must trust the data. "Grounding is law"
for the AI = no number without a source; **Operational Presence is the same rule one layer
down = no inspection without a person, place, and time.** It's also the wedge that sells
first: the engineering head doesn't buy RCA, he buys *"I finally know the rounds happened."*

Positioning: **operational verification, NOT surveillance.** We prove an inspection occurred
at the right place and time — we do NOT track people. Event-based capture only (check-in,
at-station, at-inspection). Store proof points, never a continuous movement trail.

## The proof chain (per inspection)
```
Assigned technician → check-in (selfie + time + location) → at-location station scan
→ inspection entry + photo (dup-checked) → supervisor approval
```

## What we already have (reuse, don't rebuild)
- Server-timestamped entries (proof-of-TIME; no Saturday backfill) — done.
- Photo evidence per item + per issue — done.
- Assigned technician (roster) + sign-off chain — done.
Missing = check-in/out, proof-of-PLACE, selfie, the rollup proof views, AI photo checks.

## Key decisions (confirm before build)
1. **Proof-of-place = QR/NFC station tags as PRIMARY; GPS as soft corroboration.**
   GPS is unreliable/zero in basements & plant rooms. A printed QR/NFC tag fixed at each
   location, scanned by the technician, proves presence better and works underground.
   GPS captured opportunistically where available, never required.
2. **Consent + retention.** Selfie + location of workers needs a one-line consent at
   onboarding + a retention policy (auto-purge after N days). Jurisdiction-aware (India/Gulf
   differ). Get FM-vendor + association buy-in; frame as QA, not monitoring.
3. **Verify, never accuse.** Photo/dup flags are for REVIEW (a pump room legitimately looks
   the same daily). Surface evidence; the human judges. Same discipline as the AI guard.

## Data model (new)
- `stations(building_id, station_code, asset, label)` — the QR/NFC tag registry per location.
- `shift_sessions(id, building_id, technician, check_in_ts, check_in_selfie, check_in_loc,
   check_out_ts, check_out_selfie, status)` — a worker's shift, bracketed by check-in/out.
- proof-of-place on entries: add `station_code`, `loc` (optional GPS), to checklist_run_entries
  (or a parallel `entry_proof` table to avoid widening the hot table).
- `photo_hashes(photo, phash, building_id, created_at)` — perceptual hash per stored photo
  for reused-image detection.

## API surface (new)
- `POST /presence/check-in` {technician, selfie(bytes), station?, loc?} → session_id
- `POST /presence/check-out` {session_id, selfie?, loc?}
- `GET  /presence/session/{id}` / `GET /presence/today?technician=`
- `POST /stations` / `GET /stations?building=` (station registry)
- `POST /forms/run/{rid}/scan` {station_code, loc?} → records proof-of-place for the round
- `GET  /presence/attendance?building=&from=&to=` → operational-attendance rollup (per tech /
  per vendor: present, rounds assigned/completed, issues raised, photos, signoff)
- `GET  /presence/inspection/{entry}/proof` → the full proof chain for one inspection

## AI / verification
- **Reused-photo detection — DETERMINISTIC, ships first.** Perceptual hash (pHash) on every
  photo; high similarity to a prior photo for the same item → flag "possible reused image"
  for review. No model needed.
- **Photo-vs-claim mismatch — needs the Phase-D vision model.** "Tank reads ~50% in the photo
  but 90% was entered." Reuses the vision provider; abstains without a model.

## Rollup views (the sell)
- Per inspection: person · place (station verified) · time · photo · observation · issue · approval.
- Per shift: check-in time, rounds assigned/completed, issues raised, photos uploaded, signoff.
- Per vendor (billing defense): technician × days present (with timestamps + photos) — settles
  "how do we know your staff was on site?" for BOTH the association and the FM company.

## Build order (when greenlit)
1. Stations registry + proof-of-place scan on rounds (QR/NFC).  ← proves PLACE
2. Check-in/out sessions (selfie + time).                       ← proves PERSON+shift
3. pHash reused-photo detection (deterministic).                ← anti-pencil-whip now
4. Proof-chain + per-shift + vendor-attendance rollup views.    ← the sellable reports
5. (Later) photo-vs-claim mismatch via the vision model.

## Honest scope
- Presence is the WEDGE (buy now) that makes the data credible; the agent layer is the MOAT.
  Build presence because it makes everything above it trustworthy — not instead of it.
- NOT facial recognition. Selfie = evidence, not identity-matching.
- NOT continuous location tracking. Event-based proof points only.
