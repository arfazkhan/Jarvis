"""The pilot loop, end-to-end and hermetic (no LLM — deterministic extraction floor):
create project → link group → ingest chat → Lane B confirm ask → YES → plan write →
F14/F15 notices in outbox → digest/tasks/Q&A read lane → web inbox decide → activity log."""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FBQ_DB", str(tmp_path / "fbq.db"))
    monkeypatch.delenv("FBQ_LLM", raising=False)
    monkeypatch.delenv("ARVIS_X_LLM", raising=False)
    from fbq.api import create_app
    return TestClient(create_app())


GJ = "12036302@g.us"


def _setup(client) -> int:
    pid = client.post("/api/v1/projects", json={
        "name": "3BHK Indiranagar", "template_id": "P3-MANUF-EXEC",
        "start_date": "2026-07-01", "group_jid": GJ}).json()["id"]
    return pid


def _ingest(client, text, phone="919900011122", name="Ravi", kind="text"):
    return client.post("/api/v1/ingest", json={
        "group_jid": GJ, "phone": phone, "name": name, "text": text, "kind": kind}).json()


def test_full_lane_b_loop_status_update(client):
    pid = _setup(client)
    # "false ceiling done" → matched to the plan task → Lane B ask
    r = _ingest(client, "false ceiling work is completed")
    assert "False ceiling" in r["reply"] and "YES" in r["reply"]
    # sender confirms → deterministic executor marks done
    r2 = _ingest(client, "yes")
    assert "Marked" in r2["reply"] and "done" in r2["reply"]
    plan = client.get(f"/api/v1/projects/{pid}/plan").json()
    fc = next(t for t in plan["tasks"] if t["task_id"] == "false_ceiling")
    assert fc["status"] == "done" and fc["actual_end"]
    # activity logged with lane B + actor
    acts = client.get(f"/api/v1/projects/{pid}/activity").json()["activity"]
    assert any(a["action"] == "task_done" and a["lane"] == "B" and a["actor"] == "Ravi" for a in acts)


def test_decline_is_training_signal_not_write(client):
    pid = _setup(client)
    _ingest(client, "painting is finished")
    r = _ingest(client, "no")
    assert "Ignored" in r["reply"]
    plan = client.get(f"/api/v1/projects/{pid}/plan").json()
    assert all(t["status"] != "done" for t in plan["tasks"])


def test_commitment_creates_adhoc_task_with_due(client):
    pid = _setup(client)
    r = _ingest(client, "we will fix the balcony grill tomorrow", name="Suresh")
    assert "commitment" in r["reply"].lower() and "YES" in r["reply"]
    r2 = _ingest(client, "yes", name="Suresh")
    assert "Task added" in r2["reply"] or "committed" in r2["reply"]
    plan = client.get(f"/api/v1/projects/{pid}/plan").json()
    assert any(t["task_id"].startswith("adhoc_") or "committed" in t.get("notes", "")
               for t in plan["tasks"])


def test_chatter_stays_silent(client):
    _setup(client)
    r = _ingest(client, "good morning everyone")
    assert r["reply"] == ""


def test_unlinked_group_ignored(client):
    _setup(client)
    r = client.post("/api/v1/ingest", json={"group_jid": "999@g.us", "phone": "1", "name": "x",
                                            "text": "false ceiling done", "kind": "text"}).json()
    assert r["reply"] == ""


def test_photo_is_filed_and_asked_about(client):
    """Photos are Lane A (filed, undoable) but NOT silent — the bot asks what it is rather than
    analysing the image. Full ask→answer→memory path is covered in test_brain.py."""
    pid = _setup(client)
    r = client.post("/api/v1/media", content=b"\x89PNG-fake",
                    params={"group_jid": GJ, "phone": "919900011122", "name": "Ravi",
                            "kind": "photo", "filename": "site.jpg"},
                    headers={"Content-Type": "application/octet-stream"}).json()["reply"]
    assert "what's this about" in r.lower()
    acts = client.get(f"/api/v1/projects/{pid}/activity").json()["activity"]
    assert any(a["action"] == "photo_filed" and a["lane"] == "A" for a in acts)


def test_task_list_digest_and_shift_notice(client):
    pid = _setup(client)
    txt = client.get(f"/api/v1/projects/{pid}/tasks-due").json()["text"]
    assert "Overdue" in txt or "Today" in txt or "Next 7 days" in txt
    # complete a task LATE via the web (F7) → downstream shifts → group notice queued
    r = client.post(f"/api/v1/projects/{pid}/tasks/factory_carcass",
                    json={"status": "done", "on_date": "2026-09-01"}).json()
    assert r["saved"]
    out = client.get("/api/v1/outbox").json()["outbox"]
    assert any(o["kind"] == "shift_alert" for o in out) or r["shifts"] == []
    d = client.get(f"/api/v1/projects/{pid}/digest").json()["text"]
    assert "daily digest" in d


def test_next_task_trigger_notice(client):
    pid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/tasks/material_po", json={"status": "done"})
    client.post(f"/api/v1/projects/{pid}/tasks/client_material_signoff", json={"status": "done"})
    out = client.get("/api/v1/outbox").json()["outbox"]
    assert any(o["kind"] == "next_task" and "Factory" in o["text"] for o in out)


def test_web_inbox_decide(client):
    pid = _setup(client)
    _ingest(client, "electrician did not come today, work stuck")
    pend = client.get(f"/api/v1/projects/{pid}/pending").json()["pending"]
    assert pend and pend[0]["type"] == "blocker"
    r = client.post(f"/api/v1/pending/{pend[0]['id']}/decide",
                    json={"status": "confirmed", "by": "owner"}).json()
    assert r["done"]
    acts = client.get(f"/api/v1/projects/{pid}/activity").json()["activity"]
    assert any(a["action"] == "blocker" for a in acts)


def test_outbox_ack(client):
    pid = _setup(client)
    client.post(f"/api/v1/projects/{pid}/tasks/material_po", json={"status": "done"})
    out = client.get("/api/v1/outbox").json()["outbox"]
    if out:
        ids = [o["id"] for o in out]
        client.post("/api/v1/outbox/ack", json={"ids": ids})
        assert client.get("/api/v1/outbox").json()["outbox"] == []
