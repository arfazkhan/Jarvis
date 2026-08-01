"""
Compiled Skill Registry
=======================

Maps equipment → compiled-skill directory, with source-hash for freshness and
status from the grounding gate. Lives in the same SQLite DB as the learned
skillbook (arvis_bms.db) so a single connection/back-up covers both, but the
compiled files themselves live on disk (see skill_writer). This is the join
between the static manual layer (files) and everything else.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("arvis.skills.registry")


@dataclass
class RegistryEntry:
    equipment_key: str
    skill_dir: str
    source_file: str
    source_hash: str
    version: int = 1
    status: str = "active"
    confidence: float = 0.0
    compiled_at: str = ""
    model: str = ""
    equipment_id: Optional[str] = None


def _default_db_path() -> str:
    env_db = os.getenv("ARVIS_DB_PATH", "").strip()
    if env_db:
        return env_db
    db_dir = Path(__file__).resolve().parent.parent / "data"
    db_dir.mkdir(exist_ok=True)
    return str(db_dir / "arvis_bms.db")


class SkillRegistry:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._ensure_table()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS compiled_skill (
                    equipment_key TEXT PRIMARY KEY,
                    equipment_id  TEXT,
                    skill_dir     TEXT NOT NULL,
                    source_file   TEXT NOT NULL,
                    source_hash   TEXT NOT NULL,
                    version       INTEGER DEFAULT 1,
                    status        TEXT DEFAULT 'active',
                    confidence    REAL DEFAULT 0.0,
                    compiled_at   TEXT,
                    model         TEXT
                )
                """
            )
            # Fleet sharing: many equipment instances → one compiled skill.
            # The compiled files are shared; each instance keeps its own learned
            # layer in the skillbook (keyed by equipment_id), so a shared manual
            # never blurs one instance's quirks into another's.
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_binding (
                    equipment_id  TEXT PRIMARY KEY,
                    equipment_key TEXT NOT NULL,
                    bound_at      TEXT
                )
                """
            )

    def upsert(self, e: RegistryEntry) -> None:
        with self._conn() as c:
            existing = c.execute(
                "SELECT version FROM compiled_skill WHERE equipment_key=?",
                (e.equipment_key,),
            ).fetchone()
            version = (existing["version"] + 1) if existing else e.version
            c.execute(
                """
                INSERT INTO compiled_skill
                    (equipment_key, equipment_id, skill_dir, source_file,
                     source_hash, version, status, confidence, compiled_at, model)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(equipment_key) DO UPDATE SET
                    equipment_id=excluded.equipment_id,
                    skill_dir=excluded.skill_dir,
                    source_file=excluded.source_file,
                    source_hash=excluded.source_hash,
                    version=excluded.version,
                    status=excluded.status,
                    confidence=excluded.confidence,
                    compiled_at=excluded.compiled_at,
                    model=excluded.model
                """,
                (e.equipment_key, e.equipment_id, e.skill_dir, e.source_file,
                 e.source_hash, version, e.status, e.confidence, e.compiled_at, e.model),
            )
        logger.info("Registry upsert %s (v%d, %s)", e.equipment_key, version, e.status)

    def get(self, equipment_key: str) -> Optional[RegistryEntry]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM compiled_skill WHERE equipment_key=?", (equipment_key,)
            ).fetchone()
        return self._row(row) if row else None

    def get_by_equipment_id(self, equipment_id: str) -> Optional[RegistryEntry]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM compiled_skill WHERE equipment_id=?", (equipment_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list_all(self) -> list[RegistryEntry]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM compiled_skill ORDER BY equipment_key").fetchall()
        return [self._row(r) for r in rows]

    def is_stale(self, equipment_key: str, current_hash: str) -> bool:
        """True if the source file hash differs from the compiled record —
        signals the skill needs recompilation."""
        entry = self.get(equipment_key)
        return entry is not None and entry.source_hash != current_hash

    def bind_equipment(self, equipment_key: str, equipment_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE compiled_skill SET equipment_id=? WHERE equipment_key=?",
                (equipment_id, equipment_key),
            )

    # ---- fleet bindings (many instances → one compiled skill) -------------

    def bind_instance(self, equipment_id: str, equipment_key: str) -> None:
        """Bind an equipment instance to a shared compiled skill."""
        from datetime import datetime
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO skill_binding (equipment_id, equipment_key, bound_at)
                VALUES (?,?,?)
                ON CONFLICT(equipment_id) DO UPDATE SET
                    equipment_key=excluded.equipment_key,
                    bound_at=excluded.bound_at
                """,
                (equipment_id.strip(), equipment_key.strip(),
                 datetime.now().isoformat(timespec="seconds")),
            )
        logger.info("Fleet-bound %s → %s", equipment_id, equipment_key)

    def bind_fleet(self, equipment_key: str, equipment_ids: list[str]) -> int:
        for eid in equipment_ids:
            self.bind_instance(eid, equipment_key)
        return len(equipment_ids)

    def resolve_instance(self, equipment_id: str) -> Optional[str]:
        """Return the compiled skill key an instance is fleet-bound to, if any."""
        with self._conn() as c:
            row = c.execute(
                "SELECT equipment_key FROM skill_binding WHERE equipment_id=?",
                (equipment_id.strip(),),
            ).fetchone()
        return row["equipment_key"] if row else None

    def list_fleet(self, equipment_key: str) -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT equipment_id FROM skill_binding WHERE equipment_key=? ORDER BY equipment_id",
                (equipment_key.strip(),),
            ).fetchall()
        return [r["equipment_id"] for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> RegistryEntry:
        return RegistryEntry(
            equipment_key=row["equipment_key"],
            equipment_id=row["equipment_id"],
            skill_dir=row["skill_dir"],
            source_file=row["source_file"],
            source_hash=row["source_hash"],
            version=row["version"],
            status=row["status"],
            confidence=row["confidence"],
            compiled_at=row["compiled_at"],
            model=row["model"],
        )
