"""
Diagnosis cases — how a confirmed fault becomes a ranked diagnosis.

One case per (equipment, rule). While a case is open the rule is *masked*:
repeated FAILs update it instead of opening new ones (alarm-flood control,
after ZandrEA). A terminal-unit fault whose parent AHU already has an open
supply-air case is *suppressed* under that case — the AHU problem explains the
zone symptom (ZandrEA's pinned AHU facts skipping dependent VAV rules).

Each sweep a case's evidence is auto-answered from what ARVIS already knows
(other rules on the unit, its parent, the plant, sensor validation, design,
history); the rest are asked of the operator one at a time, most informative
first. When a repair is verified or fails, the case's answers teach the
building's knowledge base.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from agent_commercial.fdd.diagnosis.catalog import default_kb
from agent_commercial.fdd.diagnosis.inference import diagnose
from agent_commercial.fdd.diagnosis.kb import RuleKB
from agent_commercial.fdd.finding import FaultFinding, Outcome
from agent_commercial.fdd.rules import RULES_BY_ID

# Parent (AHU) faults that explain downstream terminal-unit symptoms.
AIR_SUPPLY_RULES = {"FC13", "AHU-SATDEV", "FC1", "FC5", "FC7", "CMD-1", "SCHED-247"}
DOWNSTREAM_RULES = {"VAV-1", "VAV-4", "VAV-AHU-LEAVE", "VAV-REHEAT", "VAV-3", "ZONE-SETBACK-1"}

_DDL = (
    """CREATE TABLE IF NOT EXISTS fdd_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL, equipment_id TEXT NOT NULL, rule_id TEXT NOT NULL,
        status TEXT NOT NULL, opened_at TEXT, updated_at TEXT, payload TEXT)""",
    """CREATE TABLE IF NOT EXISTS fdd_kb (
        scope TEXT NOT NULL, rule_id TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT,
        PRIMARY KEY (scope, rule_id))""",
)


@dataclass
class Case:
    id: Optional[int]
    equipment_id: str
    rule_id: str
    status: str = "open"                     # open | suppressed | cleared | closed
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = ""
    suppressed_by: Optional[int] = None
    answers: Dict[str, str] = field(default_factory=dict)
    answer_sources: Dict[str, str] = field(default_factory=dict)
    diagnosis: Dict[str, Any] = field(default_factory=dict)
    finding: Dict[str, Any] = field(default_factory=dict)
    resolution: Optional[Dict[str, Any]] = None
    occurrences: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────
async def _conn(database):
    conn = await database._get_async_connection()
    for stmt in _DDL:
        await conn.execute(stmt)
    return conn


async def load_kb(database, rule_id: str, scope: str = "building") -> RuleKB:
    conn = await _conn(database)
    async with conn.execute("SELECT payload FROM fdd_kb WHERE scope=? AND rule_id=?", (scope, rule_id)) as cur:
        row = await cur.fetchone()
    return RuleKB.from_json(row[0]) if row else default_kb(rule_id)


async def save_kb(database, kb: RuleKB, scope: str = "building") -> None:
    conn = await _conn(database)
    await conn.execute("INSERT OR REPLACE INTO fdd_kb (scope, rule_id, payload, updated_at) VALUES (?,?,?,?)",
                       (scope, kb.rule_id, kb.to_json(), datetime.now().isoformat(timespec="seconds")))
    await conn.commit()


def _case_from_row(r) -> Case:
    d = json.loads(r["payload"])
    d["id"] = r["id"]
    return Case(**d)


async def list_cases(database, *, status: Optional[str] = None, equipment_id: Optional[str] = None,
                     scope: str = "building") -> List[Case]:
    conn = await _conn(database)
    sql, args = "SELECT id, payload FROM fdd_cases WHERE scope=?", [scope]
    if status:
        sql += " AND status=?"
        args.append(status)
    if equipment_id:
        sql += " AND equipment_id=?"
        args.append(equipment_id)
    async with conn.execute(sql + " ORDER BY id", tuple(args)) as cur:
        return [_case_from_row(r) for r in await cur.fetchall()]


async def save_case(database, case: Case, scope: str = "building") -> Case:
    conn = await _conn(database)
    case.updated_at = datetime.now().isoformat(timespec="seconds")
    payload = json.dumps({k: v for k, v in case.to_dict().items() if k != "id"}, default=str)
    if case.id is None:
        cur = await conn.execute(
            "INSERT INTO fdd_cases (scope, equipment_id, rule_id, status, opened_at, updated_at, payload) "
            "VALUES (?,?,?,?,?,?,?)",
            (scope, case.equipment_id, case.rule_id, case.status, case.opened_at, case.updated_at, payload))
        case.id = cur.lastrowid
    else:
        await conn.execute("UPDATE fdd_cases SET status=?, updated_at=?, payload=? WHERE id=?",
                           (case.status, case.updated_at, payload, case.id))
    await conn.commit()
    return case


# ──────────────────────────────────────────────────────────────────────────
# Auto-answering
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Context:
    finding: FaultFinding
    unit: Dict[str, str]                 # rule_id → outcome, this unit
    parent: Dict[str, str]               # rule_id → outcome, parent unit
    building_fails: set                  # rule ids failing anywhere
    failing_sensors: set                 # roles failing validation on this unit
    design: Dict[str, Any]
    previous_cases: int


def auto_answer(spec: tuple, ctx: Context) -> Optional[str]:
    """'yes' / 'no' from data, or None when the data cannot settle it."""
    kind = spec[0]
    yn = lambda b: "yes" if b else "no"  # noqa: E731

    def judged(outcomes: Dict[str, str], rules) -> Optional[str]:
        seen = [outcomes.get(r) for r in rules if outcomes.get(r) in ("pass", "fail")]
        if "fail" in seen:
            return "yes"
        return "no" if seen else None

    if kind == "sensor_invalid":
        used = set(ctx.finding.points_used) | set(ctx.finding.invalid_roles)
        return yn(bool(used & ctx.failing_sensors) or bool(ctx.finding.invalid_roles))
    if kind == "fault_pct_ge":
        return yn((ctx.finding.fault_pct or 0.0) >= float(spec[1]))
    if kind == "previous_case":
        return yn(ctx.previous_cases > 0)
    if kind == "rule":
        return judged(ctx.unit, spec[1])
    if kind == "parent_rule":
        return judged(ctx.parent, spec[1]) if ctx.parent else None
    if kind == "building_rule":
        return "yes" if set(spec[1]) & ctx.building_fails else None
    if kind == "design":
        v = ctx.design.get(spec[1])
        return None if v is None else yn(v == spec[2])
    return None


# ──────────────────────────────────────────────────────────────────────────
# Sweep processing
# ──────────────────────────────────────────────────────────────────────────
def _refresh(case: Case, kb: RuleKB, ctx: Context) -> None:
    for ev in kb.evidence:
        if case.answer_sources.get(ev.id, "").startswith("operator"):
            continue                              # a human answer is never overwritten
        ans = auto_answer(ev.auto, ctx) if ev.auto else None
        if ans is not None:
            case.answers[ev.id] = ans
            case.answer_sources[ev.id] = f"auto:{ev.auto[0]}"
    case.diagnosis = diagnose(kb, case.answers).to_dict()


async def process_findings(database, findings: Iterable[FaultFinding], *,
                           parents: Optional[Dict[str, str]] = None,
                           designs: Optional[Dict[str, Dict[str, Any]]] = None,
                           scope: str = "building") -> List[Case]:
    """Open / update / suppress / clear cases for one sweep. Returns the cases touched."""
    findings = list(findings)
    parents = parents or {}
    designs = designs or {}
    by_unit: Dict[str, Dict[str, str]] = {}
    failing_sensors: Dict[str, set] = {}
    for f in findings:
        by_unit.setdefault(f.equipment_id, {})[f.rule_id] = f.outcome.value
        if f.family == "sensor" and f.outcome is Outcome.FAIL:
            failing_sensors.setdefault(f.equipment_id, set()).update(f.invalid_roles)
    building_fails = {f.rule_id for f in findings if f.outcome is Outcome.FAIL}

    existing = await list_cases(database, scope=scope)
    live = {(c.equipment_id, c.rule_id): c for c in existing if c.status in ("open", "suppressed", "cleared")}
    history: Dict[tuple, int] = {}
    for c in existing:
        if c.status == "closed":
            history[(c.equipment_id, c.rule_id)] = history.get((c.equipment_id, c.rule_id), 0) + 1
    kbs: Dict[str, RuleKB] = {}
    touched: List[Case] = []

    # Parents first, so a child can be suppressed under a parent case opened this sweep.
    order = sorted(findings, key=lambda f: 1 if parents.get(f.equipment_id) else 0)
    for f in order:
        key = (f.equipment_id, f.rule_id)
        case = live.get(key)
        if f.outcome is not Outcome.FAIL:
            if case is not None and f.outcome is Outcome.PASS and case.status != "cleared":
                case.status = "cleared"             # fault not present now; kept for verification/learning
                touched.append(await save_case(database, case, scope))
            continue
        if f.rule_id not in kbs:
            kbs[f.rule_id] = await load_kb(database, f.rule_id, scope)
        kb = kbs[f.rule_id]
        parent_id = parents.get(f.equipment_id)
        if case is None:
            case = Case(None, f.equipment_id, f.rule_id)
            live[key] = case
        else:
            case.occurrences += 1
            if case.status == "cleared":
                case.status = "open"
        case.finding = f.to_dict()
        parent_case = None
        if parent_id and f.rule_id in DOWNSTREAM_RULES:
            parent_case = next((c for (eq, rid), c in live.items()
                                if eq == parent_id and rid in AIR_SUPPLY_RULES and c.status == "open"), None)
        if parent_case is not None:
            case.status, case.suppressed_by = "suppressed", parent_case.id
        elif case.status == "suppressed":        # the parent problem is gone; this stands alone now
            case.status, case.suppressed_by = "open", None
        ctx = Context(f, by_unit.get(f.equipment_id, {}), by_unit.get(parent_id, {}) if parent_id else {},
                      building_fails, failing_sensors.get(f.equipment_id, set()),
                      designs.get(f.equipment_id, {}), history.get(key, 0))
        _refresh(case, kb, ctx)
        touched.append(await save_case(database, case, scope))
    return touched


async def answer_question(database, case_id: int, evidence_id: str, answer: str, *,
                          answered_by: str = "operator", scope: str = "building") -> Case:
    if answer not in ("yes", "no", "unevaluated"):
        raise ValueError("answer must be yes, no or unevaluated")
    case = next((c for c in await list_cases(database, scope=scope) if c.id == case_id), None)
    if case is None:
        raise ValueError(f"case {case_id} not found")
    kb = await load_kb(database, case.rule_id, scope)
    if kb.evidence_item(evidence_id) is None:
        raise ValueError(f"{evidence_id} is not a question for rule {case.rule_id}")
    case.answers[evidence_id] = answer
    case.answer_sources[evidence_id] = f"operator:{answered_by}"
    case.diagnosis = diagnose(kb, case.answers).to_dict()
    return await save_case(database, case, scope)


async def learn_from_verification(database, verification, *, scope: str = "building") -> Optional[Dict[str, Any]]:
    """Teach the KB from a decided fix (verified / failed) and close the case."""
    if verification.status not in ("verified", "failed"):
        return None
    cases = [c for c in await list_cases(database, scope=scope)
             if c.equipment_id == verification.equipment_id and c.rule_id == verification.rule_id
             and c.status != "closed"]
    kb = await load_kb(database, verification.rule_id, scope)
    hyp = kb.match_hypothesis(verification.hypothesis)
    outcome = {"verification_id": verification.id, "status": verification.status,
               "hypothesis_id": hyp, "learned": False}
    if hyp is not None:
        answers = cases[-1].answers if cases else {}
        kb.learn(answers, hyp, verified=verification.status == "verified")
        await save_kb(database, kb, scope)
        outcome["learned"] = True
    else:
        outcome["reason"] = ("repair did not name a hypothesis of this rule"
                             if verification.hypothesis else "repair recorded without a hypothesis")
    for c in cases:
        if verification.status == "verified":
            c.status = "closed"
        c.resolution = outcome
        await save_case(database, c, scope)
    return outcome


def known_rules() -> List[str]:
    return sorted(RULES_BY_ID)
