"""
Voice notes and photos from the site.

Voice notes are transcribed ON the site box (faster-whisper): the audio never leaves
the building. The model (ARVIS_STT_MODEL, default "small" ≈ 470 MB, Arabic and
English) is loaded once, on first use, from ARVIS_STT_MODEL_DIR. Site boxes have no
internet egress, so fetch it once while setting the box up:

    python -m agent_commercial.ops_engineer.media prefetch

Photos are read by the vision model ARVIS already uses for manuals (VisionBackend:
the first configured provider). It transcribes what is legible (nameplates,
displays, gauges, labels, alarm text) and describes what is visible; it does not
diagnose. Its reading is passed on as "what the photo shows, read by a vision
model — may be wrong", never as a measurement.

Every photo is kept as evidence (MediaStore: file on disk + a row in ops_media),
linked to the equipment it is about when that is known, so the conversation, a
diagnosis and a work order can point to it.

Nothing here makes up content: no transcript → "couldn't make it out"; no vision
model → the photo is kept and ARVIS says it cannot see it.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.ops.media")

_DDL = (
    """CREATE TABLE IF NOT EXISTS ops_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, thread TEXT NOT NULL, kind TEXT NOT NULL,
        mimetype TEXT, path TEXT, caption TEXT, transcript TEXT, description TEXT, equipment_id TEXT,
        message_id TEXT, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_media_eq ON ops_media(equipment_id, id)",
)

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}

PHOTO_PROMPT = (
    "A technician at a commercial building sent this photo to the building's operations engineer. "
    "Report what it shows, factually:\n"
    "1. What equipment or part of the plant is visible.\n"
    "2. Transcribe EXACTLY any text you can read: nameplates, controller or thermostat displays, gauge "
    "readings with their units, labels, alarm or fault messages. Write [illegible] where you cannot read it.\n"
    "3. Anything visibly abnormal (leak, corrosion, ice, burn marks, disconnected or damaged parts, open panels, "
    "blocked or dirty filters).\n"
    "Do not guess values, do not diagnose causes, do not give advice. Plain text, at most 8 short lines."
)


def _local_naive_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MediaStore:
    """Photos and voice notes as evidence: the file, and what was read from it."""

    def __init__(self, database: Any, directory: Optional[str] = None, clock=None):
        self.database = database
        self.directory = Path(directory or os.getenv("ARVIS_OPS_MEDIA_DIR") or self._default_dir())
        self.clock = clock or _local_naive_now

    def _default_dir(self) -> str:
        db_path = getattr(self.database, "db_path", None)
        base = Path(str(db_path)).parent if db_path else Path("data")
        return str(base / "ops_media")

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    async def save(self, *, number: str, thread: str, kind: str, data: bytes, mimetype: str = "",
                   caption: str = "", equipment_id: Optional[str] = None, message_id: Optional[str] = None) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}{_EXT.get(mimetype, '.bin')}"
        await asyncio.to_thread(path.write_bytes, data)
        conn = await self._conn()
        cur = await conn.execute(
            "INSERT INTO ops_media (number, thread, kind, mimetype, path, caption, equipment_id, message_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (number, thread, kind, mimetype, str(path), caption, equipment_id, message_id, self.clock()))
        await conn.commit()
        return int(cur.lastrowid)

    async def annotate(self, media_id: int, *, transcript: Optional[str] = None,
                       description: Optional[str] = None) -> None:
        conn = await self._conn()
        await conn.execute("UPDATE ops_media SET transcript = COALESCE(?, transcript), "
                           "description = COALESCE(?, description) WHERE id = ?", (transcript, description, media_id))
        await conn.commit()

    async def photos_on(self, equipment_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        conn = await self._conn()
        async with conn.execute(
                "SELECT id, number, caption, description, created_at FROM ops_media WHERE kind = 'image' "
                "AND equipment_id = ? ORDER BY id DESC LIMIT ?", (equipment_id, limit)) as cur:
            rows = await cur.fetchall()
        return [{"id": r[0], "number": r[1], "caption": r[2] or "", "description": r[3] or "", "at": r[4]}
                for r in rows]


class LocalTranscriber:
    """faster-whisper on the site box. One model, loaded on first use; one note at a time
    (it is CPU-bound and would only slow every note down if run in parallel)."""

    def __init__(self, model: Optional[str] = None, directory: Optional[str] = None):
        self.model_name = model or os.getenv("ARVIS_STT_MODEL", "small")
        self.directory = directory or os.getenv("ARVIS_STT_MODEL_DIR") or None
        self.device = os.getenv("ARVIS_STT_DEVICE", "cpu")
        self.compute_type = os.getenv("ARVIS_STT_COMPUTE", "int8")
        self._model = None
        self._lock = asyncio.Lock()
        self.error: Optional[str] = None

    @staticmethod
    def installed() -> bool:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None

    def _load(self, allow_download: bool = False):
        from faster_whisper import WhisperModel
        return WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type,
                            download_root=self.directory, local_files_only=not allow_download)

    def _run(self, audio: bytes) -> Tuple[str, str]:
        segments, info = self._model.transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, getattr(info, "language", "") or ""

    async def transcribe(self, audio: bytes) -> Optional[Tuple[str, str]]:
        """(text, language), or None when it cannot (not installed / no model / failed)."""
        if not self.installed():
            self.error = "faster-whisper is not installed"
            return None
        async with self._lock:
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(self._load)
                except Exception as e:
                    self.error = f"speech model '{self.model_name}' unavailable: {type(e).__name__}"
                    logger.error(f"[Ops] {self.error}: {e} — run `python -m agent_commercial.ops_engineer.media "
                                 f"prefetch` once on this box")
                    return None
            try:
                return await asyncio.to_thread(self._run, audio)
            except Exception as e:
                self.error = f"transcription failed: {type(e).__name__}"
                logger.error(f"[Ops] voice note transcription failed: {type(e).__name__}: {e}")
                return None


class PhotoReader:
    """What a photo shows, from the vision model ARVIS already uses for manuals."""

    def __init__(self, backend: Any = None):
        self._backend = backend
        self.error: Optional[str] = None

    def _vision(self):
        if self._backend is None:
            from agent_commercial.skills.backends.vision_backend import VisionBackend
            self._backend = VisionBackend()
        return self._backend

    async def read(self, image: bytes, caption: str = "") -> Optional[str]:
        try:
            vision = await asyncio.to_thread(self._vision)
            if not vision.available:
                self.error = "no vision model configured"
                return None
            prompt = PHOTO_PROMPT + (f"\nThe technician's caption: {caption}" if caption else "")
            text = (await asyncio.to_thread(vision.describe, image, prompt, 600)).strip()
            if not text:
                self.error = "the vision model returned nothing"
                return None
            return text
        except Exception as e:
            self.error = f"vision failed: {type(e).__name__}"
            logger.error(f"[Ops] reading a photo failed: {type(e).__name__}: {e}")
            return None

    async def read_value(self, image: bytes, candidates: List[Dict[str, str]], caption: str = "") -> Optional[Dict[str, Any]]:
        """The one value a gauge or display photo shows, for one of the candidate points
        ({point_id, name, unit}). Returns {point_id, value, unit} or None — never a guess:
        an illegible dial, two plausible readings or an unknown point all give None.
        The value is only a proposal: the person confirms it before it is used."""
        if not candidates:
            return None
        listing = "\n".join(f"- {c['point_id']}: {c.get('name', '')} ({c.get('unit', '')})" for c in candidates)
        prompt = (VALUE_PROMPT + listing + (f"\nThe technician's caption: {caption}" if caption else ""))
        try:
            vision = await asyncio.to_thread(self._vision)
            if not vision.available:
                self.error = "no vision model configured"
                return None
            raw = (await asyncio.to_thread(vision.describe, image, prompt, 200)).strip()
        except Exception as e:
            self.error = f"vision failed: {type(e).__name__}"
            logger.error(f"[Ops] reading a value off a photo failed: {type(e).__name__}: {e}")
            return None
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            got = json.loads(m.group(0)) if m else None
        except ValueError:
            got = None
        if not isinstance(got, dict) or not isinstance(got.get("value"), (int, float)) or isinstance(got.get("value"), bool):
            self.error = "the photo has no single clear reading"
            return None
        ids = {c["point_id"] for c in candidates}
        pid = got.get("point_id") if got.get("point_id") in ids else (next(iter(ids)) if len(ids) == 1 else None)
        if pid is None:
            self.error = "can't tell which gauge this is"
            return None
        return {"point_id": pid, "value": float(got["value"]), "unit": str(got.get("unit") or "")}


VALUE_PROMPT = (
    "This photo, from a building technician, shows a gauge, meter or display. Read the ONE value it shows, "
    "with its unit as printed. If it is not clearly legible, or you would have to guess between two readings, "
    "say so with value null. Which of these points is it (choose only if the photo makes it clear; if there is "
    "just one, it is that one)?\n"
    'Answer with JSON only: {"point_id": "...", "value": 4.2, "unit": "bar"} or {"value": null}\n'
)


def _main() -> None:
    ap = argparse.ArgumentParser(description="ARVIS voice-note model setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prefetch", help="download the speech model into ARVIS_STT_MODEL_DIR (needs internet once)")
    ap.parse_args()
    t = LocalTranscriber()
    if not t.installed():
        raise SystemExit("pip install faster-whisper first")
    t._load(allow_download=True)
    print(f"speech model '{t.model_name}' ready in {t.directory or 'the Hugging Face cache'}")


if __name__ == "__main__":
    _main()
