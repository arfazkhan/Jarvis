"""
ArvisX live asset store — the state the ingest layer writes and the intelligence
layer reads. Replaces the static simulator list once real signals flow.

The store is seeded with the community's asset DEFINITIONS (ids, types, thresholds,
maintenance dates — the 'commissioning' of the fleet); live signal values then
arrive via the ingest adapter (MQTT/Modbus/REST) and update each asset's footprint.
Reading a never-updated signal stays absent → the intelligence layer abstains rather
than fabricating (same honesty rule as commercial ARVIS).
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, List, Optional

from arvisx.models import Asset


class AssetStore:
    def __init__(self, assets: List[Asset]):
        self._assets: Dict[str, Asset] = {a.asset_id: a for a in assets}
        self._lock = threading.Lock()
        self.last_update: Optional[datetime] = None
        self._updates = 0
        self._ts: Dict[tuple, datetime] = {}            # (asset_id, signal) → last good update
        self.quarantined: List[Dict[str, object]] = []  # rejected bad readings (sensor faults)
        self._on_update = None                          # callback(asset_id, signal) on a good reading

    def set_update_callback(self, cb) -> None:
        """Register a callback fired after each accepted reading — lets a WatchAgent
        wake the instant relevant telemetry changes (not just on a timer)."""
        self._on_update = cb

    def signal_ts(self, asset_id: str, signal: str) -> Optional[datetime]:
        """Last-good-update timestamp for one signal (None if never seen)."""
        return self._ts.get((asset_id, signal))

    @classmethod
    def from_fleet_definition(cls, assets: List[Asset]) -> "AssetStore":
        return cls(assets)

    def apply_reading(self, asset_id: str, key: str, value) -> bool:
        """Apply one signal reading. Returns False for an unknown asset (the fleet
        must be commissioned first — we don't invent assets from stray topics)."""
        # Signal-quality gate: impossible/garbage values are QUARANTINED, not stored —
        # a glitchy sensor must not overwrite a good value or trigger a false equipment
        # alarm. The bad reading is recorded so the report can flag the SENSOR.
        from arvisx.signal_quality import check_value
        if key not in ("online",):
            flag, reason = check_value(key, value)
            if flag == "bad":
                # JSON-safe quarantine record: a NaN/inf kept as a raw float would crash
                # every API response that serializes the quarantine list (found by the
                # adversarial twin test — one junk gateway message must not kill the API).
                import math as _math
                safe = value
                if isinstance(value, float) and not _math.isfinite(value):
                    safe = str(value)
                with self._lock:
                    if self._assets.get(asset_id) is None:
                        return False
                    self.quarantined.append({"asset_id": asset_id, "signal": key, "value": safe,
                                             "reason": reason, "ts": datetime.now().isoformat()})
                return False
        with self._lock:
            a = self._assets.get(asset_id)
            if a is None:
                return False
            if key == "runtime_hours":
                try:
                    a.runtime_hours = float(value)
                except (TypeError, ValueError):
                    pass
            elif key == "online":
                a.online = bool(value)
            else:
                a.signals[key] = value
            self._ts[(asset_id, key)] = datetime.now()
            self.last_update = datetime.now()
            self._updates += 1
        cb = self._on_update
        if cb is not None:
            try:
                cb(asset_id, key)
            except Exception:
                pass
        return True

    def stale_signals(self, max_age_s: float = 900.0, now: Optional[datetime] = None) -> List[tuple]:
        """(asset_id, signal, age_s) for signals not updated within max_age_s — a frozen
        live value looks current otherwise."""
        now = now or datetime.now()
        with self._lock:
            return [(aid, sig, round((now - ts).total_seconds(), 1))
                    for (aid, sig), ts in self._ts.items()
                    if (now - ts).total_seconds() > max_age_s]

    def snapshot(self) -> List[Asset]:
        with self._lock:
            return list(self._assets.values())

    def asset(self, asset_id: str) -> Optional[Asset]:
        return self._assets.get(asset_id)

    @property
    def update_count(self) -> int:
        return self._updates
