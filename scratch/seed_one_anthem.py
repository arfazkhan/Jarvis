"""Seed the One Anthem building with realistic operational data so the dashboards render
(Overview / Operations / Issues / Assets / People). Templates are already built-in
(seeds/one-anthem.json); this fills the DB with roster, vendors, PPM, runs, entries, issues.

Run:  $env:PYTHONPATH="E:\\Automation"; python scratch\\seed_one_anthem.py
DB:   ARVISX_DB env (default arvisx/data/arvisx.db) — start the API on the SAME DB after.
Idempotent-ish: re-running adds more runs; use a fresh DB for a clean demo.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from arvisx.persistence import ArvisxDb
from arvisx.checklist_forms import get_template

B = "one-anthem"
db = ArvisxDb(os.environ.get("ARVISX_DB") or str(ROOT / "arvisx" / "data" / "arvisx.db"), building_id=B)
today = datetime.now().strftime("%Y-%m-%d")


def backdate(table, _id, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with db._conn() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*cols.values(), _id))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# ── roster ────────────────────────────────────────────────────────────────
techs = {
    "Ajith": "919876543210", "Suresh": "919876543211", "Ramesh Kumar": "919876543212",
    "Vijay": "919876543213", "Mohan": "919876543214", "Athul": "919876543215",
}
for name, phone in techs.items():
    db.add_technician(B, name, phone)

# ── vendors ───────────────────────────────────────────────────────────────
for vn, cat in [("ABC Power Systems", "Electrical"), ("ABC Fire Systems", "Fire Safety"),
                ("Fire Safe Solutions", "Fire Safety"), ("Lift Care", "Lifts")]:
    db.add_vendor(B, vn, cat, "919800000000")

# ── PPM schedules ─────────────────────────────────────────────────────────
db.set_ppm_schedule(B, "MSB", interval_days=90, last_done=(datetime.now() - timedelta(days=107)).strftime("%Y-%m-%d"))
db.set_ppm_schedule(B, "DG-2", interval_days=30, last_done=(datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d"))
db.set_ppm_schedule(B, "DG-1", interval_days=90, last_done=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))

# ── declining DG-1 battery history (drives watchlist + RCA) ────────────────
for i, v in enumerate([25.0, 24.5, 23.6, 22.4]):
    d = (datetime.now() - timedelta(days=4 - i)).strftime("%Y-%m-%d")
    rid = db.create_checklist_run(B, "ANTHEM-SHIFT-3", d, technician="Suresh", assignee="Suresh")
    db.save_checklist_entry(rid, "dg_battery_v", value=str(v), status="ok")
    db.submit_checklist_run(rid)


def fill_run(template_id, assignee, n_items, started, *, alerts=None, readings=None, submit=False):
    """Create a run, fill its first n_items entries. `alerts` = {item_id: value} forced as
    issues; `readings` = {item_id: value} set as normal readings (override the generic value)."""
    alerts = alerts or {}
    readings = readings or {}
    rid = db.create_checklist_run(B, template_id, today, technician=assignee, assignee=assignee)
    backdate("checklist_runs", rid, started_at=started)
    items = get_template(template_id, B).all_items()
    for it in items[:n_items]:
        if it.item_id in alerts:
            continue
        if it.item_id in readings:
            db.save_checklist_entry(rid, it.item_id, value=readings[it.item_id], status="ok")
            continue
        val = "done" if it.kind == "tick" else ("OK" if it.kind == "state" else "75")
        db.save_checklist_entry(rid, it.item_id, value=val, status="ok")
    for iid, val in alerts.items():
        db.save_checklist_entry(rid, iid, value=val, is_issue=True)
    if submit:
        db.submit_checklist_run(rid)
    return rid


# ── today's rounds ────────────────────────────────────────────────────────
# Shift II — Ajith, 58% (12 generic + 2 alerts = 14/24), fire panel OFF + OH tank 45
s2 = fill_run("ANTHEM-SHIFT-2", "Ajith", 12, iso(datetime.now() - timedelta(hours=3)),
              alerts={"g2_fire_alarm": "OFF", "g2_oh_tank": "45"})
# Shift III — Suresh, submitted (Review). Battery continues its decline → 22.0 V today
# (keeps the DG-1 trend alive for the watchlist/RCA; matches the mockup's 22.0 V reading).
fill_run("ANTHEM-SHIFT-3", "Suresh", 17, iso(datetime.now() - timedelta(hours=6)),
         readings={"dg_battery_v": "22.0"}, submit=True)
# Shift I — Ramesh Kumar, ~40%
fill_run("ANTHEM-SHIFT-1", "Ramesh Kumar", 6, iso(datetime.now() - timedelta(minutes=41)))
# DG-1 quarterly PPM — Athul, scheduled (empty)
db.create_checklist_run(B, "ANTHEM-PPM", today, technician="Athul", assignee="Athul", asset="DG-1")

# ── issues ────────────────────────────────────────────────────────────────
# Fire Alarm Panel: OFF — auto from Shift II, assigned to vendor + visited, SLA breached
fire = db.create_issue(B, "Fire alarm panel health (main ON / no fault): OFF", asset="FIRE-PANEL",
                       severity="critical", source="auto", run_id=s2, item_id="g2_fire_alarm",
                       raised_by="Ajith", priority="high", vendor="ABC Fire Systems")
backdate("checklist_issues", fire, created_at=iso(datetime.now() - timedelta(hours=31, minutes=18)))
db.update_issue(fire, status="assigned", assignee="ABC Fire Systems", by="Suresh")
db.append_issue_history(fire, "vendor visited", by="Ramesh")
db.set_issue_fields(fire, escalated_level=2)   # resolution breached → supervisor level

# DG-2 battery low — open critical (populates DG-2 asset + watchlist)
dg2 = db.create_issue(B, "DG-2 battery voltage low", asset="DG-2", severity="critical",
                      source="auto", raised_by="Ajith", priority="high", vendor="ABC Power Systems")

print("Seeded One Anthem:")
print("  technicians:", len(db.list_technicians(B)))
print("  vendors    :", len(db.list_vendors(B)))
print("  ppm        :", [s["asset"] for s in db.list_ppm_schedules(B)])
print("  runs today :", len(db.checklist_runs_for(B, today)))
print("  open issues:", len([i for i in db.list_issues(B) if i["status"] != "resolved"]))
print("  fire issue :", fire, "| dg2 issue:", dg2)
print("Done. Start the API on the same ARVISX_DB and open /forms or the dashboards.")
