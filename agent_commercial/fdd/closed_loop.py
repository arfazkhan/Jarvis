"""
Closed-loop fix verification.

When a repair is recorded against a confirmed fault (equipment + rule), ARVIS
does not assume it worked. Each FDD sweep re-runs the SAME rule over the
telemetry since the repair:

  VERIFIED      the rule passed over ≥ min_running_hours of proven operation
  FAILED        the fault came back after the repair
  PENDING       too little running time since the repair to judge yet
  INCONCLUSIVE  the rule cannot be judged (points missing, sensor failed, …)

A verified or failed fix is the ground-truth label the diagnosis layer learns from.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent_commercial.fdd.engine import FDDEngine
from agent_commercial.fdd.finding import Outcome
from agent_commercial.fdd.rules import RULES_BY_ID, SENSOR_RULE_IDS

_DDL = """
CREATE TABLE IF NOT EXISTS fdd_fix_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    repaired_at TEXT NOT NULL,
    work_order_id TEXT,
    note TEXT,
    hypothesis TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    running_hours REAL,
    fault_hours REAL,
    checked_at TEXT,
    finding TEXT
)"""


@dataclass
class FixVerification:
    id: Optional[int]
    equipment_id: str
    rule_id: str
    repaired_at: str
    status: str = "pending"
    reason: str = "awaiting post-repair operation"
    work_order_id: Optional[str] = None
    note: str = ""
    hypothesis: Optional[str] = None       # the cause the repair addressed, if known
    running_hours: float = 0.0
    fault_hours: float = 0.0
    checked_at: Optional[str] = None
    finding: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def _conn(database):
    conn = await database._get_async_connection()
    await conn.execute(_DDL)
    return conn


async def register_repair(database, equipment_id: str, rule_id: str, *,
                          repaired_at: Optional[datetime] = None, work_order_id: Optional[str] = None,
                          note: str = "", hypothesis: Optional[str] = None) -> FixVerification:
    if rule_id not in RULES_BY_ID:
        raise ValueError(f"unknown FDD rule {rule_id}")
    when = (repaired_at or datetime.now()).isoformat(timespec="seconds")
    conn = await _conn(database)
    cur = await conn.execute(
        "INSERT INTO fdd_fix_verifications (equipment_id, rule_id, repaired_at, work_order_id, note, "
        "hypothesis, status, reason) VALUES (?,?,?,?,?,?,?,?)",
        (equipment_id, rule_id, when, work_order_id, note, hypothesis, "pending",
         "awaiting post-repair operation"))
    await conn.commit()
    return FixVerification(cur.lastrowid, equipment_id, rule_id, when, work_order_id=work_order_id,
                           note=note, hypothesis=hypothesis)


def _row(r) -> FixVerification:
    d = dict(r)
    d["finding"] = json.loads(d.get("finding") or "{}")
    return FixVerification(**d)


async def list_verifications(database, *, status: Optional[str] = None) -> List[FixVerification]:
    conn = await _conn(database)
    sql, args = "SELECT * FROM fdd_fix_verifications", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    async with conn.execute(sql + " ORDER BY id", args) as cur:
        return [_row(r) for r in await cur.fetchall()]


async def verify_fix(engine: FDDEngine, bms_state, database, v: FixVerification, *,
                     min_running_hours: float = 24.0, now: Optional[datetime] = None) -> FixVerification:
    """Re-run the fault's rule on telemetry since the repair and classify."""
    now = now or datetime.now()
    since_h = (now - datetime.fromisoformat(v.repaired_at)).total_seconds() / 3600.0
    v.checked_at = now.isoformat(timespec="seconds")
    if since_h <= 0:
        v.status, v.reason = "pending", "repair time is in the future"
        return v
    rule_engine = FDDEngine([RULES_BY_ID[r] for r in SENSOR_RULE_IDS] + [RULES_BY_ID[v.rule_id]],
                            poll_seconds=engine.poll_seconds, allow_ungated=engine.allow_ungated,
                            params_by_rule=engine.params_by_rule, economics=engine.economics)
    findings = await rule_engine.run_building(bms_state, database, hours=since_h,
                                              equipment_ids=[v.equipment_id])
    f = next((x for x in findings if x.rule_id == v.rule_id and x.equipment_id == v.equipment_id), None)
    if f is None:
        v.status, v.reason = "pending", "no telemetry for this equipment since the repair"
        return v
    v.finding = f.to_dict()
    v.running_hours = float(f.active_hours or 0.0)
    v.fault_hours = float(f.fault_hours or 0.0)
    if f.outcome is Outcome.FAIL:
        v.status, v.reason = "failed", f"fault returned after repair: {f.headline()}"
    elif f.outcome is Outcome.PASS and v.running_hours >= min_running_hours:
        v.status, v.reason = "verified", (f"no fault over {v.running_hours:.1f} h of proven operation "
                                          "since the repair")
    elif f.outcome is Outcome.PASS:
        v.status, v.reason = "pending", (f"only {v.running_hours:.1f} h of running data since the repair "
                                         f"(need {min_running_hours:g} h)")
    else:
        v.status, v.reason = "inconclusive", f"rule could not be judged: {f.reason}"
    return v


async def save_verification(database, v: FixVerification) -> None:
    conn = await _conn(database)
    await conn.execute(
        "UPDATE fdd_fix_verifications SET status=?, reason=?, running_hours=?, fault_hours=?, "
        "checked_at=?, finding=? WHERE id=?",
        (v.status, v.reason, v.running_hours, v.fault_hours, v.checked_at,
         json.dumps(v.finding, default=str), v.id))
    await conn.commit()


async def recheck_pending(engine: FDDEngine, bms_state, database, *,
                          min_running_hours: float = 24.0) -> List[FixVerification]:
    """Re-verify every pending repair; returns the ones that reached a verdict."""
    decided = []
    for v in await list_verifications(database, status="pending"):
        v = await verify_fix(engine, bms_state, database, v, min_running_hours=min_running_hours)
        await save_verification(database, v)
        if v.status != "pending":
            decided.append(v)
    return decided
