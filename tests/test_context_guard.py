"""
Agent context guard.

Logs showed agent calls failing at ~195k input tokens. The cause was not long
conversations but get_dashboard_overview returning the whole building snapshot
(every point value) as one tool result. Fixed at the source, plus a general
guard so no tool result, now or later, can do it again. Full results always
stay in the evidence ledger; only the agent's conversation copy is bounded.
"""
import asyncio
from types import SimpleNamespace

from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
from arvis_core.swarm import node as node_mod
from arvis_core.swarm.node import _compact_tool_history, _fit_tool_result


# ─────────────────────────────────────────────────────────────────────────────
# Source fix: the overview tool returns the overview it promises
# ─────────────────────────────────────────────────────────────────────────────
class _FakeState:
    async def get_snapshot(self):
        return {
            "timestamp": "2026-10-22T10:00:00",
            "equipment_count": 412,
            "point_count": 9000,
            "active_alarm_count": 2,
            "equipment_by_status": {"running": 400, "fault": 12},
            "current_values": {f"AHU-{i}/point_{j}": 21.5 for i in range(300) for j in range(30)},
            "active_alarms": [{"severity": "critical"}, {"severity": "low"}],
            "stats": {},
        }


def test_dashboard_overview_is_a_summary_not_the_whole_building():
    out = asyncio.run(EquipmentHandlerMixin._handle_get_dashboard_overview(SimpleNamespace(bms_state=_FakeState()), {}))
    assert "current_values" not in out and "active_alarms" not in out
    # the counts used to come back empty: the snapshot names them equipment_by_status
    assert out["equipment_summary"] == {"running": 400, "fault": 12}
    assert out["active_alarm_count"] == 2 and out["critical_alarm_count"] == 1
    assert out["equipment_count"] == 412 and out["point_count"] == 9000
    assert len(str(out)) < 2000


# ─────────────────────────────────────────────────────────────────────────────
# General guard
# ─────────────────────────────────────────────────────────────────────────────
def test_small_results_pass_through_unchanged():
    assert _fit_tool_result('{"value": 21.5}') == '{"value": 21.5}'


def test_oversized_result_is_bounded_and_says_so():
    big = "x" * (node_mod.MAX_TOOL_RESULT_CHARS * 5)
    out = _fit_tool_result(big)
    assert len(out) < node_mod.MAX_TOOL_RESULT_CHARS + 500
    assert "TRUNCATED" in out and "evidence ledger" in out and "Do not conclude" in out


def _conversation(turns, size):
    msgs = [{"role": "user", "content": "q"}]
    for t in range(turns):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{t}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{t}", "name": f"tool_{t}", "content": "y" * size})
    return msgs


def test_history_under_budget_is_untouched():
    msgs = _conversation(3, 1000)
    assert _compact_tool_history(msgs) == 0


def test_history_over_budget_compacts_oldest_and_keeps_latest_turn():
    size = node_mod.MAX_TOOL_HISTORY_CHARS // 3
    msgs = _conversation(6, size)
    n = _compact_tool_history(msgs)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert n >= 1
    assert sum(len(m["content"]) for m in tools) <= node_mod.MAX_TOOL_HISTORY_CHARS
    assert tools[0]["content"].startswith("[COMPACTED") and "evidence ledger" in tools[0]["content"]
    assert tools[-1]["content"] == "y" * size                                   # latest turn intact
    assert [m["tool_call_id"] for m in tools] == [f"c{t}" for t in range(6)]   # pairing preserved
    assert _compact_tool_history(msgs) == 0                                    # idempotent


def test_agent_conversation_stays_bounded_with_a_huge_tool(monkeypatch):
    """End to end: a tool that returns ~1 MB every turn cannot balloon the agent's context."""
    import agent_commercial.database as db
    from agent_unified.schema import Function, Message, ToolCall
    from arvis_core.swarm.node import SwarmNode

    monkeypatch.setattr(db, "get_database", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    sizes = []

    class LLM:
        n = 0

        async def ask_json(self, **kw):
            return {"turns": 8}

        async def ask_tool(self, messages, **kw):
            sizes.append(sum(len(str(m.get("content") or "")) for m in messages if m.get("role") == "tool"))
            LLM.n += 1
            return Message.assistant_message(content="", tool_calls=[
                ToolCall(id=f"c{LLM.n}", function=Function(name="dump", arguments=f'{{"i": {LLM.n}}}'))])

        async def ask(self, **kw):
            return Message.assistant_message(content="done")

    class Tools:
        async def execute(self, tool_name, args, plan=None, task_id="", node_name=""):
            return {"blob": "z" * 1_000_000, "i": args["i"]}

    agent = SwarmNode(name="Big_Agent", role="r", llm=LLM(), tool_handler=Tools(),
                      tools=[{"name": "dump", "description": "d", "parameters": {"type": "object", "properties": {}}}])
    asyncio.run(agent.process("q", context={"_risk_tier": 3}))
    assert len(sizes) == 8                                  # ran to its ceiling: the guard never stopped work
    assert max(sizes) <= node_mod.MAX_TOOL_HISTORY_CHARS    # but context never exceeded the bound
