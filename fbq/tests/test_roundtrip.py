"""One database, one brain: whatever happens in WhatsApp shows up in the console, and whatever
is done in the console is known to the bot. These tests exist because "it shares a DB" is easy to
say and easy to quietly break."""
import pytest
from fastapi.testclient import TestClient

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
        "name": "3BHK", "template_id": "P3-MANUF-EXEC",
        "start_date": "2026-07-01", "group_jid": GJ}).json()["id"]


def _say(client, text, name="Ravi", phone="919900011122"):
    return client.post("/api/v1/ingest", json={
        "group_jid": GJ, "phone": phone, "name": name, "text": text, "kind": "text"}).json()["reply"]


def _outbox(client):
    return client.get("/api/v1/outbox").json()["outbox"]


# ── WhatsApp → console ────────────────────────────────────────────────────
def test_whatsapp_actions_appear_in_the_console(client):
    pid = _proj(client)
    _say(client, "false ceiling is completed"); _say(client, "yes")
    _say(client, "we will fix the balcony grill tomorrow"); _say(client, "yes")
    _say(client, "client approved the walnut veneer"); _say(client, "yes")
    _say(client, "remember the client wants matte finish")

    plan = client.get(f"/api/v1/projects/{pid}/plan").json()
    assert next(t for t in plan["tasks"] if t["task_id"] == "false_ceiling")["status"] == "done"
    assert client.get(f"/api/v1/projects/{pid}/commitments").json()["commitments"]
    assert client.get(f"/api/v1/projects/{pid}/approvals").json()["approvals"]
    mems = client.get(f"/api/v1/projects/{pid}/memories").json()["memories"]
    assert any("matte" in m["text"] for m in mems)
    acts = client.get(f"/api/v1/projects/{pid}/activity").json()["activity"]
    assert {"task_done", "commitment", "approval", "memory_saved"} <= {a["action"] for a in acts}


def test_unanswered_whatsapp_extraction_lands_in_the_console_inbox(client):
    pid = _proj(client)
    _say(client, "electrician did not come, work is stuck")     # asked, nobody answered
    pend = client.get(f"/api/v1/projects/{pid}/pending").json()["pending"]
    assert pend and pend[0]["type"] == "blocker"


# ── console → WhatsApp ────────────────────────────────────────────────────
def test_console_task_edit_notifies_the_group(client):
    pid = _proj(client)
    # completing a task LATE from the console must tell the group what moved
    r = client.post(f"/api/v1/projects/{pid}/tasks/factory_carcass",
                    json={"status": "done", "on_date": "2026-09-01"}).json()
    assert r["saved"]
    kinds = [o["kind"] for o in _outbox(client)]
    assert "shift_alert" in kinds or "next_task" in kinds


def test_console_confirm_executes_and_tells_the_group(client):
    pid = _proj(client)
    _say(client, "painting is finished")                        # bot asks, nobody replies in chat
    eid = client.get(f"/api/v1/projects/{pid}/pending").json()["pending"][0]["id"]
    r = client.post(f"/api/v1/pending/{eid}/decide", json={"status": "confirmed", "by": "owner"}).json()
    assert r["done"]
    # the group is told the office confirmed it
    assert any(o["kind"] == "confirm_result" for o in _outbox(client))


def test_bot_knows_what_the_console_taught_it(client):
    """A memory added in the console is retrievable by the bot in the group — one brain."""
    pid = _proj(client)
    client.post(f"/api/v1/projects/{pid}/memories",
                json={"text": "client prefers site visits on saturdays"})
    ans = _say(client, "@firstbriq what did we say about site visits?")
    assert "saturday" in ans.lower()


def test_bot_sees_console_plan_edits(client):
    """Owner changed in the console → the bot's task list reflects it immediately."""
    pid = _proj(client)
    client.post(f"/api/v1/projects/{pid}/tasks/site_prep", json={"owner_role": "Ramesh Civil"})
    assert "Ramesh Civil" in _say(client, "@firstbriq tasks")


def test_console_close_day_pushes_the_brief_to_the_group(client):
    pid = _proj(client)
    _say(client, "false ceiling is completed"); _say(client, "yes")
    client.post(f"/api/v1/projects/{pid}/close-day", json={})
    assert any(o["kind"] == "evening_brief" for o in _outbox(client))


# ── the AI Manager's situational awareness ────────────────────────────────
def test_deterministic_answer_still_works_without_llm(client):
    pid = _proj(client)
    _say(client, "we will finish plumbing tomorrow", name="Suresh"); _say(client, "yes", name="Suresh")
    # promises are a first-class command, not a lucky semantic hit
    assert "Suresh" in _say(client, "@firstbriq promises")
