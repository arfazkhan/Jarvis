"""
Compiled-Skill Tool Handler
==========================

Executes load_equipment_skill: resolves an equipment to its compiled skill via
the registry and returns the SKILL.md core plus an optional chapter, read from
disk. Read-only and cheap. Degrades gracefully: if no skill is compiled for the
equipment, returns the list of available skills rather than erroring hard.
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("arvis.bms.tools.skills")


class SkillsHandlerMixin:
    """Mixin providing compiled-skill runtime access tools."""

    def get_handlers(self) -> Dict[str, Any]:
        return {
            "load_equipment_skill": self._handle_load_equipment_skill,
            "investigate_with_skills": self._handle_investigate_with_skills,
        }

    async def _handle_investigate_with_skills(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from agent_commercial.skills.skill_router import SkillRouter
        except Exception as e:
            return {"error": f"Skill router unavailable: {e}"}

        # Reuse the handler's live skillbook if present. Only overlay learned
        # skills when we have an already-initialized skillbook — never cold-load
        # ML models on the request path (would blow the 5s tool timeout).
        skillbook = getattr(self, "skillbook", None)
        has_learned = skillbook is not None and hasattr(skillbook, "get_relevant_skills")
        graph = getattr(self, "graph", None)
        router = SkillRouter(skillbook=skillbook if has_learned else None, graph=graph)
        try:
            result = await router.route(
                equipment_key=(args.get("equipment_key") or "").strip(),
                equipment_id=(args.get("equipment_id") or "").strip(),
                alarm_type=(args.get("alarm_type") or "").strip(),
                query=(args.get("query") or "").strip(),
                overlay_learned=has_learned,
            )
        except Exception as e:
            return {"error": f"Investigation routing failed: {e}"}
        return result.to_dict()

    async def _handle_load_equipment_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        equipment_key = (args.get("equipment_key") or "").strip()
        equipment_id = (args.get("equipment_id") or "").strip()
        topic = (args.get("topic") or "").strip()

        try:
            from agent_commercial.skills.skill_registry import SkillRegistry
        except Exception as e:
            return {"error": f"Skill registry unavailable: {e}"}

        registry = SkillRegistry()

        entry = None
        if equipment_key:
            entry = registry.get(equipment_key)
        if entry is None and equipment_id:
            entry = registry.get_by_equipment_id(equipment_id)

        if entry is None:
            available = [
                {"equipment_key": e.equipment_key, "status": e.status,
                 "confidence": e.confidence, "equipment_id": e.equipment_id}
                for e in registry.list_all()
            ]
            return {
                "error": (
                    "No compiled skill found for the requested equipment. "
                    "Pick one of available_skills, or the manual has not been compiled yet."
                ),
                "available_skills": available,
            }

        skill_dir = Path(entry.skill_dir)
        skill_md = self._read(skill_dir / "SKILL.md")
        if skill_md is None:
            return {"error": f"Compiled skill files missing at {skill_dir}",
                    "equipment_key": entry.equipment_key}

        chapter_text = ""
        if topic:
            chapter_text = self._read(skill_dir / "chapters" / f"{topic}.md") or ""
            if not chapter_text:
                # fall back to patterns.md for fault topics, else note absence
                if topic == "fault-codes":
                    chapter_text = self._read(skill_dir / "patterns.md") or ""
                if not chapter_text:
                    chapter_text = f"(no '{topic}' chapter compiled for this equipment)"

        return {
            "equipment_key": entry.equipment_key,
            "status": entry.status,
            "confidence": entry.confidence,
            "skill_core": skill_md,
            "chapter": chapter_text,
            "source_file": entry.source_file,
            "available_skills": [],
        }

    @staticmethod
    def _read(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
