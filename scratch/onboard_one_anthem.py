"""ONBOARD One Anthem — the real setup a building does on day one. NO fake activity:
just templates (built-in), roster, vendors, PPM schedules. After this the building is
'ready' — empty of rounds/issues until technicians actually start work.

Run:  $env:PYTHONPATH="E:\\Automation"
      $env:ARVISX_DB="E:\\Automation\\arvisx\\data\\one_anthem.db"   # fresh file
      python scratch\\onboard_one_anthem.py
Then start the API on the SAME ARVISX_DB.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from arvisx.persistence import ArvisxDb
from arvisx.checklist_forms import templates_for

B = "one-anthem"
db = ArvisxDb(os.environ.get("ARVISX_DB") or str(ROOT / "arvisx" / "data" / "one_anthem.db"), building_id=B)

# 1) Templates — already built in (seeds/one-anthem.json). Nothing to load for One Anthem.
#    (A DIFFERENT building would call POST /forms/seed {building, from:"one-anthem"}.)
tpls = templates_for(B)

# 2) Owner account (so a person can log in). Comment out if using API-key only.
from arvisx.auth import hash_password
if db.count_users() == 0:
    db.create_user("athul", "owner", hash_password("change-me"))   # change the password!

# 3) Roster — the real staff who perform rounds.
for name, phone in [("Ajith", "919876543210"), ("Suresh", "919876543211"),
                    ("Ramesh Kumar", "919876543212"), ("Vijay", "919876543213"),
                    ("Mohan", "919876543214"), ("Athul", "919876543215")]:
    db.add_technician(B, name, phone)

# 4) Vendors / AMCs who own external fixes.
for vn, cat in [("ABC Power Systems", "Electrical"), ("ABC Fire Systems", "Fire Safety"),
                ("Lift Care", "Lifts")]:
    db.add_vendor(B, vn, cat, "919800000000")

# 5) PPM schedules — set each asset's real last-service date + interval.
#    (Edit these to the building's actual records.)
db.set_ppm_schedule(B, "DG-1", interval_days=90, last_done="2026-04-01", run_hours_limit=250)
db.set_ppm_schedule(B, "DG-2", interval_days=90, last_done="2026-04-01", run_hours_limit=250)
db.set_ppm_schedule(B, "MSB", interval_days=90, last_done="2026-03-15")
db.set_ppm_schedule(B, "TRANSFORMER", interval_days=180, last_done="2026-01-10")

# 6) SLA config is optional — defaults apply (critical 1/4h … low 48/168h). Override if needed:
# db.set_sla_config(B, "critical", 1, 4)

print("Onboarded One Anthem (ready, no activity yet):")
print("  templates  :", [t.template_id for t in tpls])
print("  users      :", db.count_users())
print("  technicians:", len(db.list_technicians(B)))
print("  vendors    :", len(db.list_vendors(B)))
print("  ppm assets :", [s["asset"] for s in db.list_ppm_schedules(B)])
import datetime
print("  runs today :", len(db.checklist_runs_for(B, datetime.date.today().isoformat())), "(0 = clean)")
print("  open issues:", len([i for i in db.list_issues(B) if i["status"] != "resolved"]), "(0 = clean)")
print("Next: start the API on this DB → manager assigns the first round → technician fills it.")
