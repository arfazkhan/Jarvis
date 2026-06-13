"""Phase-D Vision: provider interface (Null + pluggable), suggestion lifecycle, and the
verify pattern — extraction is a proposal, only confirm writes to the entry."""
from __future__ import annotations

from arvisx import vision
from arvisx.vision import (NullVisionProvider, register_vision_provider, get_provider,
                           extract_from_photo, confirm_suggestion)
from arvisx.persistence import ArvisxDb


class _FakeVision(NullVisionProvider):
    name = "fake"
    available = True

    def extract(self, image_bytes, kind="auto", hint=""):
        return {"available": True, "kind": kind,
                "extracted": {"readings": {"voltage": 415, "current": 118, "frequency": 50},
                              "confidence": 0.9}}


def teardown_function(_):
    register_vision_provider(None)        # reset to default Null after each test


def test_null_provider_default():
    register_vision_provider(None)
    out = extract_from_photo(b"img", kind="gauge")
    assert out["available"] is False and "not configured" in out["reason"]


def test_pluggable_provider():
    register_vision_provider(_FakeVision())
    assert get_provider().name == "fake"
    out = extract_from_photo(b"img", kind="panel")
    assert out["available"] is True
    assert out["extracted"]["readings"]["voltage"] == 415


def test_suggestion_lifecycle(tmp_path):
    db = ArvisxDb(str(tmp_path / "v.db"))
    sid = db.create_vision_suggestion("one-anthem", "p.jpg", "gauge",
                                      {"readings": {"voltage": 415}}, run_id=None, item_id="")
    s = db.get_vision_suggestion(sid)
    assert s["status"] == "pending" and s["extracted"]["readings"]["voltage"] == 415
    assert len(db.list_vision_suggestions("one-anthem", "pending")) == 1
    db.set_vision_suggestion_status(sid, "rejected")
    assert db.list_vision_suggestions("one-anthem", "pending") == []


def test_confirm_writes_entry_only_on_confirm(tmp_path):
    db = ArvisxDb(str(tmp_path / "v2.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-3", "2026-06-14")
    sid = db.create_vision_suggestion("one-anthem", "panel.jpg", "gauge",
                                      {"readings": {"voltage": 415}}, run_id=rid, item_id="dg_battery_v")
    # BEFORE confirm: extraction is only a proposal — the entry must NOT exist
    assert "dg_battery_v" not in db.checklist_entries(rid)
    confirm_suggestion(db, sid, value="24.8", run_id=rid, item_id="dg_battery_v")
    ents = db.checklist_entries(rid)
    assert ents["dg_battery_v"]["value"] == "24.8"           # written ONLY now
    assert ents["dg_battery_v"]["photo"] == "panel.jpg"      # evidence attached
    assert db.get_vision_suggestion(sid)["status"] == "confirmed"


def test_confirm_unknown_returns_none(tmp_path):
    db = ArvisxDb(str(tmp_path / "v3.db"))
    assert confirm_suggestion(db, 999, value="1") is None


if __name__ == "__main__":
    import tempfile, pathlib
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, f in fns:
        if "tmp_path" in f.__code__.co_varnames:
            f(pathlib.Path(tempfile.mkdtemp()))
        else:
            f()
        register_vision_provider(None)
        print(f"  ok {name}")
    print(f"PASS — {len(fns)} vision tests")
