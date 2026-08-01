"""
Skill Freshness
===============

Phase-3 recompile-on-change. Equipment manuals are revised, replaced, or
re-scanned; a compiled skill built from an old file is stale. This module
detects staleness by comparing the current source-file hash against the hash
recorded at compile time, and recompiles stale skills.

Preservation guarantee: recompilation only overwrites the on-disk compiled files
(SKILL.md, chapters, patterns, …) and bumps the registry version. The building's
LEARNED knowledge lives in the skillbook (a separate store, keyed by
equipment_id) and fleet bindings live in a separate table — neither is touched
by a recompile. So a manual update refreshes the manufacturer lens without
losing this building's accumulated experience.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from agent_commercial.skills.skill_registry import SkillRegistry, RegistryEntry

logger = logging.getLogger("arvis.skills.freshness")


@dataclass
class FreshnessRecord:
    equipment_key: str
    source_file: str
    source_exists: bool
    stale: bool
    recorded_hash: str
    current_hash: Optional[str]
    reason: str

    def to_dict(self) -> dict:
        return {
            "equipment_key": self.equipment_key,
            "source_file": self.source_file,
            "source_exists": self.source_exists,
            "stale": self.stale,
            "recorded_hash": self.recorded_hash[:12],
            "current_hash": (self.current_hash or "")[:12],
            "reason": self.reason,
        }


class SkillFreshness:
    def __init__(self, registry: Optional[SkillRegistry] = None, compiler=None) -> None:
        self.registry = registry or SkillRegistry()
        self._compiler = compiler  # lazy — only needed for recompile

    def scan(self) -> list[FreshnessRecord]:
        """Check every compiled skill's source file against its recorded hash."""
        records: list[FreshnessRecord] = []
        for e in self.registry.list_all():
            src = Path(e.source_file)
            if not src.exists():
                records.append(FreshnessRecord(
                    e.equipment_key, e.source_file, False, False,
                    e.source_hash, None, "source file missing (cannot verify)"))
                continue
            current = self._hash_file(src)
            stale = current != e.source_hash
            records.append(FreshnessRecord(
                e.equipment_key, e.source_file, True, stale,
                e.source_hash, current,
                "source changed since compile" if stale else "up to date"))
        return records

    def stale_keys(self) -> list[str]:
        return [r.equipment_key for r in self.scan() if r.stale]

    def recompile_stale(self, max_pages: Optional[int] = None) -> list[dict]:
        """Recompile every stale skill. Returns per-skill compile summaries."""
        results = []
        for rec in self.scan():
            if not rec.stale:
                continue
            summary = self._recompile_one(rec.equipment_key, max_pages=max_pages)
            results.append(summary)
        return results

    def _recompile_one(self, equipment_key: str, max_pages: Optional[int] = None) -> dict:
        entry = self.registry.get(equipment_key)
        if entry is None:
            return {"equipment_key": equipment_key, "error": "not in registry"}
        # equipment_name comes from meta.json (needed for a faithful re-slug);
        # fall back to the key if meta is unavailable.
        equipment_name = self._equipment_name(entry) or equipment_key
        compiler = self._get_compiler()
        if compiler is None:
            return {"equipment_key": equipment_key, "error": "compiler unavailable"}
        try:
            res = compiler.compile_manual(
                entry.source_file, equipment_name,
                equipment_id=entry.equipment_id, max_pages=max_pages)
            logger.info("Recompiled %s (v bumped, learned layer preserved)", equipment_key)
            return res.summary()
        except Exception as e:
            logger.warning("Recompile failed for %s: %s", equipment_key, e)
            return {"equipment_key": equipment_key, "error": str(e)}

    def _equipment_name(self, entry: RegistryEntry) -> Optional[str]:
        try:
            meta = json.loads((Path(entry.skill_dir) / "meta.json").read_text(encoding="utf-8"))
            return meta.get("equipment_name")
        except Exception:
            return None

    def _get_compiler(self):
        if self._compiler is None:
            try:
                from agent_commercial.skills.skill_compiler import SkillCompiler
                self._compiler = SkillCompiler(registry=self.registry)
            except Exception as e:
                logger.debug("Compiler init failed: %s", e)
                self._compiler = False
        return self._compiler or None

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
