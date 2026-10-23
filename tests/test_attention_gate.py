"""
The attention gate — ARVIS speaks only when it is worth someone's attention.

Real: temp BMSDatabase, BMSStateEngine (alarms), conversation memory, ledger,
building calendar, situation (field checks, repairs, chat), gateway, gate,
morning brief. Scripted: the language model (only for wording — the gate itself
makes no LLM calls) and the WhatsApp transport. Time is passed in explicitly.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import Alarm, AlarmSeverity, AlarmState
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.fdd import Outcome
from agent_commercial.fdd.finding import FaultFinding
from agent_commercial.ops_engineer.attention import AttentionGate, parse_ack
from agent_commercial.ops_engineer.calendar import BuildingCalendar
from agent_commercial.ops_engineer.engineer import OpsEngineer
from agent_commercial.ops_engineer.gateway import OpsGateway
from agent_commercial.ops_engineer.ledger import SignalLedger
from agent_commercial.ops_engineer.memory import ConversationStore
from agent_commercial.ops_engineer.people import People
from agent_commercial.ops_engineer.proactive import ProactiveEngineer
from agent_commercial.ops_engineer.situation import Situation
from tests.test_ops_engineer import Phone, ScriptedLLM, say

SARA, HUDA, ALI, OMAR = "97455501111", "97455502222", "97455501234", "97455509999"
UTC = timezone.utc
SUN_10 = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)     # Sunday, a workday, occupied
SUN_23 = datetime(2026, 10, 25, 23, 0, tzinfo=UTC)     # quiet hours
MON_03 = datetime(2026, 10, 26, 3, 0, tzinfo=UTC)      # dead of night
MON_07 = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
FRI_10 = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)     # weekend


class LoudLLM(ScriptedLLM):
    """Every composed message just restates the facts (stays grounded); records calls."""
    async def ask(self, messages, system_msgs=None, tools=None, channel="chat", **kw):
        self.calls.append({"kind": "ask", "system": (system_msgs or [{}])[0].get("content")})
        facts = (system_msgs or [{}])[0].get("content", "").split("FACTS:\n", 1)[-1]
        return say(facts.strip()[:600])


class NoLLM(ScriptedLLM):
    async def ask(self, *a, **k):
        raise AssertionError("safety and escalation messages must not need the language model")


@pytest_asyncio.fixture
async def gate(tmp_path, monkeypatch):
    monkeypatch.setenv("ARVIS_TZ", "UTC")
    monkeypatch.setenv("ARVIS_OPS_OWNER_COST", "1000")
    monkeypatch.setenv("ARVIS_OPS_MAX_PER_HOUR", "4")
    from agent_commercial.database import BMSDatabase
    from agent_commercial.field_checks import FieldCheckService

    db = BMSDatabase(db_path=str(tmp_path / "gate.db"))
    state = BMSStateEngine()
    people = People.parse(f"Sara:{SARA}:fm, Huda:{HUDA}:fm, Ali:{ALI}:technician, Omar:{OMAR}:owner")
    phone = Phone()
    clock = SimpleNamespace(t=SUN_10)                       # one simulated "now" for everything
    store = ConversationStore(db, clock=lambda: clock.t.replace(tzinfo=None))
    checks = FieldCheckService(db, phone, roster=people.technician_roster())

    def build(llm):
        eng = OpsEngineer(llm=llm, people=people, store=store, database=db)
        gw = OpsGateway(transport=phone, people=people, store=store, engineer=eng, field_checks=checks)
        g = AttentionGate(people=people, store=store, ledger=SignalLedger(db), calendar=BuildingCalendar(),
                          situation=Situation(db, checks, clock=store.clock), engineer=eng, gateway=gw,
                          state_engine=state)
        g.clock = clock
        gw.gate = eng.gate = g
        eng.calendar = g.calendar
        g.phone, g.state, g.db, g.checks, g.people = phone, state, db, checks, people
        return g
    yield build
    await db.close()


def fault_event(eq="AHU-07", rule="FC13", cost=1200.0, case=None):
    f = FaultFinding(rule_id=rule, title="Supply air above setpoint", family="ahu", equipment_id=eq,
                     equipment_kind="ahu", outcome=Outcome.FAIL, fault_pct=80.0, fault_hours=26.0,
                     impact={"cost": cost, "currency": "QAR"} if cost is not None else {})
    return {"type": "fdd_faults_confirmed", "payload": {"faults": [dict(f.to_dict(), case=case or {})]}}


async def decisions(g, number):
    conn = await g.db._get_async_connection()
    async with conn.execute("SELECT topic, level, reasons FROM ops_decisions WHERE number=? ORDER BY id",
                            (number,)) as cur:
        return [(r[0], r[1], [x["code"] for x in json.loads(r[2])]) for r in await cur.fetchall()]


async def process(g, event, now):
    from agent_commercial.ops_engineer.signals import to_signals
    g.clock.t = now
    for s in to_signals(event):
        await g.process(s, now)


async def tick(g, now):
    g.clock.t = now
    await g.tick(now)


# ── who hears what, and when ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_costly_fault_goes_to_fms_and_owner_now_and_only_once(gate):
    g = gate(LoudLLM())
    await process(g, fault_event(cost=1200.0), SUN_10)
    assert g.phone.to(SARA) and g.phone.to(HUDA) and g.phone.to(OMAR) and not g.phone.to(ALI)
    assert "QAR" in g.phone.to(SARA)[0]
    await process(g, fault_event(cost=1200.0), SUN_10 + timedelta(minutes=20))
    assert len(g.phone.sent) == 3                                               # same fault: silence
    assert (await decisions(g, SARA))[-1][1:] == ("DROP", ["already_told"])


@pytest.mark.asyncio
async def test_medium_fault_waits_for_the_tick_and_skips_the_owner(gate):
    g = gate(LoudLLM())
    await process(g, fault_event(cost=50.0), SUN_10)
    assert g.phone.sent == []                                                  # SOON, not NOW
    await tick(g, SUN_10 + timedelta(minutes=1))
    assert len(g.phone.to(SARA)) == 1 and g.phone.to(OMAR) == []


@pytest.mark.asyncio
async def test_quiet_hours_hold_it_for_the_morning_brief(gate):
    g = gate(LoudLLM())
    await process(g, fault_event(cost=1200.0), SUN_23)                         # even a costly one
    await tick(g, SUN_23 + timedelta(minutes=5))
    assert g.phone.sent == []
    assert ("fault:AHU-07:FC13", "DIGEST", ["high", "quiet_hours"]) in await decisions(g, SARA)
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer,
                            gate=g, calendar=g.calendar)
    g.clock.t = MON_07
    assert await pro.morning_brief(MON_07) == 3                                 # 2 FMs + owner (it was held)
    assert "Supply air above setpoint" in g.phone.to(SARA)[0]
    assert await g.ledger.pending_for(SARA) == []                              # delivered, not dropped
    assert await pro.morning_brief(MON_07 + timedelta(minutes=30)) == 0       # once a day


@pytest.mark.asyncio
async def test_quiet_weekend_brief_says_nothing(gate):
    g = gate(LoudLLM())
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer,
                            gate=g, calendar=g.calendar)
    assert await pro.morning_brief(FRI_10) == 0


# ── critical things at night, escalation, acknowledgement ────────────────────
@pytest.mark.asyncio
async def test_life_safety_alarm_at_night_escalates_until_acknowledged(gate):
    g = gate(NoLLM())
    alarm = Alarm(equipment_id="L3", message="Smoke detected level 3 corridor", severity=AlarmSeverity.HIGH)
    await g.state.add_alarm(alarm)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, MON_03)
    assert g.phone.to(SARA)[0].startswith("⚠️") and g.phone.to(OMAR)          # fixed template, no LLM
    await tick(g, MON_03 + timedelta(minutes=10))
    assert len(g.phone.to(SARA)) == 1                                          # not yet
    await tick(g, MON_03 + timedelta(minutes=16))
    assert g.phone.to(SARA)[-1].startswith("Still nobody on this after 15 min")

    reply = await g.gateway.on_inbound(HUDA, "on it", message_id="h1")         # deterministic, no LLM
    assert reply.startswith("Thanks Huda — noted")
    assert alarm.state == AlarmState.ACKNOWLEDGED and alarm.acknowledged_by == "whatsapp:Huda"
    n = len(g.phone.sent)
    await tick(g, MON_03 + timedelta(minutes=40))
    assert len(g.phone.sent) == n                                              # ladder stopped


@pytest.mark.asyncio
async def test_acknowledged_on_the_dashboard_stops_the_ladder(gate):
    g = gate(NoLLM())
    alarm = Alarm(equipment_id="CH-01", message="Gas leak detected plant room", severity=AlarmSeverity.CRITICAL)
    await g.state.add_alarm(alarm)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, SUN_10)
    await g.state.acknowledge_alarm(alarm.alarm_id, by="eng.sara")
    n = len(g.phone.sent)
    await tick(g, SUN_10 + timedelta(minutes=16))
    assert len(g.phone.sent) == n


@pytest.mark.asyncio
async def test_alarm_that_clears_by_itself_is_never_announced(gate):
    g = gate(LoudLLM())
    alarm = Alarm(equipment_id="AHU-07", message="High supply air temperature", severity=AlarmSeverity.MEDIUM)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, SUN_10)
    await process(g, {"type": "bms_alarm_cleared", "payload": {"alarm": alarm.to_dict()}},
                  SUN_10 + timedelta(minutes=3))
    await tick(g, SUN_10 + timedelta(minutes=11))
    assert g.phone.sent == []


@pytest.mark.asyncio
async def test_monitoring_loss_then_back_to_normal_only_to_those_told(gate):
    g = gate(LoudLLM())
    blind = {"type": "monitoring_blind", "payload": {"since": "03:00", "assessment": {
        "fresh_points": 0, "total_points": 120, "fresh_minutes": 10,
        "adapters": [{"adapter": "bacnet", "connected": False, "stale_points": 0, "devices_missing": []}]}}}
    await process(g, blind, MON_03)
    assert "lost sight" in g.phone.to(SARA)[0]
    await process(g, {"type": "monitoring_restored", "payload": {"was": "blind", "minutes": 47, "at": "x",
                                                                 "assessment": {}}}, MON_07)
    await tick(g, MON_07 + timedelta(minutes=1))
    assert "47" in g.phone.to(SARA)[-1] and g.phone.to(ALI) == []


# ── the guards ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unbacked_llm_critical_cannot_wake_anyone(gate):
    g = gate(LoudLLM())
    adv = {"type": "terminal_advisory_fired", "payload": {"advisory_id": "ta1", "equipment_id": "CH-01",
                                                          "severity": "critical", "title": "Compressor failure risk",
                                                          "message": "Bearing temperature rising"}}
    await process(g, adv, MON_03)
    await tick(g, MON_03 + timedelta(minutes=1))
    assert g.phone.sent == []
    assert "llm_uncorroborated" in (await decisions(g, SARA))[0][2]


@pytest.mark.asyncio
async def test_already_handled_is_one_level_quieter(gate):
    from agent_commercial.fdd.diagnosis import process_findings
    from tests.test_field_checks import _f
    g = gate(LoudLLM())
    (case,) = await process_findings(g.db, [_f("FAHU-1", "FC14")])
    await g.checks.request(case.id, ALI)                                       # Ali is already checking FAHU-1
    await process(g, fault_event(eq="FAHU-1", rule="FC14", cost=50.0), SUN_10)
    (_, level, codes) = (await decisions(g, SARA))[0]
    assert level == "DIGEST" and "already_handled" in codes


@pytest.mark.asyncio
async def test_hourly_cap_folds_the_rest_into_the_brief(gate, monkeypatch):
    monkeypatch.setenv("ARVIS_OPS_MAX_PER_HOUR", "1")
    g = gate(LoudLLM())
    await process(g, fault_event(eq="AHU-07", cost=5000.0), SUN_10)
    await process(g, fault_event(eq="AHU-08", cost=5000.0), SUN_10 + timedelta(minutes=5))
    assert len(g.phone.to(SARA)) == 1
    assert (await decisions(g, SARA))[-1][1:] == ("DIGEST", ["high", "hourly_cap"])


@pytest.mark.asyncio
async def test_failed_send_is_retried_not_lost(gate):
    g = gate(LoudLLM())
    real = g.phone.send_text

    async def down(*a, **k):
        raise RuntimeError("Evolution unreachable")
    g.phone.send_text = down
    await process(g, fault_event(cost=5000.0), SUN_10)
    assert g.phone.sent == []
    g.phone.send_text = real
    await tick(g, SUN_10 + timedelta(minutes=2))
    assert g.phone.to(SARA)


@pytest.mark.asyncio
async def test_why_didnt_you_tell_me(gate):
    from tests.test_ops_engineer import call
    g = gate(LoudLLM())
    await process(g, fault_event(cost=1200.0), SUN_23)
    g.engineer.llm = ScriptedLLM(call("explain", subject="AHU-07"),
                                 say("It came in at 23:00 during quiet hours, so I held it for your morning brief."))
    reply = await g.gateway.on_inbound(SARA, "why didn't you tell me about AHU-07 last night?")
    tool_out = json.loads(next(m for m in g.engineer.llm.calls[1]["messages"] if m.get("role") == "tool")["content"])
    assert any("quiet_hours" in " ".join(d["why"]) for d in tool_out["decisions"])
    assert "quiet hours" in reply


def test_parse_ack():
    for yes in ("on it", "Seen", "got it 👍", "ok", "تمام", "on my way!"):
        assert parse_ack(yes)
    for no in ("on it but the valve looks stuck and I need a ladder", "why?", "", "no"):
        assert not parse_ack(no)


@pytest.mark.asyncio
async def test_a_day_in_the_life(gate):
    """One realistic day. The point: few messages, each one worth reading."""
    g = gate(LoudLLM())
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer,
                            gate=g, calendar=g.calendar)
    day = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)                           # a Monday
    at = lambda h, m=0: day + timedelta(hours=h, minutes=m)

    await process(g, fault_event(eq="AHU-08", cost=50.0), at(2))             # small, at night → brief
    smoke = Alarm(equipment_id="L3", message="Smoke detected level 3 corridor", severity=AlarmSeverity.HIGH)
    await g.state.add_alarm(smoke)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": smoke.to_dict()}}, at(3))   # wakes people
    await g.gateway.on_inbound(SARA, "on it", message_id="s1")
    for m in range(5, 60, 5):
        await tick(g, at(3, m))                                                # acknowledged: no chasing
    g.clock.t = at(7)
    await pro.morning_brief(at(7))
    await process(g, fault_event(eq="AHU-07", cost=1200.0), at(10))          # costly → now
    await process(g, fault_event(eq="AHU-07", cost=1200.0), at(10, 5))       # same again → nothing
    await process(g, {"type": "investigation_concluded", "payload": {
        "trigger": "anomaly", "equipment_id": "AHU-07", "advice": "CHW valve on AHU-07 is not opening.",
        "confidence": 0.7, "abstained": False, "plan_id": "p9"}}, at(10, 30))
    await tick(g, at(10, 31))
    flicker = Alarm(equipment_id="VAV-12", message="Zone temperature high", severity=AlarmSeverity.MEDIUM)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": flicker.to_dict()}}, at(14))
    await process(g, {"type": "bms_alarm_cleared", "payload": {"alarm": flicker.to_dict()}}, at(14, 3))
    for m in range(1, 60, 5):
        await tick(g, at(14, m))

    proactive = lambda n: [b for b in g.phone.to(n) if not b.startswith("Thanks")]
    assert len(proactive(SARA)) == 4      # smoke · brief (held AHU-08) · AHU-07 fault · investigation
    assert len(proactive(OMAR)) == 2      # smoke · costly AHU-07 fault
    assert proactive(ALI) == []           # nothing of his
    assert not any("VAV-12" in b for b in g.phone.sent)                     # the flicker never surfaced
