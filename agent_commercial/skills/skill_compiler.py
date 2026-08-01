"""
Skill Compiler
==============

Orchestrator for the manual→skill pipeline. Ties the four stages together:

    extract (M1)  →  analyze (M2)  →  ground (M3)  →  write files + registry (M4)

Produces an on-disk compiled skill:

    data/skills/<equipment_key>/
        SKILL.md          core: frameworks, critical params, chapter index, anti-patterns
        chapters/*.md     per functional area
        patterns.md       named fault patterns
        glossary.md       terms + ranges
        cheatsheet.md     symptom → check → do
        meta.json         source hash, pages, model, confidence, grounding report

and a compiled_skill registry row linking equipment_key → dir + hash + status.

Compilation is a batch job (minutes for a full manual). It is best run offline /
via the manuals watcher, not on a request path.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_commercial.skills.manual_extractor import ManualExtractor, ExtractedManual
from agent_commercial.skills.skill_analyzer import SkillAnalyzer, CompiledSkill
from agent_commercial.skills.skill_grounding import SkillGroundingGate, GroundingReport
from agent_commercial.skills.skill_registry import SkillRegistry, RegistryEntry

logger = logging.getLogger("arvis.skills.compiler")


def _skills_root() -> Path:
    root = Path(__file__).resolve().parent.parent / "data" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "equipment"


class CompileResult:
    def __init__(self, equipment_key: str, skill_dir: Path,
                 grounding: GroundingReport, extracted: ExtractedManual,
                 skill: CompiledSkill) -> None:
        self.equipment_key = equipment_key
        self.skill_dir = skill_dir
        self.grounding = grounding
        self.extracted = extracted
        self.skill = skill

    def summary(self) -> dict:
        return {
            "equipment_key": self.equipment_key,
            "skill_dir": str(self.skill_dir),
            "status": self.grounding.status,
            "confidence": round(self.grounding.confidence, 3),
            "grounded_items": self.grounding.grounded_items,
            "total_items": self.grounding.total_items,
            "extraction": self.extracted.summary(),
        }


class SkillCompiler:
    def __init__(
        self,
        extractor: Optional[ManualExtractor] = None,
        analyzer: Optional[SkillAnalyzer] = None,
        gate: Optional[SkillGroundingGate] = None,
        registry: Optional[SkillRegistry] = None,
    ) -> None:
        self.extractor = extractor or ManualExtractor()
        self.analyzer = analyzer or SkillAnalyzer()
        self.gate = gate or SkillGroundingGate(strict=True)
        self.registry = registry or SkillRegistry()

    def compile_manual(
        self,
        pdf_path: str,
        equipment_name: str,
        equipment_id: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> CompileResult:
        equipment_key = slugify(equipment_name)
        logger.info("Compiling %s from %s", equipment_key, pdf_path)

        # M1 extract
        extracted = self.extractor.extract(pdf_path, max_pages=max_pages)
        page_text_by_no = {p.page_no: p.text for p in extracted.pages}

        # M2 analyze
        skill = self.analyzer.analyze(equipment_name, extracted.page_marked_text())

        # M3 ground (prunes uncited/unsupported, sets status + confidence)
        grounding = self.gate.check(skill, extracted.page_count, page_text_by_no)

        # M4 write files + registry
        skill_dir = _skills_root() / equipment_key
        self._write_skill_files(skill_dir, equipment_name, skill, extracted, grounding)
        self.registry.upsert(RegistryEntry(
            equipment_key=equipment_key,
            equipment_id=equipment_id,
            skill_dir=str(skill_dir),
            source_file=str(Path(pdf_path).resolve()),
            source_hash=extracted.source_hash,
            status=grounding.status,
            confidence=grounding.confidence,
            compiled_at=datetime.now().isoformat(timespec="seconds"),
            model=skill.model,
        ))

        result = CompileResult(equipment_key, skill_dir, grounding, extracted, skill)
        logger.info("Compiled %s: %s", equipment_key, result.summary())
        return result

    # ---- file rendering ---------------------------------------------------

    def _write_skill_files(
        self, skill_dir: Path, equipment_name: str, skill: CompiledSkill,
        extracted: ExtractedManual, grounding: GroundingReport,
    ) -> None:
        chapters_dir = skill_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        (skill_dir / "SKILL.md").write_text(
            self._render_skill_md(equipment_name, skill, grounding), encoding="utf-8")
        for topic, body in skill.chapters.items():
            (chapters_dir / f"{topic}.md").write_text(body, encoding="utf-8")
        (skill_dir / "patterns.md").write_text(
            self._render_patterns(skill), encoding="utf-8")
        (skill_dir / "glossary.md").write_text(
            self._render_glossary(skill), encoding="utf-8")
        (skill_dir / "cheatsheet.md").write_text(
            self._render_cheatsheet(skill), encoding="utf-8")
        (skill_dir / "meta.json").write_text(json.dumps({
            "equipment_name": equipment_name,
            "source_file": extracted.source_file,
            "source_hash": extracted.source_hash,
            "page_count": extracted.page_count,
            "model": skill.model,
            "compiled_at": datetime.now().isoformat(timespec="seconds"),
            "grounding": grounding.to_dict(),
            "extraction": extracted.summary(),
        }, indent=2), encoding="utf-8")

    def _render_skill_md(self, name: str, skill: CompiledSkill, g: GroundingReport) -> str:
        lines = [f"# {name} — Compiled Skill", ""]
        lines.append(f"> status: **{g.status}** · grounding confidence: "
                     f"{g.confidence:.2f} · {g.grounded_items}/{g.total_items} items cited")
        lines.append("")
        lines.append("## Named Fault Frameworks")
        if skill.frameworks:
            for f in skill.frameworks:
                lines.append(f"- **{f.name}** — {f.description} "
                             f"_(applies: {f.when_applies}; pages {f.source_pages})_")
        else:
            lines.append("- _(none extracted with citations)_")
        lines.append("")
        lines.append("## Critical Parameters")
        if skill.critical_parameters:
            for p in skill.critical_parameters:
                lines.append(f"- **{p.name}**: normal {p.normal_range} — "
                             f"deviation: {p.deviation_implication} _(pages {p.source_pages})_")
        else:
            lines.append("- _(none)_")
        lines.append("")
        lines.append("## Chapter Index")
        for topic in skill.chapters:
            lines.append(f"- `{topic}` → chapters/{topic}.md")
        if not skill.chapters:
            lines.append("- _(no chapters)_")
        lines.append("")
        lines.append("## Key Anti-Patterns")
        if skill.anti_patterns:
            for a in skill.anti_patterns:
                lines.append(f"- ⚠️ {a.warning} → {a.consequence} _(pages {a.source_pages})_")
        else:
            lines.append("- _(none)_")
        lines.append("")
        return "\n".join(lines)

    def _render_patterns(self, skill: CompiledSkill) -> str:
        lines = ["# Fault Patterns", ""]
        if not skill.fault_patterns:
            lines.append("_(none extracted with citations)_")
        for fp in skill.fault_patterns:
            lines.append(f"## {fp.name}")
            lines.append(f"- **Symptom:** {fp.symptom_signature}")
            lines.append(f"- **Diagnose:** {fp.diagnostic_steps}")
            lines.append(f"- **Root cause:** {fp.root_cause}")
            lines.append(f"- **Resolution:** {fp.resolution}")
            lines.append(f"- _pages: {fp.source_pages}_")
            lines.append("")
        return "\n".join(lines)

    def _render_glossary(self, skill: CompiledSkill) -> str:
        lines = ["# Glossary", ""]
        if not skill.glossary:
            lines.append("_(none)_")
        for term, definition in sorted(skill.glossary.items()):
            lines.append(f"- **{term}**: {definition}")
        return "\n".join(lines)

    def _render_cheatsheet(self, skill: CompiledSkill) -> str:
        lines = ["# Cheatsheet — symptom → check → do", ""]
        if not skill.decision_rules:
            lines.append("_(none)_")
        for r in skill.decision_rules:
            lines.append(f"- IF {r.condition} → {r.action} _(pages {r.source_pages})_")
        return "\n".join(lines)
