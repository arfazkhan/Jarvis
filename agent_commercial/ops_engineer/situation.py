"""
Who is already handling it?

An engineer doesn't ping the FM about AHU-07's symptoms while Ali is out checking
AHU-07's valve. Before speaking up, the gate asks:

  * a field check on that equipment is waiting for a technician
  * a repair on it is recorded and awaiting re-check
  * a signal about it was acknowledged ("on it")
  * the person was talking about it in the last ARVIS_OPS_HANDLED_CHAT_H hours (2)
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional


class Situation:
    def __init__(self, database: Any, field_checks: Any = None, clock=None):
        self.database = database
        self.field_checks = field_checks
        self.clock = clock or datetime.now          # same clock as the conversation store
        self.chat_hours = float(os.getenv("ARVIS_OPS_HANDLED_CHAT_H", "2"))

    async def handling(self, subject: Optional[str], number: Optional[str] = None) -> List[str]:
        """Reasons the subject is already being dealt with (empty → nobody is)."""
        if not subject:
            return []
        out: List[str] = []
        if self.field_checks is not None:
            for c in await self.field_checks.list_checks("sent"):
                if c.equipment_id == subject:
                    out.append(f"check {c.ref} with {c.technician_name or c.technician}")
        try:
            from agent_commercial.fdd.closed_loop import list_verifications
            for v in await list_verifications(self.database, status="pending"):
                if v.equipment_id == subject:
                    out.append(f"repair on {subject} ({v.rule_id}) awaiting re-check")
        except Exception:
            pass
        conn = await self.database._get_async_connection()
        try:
            async with conn.execute("SELECT ack_by FROM ops_signals WHERE subject=? AND state='acknowledged'",
                                    (subject,)) as cur:
                for r in await cur.fetchall():
                    out.append(f"acknowledged by {r[0]}")
        except Exception:
            pass
        if number:
            cutoff = (self.clock() - timedelta(hours=self.chat_hours)).isoformat(timespec="seconds")
            pattern = re.compile(re.escape(subject).replace(r"\-", r"[-_\s]?"), re.IGNORECASE)
            try:
                # Their own words only — ARVIS having mentioned it is not them handling it.
                async with conn.execute("SELECT text FROM ops_turns WHERE number=? AND speaker='person' "
                                        "AND created_at >= ?", (number, cutoff)) as cur:
                    if any(pattern.search(r[0] or "") for r in await cur.fetchall()):
                        out.append(f"discussed with them in the last {self.chat_hours:g} h")
            except Exception:
                pass
        return out

    async def in_conversation(self, number: str, minutes: float = 5.0) -> bool:
        """They wrote to ARVIS in the last few minutes — don't interrupt mid-conversation."""
        cutoff = (self.clock() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        conn = await self.database._get_async_connection()
        try:
            async with conn.execute("SELECT 1 FROM ops_turns WHERE number=? AND speaker='person' "
                                    "AND created_at >= ? LIMIT 1", (number, cutoff)) as cur:
                return await cur.fetchone() is not None
        except Exception:
            return False
