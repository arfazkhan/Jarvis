"""Small helpers shared by the newer sources: secrets from the environment, JSON paths, points."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_SECRET_KEYS = ("password", "community", "auth_key", "priv_key", "token", "api_key", "secret")


def refuse_inline_secrets(cfg: Dict[str, Any], where: str) -> None:
    """Secrets never live in the site config: name an environment variable instead."""
    for k in _SECRET_KEYS:
        if cfg.get(k):
            raise ValueError(f"{where}: put {k} in the environment and reference it as {k}_env: VAR_NAME, "
                             "not in the config file")


def secret(cfg: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    """The value of the environment variable that cfg[f"{key}_env"] names."""
    var = cfg.get(f"{key}_env")
    if not var:
        return default
    val = os.getenv(str(var))
    if val is None:
        raise ValueError(f"environment variable {var} (for {key}) is not set")
    return val


_PATH_TOKEN = re.compile(r"\.([^.\[\]]+)|\[(\d+)\]")


def json_path(doc: Any, path: Optional[str]) -> Any:
    """'$.object.level' / '$.uplink_message.decoded_payload.temp' / '$.values[0]'. None/'$' → the document."""
    if not path or path == "$":
        return doc
    p = path[1:] if path.startswith("$") else "." + path.lstrip(".")
    cur = doc
    for key, idx in _PATH_TOKEN.findall(p):
        if idx:
            if not isinstance(cur, list) or int(idx) >= len(cur):
                return None
            cur = cur[int(idx)]
        else:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
    return cur


def number(v: Any) -> Optional[float]:
    """A reading as a float: numbers, booleans (1/0), numeric strings; anything else → None (never a fake 0)."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("on", "true", "running", "open", "alarm"):
            return 1.0
        if s in ("off", "false", "stopped", "closed", "normal"):
            return 0.0
        try:
            return float(s)
        except ValueError:
            return None
    return None


def timestamp(v: Any) -> Optional[datetime]:
    """An ISO-8601 string or epoch seconds/ms from a payload → aware datetime; else None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        secs = v / 1000.0 if v > 1e11 else float(v)
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    if isinstance(v, str) and v:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.astimezone()
        except ValueError:
            return None
    return None
