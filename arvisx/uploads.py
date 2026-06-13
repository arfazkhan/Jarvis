"""Local photo-evidence storage for Phase-0 checklists. No cloud, no external send —
the operator's photo is written to a local folder and served back by the API. Files are
content-addressed-ish (uuid name) and the stored name is what links to an entry/issue."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Optional, Tuple

_ALLOWED = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_BYTES = 8 * 1024 * 1024     # 8 MB cap per photo
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def upload_dir() -> Path:
    d = os.environ.get("ARVISX_UPLOAD_DIR")
    if not d:
        base = os.environ.get("ARVISX_DB")
        parent = Path(base).parent if base else (Path(__file__).parent / "data")
        d = str(parent / "uploads")
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ext_of(filename: str, content_type: str = "") -> Optional[str]:
    ext = (Path(filename or "").suffix.lstrip(".") or "").lower()
    if ext in _ALLOWED:
        return ext
    for e, mt in _ALLOWED.items():        # fall back to declared content-type
        if mt == (content_type or "").lower():
            return e
    return None


def save_photo(data: bytes, filename: str = "", content_type: str = "") -> Tuple[str, str]:
    """Validate + persist. Returns (stored_name, media_type). Raises ValueError on reject."""
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_BYTES:
        raise ValueError("file too large (max 8MB)")
    ext = _ext_of(filename, content_type)
    if ext is None:
        raise ValueError("only jpg/png/webp images allowed")
    name = f"{uuid.uuid4().hex}.{ext}"
    (upload_dir() / name).write_bytes(data)
    return name, _ALLOWED[ext]


def photo_path(name: str) -> Optional[Path]:
    """Resolve a stored name to a path, rejecting traversal. None if absent."""
    if not name or not _NAME_RE.match(name) or "/" in name or "\\" in name:
        return None
    p = upload_dir() / name
    return p if p.is_file() else None


def media_type_of(name: str) -> str:
    return _ALLOWED.get(Path(name).suffix.lstrip(".").lower(), "application/octet-stream")
