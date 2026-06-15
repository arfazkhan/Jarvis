"""Phase-0 digitized checklists: templates, issue rules on operator input,
run lifecycle (entries + completion + sign-off), persistence roundtrip."""
from __future__ import annotations

from datetime import datetime

from arvisx.checklist_forms import (templates_for, get_template, entry_is_issue,
                                     run_summary, manager_digest, valid_issue_transition,
                                     ISSUE_STATUSES, assets_in, items_for_asset, ppm_status, Item)
from arvisx.persistence import ArvisxDb


# ── templates ─────────────────────────────────────────────────────────────
def test_one_anthem_has_four_templates():
    ts = templates_for("one-anthem")
    ids = {t.template_id for t in ts}
    assert ids == {"ANTHEM-SHIFT-1", "ANTHEM-SHIFT-2", "ANTHEM-SHIFT-3", "ANTHEM-PPM"}


def test_templates_are_seed_data_not_code():
    # One Anthem is loaded from arvisx/seeds/one-anthem.json — the engine code holds no
    # building-specific templates/asset-map (so a new building is config, not a code change).
    import pathlib, arvisx.checklist_forms as cf
    seed = pathlib.Path(cf.__file__).parent / "seeds" / "one-anthem.json"
    assert seed.is_file()
    src = pathlib.Path(cf.__file__).read_text(encoding="utf-8")
    assert "_ANTHEM_ASSET_MAP" not in src and "ANTHEM-SHIFT-1" not in src   # no hardcoding
    # asset tags come from the seed data (e.g. DG-1 readings tagged in the JSON)
    assert any(it.asset == "DG-1" for _t, it in items_for_asset("one-anthem", "DG-1"))


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


def test_notification_queue_roundtrip(tmp_path):
    db = ArvisxDb(str(tmp_path / "n.db"))
    a = db.enqueue_notification("one-anthem", "You're assigned Shift II", to_number="919111", kind="assignment")
    b = db.enqueue_notification("one-anthem", "Fire panel OFF", to_number="", kind="issue")
    pend = db.pending_notifications()
    assert len(pend) == 2
    assert any(n["to_number"] == "919111" for n in pend)     # DM target
    assert any(n["to_number"] == "" for n in pend)           # ops broadcast
    db.mark_notifications_sent([a])
    pend2 = db.pending_notifications()
    assert len(pend2) == 1 and pend2[0]["id"] == b           # acked one stays gone


# ── Phase S: asset tagging / registry / history / PPM ───────────────────
def test_asset_tagging_and_registry():
    regs = assets_in("one-anthem")
    for a in ("DG-1", "DG-2", "FIRE-PUMP", "WTP", "STP", "TRANSFORMER", "OH-TANK"):
        assert a in regs, a
    # items map to assets
    dg1_items = {it.item_id for _t, it in items_for_asset("one-anthem", "DG-1")}
    assert "dg1_status" in dg1_items and "dg_run_hours" in dg1_items
    assert "el_dg1_panel" in dg1_items                       # the Shift-II panel too


def test_ppm_status_date_based():
    s = {"asset": "MSB", "interval_days": 90, "last_done": "2026-03-01", "run_hours_limit": None}
    st = ppm_status(s, "2026-06-14")
    assert st["overdue"] is True and st["status"] == "overdue"   # 90d from Mar 1 = May 30
    st2 = ppm_status(s, "2026-05-01")
    assert st2["status"] in ("ok", "due_soon") and not st2["overdue"]


def test_ppm_status_condition_based_run_hours():
    s = {"asset": "DG-1", "interval_days": None, "last_done": None, "run_hours_limit": 250}
    near = ppm_status(s, "2026-06-14", latest_run_hours=243)
    assert near["hours_remaining"] == 7.0 and near["status"] == "due_soon"
    over = ppm_status(s, "2026-06-14", latest_run_hours=260)
    assert over["overdue"] is True


def test_ppm_unscheduled():
    assert ppm_status({"asset": "X"}, "2026-06-14")["status"] == "unscheduled"


def test_ppm_persistence_and_partial_update(tmp_path):
    db = ArvisxDb(str(tmp_path / "ppm.db"))
    db.set_ppm_schedule("one-anthem", "DG-1", interval_days=90, last_done="2026-03-01")
    db.set_ppm_schedule("one-anthem", "DG-1", run_hours_limit=250)   # partial — keeps interval/last_done
    s = db.get_ppm_schedule("one-anthem", "DG-1")
    assert s["interval_days"] == 90 and s["last_done"] == "2026-03-01" and s["run_hours_limit"] == 250
    db.mark_ppm_done("one-anthem", "DG-1", "2026-06-14")
    assert db.get_ppm_schedule("one-anthem", "DG-1")["last_done"] == "2026-06-14"
    assert len(db.list_ppm_schedules("one-anthem")) == 1


def test_asset_entries_history(tmp_path):
    db = ArvisxDb(str(tmp_path / "hist.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-3", "2026-06-14")
    db.save_checklist_entry(rid, "dg_battery_v", value="24.9")
    db.save_checklist_entry(rid, "dg_run_hours", value="243")
    hist = db.asset_entries("one-anthem", ["dg_battery_v", "dg_run_hours"])
    assert {h["item_id"] for h in hist} == {"dg_battery_v", "dg_run_hours"}
    assert all("shift_date" in h for h in hist)               # joined run date for the timeline


# ── checklist builder (custom templates) ────────────────────────────────
def test_template_from_dict_roundtrip():
    from arvisx.checklist_forms import Template
    d = get_template("ANTHEM-SHIFT-2").to_dict()
    t2 = Template.from_dict(d)
    assert t2.template_id == "ANTHEM-SHIFT-2"
    assert {i.item_id for i in t2.all_items()} == {i["item_id"] for s in d["sections"] for i in s["items"]}


def test_validate_template_rejects_bad():
    from arvisx.checklist_forms import validate_template_dict
    import pytest
    with pytest.raises(ValueError):
        validate_template_dict({"name": "x", "sections": [{"items": [{"item_id": "a"}]}]})  # no template_id
    with pytest.raises(ValueError):
        validate_template_dict({"template_id": "T", "name": "x", "sections": []})           # no sections
    with pytest.raises(ValueError):
        validate_template_dict({"template_id": "T", "name": "x",
                                "sections": [{"items": [{"item_id": "a"}, {"item_id": "a"}]}]})  # dup
    with pytest.raises(ValueError):
        validate_template_dict({"template_id": "T", "name": "x",
                                "sections": [{"items": [{"item_id": "a", "kind": "bogus"}]}]})  # bad kind
    # valid passes
    validate_template_dict({"template_id": "T", "name": "x",
                            "sections": [{"name": "S", "items": [{"item_id": "a", "kind": "tick"}]}]})


def test_custom_template_persistence(tmp_path):
    db = ArvisxDb(str(tmp_path / "tmpl.db"))
    tmpl = {"template_id": "MY-DAILY", "name": "My Daily", "cadence": "daily",
            "sections": [{"name": "S", "items": [{"item_id": "x1", "label": "X", "kind": "reading", "unit": "V"}]}]}
    db.save_template("bldg-x", "MY-DAILY", tmpl)
    assert db.list_templates("bldg-x")[0]["template_id"] == "MY-DAILY"
    assert db.delete_template("bldg-x", "MY-DAILY") is True
    assert db.list_templates("bldg-x") == []


def test_seed_catalog_and_clone(tmp_path):
    from arvisx.checklist_forms import (seed_catalog, seed_templates, set_custom_loader,
                                        templates_for, Template)
    cat = seed_catalog()
    assert any(s["building_id"] == "one-anthem" and s["templates"] == 4 for s in cat)
    src = seed_templates("one-anthem")
    assert len(src) == 4 and seed_templates("nope") == []
    # clone into a new building via the DB loader (what POST /forms/seed does)
    db = ArvisxDb(str(tmp_path / "seed.db"))
    for t in src:
        db.save_template("green-meadows", t.template_id, t.to_dict())
    set_custom_loader(lambda b: [Template.from_dict(d) for d in db.list_templates(b)])
    try:
        ids = {t.template_id for t in templates_for("green-meadows")}
        assert ids == {"ANTHEM-SHIFT-1", "ANTHEM-SHIFT-2", "ANTHEM-SHIFT-3", "ANTHEM-PPM"}
    finally:
        set_custom_loader(None)


def test_custom_loader_merges_and_overrides():
    from arvisx.checklist_forms import set_custom_loader, templates_for, Template
    custom = Template.from_dict({"template_id": "CUSTOM-1", "name": "Custom", "cadence": "daily",
                                 "sections": [{"name": "S", "items": [{"item_id": "x1", "label": "X"}]}]})
    override = Template.from_dict({"template_id": "ANTHEM-SHIFT-1", "name": "Overridden", "cadence": "daily",
                                   "sections": [{"name": "S", "items": [{"item_id": "y1", "label": "Y"}]}]})
    set_custom_loader(lambda b: [custom, override])
    try:
        ids = {t.template_id for t in templates_for("one-anthem")}
        assert "CUSTOM-1" in ids                                  # new custom added
        s1 = get_template("ANTHEM-SHIFT-1", "one-anthem")
        assert s1.name == "Overridden"                           # same id overrides code default
    finally:
        set_custom_loader(None)


# ── round-completion reminder sweep ─────────────────────────────────────
def test_round_reminders_nudge_then_escalate(tmp_path):
    from datetime import datetime, timedelta
    from arvisx import checklist_intel as ci
    db = ArvisxDb(str(tmp_path / "rr.db"))
    today = datetime.now().strftime("%Y-%m-%d")
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", today,
                                  technician="Ajith", assignee="Ajith")
    db.add_technician("one-anthem", "Ajith", "919000")
    db.save_checklist_entry(rid, "wtp_backwash", value="done", status="ok")   # ~4% done
    # backdate start to 7h ago → past remind (6h), before escalate (10h)
    with db._conn() as c:
        c.execute("UPDATE checklist_runs SET started_at=? WHERE id=?",
                  ((datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds"), rid))
    fired = ci.round_reminders(db, "one-anthem")
    assert fired and fired[0]["level"] == 1                       # tech nudged
    assert ci.round_reminders(db, "one-anthem") == []            # dedup — no repeat at level 1
    n = db.pending_notifications()
    assert any(x["kind"] == "round_reminder" and x["to_number"] == "919000" for x in n)

    # now backdate to 11h → escalate to manager (ops broadcast)
    with db._conn() as c:
        c.execute("UPDATE checklist_runs SET started_at=? WHERE id=?",
                  ((datetime.now() - timedelta(hours=11)).isoformat(timespec="seconds"), rid))
    fired2 = ci.round_reminders(db, "one-anthem")
    assert fired2 and fired2[0]["level"] == 2
    assert any(x["kind"] == "round_escalation" and x["to_number"] == "" for x in db.pending_notifications())


def test_round_reminders_skip_complete_and_submitted(tmp_path):
    from datetime import datetime, timedelta
    from arvisx import checklist_intel as ci
    db = ArvisxDb(str(tmp_path / "rr2.db"))
    today = datetime.now().strftime("%Y-%m-%d")
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", today, assignee="Ajith")
    with db._conn() as c:
        c.execute("UPDATE checklist_runs SET started_at=? WHERE id=?",
                  ((datetime.now() - timedelta(hours=12)).isoformat(timespec="seconds"), rid))
    db.submit_checklist_run(rid)                                  # submitted → skip
    assert ci.round_reminders(db, "one-anthem") == []


# ── Fix #1: incomplete prior-day rounds get a terminal (lapse) ──────────
def test_lapse_stale_rounds(tmp_path):
    from arvisx import checklist_intel as ci
    db = ArvisxDb(str(tmp_path / "lapse.db"))
    yesterday = "2026-06-13"
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", yesterday, assignee="Ajith")
    db.save_checklist_entry(rid, "wtp_backwash", value="done", status="ok")   # incomplete
    today_rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", "2026-06-14")
    lapsed = ci.lapse_stale_rounds(db, "one-anthem", "2026-06-14")
    assert len(lapsed) == 1 and lapsed[0]["run_id"] == rid
    assert db.get_checklist_run(rid)["status"] == "lapsed"          # terminal reached
    assert db.get_checklist_run(today_rid)["status"] == "open"      # today untouched
    # idempotent — lapsed run not re-swept
    assert ci.lapse_stale_rounds(db, "one-anthem", "2026-06-14") == []
    assert any(n["kind"] == "round_lapsed" for n in db.pending_notifications())


# ── Fix #2: aged open issues surface ────────────────────────────────────
def test_aged_open_issues(tmp_path):
    from datetime import datetime, timedelta
    from arvisx import checklist_intel as ci
    db = ArvisxDb(str(tmp_path / "aged.db"))
    iid = db.create_issue("one-anthem", "STP blower FAULT", asset="STP", source="auto")
    old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    with db._conn() as c:
        c.execute("UPDATE checklist_issues SET created_at=? WHERE id=?", (old, iid))
    fresh = db.create_issue("one-anthem", "new one", asset="X", source="auto")
    aged = ci.aged_open_issues(db, "one-anthem", days=2)
    assert [a["id"] for a in aged] == [iid]                         # only the 3-day-old one
    db.update_issue(iid, status="resolved", by="x")
    assert ci.aged_open_issues(db, "one-anthem", days=2) == []      # resolved drops off


# ── Fix #3: reopen resets the escalation clock ──────────────────────────
def test_reopen_resets_escalation(tmp_path):
    db = ArvisxDb(str(tmp_path / "reopen.db"))
    iid = db.create_issue("one-anthem", "DG-2 FAULT", asset="DG-2", severity="critical", source="auto")
    db.set_issue_fields(iid, escalated_level=4)                     # was at committee
    db.update_issue(iid, status="resolved", by="x")
    db.update_issue(iid, status="open", by="y")                     # reopen
    iss = db.get_issue(iid)
    assert iss["escalated_level"] == 0                              # clock reset
    assert any(h["action"] == "reopened" for h in iss["history"])


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
