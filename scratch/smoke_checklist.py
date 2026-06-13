"""Live HTTP smoke test of the Phase-0 checklist + agentic endpoints (real FastAPI routing
+ serialization via TestClient, in-process). Exercises the workflow end to end."""
import os, tempfile
os.environ["ARVISX_DB"] = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ.pop("ARVISX_API_KEY", None)

from fastapi.testclient import TestClient
from arvisx.api import create_app

c = TestClient(create_app())
ok = 0
fail = 0


def check(label, cond, extra=""):
    global ok, fail
    mark = "OK " if cond else "XX "
    if cond: ok += 1
    else: fail += 1
    print(f"  {mark} {label}{(' — ' + extra) if extra else ''}")


# 1. templates
r = c.get("/api/v1/forms/templates")
tids = [t["template_id"] for t in r.json()["templates"]]
check("GET forms/templates", r.status_code == 200 and "ANTHEM-SHIFT-2" in tids, str(tids))

# 2. start a run
r = c.post("/api/v1/forms/run", json={"template_id": "ANTHEM-SHIFT-2", "technician": "Ajith"})
run = r.json(); rid = run["run"]["id"]
check("POST forms/run (start)", r.status_code == 200 and rid, f"run {rid}")

# 3. assign from roster
c.post("/api/v1/technicians", json={"name": "Ajith", "phone": "919000000000"})
r = c.post(f"/api/v1/forms/run/{rid}/assign", json={"assignee": "Ajith"})
check("POST forms/run/assign", r.json()["run"]["assignee"] == "Ajith")

# 4. an entry that auto-flags an issue (fire panel OFF)
r = c.post(f"/api/v1/forms/run/{rid}/entry", json={"item_id": "g2_fire_alarm", "value": "OFF"})
check("POST entry fire=OFF auto-flags", r.json()["is_issue"] is True)

# 5. a normal reading
r = c.post(f"/api/v1/forms/run/{rid}/entry", json={"item_id": "g2_oh_tank", "value": "90", "status": "ok"})
check("POST entry reading", r.json()["saved"] is True)

# 6. issues list has the auto issue
r = c.get("/api/v1/issues")
issues = r.json()["issues"]
fire_iss = next((i for i in issues if "fire alarm" in i["title"].lower()), None)
check("GET issues (auto-created)", fire_iss is not None, fire_iss["title"] if fire_iss else "none")

# 7. work-order suggestion for it
if fire_iss:
    r = c.get(f"/api/v1/agents/work-order?issue_id={fire_iss['id']}")
    check("GET agents/work-order", r.json().get("category") == "Safety", r.json().get("category"))

# 8. supervisor review of the run (L2)
r = c.get(f"/api/v1/forms/run/{rid}/review")
check("GET forms/run/review (L2)", r.status_code == 200 and "missing" in r.json())

# 9. health + watchlist + compliance
check("GET analyzers/health", c.get("/api/v1/analyzers/health").status_code == 200)
check("GET analyzers/watchlist", c.get("/api/v1/analyzers/watchlist").status_code == 200)
check("GET analyzers/compliance", c.get("/api/v1/analyzers/compliance").status_code == 200)

# 10. handover (deterministic without LLM key)
r = c.get("/api/v1/agents/handover")
check("GET agents/handover", r.status_code == 200 and "Handover" in r.json()["text"], r.json().get("source"))

# 11. ask-the-building
r = c.get("/api/v1/agents/ask", params={"q": "what is open right now?"})
check("GET agents/ask", r.status_code == 200 and r.json()["text"])

# 12. PPM schedule + status
c.post("/api/v1/ppm/schedule", json={"asset": "DG-1", "interval_days": 90, "last_done": "2026-01-01"})
r = c.get("/api/v1/ppm/schedule")
dg = next((s for s in r.json()["schedules"] if s["asset"] == "DG-1"), None)
check("PPM schedule overdue", dg and dg["status"] == "overdue", dg["status"] if dg else "none")

# 13. asset history
check("GET assets/{a}/history", c.get("/api/v1/assets/DG-1/history").status_code == 200)

# 14. builder: create a custom template, see it listed
custom = {"building": "one-anthem", "template": {
    "template_id": "CUSTOM-DG", "name": "DG Quick Check", "cadence": "daily",
    "sections": [{"name": "DG", "items": [{"item_id": "dg_q1", "label": "DG-1 oil ok?", "kind": "tick"}]}]}}
r = c.post("/api/v1/forms/templates", json=custom)
check("POST builder template", r.json().get("saved") is True)
tids2 = [t["template_id"] for t in c.get("/api/v1/forms/templates").json()["templates"]]
check("custom template now listed", "CUSTOM-DG" in tids2)

# 15. vision extract (Null provider — proposal, no entry write)
r = c.post("/api/v1/vision/extract?kind=gauge&filename=g.jpg",
           content=b"\xff\xd8\xff fake jpeg", headers={"Content-Type": "image/jpeg"})
check("POST vision/extract (null model)", r.status_code == 200 and r.json()["available"] is False)

# 16. submit + signoff
c.post(f"/api/v1/forms/run/{rid}/signoff", json={"role": "technician", "by": "Ajith"})
r = c.post(f"/api/v1/forms/run/{rid}/submit")
check("submit + signoff", r.json()["run"]["status"] == "submitted")

print(f"\n=== smoke: {ok} ok, {fail} fail ===")
raise SystemExit(1 if fail else 0)
