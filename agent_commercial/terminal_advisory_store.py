"""
Terminal Advisory Store — Persistent Registry for Critical ARVIS Advisories
============================================================================

Once ARVIS issues a terminal advisory (severity=critical, equipment failure
imminent, life safety, regulatory non-compliance), it MUST remain visible to
every subsequent swarm turn until explicitly acknowledged by an operator.

Why this exists:
    In Marina S1 P6, ARVIS issued "CH-04 60% failure probability in 14 days"
    on turn 0, then on turn 3 retreated to "Low confidence — recommend physical
    inspection" when the operator tried to dismiss. The original terminal
    advisory disappeared because each swarm turn starts fresh and doesn't see
    the prior turn's critical findings. Operators can talk ARVIS out of
    life-safety calls. This store prevents that.

Lifecycle:
    1. Swarm synthesis produces an advisory with severity >= 'high'.
    2. terminal_advisory_detector inspects → if criteria met, writes ACTIVE row.
    3. Every subsequent swarm pre-runs queries store for ACTIVE rows + injects
       them into context as TERMINAL_ADVISORIES_PENDING.
    4. Synthesis prompt clause 12 declares these AUTHORITATIVE.
    5. Operator queries scanned for acknowledgment signals → mark ACKNOWLEDGED.
    6. Hourly escalator: unack > 4h sim time → escalated_at + log event.
    7. Operator can mark resolved via explicit tool call.

Public API:
    store = TerminalAdvisoryStore(db_path)
    await store.fire(building_id, eq_id, type, severity, title, message,
                     evidence_ids, confidence, sim_day, plan_id, source_query)
    pending = await store.list_active(building_id)
    await store.acknowledge(advisory_id, operator_id, ack_signal)
    await store.resolve(advisory_id, action_text)
    await store.escalate_overdue(threshold_hours=4)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger("arvis.terminal_advisory")


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TerminalAdvisory:
    """One row from terminal_advisories table."""
    advisory_id: str
    building_id: str
    equipment_id: Optional[str]
    advisory_type: str
    severity: str
    title: str
    message: str
    evidence_ids: List[str]
    confidence: float
    fired_at: str
    sim_day: Optional[int]
    last_surfaced_at: str
    surface_count: int
    state: str
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    ack_signal: Optional[str] = None
    resolved_at: Optional[str] = None
    resolution_action: Optional[str] = None
    escalated_at: Optional[str] = None
    escalation_target: Optional[str] = None
    source_plan_id: Optional[str] = None
    source_query: Optional[str] = None

    def to_context_block(self) -> str:
        """Render as a system-prompt-friendly block for swarm context injection."""
        sim_part = f" (sim_day {self.sim_day})" if self.sim_day is not None else ""
        eq_part = f" on {self.equipment_id}" if self.equipment_id else ""
        evid = ", ".join(self.evidence_ids[:5]) if self.evidence_ids else "none"
        return (
            f"  - [{self.severity.upper()}] {self.title}{eq_part} — "
            f"fired {self.fired_at[:19]}{sim_part}, surfaced {self.surface_count}× | "
            f"evidence_ids: [{evid}]\n    {self.message[:300]}"
        )


# Criteria for auto-firing terminal advisory from synthesis output
_TERMINAL_TYPES = {
    "equipment_failure",
    "life_safety",
    "energy_critical",
    "compliance_breach",
    "physics_violation",
    "predictive_failure",
    "safety_priority",
}

_HIGH_SEVERITIES = {"critical", "severe", "high"}

# Acknowledgment signal patterns operators use in natural language
_ACK_PATTERNS = [
    re.compile(r"\b(acknowledged|noted|understood|confirmed|i (?:see|got|read) (?:that|it|this))\b", re.IGNORECASE),
    re.compile(r"\b(scheduling|dispatching|sending (?:a )?tech|will (?:action|address|handle|escalate))\b", re.IGNORECASE),
    re.compile(r"\b(work order (?:created|opened|raised|in)|wo\s*#?\d+)\b", re.IGNORECASE),
    re.compile(r"\b(carrier (?:tech|techs|coming|dispatched)|vendor (?:on (?:the )?way|notified))\b", re.IGNORECASE),
    re.compile(r"\b(approved|authorized|signing off|signed off)\b", re.IGNORECASE),
]


def _is_acknowledgment(query: str) -> Optional[str]:
    """Return the matched ack phrase if query contains acknowledgment language."""
    if not query:
        return None
    for pat in _ACK_PATTERNS:
        m = pat.search(query)
        if m:
            return m.group(0)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────

class TerminalAdvisoryStore:
    """Async wrapper over terminal_advisories + terminal_advisory_events tables."""

    def __init__(self, db_path: Optional[str] = None):
        # Honor ARVIS_DB_PATH like other ARVIS DB consumers
        if db_path is None:
            import os as _os
            _env_db = _os.getenv("ARVIS_DB_PATH", "").strip()
            if _env_db:
                db_path = _env_db
            else:
                db_path = str(Path(__file__).parent / "data" / "arvis_bms.db")
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA busy_timeout=60000")
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # Ensure schema exists (idempotent). Try the full calibration schema
        # first, but DON'T depend on it — executescript aborts the remaining
        # statements if an earlier block errors, which previously left
        # terminal_advisories uncreated ("no such table"). So always apply the
        # terminal tables explicitly afterward, independent of the big script.
        try:
            schema_path = Path(__file__).parent / "sql" / "calibration_schema.sql"
            if schema_path.exists():
                await self._conn.executescript(schema_path.read_text(encoding="utf-8"))
                await self._conn.commit()
        except Exception as e:
            logger.debug(f"[TerminalAdvisory] full-schema bootstrap skipped: {e}")

        try:
            await self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS terminal_advisories (
                    advisory_id          TEXT PRIMARY KEY,
                    building_id          TEXT NOT NULL DEFAULT 'default',
                    equipment_id         TEXT,
                    advisory_type        TEXT NOT NULL,
                    severity             TEXT NOT NULL,
                    title                TEXT NOT NULL,
                    message              TEXT NOT NULL,
                    evidence_ids         TEXT NOT NULL DEFAULT '[]',
                    confidence           REAL NOT NULL DEFAULT 0.5,
                    fired_at             TEXT NOT NULL,
                    sim_day              INTEGER,
                    last_surfaced_at     TEXT NOT NULL,
                    surface_count        INTEGER NOT NULL DEFAULT 1,
                    state                TEXT NOT NULL DEFAULT 'active',
                    acknowledged_at      TEXT,
                    acknowledged_by      TEXT,
                    ack_signal           TEXT,
                    resolved_at          TEXT,
                    resolution_action    TEXT,
                    escalated_at         TEXT,
                    escalation_target    TEXT,
                    source_plan_id       TEXT,
                    source_query         TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_terminal_state ON terminal_advisories(building_id, state, fired_at);
                CREATE INDEX IF NOT EXISTS idx_terminal_eq    ON terminal_advisories(equipment_id, state);
                CREATE TABLE IF NOT EXISTS terminal_advisory_events (
                    event_id         TEXT PRIMARY KEY,
                    advisory_id      TEXT NOT NULL,
                    event_type       TEXT NOT NULL,
                    event_at         TEXT NOT NULL,
                    actor            TEXT,
                    details          TEXT,
                    FOREIGN KEY (advisory_id) REFERENCES terminal_advisories(advisory_id)
                );
                CREATE INDEX IF NOT EXISTS idx_terminal_events ON terminal_advisory_events(advisory_id, event_at);
                """
            )
            await self._conn.commit()
        except Exception as e:
            logger.error(f"[TerminalAdvisory] table create failed: {e}")
        return self._conn

    # ── fire ───────────────────────────────────────────────────────────

    async def fire(
        self,
        *,
        building_id: str = "default",
        equipment_id: Optional[str] = None,
        advisory_type: str,
        severity: str,
        title: str,
        message: str,
        evidence_ids: Optional[List[str]] = None,
        confidence: float = 0.7,
        sim_day: Optional[int] = None,
        source_plan_id: Optional[str] = None,
        source_query: Optional[str] = None,
        dedupe_window_hours: int = 24,
    ) -> Optional[str]:
        """
        Fire a new terminal advisory. Returns advisory_id, or existing ID if a
        matching (equipment_id, advisory_type) advisory is already ACTIVE within
        the dedupe window (prevents duplicate surfacing).
        """
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        # Dedupe: if same equipment+type is ACTIVE within window, bump surface_count instead
        if equipment_id and advisory_type:
            since = (datetime.now(timezone.utc) - timedelta(hours=dedupe_window_hours)).isoformat()
            async with conn.execute(
                """
                SELECT advisory_id FROM terminal_advisories
                WHERE building_id = ? AND equipment_id = ? AND advisory_type = ?
                  AND state = 'active' AND fired_at >= ?
                ORDER BY fired_at DESC LIMIT 1
                """,
                (building_id, equipment_id, advisory_type, since),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    existing_id = row["advisory_id"]
                    await conn.execute(
                        """
                        UPDATE terminal_advisories
                        SET surface_count = surface_count + 1,
                            last_surfaced_at = ?,
                            message = ?
                        WHERE advisory_id = ?
                        """,
                        (now, message, existing_id),
                    )
                    await self._log_event(conn, existing_id, "surfaced",
                                          actor="queen", details={"reason": "dedupe_bump"})
                    await conn.commit()
                    logger.info(f"[TerminalAdvisory] DEDUPE bump on {existing_id} (eq={equipment_id} type={advisory_type})")
                    return existing_id

        # Fresh fire
        advisory_id = f"term_{uuid.uuid4().hex[:12]}"
        try:
            await conn.execute(
                """
                INSERT INTO terminal_advisories (
                    advisory_id, building_id, equipment_id, advisory_type, severity,
                    title, message, evidence_ids, confidence, fired_at, sim_day,
                    last_surfaced_at, surface_count, state,
                    source_plan_id, source_query
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    advisory_id, building_id, equipment_id, advisory_type, severity,
                    title, message, json.dumps(evidence_ids or []), float(confidence),
                    now, sim_day, now, 1,
                    source_plan_id, (source_query or "")[:500],
                ),
            )
            await self._log_event(conn, advisory_id, "fired",
                                  actor="queen",
                                  details={"severity": severity, "type": advisory_type,
                                           "confidence": confidence})
            await conn.commit()
            logger.warning(
                f"[TerminalAdvisory] FIRED {advisory_id} eq={equipment_id} "
                f"type={advisory_type} severity={severity} conf={confidence:.2f}"
            )
            return advisory_id
        except Exception as e:
            logger.error(f"[TerminalAdvisory] fire failed: {e}")
            return None

    # ── retrieve ───────────────────────────────────────────────────────

    async def list_active(self, building_id: str = "default", limit: int = 20) -> List[TerminalAdvisory]:
        """Return all ACTIVE advisories for the building, newest first."""
        conn = await self._get_conn()
        try:
            async with conn.execute(
                """
                SELECT * FROM terminal_advisories
                WHERE building_id = ? AND state = 'active'
                ORDER BY fired_at DESC LIMIT ?
                """,
                (building_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_advisory(r) for r in rows]
        except Exception as e:
            logger.error(f"[TerminalAdvisory] list_active failed: {e}")
            return []

    async def get(self, advisory_id: str) -> Optional[TerminalAdvisory]:
        conn = await self._get_conn()
        async with conn.execute(
            "SELECT * FROM terminal_advisories WHERE advisory_id = ?",
            (advisory_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_advisory(row) if row else None

    # ── surface tracking (called every turn) ──────────────────────────

    async def mark_surfaced(self, advisory_ids: List[str]) -> None:
        """Bump surface_count + last_surfaced_at on each advisory injected
        into the current turn's context."""
        if not advisory_ids:
            return
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            placeholders = ",".join("?" * len(advisory_ids))
            await conn.execute(
                f"""
                UPDATE terminal_advisories
                SET surface_count = surface_count + 1,
                    last_surfaced_at = ?
                WHERE advisory_id IN ({placeholders}) AND state = 'active'
                """,
                (now,) + tuple(advisory_ids),
            )
            await conn.commit()
        except Exception as e:
            logger.debug(f"[TerminalAdvisory] mark_surfaced failed: {e}")

    # ── acknowledgement ───────────────────────────────────────────────

    async def acknowledge_from_query(
        self,
        building_id: str,
        query: str,
        operator_id: str = "default",
    ) -> List[str]:
        """
        Scan operator query for acknowledgment language. If matched, ACK all
        currently-active advisories. Returns list of acknowledged IDs.

        Aggressive — if operator says "noted, scheduling techs", every active
        advisory at that moment is considered acknowledged. Tightening this to
        per-advisory ack requires explicit IDs in the query (rare in chat).
        """
        ack_phrase = _is_acknowledgment(query)
        if not ack_phrase:
            return []
        actives = await self.list_active(building_id)
        if not actives:
            return []
        acked: List[str] = []
        for adv in actives:
            ok = await self.acknowledge(adv.advisory_id, operator_id, ack_phrase)
            if ok:
                acked.append(adv.advisory_id)
        return acked

    async def acknowledge(
        self,
        advisory_id: str,
        operator_id: str,
        ack_signal: str,
    ) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = await conn.execute(
                """
                UPDATE terminal_advisories
                SET state = 'acknowledged',
                    acknowledged_at = ?,
                    acknowledged_by = ?,
                    ack_signal = ?
                WHERE advisory_id = ? AND state = 'active'
                """,
                (now, operator_id, ack_signal[:200], advisory_id),
            )
            await self._log_event(conn, advisory_id, "acknowledged",
                                  actor=operator_id, details={"signal": ack_signal[:200]})
            await conn.commit()
            success = (cursor.rowcount or 0) > 0
            if success:
                logger.info(f"[TerminalAdvisory] ACK {advisory_id} by {operator_id} via '{ack_signal[:60]}'")
            return success
        except Exception as e:
            logger.error(f"[TerminalAdvisory] acknowledge failed: {e}")
            return False

    async def resolve(self, advisory_id: str, action_text: str) -> bool:
        conn = await self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        try:
            cursor = await conn.execute(
                """
                UPDATE terminal_advisories
                SET state = 'resolved',
                    resolved_at = ?,
                    resolution_action = ?
                WHERE advisory_id = ? AND state IN ('active', 'acknowledged')
                """,
                (now, action_text[:500], advisory_id),
            )
            await self._log_event(conn, advisory_id, "resolved",
                                  actor="operator", details={"action": action_text[:300]})
            await conn.commit()
            return (cursor.rowcount or 0) > 0
        except Exception as e:
            logger.error(f"[TerminalAdvisory] resolve failed: {e}")
            return False

    # ── escalation ─────────────────────────────────────────────────────

    async def escalate_overdue(
        self,
        threshold_hours: float = 4.0,
        building_id: str = "default",
    ) -> List[str]:
        """
        Find ACTIVE advisories that have been unacknowledged > threshold_hours.
        Mark escalated_at + log event. Returns list of escalated IDs.

        In production this would trigger SMS / email. For Marina pilot it just
        records the event so test harness can verify the chain fired.
        """
        conn = await self._get_conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=threshold_hours)).isoformat()
        escalated: List[str] = []
        try:
            async with conn.execute(
                """
                SELECT advisory_id, equipment_id, severity, title
                FROM terminal_advisories
                WHERE building_id = ? AND state = 'active'
                  AND escalated_at IS NULL
                  AND fired_at <= ?
                """,
                (building_id, cutoff),
            ) as cursor:
                rows = await cursor.fetchall()

            now = datetime.now(timezone.utc).isoformat()
            for r in rows:
                aid = r["advisory_id"]
                target = self._pick_escalation_target(r["severity"], r["equipment_id"])
                await conn.execute(
                    """
                    UPDATE terminal_advisories
                    SET escalated_at = ?, escalation_target = ?
                    WHERE advisory_id = ?
                    """,
                    (now, target, aid),
                )
                await self._log_event(conn, aid, "escalated",
                                      actor="auto_escalator",
                                      details={"target": target,
                                               "threshold_hours": threshold_hours})
                escalated.append(aid)
                logger.warning(
                    f"[TerminalAdvisory] ESCALATED {aid} ({r['title']}) → {target} "
                    f"after {threshold_hours}h unacknowledged"
                )
            if escalated:
                await conn.commit()
        except Exception as e:
            logger.error(f"[TerminalAdvisory] escalate_overdue failed: {e}")
        return escalated

    @staticmethod
    def _pick_escalation_target(severity: str, equipment_id: Optional[str]) -> str:
        s = (severity or "").lower()
        if s == "critical":
            return "asset_owner_sms"
        if s in ("severe", "high"):
            return "fm_lead_email"
        return "ops_log"

    # ── helpers ────────────────────────────────────────────────────────

    async def _log_event(
        self,
        conn: aiosqlite.Connection,
        advisory_id: str,
        event_type: str,
        actor: str = "system",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            await conn.execute(
                """
                INSERT INTO terminal_advisory_events (
                    event_id, advisory_id, event_type, event_at, actor, details
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evt_{uuid.uuid4().hex[:12]}",
                    advisory_id,
                    event_type,
                    datetime.now(timezone.utc).isoformat(),
                    actor,
                    json.dumps(details or {}),
                ),
            )
        except Exception as e:
            logger.debug(f"[TerminalAdvisory] log_event failed: {e}")

    @staticmethod
    def _row_to_advisory(row: Any) -> TerminalAdvisory:
        ev_ids: List[str] = []
        try:
            ev_ids = json.loads(row["evidence_ids"] or "[]")
        except Exception:
            ev_ids = []
        return TerminalAdvisory(
            advisory_id=row["advisory_id"],
            building_id=row["building_id"],
            equipment_id=row["equipment_id"],
            advisory_type=row["advisory_type"],
            severity=row["severity"],
            title=row["title"],
            message=row["message"],
            evidence_ids=ev_ids,
            confidence=float(row["confidence"]),
            fired_at=row["fired_at"],
            sim_day=row["sim_day"],
            last_surfaced_at=row["last_surfaced_at"],
            surface_count=int(row["surface_count"]),
            state=row["state"],
            acknowledged_at=row["acknowledged_at"],
            acknowledged_by=row["acknowledged_by"],
            ack_signal=row["ack_signal"],
            resolved_at=row["resolved_at"],
            resolution_action=row["resolution_action"],
            escalated_at=row["escalated_at"],
            escalation_target=row["escalation_target"],
            source_plan_id=row["source_plan_id"],
            source_query=row["source_query"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Synthesis output → terminal advisory detector
# ─────────────────────────────────────────────────────────────────────────────

def detect_terminal_advisories(
    synthesis_json_text: str,
    plan_id: Optional[str] = None,
    source_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Parse Queen synthesis output (JSON string). Return list of advisory dicts
    that meet terminal criteria — caller passes each to store.fire().

    Criteria:
      - severity in {critical, severe, high}
      - type in _TERMINAL_TYPES OR message contains terminal-grade keywords
      - confidence >= 0.5

    Returns empty list if no terminals found.
    """
    if not synthesis_json_text:
        return []
    try:
        data = json.loads(synthesis_json_text)
    except Exception:
        return []

    advisories = data.get("advisories") or []
    if not isinstance(advisories, list):
        return []

    terminals: List[Dict[str, Any]] = []
    for adv in advisories:
        if not isinstance(adv, dict):
            continue
        sev = str(adv.get("severity", "")).lower()
        atype = str(adv.get("type", "")).lower()
        conf = float(adv.get("confidence", 0.0) or 0.0)
        msg = str(adv.get("message", ""))
        eq_id = adv.get("equipment_id") or _extract_equipment_id(msg, adv.get("id", ""))

        # Filter: severity + type or content
        if sev not in _HIGH_SEVERITIES:
            continue
        if conf < 0.5:
            continue
        type_ok = atype in _TERMINAL_TYPES
        content_ok = any(kw in msg.lower() for kw in [
            "imminent failure", "predicted to fail", "remaining useful life",
            "rul ", "bearing degradation", "thermal runaway", "refrigerant leak",
            "compressor lock", "evacuat", "fire alarm", "safety violation",
            "regulatory non-compliance", "gsas violation",
        ])
        if not (type_ok or content_ok):
            continue

        terminals.append({
            "equipment_id": eq_id,
            "advisory_type": atype if type_ok else _infer_type(msg),
            "severity": sev,
            "title": _make_title(adv, eq_id),
            "message": msg[:2000],
            "evidence_ids": list(adv.get("evidence_ids") or [])[:20],
            "confidence": conf,
            "source_plan_id": plan_id,
            "source_query": source_query,
        })

    return terminals


def _extract_equipment_id(message: str, fallback_id: str = "") -> Optional[str]:
    """Try to pull equipment ID from message text using common BMS patterns."""
    if not message:
        return fallback_id or None
    patterns = [
        r"\b(CH-\d{1,3})\b",
        r"\b(AHU-\d{1,3}[A-Z]?)\b",
        r"\b(VAV-\d{1,3}[A-Z]?)\b",
        r"\b(FCU-\d{1,3}[A-Z]?)\b",
        r"\b(CT-\d{1,3})\b",
        r"\b(CHWP-\d{1,3})\b",
        r"\b(FLOOR-\d{1,3})\b",
        r"\b(ZONE-\d{1,3}[A-Z]?)\b",
    ]
    for p in patterns:
        m = re.search(p, message, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return fallback_id or None


def _infer_type(message: str) -> str:
    m = message.lower()
    if any(k in m for k in ("fire", "smoke", "evacuat", "life", "safety")):
        return "life_safety"
    if any(k in m for k in ("bearing", "fail", "rul", "predicted")):
        return "predictive_failure"
    if any(k in m for k in ("gsas", "compliance", "regulat")):
        return "compliance_breach"
    if any(k in m for k in ("refrigerant", "leak", "physics")):
        return "physics_violation"
    return "equipment_failure"


def _make_title(adv: Dict[str, Any], eq_id: Optional[str]) -> str:
    """Build a short title for the advisory."""
    given = str(adv.get("title") or "").strip()
    if given:
        return given[:160]
    atype = str(adv.get("type", "advisory"))
    sev = str(adv.get("severity", "")).upper()
    if eq_id:
        return f"{sev} {atype} on {eq_id}"[:160]
    return f"{sev} {atype}"[:160]
