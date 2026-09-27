"""
Telemetry Recorder
==================

Persists every accepted point update into the ``data_points`` history table.

Why this exists: the live runtime never wrote telemetry to the database, so
everything that learns from history — the ThresholdCalibrator, digests,
``get_historical_telemetry`` and the rule-based FDD engine — had nothing to
learn from on a real building. The recorder subscribes to
``BMSStateEngine.on_point_update`` (so it only ever sees values the state engine
accepted: suppression and source-priority already applied), buffers them in
memory and flushes in batches.

Only finite numeric values are recorded. Nothing is interpolated or invented.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("arvis.telemetry_recorder")


def _to_naive_local(ts: Optional[datetime]) -> datetime:
    """History readers (digests, calibrator, get_point_history) compare naive
    local ISO strings and bucket by local calendar day, so aware timestamps
    (adapters stamp UTC) are converted to naive local time before storage."""
    if ts is None:
        return datetime.now()
    if ts.tzinfo is not None:
        return ts.astimezone().replace(tzinfo=None)
    return ts


class TelemetryRecorder:
    """Buffers accepted point updates and flushes them to ``data_points``."""

    # Sources whose values are declared, not measured (e.g. a commissioning
    # spec's snapshot `value:`) — never stored as telemetry history.
    NON_MEASURED_SOURCES = frozenset({"commission"})

    def __init__(self, database: Any, flush_interval_s: float = 60.0,
                 max_buffer: int = 20000):
        self.database = database
        self.flush_interval_s = flush_interval_s
        self.max_buffer = max_buffer
        self._buffer: List[Dict[str, Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.stats = {"recorded": 0, "flushed": 0, "dropped": 0,
                      "skipped_non_numeric": 0, "flush_errors": 0}

    # ── Subscriber (sync — called from BMSStateEngine callbacks) ──────────────
    def on_point(self, point: Any) -> None:
        if str(getattr(point, "source", "") or "").lower() in self.NON_MEASURED_SOURCES:
            return
        q = getattr(point, "quality", None)
        if str(getattr(q, "value", q) or "").lower() == "stale":
            return      # an adapter re-announcing a silent point, not a new measurement
        value = getattr(point, "value", None)
        if isinstance(value, bool):
            value = 1.0 if value else 0.0
        try:
            value = float(value)
        except (TypeError, ValueError):
            self.stats["skipped_non_numeric"] += 1
            return
        if not math.isfinite(value):
            self.stats["skipped_non_numeric"] += 1
            return

        if len(self._buffer) >= self.max_buffer:
            # Never block ingestion; drop the oldest sample and count it.
            self._buffer.pop(0)
            self.stats["dropped"] += 1

        ts = _to_naive_local(getattr(point, "timestamp", None))
        quality = getattr(point, "quality", "good")
        self._buffer.append({
            # Copy fields now: the state engine hands us its canonical, mutable
            # point object, which the next update will overwrite.
            "point_id": point.point_id,
            "equipment_id": getattr(point, "equipment_id", None),
            "value": value,
            "unit": getattr(point, "unit", "") or "",
            "quality": quality.value if hasattr(quality, "value") else str(quality),
            "timestamp": ts,
        })
        self.stats["recorded"] += 1

    # ── Flushing ──────────────────────────────────────────────────────────────
    async def flush(self) -> int:
        if not self._buffer or self.database is None:
            return 0
        batch, self._buffer = self._buffer, []
        try:
            await self.database.save_data_points_batch(batch)
            self.stats["flushed"] += len(batch)
            return len(batch)
        except Exception as e:
            # Put the batch back (bounded) so a transient DB error loses nothing.
            self.stats["flush_errors"] += 1
            logger.warning("Telemetry flush failed (%d rows kept for retry): %s",
                           len(batch), e)
            self._buffer = (batch + self._buffer)[-self.max_buffer:]
            return 0

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval_s)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Telemetry recorder loop error: %s", e)

    def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        return self._task

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.flush()

    def get_stats(self) -> Dict[str, Any]:
        return {**self.stats, "buffered": len(self._buffer)}
