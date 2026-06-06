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

    @classmethod
    def from_fleet_definition(cls, assets: List[Asset]) -> "AssetStore":
        return cls(assets)

    def apply_reading(self, asset_id: str, key: str, value) -> bool:
        """Apply one signal reading. Returns False for an unknown asset (the fleet
        must be commissioned first — we don't invent assets from stray topics)."""
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
            self.last_update = datetime.now()
            self._updates += 1
            return True

    def snapshot(self) -> List[Asset]:
        with self._lock:
            return list(self._assets.values())

    def asset(self, asset_id: str) -> Optional[Asset]:
        return self._assets.get(asset_id)

    @property
    def update_count(self) -> int:
        return self._updates
