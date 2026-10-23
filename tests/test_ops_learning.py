"""
Phase 3 — ARVIS learns the building and its people.

Real: temp BMSDatabase, gate, ledger, calendar, conversation memory, Learning
tables, diagnosis cases / repair verification, BuildingSkillbook (word-overlap
matcher instead of the embedding model). Scripted: the language model and WhatsApp.
"""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import Alarm, AlarmSeverity
from agent_commercial.ops_engineer.learning import Learning
from tests.test_attention_gate import (ALI, MON_03, OMAR, SARA, SUN_10, LoudLLM, NoLLM, decisions, fault_event,
                                       gate, process, tick)  # noqa: F401  (gate is a fixture)
from tests.test_ops_engineer import ScriptedLLM, call, say


def learning_for(g):
    lr = Learning(g.db, clock=g.store.clock)
    g.learning = lr
    g.engineer.learning = lr
    return lr


@pytest_asyncio.fixture
async def skillbook(tmp_path, monkeypatch):
    from agent_commercial import skillbook as sb_mod
    from tests.test_role_agents import WordMatcher
    sb = sb_mod.BuildingSkillbook("default", db_path=str(tmp_path / "skills.db"))
    sb.matcher = WordMatcher()
    await sb.ensure_initialized()
    monkeypatch.setitem(sb_mod._skillbooks, "default", sb)
    yield sb
    await sb.close()


# ── engagement ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_kinds_someone_keeps_ignoring_get_quieter_for_them_but_never_safety(gate):
    g = gate(LoudLLM())
    lr = learning_for(g)
    for i in range(6):                                          # 6 investigation messages, all ignored
        g.clock.t = SUN_10 - timedelta(days=i + 1)
        await lr.record_delivery(SARA, f"investigation:AHU-0{i}:p", "investigation", f"AHU-0{i}", None, "workday", 10)
    g.clock.t = SUN_10
    assert await lr.sweep() == 6
    e = await lr.engagement(SARA, "investigation")
    assert e["n"] == 6 and e["ignored"] == 6 and e["p"] < 0.25

    await process(g, {"type": "investigation_concluded", "payload": {
        "trigger": "anomaly", "equipment_id": "AHU-07", "advice": "Valve stuck.", "abstained": False,
        "plan_id": "p1"}}, SUN_10)
    (_, level, codes) = (await decisions(g, SARA))[-1]
    assert level == "DIGEST" and "low_engagement" in codes

    alarm = Alarm(equipment_id="L3", message="Smoke detected", severity=AlarmSeverity.HIGH)
    g.engineer.llm = NoLLM()
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": alarm.to_dict()}}, SUN_10)
    assert g.phone.to(SARA) and g.phone.to(SARA)[-1].startswith("⚠️")       # safety ignores learning


@pytest.mark.asyncio
async def test_reactions_are_attributed(gate):
    g = gate(LoudLLM())
    lr = learning_for(g)
    await process(g, fault_event(cost=1200.0), SUN_10)                     # delivered NOW → recorded
    g.engineer.llm = ScriptedLLM(say("Understood."))
    await g.gateway.on_inbound(SARA, "I know, it's normal for AHU-07 on Sundays")
    conn = await g.db._get_async_connection()
    async with conn.execute("SELECT reaction FROM ops_engagement WHERE number=?", (SARA,)) as cur:
        assert [r[0] for r in await cur.fetchall()] == ["dismissed"]
    async with conn.execute("SELECT reaction FROM ops_engagement WHERE number=?", (OMAR,)) as cur:
        assert [r[0] for r in await cur.fetchall()] == ["pending"]          # Omar hasn't reacted (yet)


# ── preferences ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_preferences_mute_and_digest_but_safety_comes_through(gate):
    g = gate(LoudLLM())
    lr = learning_for(g)
    g.engineer.llm = ScriptedLLM(call("set_preference", scope="equipment", equipment_id="AHU-07", mode="mute"),
                                 say("Got it — I won't message you about AHU-07 unless it's a safety issue."))
    reply = await g.gateway.on_inbound(SARA, "stop messaging me about AHU-07 please")
    assert "safety" in reply
    assert (await lr.preferences(SARA))[0]["mode"] == "mute"

    await process(g, fault_event(eq="AHU-07", cost=5000.0), SUN_10)
    (topic, level, codes) = [d for d in await decisions(g, SARA) if d[0] == "fault:AHU-07:FC13"][0]
    assert level == "DROP" and codes[-1] == "muted_by_person"
    assert not any("AHU-07" in b for b in g.phone.to(SARA)[1:])

    await lr.set_preference(SARA, "fault", "", "digest")
    await process(g, fault_event(eq="AHU-09", cost=5000.0), SUN_10 + timedelta(minutes=1))
    assert (await decisions(g, SARA))[-1][1:] == ("DIGEST", ["high", "digest_by_person"])

    g.engineer.llm = NoLLM()
    smoke = Alarm(equipment_id="AHU-07", message="Smoke in AHU-07 supply duct", severity=AlarmSeverity.HIGH)
    await process(g, {"type": "bms_alarm_raised", "payload": {"alarm": smoke.to_dict()}}, SUN_10)
    assert g.phone.to(SARA)[-1].startswith("⚠️")


# ── the building's normal ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recurring_dismissals_become_a_normal_announced_once_and_undoable(gate):
    g = gate(LoudLLM())
    lr = learning_for(g)
    for week in (3, 2, 1):                                     # three Sundays, ~10:00, dismissed each time
        g.clock.t = SUN_10 - timedelta(weeks=week)
        await lr.record_delivery(SARA, f"fault:AHU-07:FC13:w{week}", "fdd_fault", "AHU-07", f"m{week}", "workday", 10)
        await lr.observe(SARA, "I know, ignore it", reply_to=f"m{week}")
    g.clock.t = SUN_10
    (normal,) = await lr.learn_normals()
    assert normal["subject"] == "AHU-07" and normal["day_type"] == "workday" and normal["dismissals"] == 3

    await process(g, fault_event(eq="AHU-07", cost=50.0), SUN_10)
    assert (await decisions(g, SARA))[-1][2][-1] == "learned_normal"
    await process(g, fault_event(eq="AHU-07", rule="FC14", cost=50.0), SUN_10 + timedelta(hours=8))
    assert "learned_normal" not in (await decisions(g, SARA))[-1][2]          # 18:00 is not the pattern

    from agent_commercial.ops_engineer.proactive import ProactiveEngineer
    pro = ProactiveEngineer(people=g.people, store=g.store, gateway=g.gateway, engineer=g.engineer, gate=g,
                            calendar=g.calendar)
    pro.learning = lr
    monday = SUN_10 + timedelta(hours=21)                     # Monday 07:00
    g.clock.t = monday
    await pro.morning_brief(monday)
    assert any("Learned as normal" in b for b in g.phone.to(SARA))
    assert await lr.unannounced_normals() == []                # announced once

    g.engineer.llm = ScriptedLLM(call("forget_normal", equipment_id="AHU-07"), say("OK, I'll flag AHU-07 again."))
    await g.gateway.on_inbound(SARA, "actually keep watching AHU-07")
    assert await lr.normal_for("fdd_fault", "AHU-07", "workday", 10) is None


# ── facts ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_facts_are_saved_only_after_yes_and_then_used(gate, skillbook):
    from agent_commercial.role_agents import RoleOrchestrator
    g = gate(LoudLLM())
    lr = learning_for(g)
    g.engineer.llm = ScriptedLLM(call("remember_fact", equipment_id="AHU-07", fact="AHU-07 serves level 3 west"),
                                 say("Just to confirm — AHU-07 serves level 3 west. Shall I remember that?"))
    await g.gateway.on_inbound(SARA, "fyi AHU-07 serves level 3 west")
    assert await lr.facts() == []                              # staged, not saved

    reply = await g.gateway.on_inbound(SARA, "yes")            # deterministic, no LLM needed
    assert reply == "Saved — I'll remember that: AHU-07 serves level 3 west"
    (fact,) = await lr.facts(["AHU-07"])
    assert fact.said_by_name == "Sara" and fact.status == "active"

    async with skillbook.get_db() as conn:
        async with conn.execute("SELECT title, created_by FROM skills") as cur:
            assert [tuple(r) for r in await cur.fetchall()] == [("AHU-07 serves level 3 west", "whatsapp:Sara")]

    roles = RoleOrchestrator(g.state, g.db, building_id="default")
    from agent_commercial.bms_data_model import Equipment
    await g.state.register_equipment(Equipment(equipment_id="AHU-07", name="AHU-07"))
    k = await roles.knowledge.run("why is level 3 hot near AHU-07?", {"AHU-07"}, None)
    assert any(i["kind"] == "fact" and "level 3 west" in i["title"] for i in k.items)

    g.engineer.llm = ScriptedLLM(say("Level 3 west is on AHU-07."))
    await g.gateway.on_inbound(SARA, "what serves level 3 west? AHU-07?")
    assert "Facts the team told me: AHU-07 serves level 3 west" in g.engineer.llm.calls[0]["system"]


@pytest.mark.asyncio
async def test_no_means_not_saved(gate):
    g = gate(LoudLLM())
    lr = learning_for(g)
    await lr.propose_fact("AHU-07", "AHU-07 serves level 4", SARA, "Sara")
    assert await g.gateway.on_inbound(SARA, "no") == "OK, I won't save that."
    assert await lr.facts() == []


# ── repairs teach the diagnosis and the skillbook ────────────────────────────
@pytest.mark.asyncio
async def test_record_repair_captures_which_cause_was_fixed(gate):
    from agent_commercial.fdd.closed_loop import list_verifications
    from agent_commercial.fdd.diagnosis import process_findings
    from tests.test_field_checks import _f
    g = gate(LoudLLM())
    (case,) = await process_findings(g.db, [_f("FAHU-1", "FC14")])
    labels = [h["label"] for h in case.diagnosis["posterior"]]
    out = json.loads(await g.engineer._run_tool(g.people.get(ALI), "record_repair", {"equipment_id": "FAHU-1"}))
    assert "which cause was fixed" in out["error"] and out["likely_causes"]
    passing = next(lab for lab in labels if "passing" in lab)
    out = json.loads(await g.engineer._run_tool(g.people.get(ALI), "record_repair",
                                                {"equipment_id": "FAHU-1", "cause_fixed": "valve was passing",
                                                 "what_was_done": "re-seated the valve"}))
    assert out["cause_fixed"] == passing
    (v,) = await list_verifications(g.db)
    assert v.hypothesis == passing


@pytest.mark.asyncio
async def test_verified_repairs_create_one_skill_and_mature_it(gate, skillbook):
    from agent_commercial.fdd.diagnosis import load_kb
    from agent_commercial.fdd.lessons import apply_verification
    g = gate(LoudLLM())
    kb = await load_kb(g.db, "FC14")
    label = kb.hypotheses[0].label

    def v(i, status):
        return SimpleNamespace(id=i, status=status, equipment_id="FAHU-1", rule_id="FC14", hypothesis=label,
                               repaired_at="2026-10-20T10:00:00", work_order_id=None)
    assert (await apply_verification(g.db, skillbook, v(1, "failed")))["skipped"]     # failure alone teaches nothing
    first = await apply_verification(g.db, skillbook, v(2, "verified"))
    second = await apply_verification(g.db, skillbook, v(3, "verified"))
    third = await apply_verification(g.db, skillbook, v(4, "failed"))
    assert first["created"] and not second["created"] and first["skill_id"] == second["skill_id"] == third["skill_id"]
    async with skillbook.get_db() as conn:
        async with conn.execute("SELECT COUNT(*), MAX(verified_count), MAX(failed_count) FROM skills") as cur:
            assert tuple(await cur.fetchone()) == (1, 2, 1)
