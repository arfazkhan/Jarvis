"""Phase C-1 Shift Handover: deterministic gather/render + LLM-polish with the
grounding guard + fallback. No real LLM."""
from __future__ import annotations

import asyncio

from arvisx.checklist_skills import (gather_handover, render_handover, run_handover,
                                     gather_rca, render_rca, run_rca,
                                     suggest_work_order, render_work_order,
                                     building_qa_deterministic, run_building_qa)
from arvisx.persistence import ArvisxDb

T = "2026-06-14"


def _seed(tmp_path, with_issues=True):
    db = ArvisxDb(str(tmp_path / "ho.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-2", T, assignee="Ajith")
    db.save_checklist_entry(rid, "wtp_backwash", value="done", status="ok")  # leaves many missing
    if with_issues:
        db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical",
                        source="auto", run_id=rid, item_id="el_dg2_panel")
    return db


def test_gather_and_render_has_sections(tmp_path):
    db = _seed(tmp_path)
    data = gather_handover(db, "one-anthem", T)
    assert data["priority"] == "High"                  # critical issue present
    assert data["open_issues"] and data["pending"]
    txt = render_handover(data)
    assert "Shift Handover" in txt and "Open Issues" in txt and "Pending Tasks" in txt
    assert "DG-2 panel: FAULT" in txt and "Priority:* High" in txt


def test_render_all_clear(tmp_path):
    db = ArvisxDb(str(tmp_path / "clear.db"))
    txt = render_handover(gather_handover(db, "one-anthem", T))
    assert "All clear" in txt


def test_run_handover_deterministic_without_llm(tmp_path):
    db = _seed(tmp_path)
    res = asyncio.run(run_handover(None, db, "one-anthem", T))
    assert res["source"] == "deterministic" and "Shift Handover" in res["text"]


class _FakeLLM:
    def __init__(self, final_text):
        self.turn = 0
        self.final = final_text

    async def ask_tools(self, messages, schemas, system_msgs=None, **k):
        self.turn += 1
        if self.turn == 1:
            return {"assistant_message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "1", "type": "function",
                                    "function": {"name": "open_issues", "arguments": "{}"}}]},
                    "tool_calls": [{"id": "1", "name": "open_issues", "args": {}}],
                    "content": "", "finish": "tool_calls"}
        return {"assistant_message": {"role": "assistant", "content": self.final},
                "tool_calls": [], "content": self.final, "finish": "stop"}


def test_run_handover_uses_grounded_agent_text(tmp_path):
    db = _seed(tmp_path)
    # only single-digit/asset numbers → grounded
    llm = _FakeLLM("*Shift Handover*\nOpen Issues:\n1. DG-2 panel FAULT\nPriority: High")
    res = asyncio.run(run_handover(llm, db, "one-anthem", T))
    assert res["source"] == "agent" and "DG-2" in res["text"]


def test_run_handover_falls_back_on_fabricated_number(tmp_path):
    db = _seed(tmp_path)
    llm = _FakeLLM("Failure risk 82% within 30 days for DG-2.")   # 82/30 not in evidence
    res = asyncio.run(run_handover(llm, db, "one-anthem", T))
    assert res["source"] == "deterministic-fallback"
    assert "82" not in res["text"]


# ── C-2 Root-Cause Investigator ─────────────────────────────────────────
def _seed_declining_battery(tmp_path):
    db = ArvisxDb(str(tmp_path / "rca.db"))
    for v in (25.0, 24.0, 23.0, 22.0):          # steady decline across shifts → trend
        rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-3", T)
        db.save_checklist_entry(rid, "dg_battery_v", value=str(v))
    return db


def test_rca_infers_battery_cause(tmp_path):
    db = _seed_declining_battery(tmp_path)
    data = gather_rca(db, "one-anthem", "DG-1", T)
    assert data["probable_cause"] and "Battery" in data["probable_cause"]
    assert any("declining" in o for o in data["observations"])
    txt = render_rca(data)
    assert "Root Cause — DG-1" in txt and "Recommended:" in txt and "Confidence:" in txt


def test_rca_recurring_detected(tmp_path):
    db = ArvisxDb(str(tmp_path / "rec.db"))
    db.create_issue("one-anthem", "STP blower: FAULT", asset="STP", source="auto")
    db.create_issue("one-anthem", "STP blower: FAULT", asset="STP", source="auto")
    data = gather_rca(db, "one-anthem", "STP", T)
    assert data["recurring"] and any("recurring" in o for o in data["observations"])


def test_rca_abstains_without_pattern(tmp_path):
    db = ArvisxDb(str(tmp_path / "thin.db"))
    data = gather_rca(db, "one-anthem", "LIFT", T)
    assert data["probable_cause"] is None
    assert "inspect on site" in render_rca(data).lower()


def test_run_rca_deterministic_without_llm(tmp_path):
    db = _seed_declining_battery(tmp_path)
    res = asyncio.run(run_rca(None, db, "one-anthem", "DG-1", T))
    assert res["source"] == "deterministic" and "Battery" in res["text"]


def test_run_rca_falls_back_on_fabricated_number(tmp_path):
    db = _seed_declining_battery(tmp_path)
    llm = _FakeLLM("Root cause: failure probability 73% over 40 days.")
    res = asyncio.run(run_rca(llm, db, "one-anthem", "DG-1", T))
    assert res["source"] == "deterministic-fallback" and "73" not in res["text"]


# ── C-3 Work-Order agent ────────────────────────────────────────────────
def test_work_order_classifies_electrical(tmp_path):
    db = ArvisxDb(str(tmp_path / "wo.db"))
    iid = db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical",
                          source="auto")
    s = suggest_work_order(db, "one-anthem", iid, T)
    assert s["category"] == "Electrical" and s["required_team"] == "Electrical"
    assert s["priority"] == "High"                  # critical → High
    assert render_work_order(s).count("create work order") == 1


def test_work_order_plumbing_and_safety(tmp_path):
    db = ArvisxDb(str(tmp_path / "wo2.db"))
    leak = db.create_issue("one-anthem", "WTP leakage: DETECTED", asset="WTP", source="auto")
    fire = db.create_issue("one-anthem", "Fire alarm: OFF", asset="FIRE-PANEL", severity="critical",
                           source="auto")
    assert suggest_work_order(db, "one-anthem", leak, T)["category"] == "Plumbing"
    fs = suggest_work_order(db, "one-anthem", fire, T)
    assert fs["category"] == "Safety" and fs["required_team"] == "Fire-Safety"


def test_work_order_action_from_rca(tmp_path):
    db = ArvisxDb(str(tmp_path / "wo3.db"))
    for v in (25.0, 24.0, 23.0, 22.0):
        rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-3", T)
        db.save_checklist_entry(rid, "dg_battery_v", value=str(v))
    iid = db.create_issue("one-anthem", "DG-1 battery low", asset="DG-1", source="auto")
    s = suggest_work_order(db, "one-anthem", iid, T)
    assert "load test" in s["suggested_action"].lower()   # borrowed from the battery RCA


def test_work_order_unknown_issue(tmp_path):
    db = ArvisxDb(str(tmp_path / "wo4.db"))
    assert suggest_work_order(db, "one-anthem", 999, T) == {}


# ── C-4 Digital-Twin Q&A ─────────────────────────────────────────────────
def test_qa_riskiest_system(tmp_path):
    db = ArvisxDb(str(tmp_path / "qa.db"))
    db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical", source="auto")
    ans = building_qa_deterministic(db, "one-anthem", T, "what's the riskiest system?")
    assert "Riskiest systems" in ans and "DG-2" in ans


def test_qa_open_issues(tmp_path):
    db = ArvisxDb(str(tmp_path / "qa2.db"))
    db.create_issue("one-anthem", "WTP leakage: DETECTED", asset="WTP", source="auto")
    ans = building_qa_deterministic(db, "one-anthem", T, "what is open right now?")
    assert "Open issues" in ans and "WTP leakage" in ans


def test_qa_default_overview(tmp_path):
    db = ArvisxDb(str(tmp_path / "qa3.db"))
    # An overview-ish question still gets the overview…
    assert "Building overview" in building_qa_deterministic(db, "one-anthem", T, "how is the building")
    # …but an unrelated/meta question gets a helpful redirect, NOT a stats dump.
    other = building_qa_deterministic(db, "one-anthem", T, "hello")
    assert "Building overview" not in other and "help" in other.lower()


def test_run_qa_deterministic_without_llm(tmp_path):
    db = ArvisxDb(str(tmp_path / "qa4.db"))
    db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical", source="auto")
    res = asyncio.run(run_building_qa(None, db, "one-anthem", "riskiest system?", T))
    assert res["source"] == "deterministic" and "DG-2" in res["text"]


def test_run_qa_fallback_on_fabricated_number(tmp_path):
    db = ArvisxDb(str(tmp_path / "qa5.db"))
    db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical", source="auto")
    llm = _FakeLLM("The riskiest system is DG-2 at 41% with 5 faults pending.")  # 41/5 not in evidence... 5 is single
    res = asyncio.run(run_building_qa(llm, db, "one-anthem", "riskiest?", T))
    assert res["source"] == "deterministic"          # 41 ungrounded → fell back


if __name__ == "__main__":
    import tempfile, pathlib
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        if "tmp_path" in f.__code__.co_varnames:
            f(pathlib.Path(tempfile.mkdtemp()))
        else:
            f()
        print(f"  ok {f.__name__}")
    print(f"PASS — {len(fns)} handover tests")
