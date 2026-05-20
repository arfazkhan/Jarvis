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

    def __init__(self, knowledge_base=None, poll_interval: int = POLL_INTERVAL):
        self._kb = knowledge_base
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> asyncio.Task:
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._watch_loop(), name="ingestion_watcher")
        logger.info(f"[IngestionWatcher] Started — watching {WATCH_DIR}")
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
        except Exception as e:
            logger.error(f"[IngestionWatcher] Failed to ingest '{path.name}': {e}")
