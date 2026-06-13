"""Phase C-1 Shift Handover: deterministic gather/render + LLM-polish with the
grounding guard + fallback. No real LLM."""
from __future__ import annotations

import asyncio

from arvisx.checklist_skills import gather_handover, render_handover, run_handover
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
