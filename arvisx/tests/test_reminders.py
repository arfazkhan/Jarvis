"""Manager reminders: DM the person, and carry WHAT was actually asked.

Before this, `remind` only looked at the technicians table and sent a fixed pending-round
template — so "remind Rohit to check the DG oil" dropped the instruction entirely, and
"remind the manager" found nobody at all.

Contract:
- The note is the manager's OWN words, verbatim, with attribution. The recipient must know a
  person asked this, not that a bot decided it.
- It reaches anyone on the roster we have a number for — technician, manager, or owner.
- A technician also gets their still-open round.
- Nothing pending AND nothing asked → send NOTHING (no empty ping).
"""
from __future__ import annotations

import pytest

from arvisx.persistence import ArvisxDb


_KEY = "test-key-123"


def _app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from arvisx.api import create_app
    path = str(tmp_path / "rem.db")
    monkeypatch.setenv("ARVISX_DB", path)
    # Adding an owner turns auth on (count_users() > 0), so the client must present a key.
    monkeypatch.setenv("ARVISX_API_KEY", _KEY)
    db = ArvisxDb(path)
    db.add_technician("one-anthem", "Rohit", phone="919000000001")
    db.create_user("Arfaz", "owner", "x", phone="919000000009")
    return TestClient(create_app()), db


def _dms(db, phone):
    """Queued outbound messages addressed to this number."""
    return [n for n in db.pending_notifications()
            if str(n.get("to_number", "")) == phone]


def _ask(client, text, by="919000000009"):
    r = client.post("/api/v1/whatsapp/ask", headers={"X-API-Key": _KEY},
                    json={"question": text, "role": "manager", "by": by})
    assert r.status_code == 200, r.text
    return r.json()["text"]


# ── the ask is carried, verbatim, with attribution ──────────────────────────
def test_remind_carries_the_actual_instruction(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    out = _ask(client, "remind Rohit to check the DG oil")
    assert "Rohit" in out
    dms = _dms(db, "919000000001")
    assert dms, "Rohit should have been DM'd"
    body = dms[-1]["text"]
    assert "check the DG oil" in body, "the manager's actual ask must reach them"
    assert "Arfaz" in body, "the recipient must know WHO asked (attribution)"


def test_note_is_not_reworded(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    _ask(client, "remind Rohit to bring the 12mm spanner and torch")
    body = _dms(db, "919000000001")[-1]["text"]
    assert "bring the 12mm spanner and torch" in body   # verbatim, not paraphrased


# ── reaches managers/owners too, not just technicians ───────────────────────
def test_can_remind_a_manager_by_name(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    out = _ask(client, "remind Arfaz to sign off shift 2")
    assert "Arfaz" in out
    body = _dms(db, "919000000009")[-1]["text"]
    assert "sign off shift 2" in body


def test_can_remind_by_role_word(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    _ask(client, "remind the owner to call the lift vendor")
    assert _dms(db, "919000000009"), "'the owner' should resolve to the owner on the roster"


def test_unknown_person_is_reported_not_silently_dropped(tmp_path, monkeypatch):
    client, _db = _app(tmp_path, monkeypatch)
    out = _ask(client, "remind Bhaskar to check the pump")
    assert "Bhaskar" in out and "matches" in out.lower()


# ── don't send an empty ping ────────────────────────────────────────────────
def test_no_pending_and_no_note_sends_nothing(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    out = _ask(client, "remind Rohit")          # nothing assigned, nothing asked
    assert not _dms(db, "919000000001"), "must not send an empty reminder"
    assert "nothing to remind" in out.lower() or "didn't say what" in out.lower()


def test_missing_phone_tells_the_manager(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    db.add_technician("one-anthem", "Suresh", phone="")
    out = _ask(client, "remind Suresh to mop the lobby")
    assert "no whatsapp number" in out.lower()


# ── a technician still gets their pending round ─────────────────────────────
def test_technician_also_gets_their_open_round(tmp_path, monkeypatch):
    client, db = _app(tmp_path, monkeypatch)
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-1", today, assignee="Rohit")
    _ask(client, "remind Rohit to also check the DG oil")
    body = _dms(db, "919000000001")[-1]["text"]
    assert "check the DG oil" in body          # the ask
    assert "pending" in body.lower()           # AND their open round
