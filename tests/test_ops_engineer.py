"""
ARVIS on WhatsApp — the operations engineer.

Real: temp BMSDatabase, rule-FDD findings and diagnosis cases, role agents over
the real state engine, field checks, conversation memory, gateway, proactive
judgement. Scripted: the language model (ScriptedLLM replays the decisions a
model would make, including tool calls) and the WhatsApp transport (records
what would be sent).
"""
import json
from datetime import datetime

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import Equipment
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.fdd import Outcome
from agent_commercial.fdd.closed_loop import list_verifications
from agent_commercial.fdd.diagnosis import process_findings
from agent_commercial.fdd.finding import FaultFinding
from agent_commercial.fdd.store import save_findings
from agent_commercial.field_checks import FieldCheckService
from agent_commercial.ops_engineer.engineer import OpsEngineer, ungrounded_numbers
from agent_commercial.ops_engineer.gateway import OpsGateway
from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People
from agent_commercial.role_agents import RoleOrchestrator
from agent_unified.schema import Function, Message, ToolCall

SARA, ALI, OMAR, STRANGER = "97455501111", "97455501234", "97455509999", "97400000000"


def say(text):
    return Message.assistant_message(content=text)


def call(name, **args):
    return Message.assistant_message(content="", tool_calls=[
        ToolCall(id=f"t-{name}", function=Function(name=name, arguments=json.dumps(args)))])


class ScriptedLLM:
    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def _next(self):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def ask_tool(self, messages, system_msgs, tools, tool_choice="auto", channel="chat", **kw):
        self.calls.append({"kind": "ask_tool", "messages": messages, "system": system_msgs[0]["content"]})
        return self._next()

    async def ask(self, messages, system_msgs=None, tools=None, channel="chat", **kw):
        self.calls.append({"kind": "ask", "messages": messages, "system": (system_msgs or [{}])[0].get("content")})
        return self._next()


class Phone:
    """Records what would be sent over WhatsApp."""
    def __init__(self):
        self.sent = []

    async def send_text(self, to, body, delay_ms=None):
        self.sent.append((to, body))
        return f"wamid.{len(self.sent)}"

    async def send_check(self, to, body, ref):
        return await self.send_text(to, body)

    def to(self, number):
        return [b for t, b in self.sent if t == number]


def _f(eq, rule, cost=None):
    return FaultFinding(rule_id=rule, title=rule, family="ahu", equipment_id=eq, equipment_kind="ahu",
                        outcome=Outcome.FAIL, fault_pct=80.0, fault_hours=26.0,
                        impact={"cost": cost, "currency": "QAR"} if cost is not None else {})


@pytest_asyncio.fixture
async def site(tmp_path, monkeypatch):
    from agent_commercial import skillbook as sb_mod
    from agent_commercial.database import BMSDatabase

    class NoMatch:
        is_available = False

    db = BMSDatabase(db_path=str(tmp_path / "ops.db"))
    state = BMSStateEngine()
    for eq in ("FAHU-1", "AHU-07"):
        await state.register_equipment(Equipment(equipment_id=eq, name=eq))
    sb = sb_mod.BuildingSkillbook("default", db_path=str(tmp_path / "skills.db"))
    sb.matcher = NoMatch()
    await sb.ensure_initialized()
    monkeypatch.setitem(sb_mod._skillbooks, "default", sb)

    people = People.parse(f"Sara:{SARA}:fm, Ali:{ALI}:technician, Omar:{OMAR}:owner")
    phone = Phone()
    store = ConversationStore(db)
    roles = RoleOrchestrator(state, db, building_id="default")
    checks = FieldCheckService(db, phone, roster=people.technician_roster())

    class Site:
        pass
    s = Site()
    s.db, s.state, s.people, s.phone, s.store, s.roles, s.checks = db, state, people, phone, store, roles, checks
    s.investigations = []

    def build(llm):
        async def investigate(question, person):
            s.investigations.append((question, person.name))
            return "Root cause: FAHU-1 chilled-water valve passing (p=0.82). Evidence: coil cooling with valve commanded shut."
        eng = OpsEngineer(llm=llm, people=people, store=store, database=db, roles=roles, field_checks=checks,
                          investigate=investigate, building_name="Tower 1")
        gw = OpsGateway(transport=phone, people=people, store=store, engineer=eng, field_checks=checks)
        eng.notify = lambda person, text, kind: gw.send(person, text, kind=kind)
        return eng, gw
    s.build = build
    yield s
    await sb.close()
    await db.close()


# ── roster ───────────────────────────────────────────────────────────────────
def test_roster_roles_and_lookup():
    p = People.parse("Sara Ahmed:+974 5550 1111:fm, Ali:97455501234:technician, Omar:97455509999:owner, x")
    assert p.get("+974-5550-1111").role == "fm" and p.by_name("sara").number == SARA
    assert p.technician_roster() == {ALI: "Ali"}
    with pytest.raises(ValueError, match="unknown role"):
        People.parse("Bob:974111:janitor")


def test_number_grounding():
    facts = ["FC13 cost 1200.0 QAR, p=0.61, 26.0 h"]
    assert ungrounded_numbers("Costing about QAR 1,200 a month, 61% likely, 26 hours", facts) == []
    assert ungrounded_numbers("It will save QAR 9,999", facts) == [9999.0]
    assert ungrounded_numbers("Check 2 valves in 5 minutes", facts) == []          # small counts are free
    assert ungrounded_numbers("AHU-07 and C12 look fine", facts) == []             # ids are not figures


# ── conversation ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_strangers_are_ignored_and_retries_handled_once(site):
    eng, gw = site.build(ScriptedLLM(say("Morning Sara.")))
    assert await gw.on_inbound(STRANGER, "hello") is None
    assert await gw.on_inbound(SARA, "morning", message_id="m1") == "Morning Sara."
    assert await gw.on_inbound(SARA, "morning", message_id="m1") is None             # webhook retry
    assert site.phone.to(SARA) == ["Morning Sara."] and site.phone.to(STRANGER) == []


@pytest.mark.asyncio
async def test_engineer_reasons_with_tools_and_remembers_the_thread(site):
    await save_findings(site.db, [_f("FAHU-1", "FC14", cost=1200.0)])
    await process_findings(site.db, [_f("FAHU-1", "FC14", cost=1200.0)])
    llm = ScriptedLLM(
        call("open_cases", equipment_id="FAHU-1"),
        say("FAHU-1's coil is cooling while it should be off. Most likely the CHW valve is passing — "
            "worth having someone shut the isolation valve and see if the cooling stops."),
        say("It's costing about QAR 1,200 in avoidable energy, so I'd do it today."),
    )
    eng, gw = site.build(llm)
    first = await gw.on_inbound(SARA, "what's going on with FAHU-1?", message_id="a")
    assert "CHW valve is passing" in first
    tool_msg = next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")
    assert "likely_causes" in tool_msg["content"]                                   # reasoned from the case

    second = await gw.on_inbound(SARA, "how much is it costing us?", message_id="b")
    assert "1,200" in second
    seen = llm.calls[-1]["messages"]
    assert [m["content"] for m in seen if m["role"] == "user"][:2] == ["what's going on with FAHU-1?",
                                                                       "how much is it costing us?"]
    assert any(m["role"] == "assistant" and "CHW valve" in (m["content"] or "") for m in seen)   # remembers
    assert "Sara" in llm.calls[0]["system"] and "facilities manager" in llm.calls[0]["system"]

    turns = await site.store.recent(SARA)
    assert [t.speaker for t in turns] == ["person", "arvis", "person", "arvis"]


@pytest.mark.asyncio
async def test_made_up_numbers_are_challenged_then_removed(site):
    llm = ScriptedLLM(say("All good. You'll save QAR 9,999 this month."),
                      say("All good. Savings this month are QAR 8,888."))
    eng, gw = site.build(llm)
    reply = await gw.on_inbound(SARA, "any savings?")
    assert "CHECK: these numbers are not in your data" in llm.calls[1]["messages"][-1]["content"]
    assert "9,999" not in reply and "8,888" not in reply and reply == "All good."


@pytest.mark.asyncio
async def test_it_does_not_parrot_itself(site):
    llm = ScriptedLLM(say("Nothing urgent on the building right now."),
                      say("Nothing urgent on the building right now."),
                      say("Still quiet — no new faults since we spoke."))
    eng, gw = site.build(llm)
    await gw.on_inbound(SARA, "anything?")
    assert await gw.on_inbound(SARA, "and now?") == "Still quiet — no new faults since we spoke."


@pytest.mark.asyncio
async def test_language_model_down_is_said_plainly_with_the_facts(site):
    await save_findings(site.db, [_f("AHU-07", "FC13", cost=300.0)])
    eng, gw = site.build(ScriptedLLM(RuntimeError("Bedrock throttled")))
    reply = await gw.on_inbound(SARA, "status?")
    assert reply.startswith("I can't reach my reasoning engine right now")
    assert "AHU-07" in reply                                                        # facts still delivered


# ── actions in plain words ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fm_asks_for_a_check_and_the_technicians_answer_closes_the_loop(site):
    (case,) = await process_findings(site.db, [_f("FAHU-1", "FC14")])
    llm = ScriptedLLM(call("ask_technician", technician="ali", equipment_id="FAHU-1"),
                      say("Sent Ali the isolation-valve check. I'll tell you what he finds."))
    eng, gw = site.build(llm)
    await gw.on_inbound(SARA, "get Ali to check FAHU-1 please")
    assert any("ARVIS check — FAHU-1" in b for b in site.phone.to(ALI))

    reply = await gw.on_inbound(ALI, "yes", message_id="ali-1")                     # short answer → the check
    assert reply.startswith("Thanks Ali — recorded.")
    assert (await site.checks.list_checks())[0].status == "answered"
    assert len(llm.script) == 0                                                     # no LLM spent on a yes


@pytest.mark.asyncio
async def test_technician_reports_a_repair_in_plain_words(site):
    await process_findings(site.db, [_f("FAHU-1", "FC14")])
    llm = ScriptedLLM(call("record_repair", equipment_id="FAHU-1", what_was_done="replaced the valve actuator"),
                      say("Logged. I'll re-check FAHU-1 once it has run long enough and tell you if it held."))
    eng, gw = site.build(llm)
    reply = await gw.on_inbound(ALI, "I've replaced the valve actuator on FAHU-1, it's done")
    assert reply.startswith("Logged.")
    (v,) = await list_verifications(site.db)
    assert v.equipment_id == "FAHU-1" and v.rule_id == "FC14" and v.status == "pending" and "Ali" in v.note


@pytest.mark.asyncio
async def test_owner_role_is_enforced(site):
    eng, _ = site.build(ScriptedLLM())
    out = await eng._run_tool(site.people.get(OMAR), "record_repair", {"equipment_id": "FAHU-1"})
    assert "facilities manager or a technician" in out
    out = await eng._run_tool(site.people.get(ALI), "ask_technician", {"technician": "Ali", "equipment_id": "X"})
    assert "only the facilities manager or owner" in out


@pytest.mark.asyncio
async def test_deep_investigation_reports_back_when_done(site):
    llm = ScriptedLLM(call("deep_investigation", question="why is FAHU-1 cooling when off?"),
                      say("Good question — running a full investigation, I'll message you with what I find."),
                      say("Found it: FAHU-1's chilled-water valve is passing (82% likely) — "
                          "the coil keeps cooling with the valve commanded shut."))
    eng, gw = site.build(llm)
    first = await gw.on_inbound(SARA, "why is FAHU-1 cooling when it's off?")
    assert "running a full investigation" in first
    import asyncio
    for _ in range(50):
        if len(site.phone.to(SARA)) >= 2:
            break
        await asyncio.sleep(0.02)
    assert site.investigations == [("why is FAHU-1 cooling when off?", "Sara")]
    assert "82% likely" in site.phone.to(SARA)[1]                                   # grounded in the result


# (Speaking up unprompted — the attention gate — is tested in tests/test_attention_gate.py.)


# ── transport ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_evolution_typing_delay(monkeypatch):
    import httpx
    from agent_commercial.messaging.evolution import EvolutionTransport
    bodies = []

    def handler(r):
        bodies.append(json.loads(r.content))
        return httpx.Response(201, json={"key": {"id": "X1"}})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    t = EvolutionTransport("http://e", "i", "k")
    await t.send_text(SARA, "hi", delay_ms=1200)
    await t.send_text(SARA, "hi")
    assert bodies == [{"number": SARA, "text": "hi", "delay": 1200}, {"number": SARA, "text": "hi"}]


# ── "Did the reset help?" — time-aware answers ───────────────────────────────
from datetime import timedelta, timezone  # noqa: E402

from agent_commercial.ops_engineer.engineer import analyze_change  # noqa: E402


def _series(start, minutes_values):
    return [(start + timedelta(minutes=m), v) for m, v in minutes_values]


def test_analyze_change_reports_recovery_time_and_direction():
    t0 = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    reset = t0 + timedelta(minutes=30)
    pts = _series(t0, [(0, 26.4), (10, 26.6), (20, 26.5), (30, 26.5), (36, 25.6), (42, 24.9),
                       (48, 24.3), (54, 24.1), (60, 24.0)])
    out = analyze_change(pts, reset, target=24.0, band=0.3, tz=timezone.utc)
    assert out["before"] == 26.5 and out["now"] == 24.0 and out["direction"] == "down"
    assert out["moved_toward_target"] is True and out["within_target_now"] is True
    assert out["reached_target_at"] == "10:48" and out["minutes_to_target"] == 18
    assert out["action_at"] == "10:30"


def test_analyze_change_says_when_it_did_not_help_or_cannot_tell():
    t0 = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
    flat = _series(t0, [(0, 26.5), (20, 26.5), (40, 26.6), (60, 26.6)])
    out = analyze_change(flat, t0 + timedelta(minutes=30), target=24.0, tz=timezone.utc)
    assert out["moved_toward_target"] is False and out["reached_target"] is False
    assert out["within_target_now"] is False
    none_after = analyze_change(flat, t0 + timedelta(minutes=90), target=24.0)
    assert none_after["note"].startswith("no readings since")                  # never extrapolates


@pytest.mark.asyncio
async def test_did_the_reset_help_conversation(site):
    """The brochure exchange, end to end on the real state engine and tool handler."""
    from agent_commercial.bms_data_model import Alarm, AlarmSeverity, BMSDataPoint
    from agent_commercial.tools.handlers.base import BMSToolHandler

    state = site.state
    await state.register_equipment(Equipment(equipment_id="AHU-03", name="AHU-03"))
    now = datetime.now().astimezone()
    for m, v in [(-50, 26.4), (-40, 26.6), (-30, 26.5), (-24, 26.5), (-18, 25.4), (-12, 24.6),
                 (-6, 24.1), (0, 24.0)]:
        await state.update_point(BMSDataPoint(point_id="L3-W/ZT", name="Level 3 west zone temp", value=v,
                                              unit="°C", equipment_id="AHU-03",
                                              timestamp=(now + timedelta(minutes=m)).replace(tzinfo=None)))
    alarm = Alarm(equipment_id="AHU-03", message="Level 3 west zone above setpoint",
                  severity=AlarmSeverity.MEDIUM, source_point_id="L3-W/ZT")
    alarm.triggered_at = (now - timedelta(minutes=60)).replace(tzinfo=None)
    await state.add_alarm(alarm)
    await state.resolve_alarm(alarm.alarm_id)                                      # cleared just now

    llm = ScriptedLLM(
        call("change_since", point_id="L3-W/ZT", minutes_ago=25, target=24.0, band=0.5),
        call("alarm_changes", equipment_id="AHU-03", minutes_ago=25),
        say("Yes. The alarm cleared and Level 3 west came back to 24.0 °C — it got within range "
            "19 minutes after the reset, and it's holding."))
    eng, gw = site.build(llm)
    eng.tool_handler = BMSToolHandler(bms_state=state)
    reply = await gw.on_inbound(SARA, "I reset AHU-03 about 25 minutes ago — did it help?")

    change = json.loads(next(m for m in llm.calls[1]["messages"] if m.get("role") == "tool")["content"])
    assert change["before"] == 26.5 and change["now"] == 24.0 and change["direction"] == "down"
    assert change["minutes_to_target"] == 19 and change["within_target_now"] is True
    alarms = json.loads([m for m in llm.calls[2]["messages"] if m.get("role") == "tool"][1]["content"])
    assert alarms["cleared_since"][0]["message"] == "Level 3 west zone above setpoint"
    assert alarms["still_active"] == []
    assert reply.startswith("Yes. The alarm cleared")                              # 19 and 24.0 are grounded


@pytest.mark.asyncio
async def test_unknown_time_makes_it_ask_rather_than_guess(site):
    eng, _ = site.build(ScriptedLLM())
    from agent_commercial.tools.handlers.base import BMSToolHandler
    eng.tool_handler = BMSToolHandler(bms_state=site.state)
    out = json.loads(await eng._run_tool(site.people.get(SARA), "change_since", {"point_id": "L3-W/ZT"}))
    assert "say when the action happened" in out["error"]


@pytest.mark.asyncio
async def test_point_history_is_time_aware(site):
    from agent_commercial.bms_data_model import BMSDataPoint
    from agent_commercial.tools.handlers.base import BMSToolHandler
    now = datetime.now().astimezone()
    for m, v in [(-30, 13.0), (-20, 15.5), (-10, 14.0), (0, 13.2)]:
        await site.state.update_point(BMSDataPoint(point_id="AHU-07/SAT", name="SAT", value=v, equipment_id="AHU-07",
                                                   timestamp=(now + timedelta(minutes=m)).replace(tzinfo=None)))
    eng, _ = site.build(ScriptedLLM())
    eng.tool_handler = BMSToolHandler(bms_state=site.state)
    out = json.loads(await eng._run_tool(site.people.get(SARA), "point_history", {"point_id": "AHU-07/SAT",
                                                                                  "minutes": 60}))
    local = lambda m: (now + timedelta(minutes=m)).astimezone(eng._tz()).strftime("%H:%M")
    assert out["max"] == 15.5 and out["max_at"] == local(-20)
    assert out["last_at"] == local(0) and len(out["timeline"]) == 4
