"""
Work orders raised from WhatsApp.

The FM says "raise a job for it" and ARVIS writes the work order from what it
knows (the fault, the likely cause with its probability, what was checked) and
pushes it to the site's CAFM system (Maximo / Planon / REST — agent_commercial/
adapters/cafm_adapter.py). This writes to the maintenance system, never to the BMS.

Every order is also kept here (ops_work_orders): with no CAFM configured it is still
logged; when the CAFM push fails it stays "queued" and is retried, durably — the
CAFM integration's own retry queue is in memory and would be lost on restart.
An open order counts as "someone is handling it" for the attention gate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.ops.work_orders")

_DDL = """CREATE TABLE IF NOT EXISTS ops_work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_id TEXT, rule_id TEXT, case_id INT,
    description TEXT, priority TEXT, status TEXT NOT NULL,     -- raised | logged | queued | done
    cafm_id TEXT, raised_by TEXT, raised_by_number TEXT, raised_at TEXT, attempts INT DEFAULT 0, error TEXT)"""


class WorkOrderLog:
    def __init__(self, database: Any, cafm: Any = None, clock=None):
        self.database = database
        self.cafm = cafm                     # CAFMIntegration (has .adapter.push_work_order) or None
        self.clock = clock or datetime.now

    async def _conn(self):
        conn = await self.database._get_async_connection()
        await conn.execute(_DDL)
        return conn

    async def raise_order(self, *, equipment_id: str, description: str, priority: str, raised_by: str,
                          raised_by_number: Optional[str] = None, rule_id: Optional[str] = None,
                          case_id: Optional[int] = None) -> Dict[str, Any]:
        conn = await self._conn()
        cur = await conn.execute("INSERT INTO ops_work_orders (equipment_id, rule_id, case_id, description, priority, "
                                 "status, raised_by, raised_by_number, raised_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (equipment_id, rule_id, case_id, description, priority,
                                  "queued" if self.cafm else "logged", raised_by, raised_by_number,
                                  self.clock().isoformat(timespec="seconds")))
        await conn.commit()
        oid = cur.lastrowid
        if self.cafm is None:
            return {"id": oid, "status": "logged", "note": "no CAFM system connected — logged in ARVIS only"}
        return await self._push(oid)

    async def _push(self, oid: int) -> Dict[str, Any]:
        from agent_commercial.adapters.cafm_adapter import WorkOrder
        conn = await self._conn()
        async with conn.execute("SELECT equipment_id, description, priority, rule_id, case_id, raised_by "
                                "FROM ops_work_orders WHERE id=?", (oid,)) as cur:
            eq, desc, prio, rule, case_id, by = await cur.fetchone()
        wo = WorkOrder(equipment_id=eq, description=desc, priority=prio, work_type="corrective",
                       metadata={"source": "ARVIS (WhatsApp)", "raised_by": by, "rule_id": rule, "case_id": case_id})
        try:
            cafm_id = await self.cafm.adapter.push_work_order(wo)
        except Exception as e:
            cafm_id, err = None, f"{type(e).__name__}: {e}"
        else:
            err = None if cafm_id else "CAFM returned no work order id"
        if cafm_id:
            await conn.execute("UPDATE ops_work_orders SET status='raised', cafm_id=?, error=NULL WHERE id=?",
                               (str(cafm_id), oid))
            await conn.commit()
            return {"id": oid, "status": "raised", "cafm_id": str(cafm_id)}
        await conn.execute("UPDATE ops_work_orders SET status='queued', attempts=attempts+1, error=? WHERE id=?",
                           (err, oid))
        await conn.commit()
        logger.warning(f"[WorkOrders] #{oid} not accepted by CAFM yet: {err}")
        return {"id": oid, "status": "queued", "note": "CAFM did not accept it yet — I'll keep retrying", "error": err}

    async def retry_queued(self, max_attempts: int = 20) -> List[Dict[str, Any]]:
        """Push queued orders again; returns the ones CAFM accepted this time (with who raised them)."""
        if self.cafm is None:
            return []
        conn = await self._conn()
        async with conn.execute("SELECT id, equipment_id, raised_by_number FROM ops_work_orders "
                                "WHERE status='queued' AND attempts < ?", (max_attempts,)) as cur:
            rows = await cur.fetchall()
        raised = []
        for oid, eq, number in rows:
            out = await self._push(oid)
            if out["status"] == "raised":
                raised.append({**out, "equipment_id": eq, "raised_by_number": number})
        return raised

    async def open_on(self, equipment_id: str, days: float = 14.0) -> List[Dict[str, Any]]:
        cutoff = (self.clock() - timedelta(days=days)).isoformat(timespec="seconds")
        conn = await self._conn()
        async with conn.execute("SELECT id, status, cafm_id, raised_by, rule_id FROM ops_work_orders WHERE equipment_id=? "
                                "AND status IN ('raised','logged','queued') AND raised_at >= ?",
                                (equipment_id, cutoff)) as cur:
            return [{"id": r[0], "status": r[1], "cafm_id": r[2], "raised_by": r[3], "rule_id": r[4]}
                    for r in await cur.fetchall()]
