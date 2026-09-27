"""
fdd_findings persistence — one row per (run, equipment, rule) result, so the
dashboard, the LLM tools and later closed-loop verification can read history.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterable, List, Optional

from agent_commercial.fdd.finding import FaultFinding

_DDL = """
CREATE TABLE IF NOT EXISTS fdd_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    fault_hours REAL,
    fault_pct REAL,
    first_fault TEXT,
    last_fault TEXT,
    window_start TEXT,
    window_end TEXT,
    reason TEXT,
    payload TEXT
)"""
_IDX = ("CREATE INDEX IF NOT EXISTS idx_fdd_eq_rule ON fdd_findings(equipment_id, rule_id, evaluated_at)",
        "CREATE INDEX IF NOT EXISTS idx_fdd_run ON fdd_findings(run_id)")


async def _conn(database: Any):
    conn = await database._get_async_connection()
    await conn.execute(_DDL)
    for stmt in _IDX:
        await conn.execute(stmt)
    return conn


async def save_findings(database: Any, findings: Iterable[FaultFinding],
                        run_id: Optional[str] = None) -> str:
    run_id = run_id or uuid.uuid4().hex[:12]
    rows = [(run_id, f.evaluated_at, f.equipment_id, f.rule_id, f.outcome.value,
             f.fault_hours, f.fault_pct, f.first_fault, f.last_fault, f.window_start,
             f.window_end, f.reason, json.dumps(f.to_dict(), default=str))
            for f in findings]
    lock = getattr(database, "_write_lock", None)
    if lock is not None:
        async with lock:
            conn = await _conn(database)
            await conn.executemany(
                "INSERT INTO fdd_findings (run_id, evaluated_at, equipment_id, rule_id, outcome, "
                "fault_hours, fault_pct, first_fault, last_fault, window_start, window_end, reason, payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            await conn.commit()
    else:
        conn = await _conn(database)
        await conn.executemany(
            "INSERT INTO fdd_findings (run_id, evaluated_at, equipment_id, rule_id, outcome, "
            "fault_hours, fault_pct, first_fault, last_fault, window_start, window_end, reason, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        await conn.commit()
    return run_id


async def latest_findings(database: Any, *, equipment_id: Optional[str] = None,
                          outcome: Optional[str] = None) -> List[Dict[str, Any]]:
    """Most recent result per (equipment, rule)."""
    conn = await _conn(database)
    where, args = [], []
    if equipment_id:
        where.append("f.equipment_id = ?")
        args.append(equipment_id)
    if outcome:
        where.append("f.outcome = ?")
        args.append(outcome)
    sql = ("SELECT f.payload FROM fdd_findings f JOIN ("
           "  SELECT equipment_id, rule_id, MAX(id) AS max_id FROM fdd_findings"
           "  GROUP BY equipment_id, rule_id) last"
           " ON f.id = last.max_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY f.equipment_id, f.rule_id"
    async with conn.execute(sql, tuple(args)) as cur:
        return [json.loads(r[0]) for r in await cur.fetchall()]
