"""
ArvisX Phase-11a — commissioning: teach ARVIS how a building works.

Commissioning is not "install sensor, connect WiFi". It's mapping a building's
structure so a signal has *meaning*: Tank Sensor A → Overhead Tank → Water
Availability. ArvisX's building structure used to be hardcoded; now it's a
PER-BUILDING config, persisted and editable through a wizard API:

    DRAFT → ASSETS → SIGNALS → DEPENDENCIES → LEARNING → OPERATIONAL

Each transition is gated (can't add signals before assets, can't go live before
learning). This is the foundation that makes ArvisX deployable to many buildings,
not just the demo community. (Phase 11b adds the learning gate + speed enablers.)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CommissioningState(str, Enum):
    DRAFT = "draft"
    ASSETS = "assets"             # services chosen, assets being added
    SIGNALS = "signals"           # assets mapped, signals being connected
    DEPENDENCIES = "dependencies" # signals connected, dependency graph being drawn
    LEARNING = "learning"         # observing to build the baseline (no alerts yet)
    OPERATIONAL = "operational"   # live — alerts + Community Readiness active


# Forward order + the prerequisite that must be satisfied to ENTER each state.
_ORDER = [CommissioningState.DRAFT, CommissioningState.ASSETS, CommissioningState.SIGNALS,
          CommissioningState.DEPENDENCIES, CommissioningState.LEARNING, CommissioningState.OPERATIONAL]


@dataclass
class BuildingConfig:
    building_id: str
    name: str
    state: str = CommissioningState.DRAFT.value
    services: List[str] = field(default_factory=list)          # ServiceType values
    assets: List[Dict[str, Any]] = field(default_factory=list)  # {id,type,name,location,service?}
    signal_maps: List[Dict[str, Any]] = field(default_factory=list)  # {source,asset_id,signal}
    dependencies: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)  # service → [{asset_type/asset_id,role,redundancy}]

    def to_dict(self) -> Dict[str, Any]:
        return {"building_id": self.building_id, "name": self.name, "state": self.state,
                "services": self.services, "assets": self.assets, "signal_maps": self.signal_maps,
                "dependencies": self.dependencies}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BuildingConfig":
        return cls(building_id=d["building_id"], name=d.get("name", ""), state=d.get("state", "draft"),
                   services=d.get("services", []), assets=d.get("assets", []),
                   signal_maps=d.get("signal_maps", []), dependencies=d.get("dependencies", {}))


class CommissioningError(Exception):
    pass


class CommissioningManager:
    """CRUD + gated state machine for building commissioning, persisted via ArvisxDb."""
    def __init__(self, db):
        self.db = db

    # ── persistence ──────────────────────────────────────────────────────
    def _save(self, b: BuildingConfig):
        self.db.save_building(b.building_id, b.name, b.state, b.to_dict())

    def get(self, building_id: str) -> Optional[BuildingConfig]:
        d = self.db.load_building(building_id)
        return BuildingConfig.from_dict(d) if d else None

    def list(self) -> List[Dict[str, Any]]:
        return self.db.list_buildings()

    def _require(self, building_id: str) -> BuildingConfig:
        b = self.get(building_id)
        if b is None:
            raise CommissioningError(f"unknown building {building_id}")
        return b

    # ── wizard steps ─────────────────────────────────────────────────────
    def create_building(self, name: str) -> BuildingConfig:
        b = BuildingConfig(building_id=f"BLD-{uuid.uuid4().hex[:8]}", name=name)
        self._save(b)
        return b

    def set_services(self, building_id: str, services: List[str]) -> BuildingConfig:
        b = self._require(building_id)
        b.services = list(dict.fromkeys(services))   # dedup, keep order
        self._save(b)
        return b

    def add_asset(self, building_id: str, asset: Dict[str, Any]) -> BuildingConfig:
        b = self._require(building_id)
        if not asset.get("id") or not asset.get("type"):
            raise CommissioningError("asset needs 'id' and 'type'")
        b.assets = [a for a in b.assets if a.get("id") != asset["id"]] + [asset]   # upsert
        self._save(b)
        return b

    def add_signal_map(self, building_id: str, source: str, asset_id: str, signal: str) -> BuildingConfig:
        b = self._require(building_id)
        if not any(a.get("id") == asset_id for a in b.assets):
            raise CommissioningError(f"signal maps to unknown asset {asset_id}")
        b.signal_maps = [m for m in b.signal_maps if not (m["source"] == source)] + [
            {"source": source, "asset_id": asset_id, "signal": signal}]
        self._save(b)
        return b

    def set_dependencies(self, building_id: str, service: str, nodes: List[Dict[str, str]]) -> BuildingConfig:
        b = self._require(building_id)
        b.dependencies[service] = nodes
        self._save(b)
        return b

    # ── gated state machine ──────────────────────────────────────────────
    def _can_enter(self, b: BuildingConfig, target: CommissioningState) -> Optional[str]:
        reqs = {
            CommissioningState.ASSETS: (b.services, "select at least one service first"),
            CommissioningState.SIGNALS: (b.assets, "add at least one asset first"),
            CommissioningState.DEPENDENCIES: (b.signal_maps, "connect at least one signal first"),
            CommissioningState.LEARNING: (b.dependencies, "map dependencies first"),
            CommissioningState.OPERATIONAL: (b.state == CommissioningState.LEARNING.value,
                                             "must complete LEARNING before going operational"),
        }
        if target in reqs:
            ok, msg = reqs[target]
            if not ok:
                return msg
        return None

    def transition(self, building_id: str, target: str) -> BuildingConfig:
        b = self._require(building_id)
        try:
            tgt = CommissioningState(target)
        except ValueError:
            raise CommissioningError(f"invalid state '{target}'")
        cur_i, tgt_i = _ORDER.index(CommissioningState(b.state)), _ORDER.index(tgt)
        if tgt_i != cur_i + 1 and not (tgt == CommissioningState.OPERATIONAL and b.state == CommissioningState.LEARNING.value):
            raise CommissioningError(f"cannot jump {b.state} → {target}; advance one step at a time")
        why = self._can_enter(b, tgt)
        if why:
            raise CommissioningError(why)
        b.state = tgt.value
        self._save(b)
        return b
