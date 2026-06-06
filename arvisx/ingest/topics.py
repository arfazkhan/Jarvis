"""
Pure topic/payload parsing for the MQTT ingest (no network — fully testable).

Topic convention:  <prefix>/<asset_id>/<signal_key>
  e.g.  arvisx/BOOST-PUMP-01/runtime_hours        payload: 8600
        arvisx/GEN-01/fuel_level_pct              payload: 18.5
        arvisx/GEN-01/fault                       payload: true
        arvisx/POOL-FILT-01/runtime_today_hours   payload: 3.0

Payloads are coerced: bool ('true'/'false'/'1'/'0' for *fault*/*online*/*_on*),
float when numeric, JSON when it parses to a dict/list, else the raw string.
A nested JSON payload like {"runtime_hours": 8600, "fault": false} is also accepted
on a topic ending in the asset id (no signal segment) → expands to multiple readings.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Tuple

Reading = Tuple[str, str, object]   # (asset_id, signal_key, value)

_BOOLISH_KEYS = ("fault", "online", "_on", "active", "status_on")


def _coerce(key: str, raw: str):
    s = (raw or "").strip()
    kl = key.lower()
    if any(b in kl for b in _BOOLISH_KEYS):
        if s.lower() in ("true", "1", "on", "yes"):
            return True
        if s.lower() in ("false", "0", "off", "no"):
            return False
    # numeric
    try:
        f = float(s)
        return int(f) if f.is_integer() and "." not in s else f
    except (TypeError, ValueError):
        pass
    # json object/array
    if s[:1] in ("{", "["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    # ISO datetime (e.g. a *_due / *_date signal sent as a timestamp string)
    if len(s) >= 8 and s[:4].isdigit() and "-" in s:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    return s


def parse(topic: str, payload: str, prefix: str = "arvisx") -> List[Reading]:
    """Parse one MQTT message into 0+ readings. Robust: silently returns [] for
    topics outside the prefix or malformed messages (never raises)."""
    try:
        parts = [p for p in str(topic).strip("/").split("/") if p]
        if prefix:
            if not parts or parts[0] != prefix:
                return []
            parts = parts[1:]
        if not parts:
            return []
        asset_id = parts[0]

        # Case A: <prefix>/<asset>/<signal>  → single reading.
        if len(parts) >= 2:
            signal = parts[1]
            return [(asset_id, signal, _coerce(signal, payload))]

        # Case B: <prefix>/<asset>  with a JSON object payload → many readings.
        s = (payload or "").strip()
        if s[:1] == "{":
            obj = json.loads(s)
            if isinstance(obj, dict):
                return [(asset_id, k, _coerce(k, str(v) if not isinstance(v, (dict, list)) else json.dumps(v)))
                        for k, v in obj.items()]
        return []
    except Exception:
        return []
