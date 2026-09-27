"""Phase 3 — Bayesian diagnosis (NIST ZandrEA method) on the FDD rules."""
import asyncio
from types import SimpleNamespace

import pytest

from agent_commercial.fdd.diagnosis import (
    EvidenceItem, Hypothesis, RuleKB, answer_question, default_kb, diagnose,
    learn_from_verification, list_cases, load_kb, process_findings,
)
from agent_commercial.fdd.finding import FaultFinding, Outcome


def _kb4():
    hyps = [Hypothesis(f"H{i}", f"cause {i}") for i in range(1, 5)]
    ev = [EvidenceItem("E1", "q1", {"H1": "excludes", "H2": "requires", "H3": "requires", "H4": "requires"}),
          EvidenceItem("E2", "q2", {"H2": "requires", "H3": "excludes", "H4": "excludes"}),
          EvidenceItem("E3", "q3", {"H1": "requires", "H2": "requires", "H3": "requires", "H4": "requires"})]
    return RuleKB.seeded("TEST", hyps, ev)


def _p(d, hid):
    return next(x["p"] for x in d.posterior if x["id"] == hid)


def test_zandrea_primer_worked_example():
    kb = _kb4()
    d0 = diagnose(kb, {})
    assert [x["p"] for x in d0.posterior] == [0.25] * 4
    d1 = diagnose(kb, {"E1": "yes"})
    assert _p(d1, "H1") == 0.0 and "H1" in d1.eliminated
    assert all(_p(d1, h) == pytest.approx(1 / 3, abs=1e-3) for h in ("H2", "H3", "H4"))
    d2 = diagnose(kb, {"E1": "yes", "E2": "yes"})
    assert d2.top["id"] == "H2" and d2.top["p"] == 1.0


def test_kb_bust_is_reported_not_hidden():
    d = diagnose(_kb4(), {"E3": "no"})
    assert d.kb_bust and d.next_question is None


def test_next_question_is_the_most_informative():
    kb = _kb4()
    kb.evidence.append(EvidenceItem("E0", "useless", {"H1": "supports", "H2": "supports",
                                                      "H3": "supports", "H4": "supports"}))
    q = diagnose(kb, {}).next_question
    assert q["evidence_id"] in ("E1", "E2")


def test_verified_repairs_teach_the_kb():
    kb = default_kb("FC14")
    passing = kb.match_hypothesis("valve passing")
    actuator = kb.match_hypothesis("actuator")
    answers = {"E_FEEDBACK": "yes", "G_PERSIST": "yes"}
    before = _p(diagnose(kb, answers), passing)
    for _ in range(3):
        kb.learn(answers, passing, verified=True)
    after = _p(diagnose(kb, answers), passing)
    assert after > before
    assert kb.track[passing] == [3, 0]
    kb.learn(answers, actuator, verified=False)
    assert kb.track[actuator] == [0, 1] and kb.prior()[actuator] < kb.prior()[passing]
    assert RuleKB.from_json(kb.to_json()).track == kb.track


def test_default_kbs_exist_for_every_rule_and_link_curated_evidence():
    from agent_commercial.fdd import RULES_BY_ID
    for rid in RULES_BY_ID:
        kb = default_kb(rid)
        assert kb.hypotheses[0].id == "H1"
    fc14 = default_kb("FC14")
    iso = fc14.evidence_item("E_ISOLATE")
    assert iso.links[fc14.match_hypothesis("passing")] == "requires"
    assert fc14.match_hypothesis("FC14:H3") == "H3"


# ── cases ─────────────────────────────────────────────────────────────────────

def _f(eq, rule, outcome=Outcome.FAIL, pct=80.0, family="ahu", roles=None, invalid=None):
    return FaultFinding(rule_id=rule, title=rule, family=family, equipment_id=eq, equipment_kind="ahu",
                        outcome=outcome, fault_pct=pct if outcome is Outcome.FAIL else None,
                        fault_hours=5.0 if outcome is Outcome.FAIL else 0.0,
                        points_used={r: f"{eq}/{r}" for r in (roles or [])},
                        invalid_roles=list(invalid or []))


@pytest.fixture
def db(tmp_path):
    from agent_commercial.database import BMSDatabase
    d = BMSDatabase(db_path=str(tmp_path / "diag.db"))
    yield d
    asyncio.run(d.close())


def test_case_opens_with_auto_answers_and_masks_repeats(db):
    async def go():
        first = await process_findings(db, [_f("FAHU-1", "FC14")])
        second = await process_findings(db, [_f("FAHU-1", "FC14")])
        return first, second, await list_cases(db)
    first, second, cases = asyncio.run(go())
    assert len(cases) == 1 and cases[0].occurrences == 2 and first[0].id == second[0].id
    c = cases[0]
    assert c.answers["G_PERSIST"] == "yes" and c.answer_sources["G_PERSIST"] == "auto:fault_pct_ge"
    ranked = c.diagnosis["posterior"]
    assert ranked[-1]["id"] == "H1" or ranked[0]["id"] != "H1"          # spurious is not the lead
    assert c.diagnosis["next_question"]["evidence_id"] in ("E_ISOLATE", "E_FEEDBACK")


def test_zone_fault_is_suppressed_under_its_ahu_case(db):
    async def go():
        await process_findings(db, [_f("AHU-1", "FC13"), _f("VAV-9", "VAV-1", family="vav")],
                               parents={"VAV-9": "AHU-1"})
        return await list_cases(db)
    cases = {c.equipment_id: c for c in asyncio.run(go())}
    vav, ahu = cases["VAV-9"], cases["AHU-1"]
    assert vav.status == "suppressed" and vav.suppressed_by == ahu.id
    assert vav.answers["E_AHU_WARM"] == "yes"
    top = vav.diagnosis["posterior"][0]
    assert "AHU supply" in top["label"]


def test_case_clears_and_reopens(db):
    async def go():
        await process_findings(db, [_f("AHU-2", "AHU-SATDEV")])
        await process_findings(db, [_f("AHU-2", "AHU-SATDEV", outcome=Outcome.PASS)])
        cleared = (await list_cases(db))[0].status
        await process_findings(db, [_f("AHU-2", "AHU-SATDEV")])
        return cleared, (await list_cases(db))[0].status
    assert asyncio.run(go()) == ("cleared", "open")


def test_operator_answers_are_kept_and_reranked(db):
    async def go():
        (case,) = await process_findings(db, [_f("FAHU-1", "FC14")])
        updated = await answer_question(db, case.id, "E_ISOLATE", "yes", answered_by="tech.ali")
        again = (await process_findings(db, [_f("FAHU-1", "FC14")]))[0]
        return updated, again
    updated, again = asyncio.run(go())
    assert updated.answer_sources["E_ISOLATE"] == "operator:tech.ali"
    kb = default_kb("FC14")
    assert updated.diagnosis["posterior"][0]["id"] == kb.match_hypothesis("passing")
    assert again.answers["E_ISOLATE"] == "yes"


def test_verified_fix_closes_case_and_updates_building_kb(db):
    async def go():
        await process_findings(db, [_f("FAHU-1", "FC14")])
        v = SimpleNamespace(id=7, status="verified", equipment_id="FAHU-1", rule_id="FC14",
                            hypothesis="chilled-water valve passing")
        out = await learn_from_verification(db, v)
        kb = await load_kb(db, "FC14")
        return out, kb, await list_cases(db)
    out, kb, cases = asyncio.run(go())
    hid = kb.match_hypothesis("passing")
    assert out["learned"] and out["hypothesis_id"] == hid
    assert kb.track[hid] == [1, 0]
    assert cases[0].status == "closed" and cases[0].resolution["status"] == "verified"


def test_unmatched_repair_hypothesis_is_recorded_not_guessed(db):
    async def go():
        await process_findings(db, [_f("FAHU-1", "FC14")])
        v = SimpleNamespace(id=8, status="verified", equipment_id="FAHU-1", rule_id="FC14",
                            hypothesis="replaced the thermostat")
        return await learn_from_verification(db, v)
    out = asyncio.run(go())
    assert out["learned"] is False and "did not name a hypothesis" in out["reason"]
