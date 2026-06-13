"""Phase-B agent core: grounded tool set, the ReAct loop (fake LLM), and the
fabricated-number guard. No real LLM, no network."""
from __future__ import annotations

import asyncio

from arvisx.checklist_agent import (CHECKLIST_REGISTRY, build_ctx, run_agent, verify_grounded)
from arvisx.persistence import ArvisxDb


def _seed(tmp_path):
    db = ArvisxDb(str(tmp_path / "agent.db"))
    rid = db.create_checklist_run("one-anthem", "ANTHEM-SHIFT-3", "2026-06-14")
    db.save_checklist_entry(rid, "dg1_status", value="OK", status="ok")
    db.save_checklist_entry(rid, "dg_battery_v", value="24.9")
    db.create_issue("one-anthem", "DG-2 panel: FAULT", asset="DG-2", severity="critical", source="auto")
    return db


# ── tools return real grounded data ─────────────────────────────────────
def test_tools_return_real_data(tmp_path):
    db = _seed(tmp_path)
    ctx = build_ctx(db, "one-anthem", "2026-06-14")
    assets = CHECKLIST_REGISTRY.call("list_assets", ctx, {})
    assert "DG-1" in assets["assets"] and "DG-2" in assets["assets"]

    h = CHECKLIST_REGISTRY.call("asset_health", ctx, {"asset": "DG-2"})
    assert h["asset"] == "DG-2" and h["score"] < 100        # has a critical issue
    assert h["open_issues"] == 1

    iss = CHECKLIST_REGISTRY.call("open_issues", ctx, {"asset": "DG-2"})
    assert len(iss["open_issues"]) == 1

    ov = CHECKLIST_REGISTRY.call("health_overview", ctx, {})
    assert ov["assets"][0]["score"] <= ov["assets"][-1]["score"]   # riskiest first


# ── grounding guard ──────────────────────────────────────────────────────
def test_guard_passes_grounded_numbers():
    ev = [{"asset": "DG-2", "score": 58, "open_issues": 1}]
    g = verify_grounded("DG-2 is at 58/100 with 1 open issue.", ev)
    assert g["grounded"] is True


def test_guard_catches_fabricated_number():
    ev = [{"asset": "DG-2", "score": 58}]
    g = verify_grounded("Failure risk is 82% within 30 days.", ev)
    assert g["grounded"] is False
    assert "82" in g["ungrounded"] or "30" in g["ungrounded"]


def test_guard_ignores_single_digits():
    g = verify_grounded("1. Check DG-2  2. Check pump", [])
    assert g["grounded"] is True            # ordinals/single digits not policed


# ── ReAct loop with a scripted fake LLM ──────────────────────────────────
class _FakeLLM:
    def __init__(self, script):
        self.script, self.i = script, 0

    async def ask_tools(self, messages, schemas, system_msgs=None, **k):
        r = self.script[self.i]; self.i += 1
        return r


def test_run_agent_executes_tools_then_answers(tmp_path):
    db = _seed(tmp_path)
    ctx = build_ctx(db, "one-anthem", "2026-06-14")
    script = [
        {"assistant_message": {"role": "assistant", "content": "",
                               "tool_calls": [{"id": "1", "type": "function",
                                               "function": {"name": "asset_health", "arguments": "{\"asset\":\"DG-2\"}"}}]},
         "tool_calls": [{"id": "1", "name": "asset_health", "args": {"asset": "DG-2"}}],
         "content": "", "finish": "tool_calls"},
        {"assistant_message": {"role": "assistant", "content": "DG-2 needs attention."},
         "tool_calls": [], "content": "DG-2 needs attention.", "finish": "stop"},
    ]
    out = asyncio.run(run_agent(_FakeLLM(script), "You are the supervisor.", "How is DG-2?", ctx))
    assert out["steps"] == 2 and out["truncated"] is False
    assert out["text"] == "DG-2 needs attention."
    assert out["evidence"] and out["evidence"][0]["asset"] == "DG-2"   # tool ran, grounded


def test_run_agent_truncates_at_max_steps(tmp_path):
    db = _seed(tmp_path)
    ctx = build_ctx(db, "one-anthem", "2026-06-14")
    loop_turn = {"assistant_message": {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "x", "type": "function",
                                 "function": {"name": "list_assets", "arguments": "{}"}}]},
                 "tool_calls": [{"id": "x", "name": "list_assets", "args": {}}],
                 "content": "", "finish": "tool_calls"}
    out = asyncio.run(run_agent(_FakeLLM([loop_turn] * 10), "sys", "loop", ctx, max_steps=3))
    assert out["truncated"] is True and out["steps"] == 3


if __name__ == "__main__":
    import tempfile, pathlib
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        if "tmp_path" in f.__code__.co_varnames:
            f(pathlib.Path(tempfile.mkdtemp()))
        else:
            f()
        print(f"  ok {f.__name__}")
    print(f"PASS — {len(fns)} agent-core tests")
