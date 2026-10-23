"""
Role agents — Anomaly, Diagnostic, Investigation, Recommendation, Verification,
Knowledge, Briefing.

Built on the real engines: a temp BMSDatabase holding rule-FDD findings, the
real diagnosis cases (default knowledge bases, Bayesian ranking, information-
gain next question), the closed-loop repair table, the real BMS state engine,
and a real skillbook (word-overlap matcher instead of the embedding model).
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio

from agent_commercial.bms_data_model import (
    Alarm, AlarmSeverity, BMSDataPoint, Equipment, PointQuality,
)
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.fdd import Outcome
from agent_commercial.fdd.closed_loop import list_verifications, register_repair, save_verification
from agent_commercial.fdd.diagnosis import learn_from_verification, process_findings
from agent_commercial.fdd.finding import FaultFinding
from agent_commercial.fdd.store import save_findings
from agent_commercial.role_agents import RoleOrchestrator
from arvis_core.plan import InvestigationPlan


class WordMatcher:
    is_available = True

    def __init__(self):
        self.texts = {}

    def add_skill(self, sid, text):
        self.texts[sid] = set(text.lower().split())

    def nearest(self, q, top_k=3):
        qw = set(q.lower().split())
        return sorted(((s, len(qw & t) / max(1, len(qw | t))) for s, t in self.texts.items()),
                      key=lambda x: -x[1])[:top_k]

    def find_similar(self, q, top_k=5, threshold=0.3):
        return [(s, sc) for s, sc in self.nearest(q, top_k) if sc >= threshold]


def _f(eq, rule, cost=None, hours=5.0):
    return FaultFinding(rule_id=rule, title=rule, family="ahu", equipment_id=eq, equipment_kind="ahu",
                        outcome=Outcome.FAIL, fault_pct=80.0, fault_hours=hours,
                        impact={"cost": cost, "currency": "QAR"} if cost is not None else {})


@pytest_asyncio.fixture
async def site(tmp_path, monkeypatch):
    from agent_commercial import skillbook as sb_mod
    from agent_commercial.database import BMSDatabase

    db = BMSDatabase(db_path=str(tmp_path / "roles.db"))
    state = BMSStateEngine()
    for eq in ("AHU-07", "AHU-03", "FAHU-1", "CH-01"):
        await state.register_equipment(Equipment(equipment_id=eq, name=eq))

    sb = sb_mod.BuildingSkillbook("default", db_path=str(tmp_path / "skills.db"))
    sb.matcher = WordMatcher()
    await sb.ensure_initialized()
    monkeypatch.setitem(sb_mod._skillbooks, "default", sb)

    yield SimpleNamespace(db=db, state=state, sb=sb,
                          roles=RoleOrchestrator(state, db, building_id="default"))
    await sb.close()
    await db.close()


# ── scope ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_scope_matches_registered_units_in_any_spelling(site):
    assert await site.roles.scope("why is ahu 7 hot") == {"AHU-07"}
    assert await site.roles.scope("compare AHU-03 and chiller 1") == {"AHU-03", "CH-01"}
    assert await site.roles.scope("what about AHU-99") == set()        # unknown unit: no false scope


# ── the dossier ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dossier_reports_faults_alarms_diagnosis_knowledge_and_repairs(site):
    db, state, sb = site.db, site.state, site.sb
    findings = [_f("AHU-07", "FC13", cost=1200.0), _f("AHU-03", "FC14", cost=50.0)]
    await save_findings(db, findings)
    await process_findings(db, findings)                                  # opens real cases
    await state.add_alarm(Alarm(equipment_id="AHU-07", message="High supply air temperature",
                                severity=AlarmSeverity.HIGH, source_point_id="AHU-07/SAT"))
    await state.update_point(BMSDataPoint(point_id="AHU-07/RAT", name="RAT", value=24.0,
                                          equipment_id="AHU-07", quality=PointQuality.STALE))
    await sb.add_skill(skill_type="fault_pattern", title="AHU-07 coil capacity exhausted in extreme heat",
                       description="AHU-07 hot supply air coil capacity exhausted", equipment_id="AHU-07",
                       confidence=0.7)
    await sb.add_skill(skill_type="fault_pattern", title="CH-01 condenser fouling hot supply air",
                       description="CH-01 hot supply air condenser fouling", equipment_id="CH-01",
                       confidence=0.7)
    failed = await register_repair(db, "AHU-07", "FC13", hypothesis="valve stuck")
    failed.status, failed.reason = "failed", "fault present 6.0 h after repair"
    await save_verification(db, failed)

    plan = InvestigationPlan(query="AHU-07 supply air is hot, root cause?")
    out = await site.roles.before_investigation(plan.query, {}, plan)
    rep = out["reports"]

    assert out["scope"] == ["AHU-07"]
    a = rep["Anomaly_Agent"]
    kinds = {i["kind"] for i in a.items}
    assert kinds == {"fault", "alarm", "data_quality"}
    assert all(i["equipment_id"] == "AHU-07" for i in a.items)          # AHU-03 is out of scope

    d = rep["Diagnostic_Agent"].items
    assert len(d) == 1 and d[0]["rule_id"] == "FC13" and d[0]["causes"]
    assert d[0]["next_question"] and d[0]["next_question"]["question"]   # information-gain question

    k = rep["Knowledge_Agent"].items
    assert [i["title"] for i in k if i["kind"] == "skill"] == ["AHU-07 coil capacity exhausted in extreme heat"]

    assert rep["Verification_Agent"].items[0]["status"] == "failed"

    checks = rep["Recommendation_Agent"].items
    assert checks[0]["check"].startswith("Respond to the high alarm on AHU-07")
    assert "Re-open the repair on AHU-07" in checks[1]["check"]
    assert any(c.get("case_id") == d[0]["case_id"] for c in checks)       # the diagnosis question
    assert all(c.get("source") for c in checks)                            # every check cites its source

    # Everything is in the evidence ledger, attributed to its role, and cited in the prompt.
    by_role = {}
    for ev in plan.evidence.get_all():
        by_role.setdefault(ev.node_name, []).append(ev)
    assert set(by_role) == {"Anomaly_Agent", "Diagnostic_Agent", "Knowledge_Agent", "Verification_Agent"}
    for ev in plan.evidence.get_all():
        assert f"[{ev.id}]" in out["prompt"] or ev.node_name == "Anomaly_Agent"
    assert "ROLE AGENT REPORTS" in out["prompt"] and "Focus equipment: AHU-07" in out["prompt"]
    assert "Next checks:" in rep["Briefing_Agent"].summary


@pytest.mark.asyncio
async def test_building_wide_question_focuses_on_faulting_units(site):
    findings = [_f("AHU-03", "FC14", cost=50.0), _f("AHU-07", "FC13", cost=1200.0)]
    await save_findings(site.db, findings)
    await process_findings(site.db, findings)
    out = await site.roles.before_investigation("anything wrong in the building?", {}, InvestigationPlan())
    assert out["scope"] == [] and out["focus"] == ["AHU-03", "AHU-07"]
    faults = [i for i in out["reports"]["Anomaly_Agent"].items if i["kind"] == "fault"]
    assert [f["equipment_id"] for f in faults] == ["AHU-07", "AHU-03"]    # costliest first
    diag = out["reports"]["Diagnostic_Agent"].items
    assert {c["equipment_id"] for c in diag} == {"AHU-03", "AHU-07"}


@pytest.mark.asyncio
async def test_quiet_building_says_nothing_found_instead_of_inventing(site):
    plan = InvestigationPlan()
    out = await site.roles.before_investigation("how is CH-01 doing?", {}, plan)
    rep = out["reports"]
    for role in ("Anomaly_Agent", "Diagnostic_Agent", "Knowledge_Agent", "Verification_Agent",
                 "Recommendation_Agent"):
        assert rep[role].status == "empty"
        if role != "Knowledge_Agent":
            assert rep[role].items == []
    assert rep["Knowledge_Agent"].summary.startswith("No relevant past experience")
    assert len(plan.evidence) == 0                                          # nothing to cite, nothing written


@pytest.mark.asyncio
async def test_knowledge_reports_how_past_cases_were_resolved(site):
    await process_findings(site.db, [_f("FAHU-1", "FC14")])
    await learn_from_verification(site.db, SimpleNamespace(
        id=1, status="verified", equipment_id="FAHU-1", rule_id="FC14", hypothesis="chilled-water valve passing"))
    out = await site.roles.before_investigation("FAHU-1 cooling while off again", {}, InvestigationPlan())
    past = [i for i in out["reports"]["Knowledge_Agent"].items if i["kind"] == "past_case"]
    assert past and past[0]["resolution"]["status"] == "verified"


@pytest.mark.asyncio
async def test_pending_repair_becomes_a_recheck_step(site):
    await register_repair(site.db, "AHU-03", "FC14")
    out = await site.roles.before_investigation("AHU-03 status", {}, InvestigationPlan())
    checks = out["reports"]["Recommendation_Agent"].items
    assert checks and checks[-1]["why"] == "closed-loop verification pending"
    assert (await list_verifications(site.db))[0].status == "pending"      # roles never change state


@pytest.mark.asyncio
async def test_a_broken_engine_is_reported_unavailable_not_papered_over(site, monkeypatch):
    import agent_commercial.fdd.closed_loop as cl

    async def boom(*a, **k):
        raise RuntimeError("table locked")
    monkeypatch.setattr(cl, "list_verifications", boom)
    out = await site.roles.before_investigation("AHU-07", {}, InvestigationPlan())
    v = out["reports"]["Verification_Agent"]
    assert v.status == "unavailable" and v.items == []
    assert out["reports"]["Anomaly_Agent"].status in ("ok", "empty")        # the others still ran


# ── after the specialists ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_investigation_report_and_plan_persistence(site):
    from arvis_core.evidence import Evidence
    await save_findings(site.db, [_f("AHU-07", "FC13", cost=10.0)])
    plan = InvestigationPlan(query="AHU-07")
    await site.roles.before_investigation("AHU-07", {}, plan)
    plan.evidence.add(Evidence(source_tool="get_point_history", node_name="Comfort_Agent", summary="x"))
    plan.evidence.add(Evidence(source_tool="analyze_root_cause", node_name="Alarm_Agent", summary="y"))
    plan.evidence.add(Evidence(source_tool="explain_alarm", node_name="Alarm_Agent", summary="z"))
    site.roles.after_investigation(plan, ["Alarm_Agent", "Comfort_Agent"])

    inv = plan.role_reports["Investigation_Agent"]
    assert {i["specialist"]: i["evidence_added"] for i in inv["items"]} == {"Alarm_Agent": 2, "Comfort_Agent": 1}
    assert set(plan.role_reports) >= {"Anomaly_Agent", "Diagnostic_Agent", "Investigation_Agent",
                                      "Recommendation_Agent", "Verification_Agent", "Knowledge_Agent",
                                      "Briefing_Agent"}
    restored = InvestigationPlan.from_json(__import__("json").dumps(plan.to_persist_dict(), default=str))
    assert restored.role_reports["Investigation_Agent"]["summary"] == inv["summary"]
    assert plan.to_dict()["role_reports"]["Anomaly_Agent"]["items"]


def test_queen_accepts_a_role_orchestrator():
    from arvis_core.swarm.queen import QueenCoordinator
    assert "role_orchestrator" in QueenCoordinator.model_fields
