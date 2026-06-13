"""Phase-0 digitized checklists: templates, issue rules on operator input,
run lifecycle (entries + completion + sign-off), persistence roundtrip."""
from __future__ import annotations

from datetime import datetime

from arvisx.checklist_forms import (templates_for, get_template, entry_is_issue,
                                     run_summary, manager_digest, valid_issue_transition,
                                     ISSUE_STATUSES, Item)
from arvisx.persistence import ArvisxDb


# ── templates ─────────────────────────────────────────────────────────────
def test_one_anthem_has_four_templates():
    ts = templates_for("one-anthem")
    ids = {t.template_id for t in ts}
    assert ids == {"ANTHEM-SHIFT-1", "ANTHEM-SHIFT-2", "ANTHEM-SHIFT-3", "ANTHEM-PPM"}


def test_shift2_matches_the_real_sheet():
    t = get_template("ANTHEM-SHIFT-2")
    items = {i.item_id for i in t.all_items()}
    # the sheet's distinctive items
    for need in ("wtp_backwash", "wtp_chemical", "el_transformer", "el_dg1_panel",
                 "g2_fire_alarm", "g2_oh_tank", "g2_japan_water", "g2_borewell"):
        assert need in items, need
    assert t.signoff_roles[0] == "technician" and "president" in t.signoff_roles


def test_ppm_is_quarterly_and_per_asset():
    t = get_template("ANTHEM-PPM")
    assert t.cadence == "quarterly"
    assert "Transformer Panel" in t.per_asset and "DG Panel" in t.per_asset
    assert len(t.sections) == 10


# ── issue rules on the operator's OWN input (no sensors) ──────────────────
def test_fire_panel_off_auto_flags_issue():
    item = next(i for i in get_template("ANTHEM-SHIFT-2").all_items() if i.item_id == "g2_fire_alarm")
    assert entry_is_issue(item, "OFF")        # the exact real-sheet failure
    assert entry_is_issue(item, "FAULT")
    assert not entry_is_issue(item, "ON")


def test_leakage_detected_flags_and_explicit_issue_status():
    leak = next(i for i in get_template("ANTHEM-SHIFT-2").all_items() if i.item_id == "wtp_leakage")
    assert entry_is_issue(leak, "DETECTED")
    assert not entry_is_issue(leak, "NIL")
    # explicit operator 'issue' on any item
    assert entry_is_issue(Item("x", "X", "tick"), None, status="issue")


# ── run summary ───────────────────────────────────────────────────────────
def test_run_summary_completion_and_issues():
    t = get_template("ANTHEM-SHIFT-2")
    entries = {
        "wtp_backwash": {"value": "done", "status": "ok"},
        "g2_fire_alarm": {"value": "OFF", "status": ""},     # auto-issue
        "g2_oh_tank": {"value": "90", "status": "ok"},
    }
    s = run_summary(t, entries)
    assert s["done"] == 3 and s["total"] == len(t.all_items())
    assert 0 < s["completion_pct"] < 100
    assert any(i["item_id"] == "g2_fire_alarm" for i in s["issues"])
    assert "wtp_chemical" in s["missing"]


# ── persistence lifecycle ─────────────────────────────────────────────────
def test_run_lifecycle_roundtrip(tmp_path):
    db = ArvisxDb(str(tmp_path / "cl.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14", technician="Ajith")
    assert db.find_open_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14") == rid

    db.save_checklist_entry(rid, "g2_fire_alarm", value="OFF", is_issue=True)
    db.save_checklist_entry(rid, "g2_oh_tank", value="90", status="ok")
    db.save_checklist_entry(rid, "g2_oh_tank", value="92", status="ok")   # correction → upsert
    ents = db.checklist_entries(rid)
    assert ents["g2_oh_tank"]["value"] == "92"        # last write wins, one row
    assert ents["g2_fire_alarm"]["is_issue"] is True

    db.add_checklist_signoff(rid, "technician", "Ajith")
    db.add_checklist_signoff(rid, "supervisor", "Athul")
    so = db.checklist_signoffs(rid)
    assert {s["role"] for s in so} == {"technician", "supervisor"}

    db.submit_checklist_run(rid)
    run = db.get_checklist_run(rid)
    assert run["status"] == "submitted" and run["submitted_at"]
    assert db.find_open_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14") is None  # no longer open


def test_entries_are_server_timestamped(tmp_path):
    db = ArvisxDb(str(tmp_path / "cl2.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-1", "2026-06-14")
    db.save_checklist_entry(rid, "pool_ph", value="7.2")
    ts = db.checklist_entries(rid)["pool_ph"]["ts"]
    # a real ISO timestamp the operator can't backdate from the form
    datetime.fromisoformat(ts)


def test_manager_digest_surfaces_issues_and_completion():
    runs = [
        {"template_id": "ANTHEM-SHIFT-1", "name": "Shift I", "status": "submitted",
         "completion_pct": 100, "issues": [], "signoffs": ["technician", "supervisor"]},
        {"template_id": "ANTHEM-SHIFT-2", "name": "Shift II", "status": "open",
         "completion_pct": 60, "issues": [{"label": "Fire alarm panel health", "value": "OFF"}],
         "signoffs": []},
    ]
    t = manager_digest(runs, "2026-06-14")
    assert "Shift I" in t and "100%" in t
    assert "Fire alarm panel health" in t and "OFF" in t
    assert "Flagged" in t


def test_manager_digest_empty_day():
    assert "No checklists started" in manager_digest([], "2026-06-14")


# ── issue lifecycle ─────────────────────────────────────────────────────
def test_issue_transitions():
    assert valid_issue_transition("open", "assigned")
    assert valid_issue_transition("in_progress", "resolved")
    assert valid_issue_transition("resolved", "open")        # reopen
    assert not valid_issue_transition("resolved", "assigned")
    assert not valid_issue_transition("open", "bogus")


def test_issue_persistence_and_history(tmp_path):
    db = ArvisxDb(str(tmp_path / "iss.db"))
    iid = db.create_issue("one-anthem", "Fire alarm panel: OFF", detail="main panel off",
                          asset="Fire Panel", severity="critical", source="manual", raised_by="Ajith")
    iss = db.get_issue(iid)
    assert iss["status"] == "open" and iss["history"][0]["action"] == "opened"
    db.update_issue(iid, assignee="Arjun", by="Athul")
    db.update_issue(iid, status="in_progress", by="Arjun", note="checking breaker")
    db.update_issue(iid, status="resolved", by="Arjun", note="reset, normal")
    iss = db.get_issue(iid)
    assert iss["status"] == "resolved" and iss["assignee"] == "Arjun"
    assert len(iss["history"]) == 4                          # open + assign + 2 status
    assert db.list_issues("one-anthem", status="resolved")[0]["id"] == iid
    assert db.list_issues("one-anthem", status="open") == []


def test_auto_issue_dedup_per_run_item(tmp_path):
    db = ArvisxDb(str(tmp_path / "iss2.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14")
    assert db.find_auto_issue(rid, "g2_fire_alarm") is None
    aid = db.create_issue("one-anthem", "Fire alarm: OFF", run_id=rid, item_id="g2_fire_alarm",
                          source="auto")
    assert db.find_auto_issue(rid, "g2_fire_alarm") == aid    # found before resolve
    db.update_issue(aid, status="resolved", by="system", note="corrected")
    assert db.find_auto_issue(rid, "g2_fire_alarm") is None    # resolved → not re-found


# ── photo evidence storage ──────────────────────────────────────────────
def test_photo_save_and_resolve(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVISX_UPLOAD_DIR", str(tmp_path / "up"))
    from arvisx.uploads import save_photo, photo_path
    name, mt = save_photo(b"\xff\xd8\xff fake jpeg bytes", filename="round.jpg")
    assert mt == "image/jpeg" and name.endswith(".jpg")
    assert photo_path(name) is not None
    assert photo_path("nope.jpg") is None


def test_photo_rejects_bad_type_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVISX_UPLOAD_DIR", str(tmp_path / "up2"))
    from arvisx.uploads import save_photo, photo_path
    import pytest
    with pytest.raises(ValueError):
        save_photo(b"data", filename="evil.exe")
    with pytest.raises(ValueError):
        save_photo(b"", filename="empty.png")
    assert photo_path("../secret") is None                    # traversal rejected


# ── technician roster + run assignment ──────────────────────────────────
def test_roster_add_list_reactivate_deactivate(tmp_path):
    db = ArvisxDb(str(tmp_path / "r.db"))
    a = db.add_technician("one-anthem", "Ajith", "9111")
    db.add_technician("one-anthem", "Suresh")
    assert {t["name"] for t in db.list_technicians("one-anthem")} == {"Ajith", "Suresh"}
    db.set_technician_active(a, False)
    assert {t["name"] for t in db.list_technicians("one-anthem")} == {"Suresh"}
    # re-adding a soft-deleted name reactivates (no duplicate)
    a2 = db.add_technician("one-anthem", "Ajith", "9222")
    assert a2 == a
    assert len(db.list_technicians("one-anthem")) == 2


def test_run_assignment_and_my_tasks(tmp_path):
    db = ArvisxDb(str(tmp_path / "as.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14", assignee="Ajith")
    assert db.get_checklist_run(rid)["assignee"] == "Ajith"
    # reassign — task isn't bound to one person
    db.assign_checklist_run(rid, "Suresh")
    assert db.get_checklist_run(rid)["assignee"] == "Suresh"
    mine = db.runs_assigned_to("one-anthem", "Suresh", "2026-06-14")
    assert len(mine) == 1 and mine[0]["id"] == rid
    assert db.runs_assigned_to("one-anthem", "Ajith", "2026-06-14") == []


def test_digest_flags_unassigned():
    runs = [{"template_id": "ANTHEM-SHIFT-1", "name": "Shift I", "status": "open",
             "completion_pct": 0, "issues": [], "signoffs": [], "assignee": ""}]
    assert "unassigned" in manager_digest(runs, "2026-06-14").lower()
    runs[0]["assignee"] = "Ajith"
    assert "Ajith" in manager_digest(runs, "2026-06-14")


if __name__ == "__main__":
    import sys, tempfile, pathlib
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        if "tmp_path" in f.__code__.co_varnames:
            f(pathlib.Path(tempfile.mkdtemp()))
        else:
            f()
        print(f"  ok {f.__name__}")
    print(f"PASS — {len(fns)} checklist-form tests")
