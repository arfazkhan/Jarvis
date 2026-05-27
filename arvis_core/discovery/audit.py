"""Append-only signed audit log for the ARVIS Discovery Agent.

Every discovery action (probe, register, quarantine, reject, etc.) is
appended to SQLite with an HMAC-SHA256 signature chained to the previous
entry's signature — providing tamper-evidence over the action sequence.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from arvis_core.discovery.security import sign_action, verify_signature

logger = logging.getLogger("arvis.discovery.audit")


class DiscoveryAuditLog:
    """Append-only signed audit log. Tamper-evident via signature chaining."""

    _lock = threading.Lock()

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS discovery_audit (
                    id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    point_id TEXT,
                    equipment_id TEXT,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    prev_signature TEXT,
                    outcome TEXT
                )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON discovery_audit(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_eq ON discovery_audit(equipment_id)")

    def append(
        self,
        agent_id: str,
        action_type: str,
        payload: dict,
        point_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> str:
        with self._lock:
            entry_id = str(uuid.uuid4())
            nonce = entry_id
            with sqlite3.connect(str(self.db_path)) as c:
                prev = c.execute(
                    "SELECT signature FROM discovery_audit ORDER BY ts DESC LIMIT 1"
                ).fetchone()
                prev_sig = prev[0] if prev else None
                full_payload = {**payload, "prev_signature": prev_sig}
                sig = sign_action(full_payload, nonce)
                c.execute(
                    """INSERT INTO discovery_audit
                       (id, ts, agent_id, action_type, point_id, equipment_id,
                        payload_json, signature, prev_signature, outcome)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry_id,
                        time.time(),
                        agent_id,
                        action_type,
                        point_id,
                        equipment_id,
                        json.dumps(payload, default=str),
                        sig,
                        prev_sig,
                        outcome,
                    ),
                )
            return entry_id

    def query(
        self, equipment_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        with sqlite3.connect(str(self.db_path)) as c:
            c.row_factory = sqlite3.Row
            if equipment_id:
                rows = c.execute(
                    "SELECT * FROM discovery_audit WHERE equipment_id=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (equipment_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM discovery_audit ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def verify_chain(self) -> bool:
        """Walk the chain in ts order, verify each signature.

        Returns True only if every entry's signature verifies against its
        payload + the previous entry's signature.
        """
        with sqlite3.connect(str(self.db_path)) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM discovery_audit ORDER BY ts ASC"
            ).fetchall()
            prev_sig: Optional[str] = None
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload["prev_signature"] = prev_sig
                if not verify_signature(payload, row["id"], row["signature"]):
                    logger.error(
                        "[DiscoveryAudit] Signature mismatch at entry %s", row["id"]
                    )
                    return False
                prev_sig = row["signature"]
        return True
