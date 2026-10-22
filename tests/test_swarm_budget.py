"""
Swarm investigation budget: the four leaks this guards against.

1. The wall-clock limit was never measured (used_wall_seconds stayed 0).
2. Only Bedrock calls were metered — K2-Think / Groq / OpenAI spend was never
   charged, and callers outside the node loop (depth planner, synthesis,
   verifiers) were never charged on any provider.
3. An exhausted budget stopped tool execution but not the LLM loop.
4. One global usage log mixed concurrent investigations' spend.
"""
import asyncio
from types import SimpleNamespace

import pytest

from agent_unified import llm as llm_mod
from agent_unified.metering import active_investigation, bind_investigation
from agent_unified.schema import Function, Message, ToolCall, UsageInfo
from arvis_core import plan as plan_mod
from arvis_core.plan import Budget, InvestigationPlan


# ─────────────────────────────────────────────────────────────────────────────
# 1. Wall clock
# ─────────────────────────────────────────────────────────────────────────────
def test_wall_clock_is_measured_and_is_a_runaway_guard(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(plan_mod.time, "monotonic", lambda: now[0])
    b = Budget()
    assert b.max_wall_seconds == 600.0          # above measured p90 (~430 s), not 120
    now[0] += 450
    assert not b.exhausted and round(b.used_wall_seconds) == 450
    now[0] += 200
    assert b.exhausted


def test_restored_budget_resumes_elapsed_time(monkeypatch):
    now = [5000.0]
    monkeypatch.setattr(plan_mod.time, "monotonic", lambda: now[0])
    b = Budget.from_dict({"used_wall_seconds": 590.0})
    now[0] += 15
    assert b.exhausted                           # 590 s before + 15 s since restore


def test_limits_are_configurable_per_site(monkeypatch):
    monkeypatch.setenv("ARVIS_BUDGET_MAX_TOKENS", "200000")
    monkeypatch.setenv("ARVIS_BUDGET_MAX_WALL_SECONDS", "900")
    b = Budget()
    assert b.max_tokens == 200000 and b.max_wall_seconds == 900.0


# ─────────────────────────────────────────────────────────────────────────────
# 2 + 4. Metering: every call charged to the right investigation, never mixed
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_usage_log():
    llm_mod.drain_usage_log()
    yield
    llm_mod.drain_usage_log()


def _usage(tokens_in=100, tokens_out=50):
    return UsageInfo(input_tokens=tokens_in, output_tokens=tokens_out, model_id="m", cost_usd=0.01)


def test_calls_from_parallel_nodes_charge_their_own_investigation():
    async def investigation(plan):
        bind_investigation(plan.id, plan.budget)

        async def node():                         # nodes run as gathered child tasks
            llm_mod._meter_usage(_usage(), "swarm")

        await asyncio.gather(node(), node(), node())

    async def main():
        a, b = InvestigationPlan(query="a", budget=Budget()), InvestigationPlan(query="b", budget=Budget())
        await asyncio.gather(asyncio.create_task(investigation(a)), asyncio.create_task(investigation(b)))
        return a, b

    a, b = asyncio.run(main())
    assert a.budget.used_tokens == 3 * 150 and b.budget.used_tokens == 3 * 150
    assert abs(a.budget.used_cost_usd - 0.03) < 1e-9
    a_entries = llm_mod.drain_usage_log(plan_id=a.id)
    assert len(a_entries) == 3 and all(e["plan_id"] == a.id for e in a_entries)
    assert len(llm_mod.drain_usage_log(plan_id=b.id)) == 3   # b's spend was not absorbed by a's flush


def test_calls_outside_an_investigation_charge_nothing():
    async def main():
        assert active_investigation() is None
        llm_mod._meter_usage(_usage(), "chat")
    asyncio.run(main())
    assert [e["plan_id"] for e in llm_mod.drain_usage_log()] == [""]


def test_queen_binding_does_not_leak_to_caller():
    from arvis_core.swarm.queen import QueenCoordinator
    seen = {}

    async def fake_inner(query, context, channel):
        bind_investigation("plan-x", None)
        seen["inside"] = active_investigation().plan_id
        return {"advice": "ok"}

    queen = SimpleNamespace(_execute_swarm=fake_inner)

    async def main():
        result = await QueenCoordinator.execute_swarm(queen, "q")
        return result, active_investigation()

    result, after = asyncio.run(main())
    assert result == {"advice": "ok"} and seen["inside"] == "plan-x" and after is None


def test_openai_compatible_providers_report_and_charge_usage():
    """K2-Think / Groq / OpenAI responses carry usage; it must reach the budget."""
    raw = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=300),
    )
    agent = SimpleNamespace(provider="k2think", k2think_model="K2",
                            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: raw))))

    async def main():
        plan = InvestigationPlan(query="q", budget=Budget())
        bind_investigation(plan.id, plan.budget)
        msg = await llm_mod.UnifiedLLM._ask_openai_compat(SimpleNamespace(), agent, "", [{"role": "user", "content": "hi"}],
                                                          None, "auto", channel="swarm")
        return plan, msg

    plan, msg = asyncio.run(main())
    assert msg.usage is not None and msg.usage.input_tokens == 1200 and msg.usage.output_tokens == 300
    assert plan.budget.used_tokens == 1500


# ─────────────────────────────────────────────────────────────────────────────
# 3. An exhausted budget stops the node's LLM loop
# ─────────────────────────────────────────────────────────────────────────────
class _FakeLLM:
    """Always asks for two more tools, as a model that never wants to stop would."""

    def __init__(self):
        self.tool_turns = 0
        self.asks = 0
        self.n = 0

    async def ask_json(self, **kw):
        return {"turns": 8, "reason": "test"}

    async def ask_tool(self, **kw):
        self.tool_turns += 1
        llm_mod._meter_usage(_usage(), "swarm")
        calls = []
        for _ in range(2):
            self.n += 1
            calls.append(ToolCall(id=f"c{self.n}", function=Function(name="read_point", arguments=f'{{"i": {self.n}}}')))
        return Message.assistant_message(content="", tool_calls=calls)

    async def ask(self, **kw):
        self.asks += 1
        return Message.assistant_message(content="synthesis")


class _FakeTools:
    async def execute(self, tool_name, args, plan=None, task_id="", node_name=""):
        plan.budget.record_tool_call()
        return {"value": args["i"]}


def _node(llm):
    from arvis_core.swarm.node import SwarmNode
    return SwarmNode(name="Test_Agent", role="test", llm=llm, tool_handler=_FakeTools(),
                     tools=[{"name": "read_point", "description": "d", "parameters": {"type": "object", "properties": {}}}])


@pytest.fixture
def _no_db(monkeypatch):
    import agent_commercial.database as db
    monkeypatch.setattr(db, "get_database", lambda: (_ for _ in ()).throw(RuntimeError("no db in test")))


def test_exhausted_budget_ends_llm_loop_and_answers_every_tool_call(_no_db):
    llm = _FakeLLM()

    async def main():
        plan = InvestigationPlan(query="q", budget=Budget(max_tool_calls=3))
        bind_investigation(plan.id, plan.budget)
        out = await _node(llm).process("why is AHU-2 cold?", context={"_risk_tier": 3}, plan=plan)
        return plan, out

    plan, out = asyncio.run(main())
    # Ceiling is 8 turns; the budget (3 tool calls) must stop it after the 2nd turn.
    assert llm.tool_turns == 2, llm.tool_turns
    assert llm.asks == 1                                     # exactly one synthesis call
    assert out["response"].content == "synthesis"
    asked = {tc["id"] for m in out["history"] if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])}
    answered = {m["tool_call_id"] for m in out["history"] if m.get("role") == "tool"}
    assert asked == answered                                 # no unanswered tool call (Bedrock rejects those)


def test_node_spends_nothing_when_budget_already_gone(_no_db):
    llm = _FakeLLM()

    async def main():
        plan = InvestigationPlan(query="q", budget=Budget(max_tool_calls=0))
        return await _node(llm).process("q", context={"_risk_tier": 3}, plan=plan)

    out = asyncio.run(main())
    assert llm.tool_turns == 0 and llm.asks == 0
    assert "No findings" in out["response"].content
