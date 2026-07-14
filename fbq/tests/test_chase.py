"""Commitment aging, manager remind/escalate, briefs, approval log + evidence pack.
Hermetic — no LLM, deterministic floors only."""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fbq import chase

GJ = "12036302@g.us"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FBQ_DB", str(tmp_path / "fbq.db"))
    monkeypatch.setenv("FBQ_MEDIA_DIR", str(tmp_path / "media"))
    for k in ("FBQ_LLM", "ARVIS_X_LLM", "GROQ_API_KEY", "ARVISX_EMBED_KEY"):
        monkeypatch.delenv(k, raising=False)
    from fbq.api import create_app
    return TestClient(create_app())


def _proj(client) -> int:
    return client.post("/api/v1/projects", json={
        "name": "3BHK Indiranagar", "template_id": "P3-MANUF-EXEC",
        "start_date": "2026-07-01", "group_jid": GJ}).json()["id"]


def _say(client, text, phone="919900011122", name="Ravi"):
    return client.post("/api/v1/ingest", json={
        "group_jid": GJ, "phone": phone, "name": name, "text": text, "kind": "text"}).json()["reply"]


# ── the ladder (pure) ─────────────────────────────────────────────────────
def test_aging_ladder_escalates_and_names_the_person():
    c = {"owner_name": "Ravi", "text": "balcony grill", "promised_on": "2026-08-01",
         "due_date": "2026-08-05", "status": "open", "nudges": 0}
    assert chase.commitment_nudge(c, -1) is None                     # not due → silent
    assert "due today" in chase.commitment_nudge(c, 0)["text"]
    assert "yesterday" in chase.commitment_nudge(c, 1)["text"]
    firm = chase.commitment_nudge(c, 3)
    assert "3 days" in firm["text"] and "Ravi" in firm["text"] and firm["to"] == "group"
    chronic = chase.commitment_nudge(c, 6)
    assert chronic["to"] == "manager" and "Chronic" in chronic["text"] and "6 days" in chronic["text"]


def test_one_nudge_per_promise_per_day():
    c = {"owner_name": "Ravi", "text": "x", "due_date": "2026-08-01", "status": "open",
         "nudges": 1, "last_nudge": "2026-08-03"}
    assert chase.due_nudges([c], "2026-08-03") == []                 # already chased today
    assert chase.due_nudges([c], "2026-08-04")                       # new day → chase again


# ── promise ledger ────────────────────────────────────────────────────────
def test_commitment_becomes_a_tracked_promise(client):
    pid = _proj(client)
    _say(client, "we will fix the balcony grill tomorrow", name="Ravi")
    r = _say(client, "yes", name="Ravi")
    assert "I'll follow up" in r
    cs = client.get(f"/api/v1/projects/{pid}/commitments").json()["commitments"]
    assert len(cs) == 1 and cs[0]["owner_name"] == "Ravi" and cs[0]["due_date"]
    # and it's in the brain
    ans = client.get(f"/api/v1/projects/{pid}/recall", params={"q": "balcony grill"}).json()["answer"]
    assert "balcony" in ans.lower()


def test_doing_the_task_keeps_the_promise(client):
    pid = _proj(client)
    _say(client, "false ceiling will be done tomorrow", name="Ravi")
    _say(client, "yes", name="Ravi")
    assert client.get(f"/api/v1/projects/{pid}/commitments").json()["commitments"]
    _say(client, "false ceiling is completed", name="Ravi")
    r = _say(client, "yes", name="Ravi")
    assert "promise kept" in r
    assert client.get(f"/api/v1/projects/{pid}/commitments").json()["commitments"] == []


def test_promises_command(client):
    _proj(client)
    _say(client, "we will finish plumbing tomorrow", name="Suresh")
    _say(client, "yes", name="Suresh")
    r = _say(client, "@firstbriq promises")
    assert "Suresh" in r and "Open promises" in r


# ── manager remind / escalate ─────────────────────────────────────────────
def test_manager_remind_lists_that_persons_promises(client):
    _proj(client)
    _say(client, "we will fix the grill tomorrow", name="Ravi")
    _say(client, "yes", name="Ravi")
    r = _say(client, "remind Ravi", name="Owner", phone="918800022233")
    assert "Ravi" in r and "grill" in r


def test_remind_unknown_person_is_honest(client):
    _proj(client)
    r = _say(client, "remind Nobody", name="Owner")
    assert "nothing open" in r.lower()


# ── approval log + evidence pack ──────────────────────────────────────────
def test_approval_recorded_with_provenance(client):
    pid = _proj(client)
    _say(client, "client approved the walnut veneer for the wardrobe", name="Suresh")
    r = _say(client, "yes", name="Suresh")
    assert "Approval #1" in r and "Suresh" in r
    aps = client.get(f"/api/v1/projects/{pid}/approvals").json()["approvals"]
    assert len(aps) == 1 and aps[0]["approver_name"] == "Suresh" and aps[0]["source_msg"]
    assert "approval log" in _say(client, "@firstbriq approvals").lower()


def test_evidence_pack_pdf(client):
    pid = _proj(client)
    _say(client, "client approved the extra socket in the kitchen", name="Suresh")
    _say(client, "yes", name="Suresh")
    r = client.get(f"/api/v1/projects/{pid}/evidence.pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
    assert "attachment" in r.headers["content-disposition"]


# ── the sweep: briefs + chases ────────────────────────────────────────────
def test_sweep_queues_morning_then_evening_once(client, monkeypatch):
    # Pin the brief hours to 0 so the sweep fires deterministically whatever time the suite runs.
    monkeypatch.setenv("FBQ_MORNING_HOUR", "0")
    monkeypatch.setenv("FBQ_EVENING_HOUR", "0")
    pid = _proj(client)
    _say(client, "false ceiling is completed")
    _say(client, "yes")
    client.post("/api/v1/sweep", json={})
    kinds = [o["kind"] for o in client.get("/api/v1/outbox").json()["outbox"]]
    assert "morning_brief" in kinds and "evening_brief" in kinds
    before = len(client.get("/api/v1/outbox").json()["outbox"])
    client.post("/api/v1/sweep", json={})          # again same day → no duplicate briefs
    after = len(client.get("/api/v1/outbox").json()["outbox"])
    assert after == before
    # the day was captured as a memory by the evening close-out
    mems = client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
    assert any(m["source"] == "daily" for m in mems)


def test_morning_brief_content():
    from fbq.models import PlanTask
    t = PlanTask("a", "Install shutters", owner_role="Installer")
    t.start, t.end = "2026-08-03", "2026-08-05"
    txt = chase.morning_brief("Villa", "2026-08-04", [t], [], [], [])
    assert "Villa" in txt and "Install shutters" in txt and "Installer" in txt


def test_evening_brief_flags_open_promises_and_photos():
    txt = chase.evening_brief("Villa", "2026-08-10", "- did stuff",
                              [{"owner_name": "Ravi", "text": "grill", "due_date": "2026-08-05"}],
                              unanswered_photos=2)
    assert "Still open" in txt and "Ravi" in txt and "2 photo" in txt
