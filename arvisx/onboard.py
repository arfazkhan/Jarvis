"""Data-driven building onboarding — run INSIDE the pilot api container.

Usage:
    python -m arvisx.onboard /data/onboard.json

The JSON describes the REAL building (roster + field PINs, vendors, PPM dates).
Templates are NOT onboarded here — they seed from arvisx/seeds/<building>.json
(One Anthem ships 4 built-in). This is idempotent for the roster/vendors
(reactivates by name) and safe to re-run after editing the JSON.

JSON shape:
{
  "building": "one-anthem",
  "owner": {"username": "athul", "role": "owner"},   # password from ARVISX_ADMIN_PASSWORD
  "technicians": [{"name": "Ajith", "phone": "9198...", "pin": "1001"}, ...],
  "vendors":     [{"name": "ABC Power", "category": "Electrical", "contact": "9198..."}, ...],
  "ppm":         [{"asset": "DG-1", "interval_days": 90, "last_done": "2026-04-01",
                   "run_hours_limit": 250}, ...]
}
"""
from __future__ import annotations

import json
import os
import sys

from arvisx.persistence import ArvisxDb
from arvisx.auth import hash_password


def onboard(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)

    building = cfg.get("building", "one-anthem")
    db = ArvisxDb(os.environ.get("ARVISX_DB") or "arvisx/data/arvisx.db", building_id=building)

    # 1) Owner login. Password comes from the environment, never the JSON file.
    owner = cfg.get("owner") or {}
    if owner.get("username") and db.count_users() == 0:
        pw = os.environ.get("ARVISX_ADMIN_PASSWORD")
        if not pw:
            sys.exit("ARVISX_ADMIN_PASSWORD not set — refusing to create the owner with no password.")
        db.create_user(owner["username"], owner.get("role", "owner"), hash_password(pw))

    # 2) Roster + field PINs. Distinct PINs per building (PIN+building resolves one tech).
    seen_pins = {}
    for t in cfg.get("technicians", []):
        tid = db.add_technician(building, t["name"], t.get("phone", ""))
        pin = str(t.get("pin", "")).strip()
        if pin:
            if pin in seen_pins:
                sys.exit(f"Duplicate PIN {pin} for '{t['name']}' and '{seen_pins[pin]}' — PINs must be distinct.")
            seen_pins[pin] = t["name"]
            db.set_technician_pin(tid, hash_password(pin))

    # 3) Vendors / AMCs.
    for v in cfg.get("vendors", []):
        db.add_vendor(building, v["name"], v.get("category", "Other"), v.get("contact", ""))

    # 4) PPM schedules — real last-service dates.
    for p in cfg.get("ppm", []):
        db.set_ppm_schedule(building, p["asset"], interval_days=p.get("interval_days", 90),
                            last_done=p.get("last_done", ""),
                            run_hours_limit=p.get("run_hours_limit"))

    techs = db.list_technicians(building)
    with_pin = sum(1 for t in techs if t.get("pin_hash"))
    print(f"Onboarded '{building}':")
    print(f"  users      : {db.count_users()}")
    print(f"  technicians: {len(techs)} ({with_pin} with a field PIN)")
    print(f"  vendors    : {len(db.list_vendors(building))}")
    print(f"  ppm assets : {[s['asset'] for s in db.list_ppm_schedules(building)]}")
    print("Next: log into the console as owner, verify the roster, distribute PINs.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m arvisx.onboard <onboard.json>")
    onboard(sys.argv[1])
