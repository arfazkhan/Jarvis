"""
Ingestion Watcher Service
=========================
Watches data/manuals/ for new PDF/Markdown files and triggers ManualIngester
automatically. Files are processed once and moved to data/manuals/processed/.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("arvis.services.ingestion_watcher")

WATCH_DIR = Path(__file__).parent.parent / "data" / "manuals"
PROCESSED_DIR = WATCH_DIR / "processed"
POLL_INTERVAL = 10  # seconds


class IngestionWatcher:
    """
    Background service that polls WATCH_DIR for new documents and ingests them.
    Call start() once during app startup; it runs as an asyncio task.
    """

    def __init__(self, knowledge_base=None, poll_interval: int = POLL_INTERVAL,
                 compile_skills: bool = True):
        self._kb = knowledge_base
        self._poll_interval = poll_interval
        # Also compile dropped PDF manuals into CBI skills (manual→skill pipeline).
        self._compile_skills = compile_skills
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> asyncio.Task:
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._watch_loop(), name="ingestion_watcher")
        logger.info(f"[IngestionWatcher] Started — watching {WATCH_DIR}")
        # One-shot: recompile any compiled skills whose source manual changed.
        if self._compile_skills:
            asyncio.create_task(self._startup_freshness(), name="skill_freshness_startup")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _watch_loop(self) -> None:
        while self._running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[IngestionWatcher] Scan error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _scan_once(self) -> None:
        candidates = [
            p for p in WATCH_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".md", ".markdown")
        ]
        for path in candidates:
            await self._ingest_file(path)

    async def _ingest_file(self, path: Path) -> None:
        logger.info(f"[IngestionWatcher] Ingesting: {path.name}")
        try:
            from agent_advisory.manual_ingester import ManualIngester
            from agent_advisory.knowledge_base import TechnicalKnowledgeBase
            kb = self._kb or TechnicalKnowledgeBase()
            ingester = ManualIngester(kb)
            if path.suffix.lower() == ".pdf":
                result = await ingester.ingest_pdf(str(path))
            else:
                result = await ingester.ingest_markdown(str(path))
            logger.info(
                f"[IngestionWatcher] Indexed {getattr(result, 'nodes_indexed', '?')} "
                f"chunks from '{path.name}'"
            )
            # Move to processed/ to avoid re-ingestion
            dest = PROCESSED_DIR / path.name
            path.rename(dest)
            logger.info(f"[IngestionWatcher] Moved '{path.name}' → processed/")

            # CBI: compile PDF manuals into a source-cited skill. Runs in a
            # background thread (compile is minutes-long OCR+LLM) from the stable
            # processed/ path so the registry source_file stays valid for
            # freshness checks. Best-effort — never blocks or fails ingestion.
            if self._compile_skills and dest.suffix.lower() == ".pdf":
                asyncio.create_task(
                    self._compile_skill_bg(dest),
                    name=f"skill_compile:{dest.stem}")
        except Exception as e:
            logger.error(f"[IngestionWatcher] Failed to ingest '{path.name}': {e}")

    async def _compile_skill_bg(self, pdf_path: Path) -> None:
        """Compile a manual PDF into a CBI skill off the event loop."""
        equipment_name = self._equipment_name_from_file(pdf_path)
        try:
            from agent_commercial.skills.skill_compiler import SkillCompiler
            compiler = SkillCompiler()
            if not getattr(compiler.analyzer, "available", False):
                logger.info(
                    "[IngestionWatcher] Skill compile skipped for '%s' — no compile "
                    "LLM key configured.", pdf_path.name)
                return
            result = await asyncio.to_thread(
                compiler.compile_manual, str(pdf_path), equipment_name)
            logger.info("[IngestionWatcher] Compiled skill '%s': %s",
                        equipment_name, result.summary())
        except Exception as e:
            logger.error("[IngestionWatcher] Skill compile failed for '%s': %s",
                         pdf_path.name, e)

    async def _startup_freshness(self) -> None:
        """Recompile any compiled skills whose source manual has changed."""
        try:
            from agent_commercial.skills.skill_freshness import SkillFreshness
            fresh = SkillFreshness()
            stale = fresh.stale_keys()
            if not stale:
                logger.info("[IngestionWatcher] Skill freshness: all up to date.")
                return
            logger.info("[IngestionWatcher] Skill freshness: recompiling stale %s", stale)
            await asyncio.to_thread(fresh.recompile_stale)
        except Exception as e:
            logger.error("[IngestionWatcher] Startup freshness check failed: %s", e)

    @staticmethod
    def _equipment_name_from_file(path: Path) -> str:
        """Derive a human equipment name from a manual filename."""
        import re
        stem = path.stem
        # strip common download prefixes/junk, normalize separators
        stem = re.sub(r"(?i)^(pdfcoffee\.com[_-]+|www\.[^_]+[_-]+)", "", stem)
        stem = re.sub(r"[-_]+", " ", stem)
        stem = re.sub(r"(?i)\b(pdf|free|download|manual)\b", " ", stem)
        stem = re.sub(r"\s+", " ", stem).strip()
        return stem.title() or path.stem
