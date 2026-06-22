"""Phase A — WhatsApp ops loop: sender identity (A0), issue-lifecycle alerts (A1),
manager actions (A2), resident tickets (A3). Deterministic (no LLM)."""
from __future__ import annotations

import os
import tempfile

from arvisx.persistence import ArvisxDb


# ── A0/A3 residents roster persistence ──────────────────────────────────────
def test_resident_roster_roundtrip_and_phone_norm():
    db = ArvisxDb(os.path.join(tempfile.mkdtemp(), "r.db"))
    rid = db.add_resident("one-anthem", "Asha", "+91 90480 57376", unit="B-204")
    assert rid > 0
    # stored digits-only; lookup tolerates +, spaces, and @s.whatsapp.net suffix
    assert db.resident_by_phone("one-anthem", "919048057376@s.whatsapp.net")["name"] == "Asha"
    assert db.resident_by_phone("one-anthem", "+91-90480-57376")["unit"] == "B-204"
    assert [r["name"] for r in db.list_residents("one-anthem")] == ["Asha"]
    # re-add same phone updates, doesn't duplicate
    db.add_resident("one-anthem", "Asha K", "919048057376", unit="B-204")
    assert len(db.list_residents("one-anthem")) == 1
    db.set_resident_active(rid, False)
    assert db.resident_by_phone("one-anthem", "919048057376") is None
    assert db.list_residents("one-anthem") == []


# ── TestClient helpers ──────────────────────────────────────────────────────
def _client(owner="919900000001"):
    os.environ["ARVISX_DB"] = os.path.join(tempfile.mkdtemp(), "c.db")
    os.environ["OWNER_NUMBER"] = owner
    os.environ["ARVIS_X_LLM"] = "0"                 # deterministic — no LLM override
    os.environ["ARVISX_PUBLIC_URL"] = "https://test.local"
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    return TestClient(create_app())


def _pending(c, kind=None):
    rows = c.get("/api/v1/whatsapp/notifications").json().get("notifications", [])
    return [r for r in rows if kind is None or r.get("kind") == kind]


# ── A1: issue lifecycle alerts ──────────────────────────────────────────────
def test_issue_open_notifies_manager():
    c = _client(owner="919900000001")
    c.post("/api/v1/issues", json={"building": "one-anthem", "title": "Lobby light out"})
    notes = _pending(c, "issue_lifecycle")
    assert any(n["to_number"] == "919900000001" and "Opened" in n["text"] for n in notes)


def test_issue_assign_notifies_tech_and_manager():
    c = _client(owner="919900000001")
    c.post("/api/v1/technicians", json={"building": "one-anthem", "name": "Ravi", "phone": "919812345678"})
    iss = c.post("/api/v1/issues", json={"building": "one-anthem", "title": "Pump noise"}).json()
    c.post(f"/api/v1/issues/{iss['id']}/transition",
           json={"status": "assigned", "assignee": "Ravi", "by": "manager"})
    notes = _pending(c, "issue_lifecycle")
    tos = {n["to_number"] for n in notes}
    assert "919812345678" in tos and "919900000001" in tos   # tech + manager
    assert any("Assigned to Ravi" in n["text"] for n in notes)


# ── A2: manager actions over WhatsApp (backend-resolved manager only) ────────
def test_manager_assign_command_from_owner_number():
    c = _client(owner="919900000001")
    c.post("/api/v1/technicians", json={"building": "one-anthem", "name": "Ravi", "phone": "919812345678"})
    c.post("/api/v1/forms/open-today", params={"building": "one-anthem"})
    r = c.post("/api/v1/whatsapp/ask",
               json={"question": "assign shift 1 to Ravi", "by": "919900000001"}).json()
    assert r["intent"] == "action" and "Assigned" in r["text"] and "Ravi" in r["text"]
    # the run is now owned by Ravi
    runs = c.get("/api/v1/forms/today", params={"building": "one-anthem"}).json()["runs"]
    s1 = next(x for x in runs if x["name"].startswith("Shift I "))
    assert s1["assignee"] == "Ravi"


def test_manager_close_issue_requires_confirm():
    c = _client(owner="919900000001")
    iss = c.post("/api/v1/issues", json={"building": "one-anthem", "title": "Leak"}).json()
    # first message asks for confirmation, does NOT close
    r1 = c.post("/api/v1/whatsapp/ask",
                json={"question": f"close issue {iss['id']}", "by": "919900000001"}).json()
    assert "confirm" in r1["text"].lower()
    assert c.get(f"/api/v1/issues/{iss['id']}").json()["status"] == "open"
    # YES executes
    r2 = c.post("/api/v1/whatsapp/ask", json={"question": "yes", "by": "919900000001"}).json()
    assert "#" in r2["text"]
    assert c.get(f"/api/v1/issues/{iss['id']}").json()["status"] == "resolved"


def test_unknown_number_cannot_run_manager_actions():
    c = _client(owner="919900000001")
    c.post("/api/v1/forms/open-today", params={"building": "one-anthem"})
    # an unknown number CLAIMING owner must not be able to act
    r = c.post("/api/v1/whatsapp/ask",
               json={"question": "open today", "by": "910000000009", "role": "owner"}).json()
    assert r.get("source") != "command" and r["intent"] != "action"


# ── A3: resident tickets ────────────────────────────────────────────────────
def test_resident_message_creates_common_area_ticket():
    c = _client(owner="919900000001")
    c.post("/api/v1/residents",
           json={"building": "one-anthem", "name": "Asha", "phone": "919048057376", "unit": "B-204"})
    r = c.post("/api/v1/whatsapp/ask",
               json={"question": "Lift not working in B block", "by": "919048057376"}).json()
    assert r["intent"] == "resident" and "ticket #" in r["text"].lower()
    issues = c.get("/api/v1/issues", params={"building": "one-anthem"}).json()["issues"]
    lift = next(i for i in issues if "Lift" in i["title"])
    assert lift["source"] == "resident" and lift["asset"] == "Lift/Elevator"
    assert "B-204" in lift.get("raised_by", "")
    # manager was notified
    assert any(n["to_number"] == "919900000001" for n in _pending(c, "issue_lifecycle"))


def test_resident_greeting_gives_instructions_not_ticket():
    c = _client(owner="919900000001")
    c.post("/api/v1/residents",
           json={"building": "one-anthem", "name": "Asha", "phone": "919048057376"})
    r = c.post("/api/v1/whatsapp/ask", json={"question": "hi", "by": "919048057376"}).json()
    assert r["intent"] == "resident" and "describe" in r["text"].lower()
    assert c.get("/api/v1/issues", params={"building": "one-anthem"}).json()["issues"] == []
