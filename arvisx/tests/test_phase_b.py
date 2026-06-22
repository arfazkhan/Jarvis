"""Phase B — equipment manuals (B1) + date+time scheduled checklists (B2)."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

from arvisx.persistence import ArvisxDb
from arvisx import checklist_intel as ci
from arvisx.uploads import save_document


# ── B1: manuals ─────────────────────────────────────────────────────────────
def test_save_document_accepts_pdf_rejects_junk():
    os.environ["ARVISX_UPLOAD_DIR"] = tempfile.mkdtemp()
    name, mt = save_document(b"%PDF-1.4 ...", filename="pump.pdf")
    assert name.endswith(".pdf") and mt == "application/pdf"
    try:
        save_document(b"MZ...", filename="virus.exe")
        assert False, "should reject .exe"
    except ValueError:
        pass


def test_asset_manual_attach_roundtrip():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "m.db"))
    aid = db.add_asset("one-anthem", "DG-1", kind="DG")
    assert db.get_asset(aid)["manual_path"] in (None, "")
    db.set_asset_manual(aid, "abc123.pdf", "DG-1 manual.pdf")
    a = db.get_asset(aid)
    assert a["manual_path"] == "abc123.pdf" and a["manual_name"] == "DG-1 manual.pdf"
    # surfaces in the registry list (for the Setup UI)
    reg = {r["name"]: r for r in db.list_assets_registry("one-anthem")}
    assert reg["DG-1"]["manual_path"] == "abc123.pdf"


# ── B2: schedule due-logic ──────────────────────────────────────────────────
def test_schedule_due_logic():
    mon_9 = datetime(2026, 6, 22, 9, 5)        # a Monday, 09:05
    assert ci._schedule_due({"mode": "once", "run_date": "2026-06-22", "run_time": "09:00"}, mon_9)
    assert not ci._schedule_due({"mode": "once", "run_date": "2026-06-23", "run_time": "09:00"}, mon_9)
    # time not reached yet
    assert not ci._schedule_due({"mode": "once", "run_date": "2026-06-22", "run_time": "10:00"}, mon_9)
    assert ci._schedule_due({"mode": "recurring", "recur": "daily", "run_time": "09:00"}, mon_9)
    assert ci._schedule_due({"mode": "recurring", "recur": "weekly", "dow": 0, "run_time": "08:00"}, mon_9)
    assert not ci._schedule_due({"mode": "recurring", "recur": "weekly", "dow": 2, "run_time": "08:00"}, mon_9)
    assert ci._schedule_due({"mode": "recurring", "recur": "monthly", "dom": 22, "run_time": "09:00"}, mon_9)
    assert not ci._schedule_due({"mode": "recurring", "recur": "monthly", "dom": 1, "run_time": "09:00"}, mon_9)


def test_due_scheduled_checklists_fires_once_and_deactivates_oneoff():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "s.db"))
    now = datetime(2026, 6, 22, 9, 5)
    today = now.strftime("%Y-%m-%d")
    sid = db.add_schedule("one-anthem", "ANTHEM-SHIFT-1", mode="once",
                          run_date=today, run_time="09:00", assignee="Ravi")
    fired = ci.due_scheduled_checklists(db, "one-anthem", now)
    assert len(fired) == 1 and fired[0]["assignee"] == "Ravi"
    run = db.get_checklist_run(fired[0]["run_id"])
    assert run["template_id"] == "ANTHEM-SHIFT-1" and run["assignee"] == "Ravi" and run["status"] == "open"
    # fired once: a second sweep the same day does nothing, and the one-off is now inactive
    assert ci.due_scheduled_checklists(db, "one-anthem", now) == []
    assert db.get_schedule(sid)["active"] == 0


def test_recurring_schedule_refires_next_day():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "s2.db"))
    sid = db.add_schedule("one-anthem", "ANTHEM-SHIFT-1", mode="recurring",
                          recur="daily", run_time="09:00")
    d1 = datetime(2026, 6, 22, 9, 5)
    d2 = datetime(2026, 6, 23, 9, 5)
    assert len(ci.due_scheduled_checklists(db, "one-anthem", d1)) == 1
    assert ci.due_scheduled_checklists(db, "one-anthem", d1) == []     # same day → no refire
    assert len(ci.due_scheduled_checklists(db, "one-anthem", d2)) == 1  # next day → refires
    assert db.get_schedule(sid)["active"] == 1                         # recurring stays active


# ── B2: API ─────────────────────────────────────────────────────────────────
def _client():
    os.environ["ARVISX_DB"] = os.path.join(tempfile.mkdtemp(), "c.db")
    os.environ["ARVIS_X_LLM"] = "0"
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def test_schedule_api_create_list_run_now():
    c = _client()
    r = c.post("/api/v1/schedules", json={"building": "one-anthem", "template_id": "ANTHEM-SHIFT-1",
                                          "label": "Fire drill", "mode": "recurring", "recur": "weekly",
                                          "dow": 0, "time": "08:00"})
    assert r.status_code == 200
    sid = r.json()["id"]
    lst = c.get("/api/v1/schedules", params={"building": "one-anthem"}).json()["schedules"]
    assert any(s["id"] == sid and s["template_name"] for s in lst)
    # run-now opens a real run immediately
    run = c.post(f"/api/v1/schedules/{sid}/run-now").json()
    assert "run_id" in run
    runs = c.get("/api/v1/forms/today", params={"building": "one-anthem"}).json()["runs"]
    assert any(x["run_id"] == run["run_id"] for x in runs)


def test_schedule_api_rejects_bad_config():
    c = _client()
    assert c.post("/api/v1/schedules", json={"building": "one-anthem",
                  "template_id": "ANTHEM-SHIFT-1", "mode": "once"}).status_code == 400   # no date
    assert c.post("/api/v1/schedules", json={"building": "one-anthem",
                  "template_id": "ANTHEM-SHIFT-1", "mode": "recurring"}).status_code == 400  # no recur
