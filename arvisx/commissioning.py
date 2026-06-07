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
    learning_started_at: Optional[str] = None
    learning_days: int = 14
    validations: List[Dict[str, Any]] = field(default_factory=list)  # operator baseline tuning

    def to_dict(self) -> Dict[str, Any]:
        return {"building_id": self.building_id, "name": self.name, "state": self.state,
                "services": self.services, "assets": self.assets, "signal_maps": self.signal_maps,
                "dependencies": self.dependencies, "learning_started_at": self.learning_started_at,
                "learning_days": self.learning_days, "validations": self.validations}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BuildingConfig":
        return cls(building_id=d["building_id"], name=d.get("name", ""), state=d.get("state", "draft"),
                   services=d.get("services", []), assets=d.get("assets", []),
                   signal_maps=d.get("signal_maps", []), dependencies=d.get("dependencies", {}),
                   learning_started_at=d.get("learning_started_at"), learning_days=d.get("learning_days", 14),
                   validations=d.get("validations", []))


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

    def apply_template(self, building_id: str, service: str) -> BuildingConfig:
        """Half-day enabler: auto-load a service's standard assets + dependency graph
        (the technician then confirms/edits, instead of typing everything)."""
        from arvisx.templates import template_for
        t = template_for(service)
        b = self._require(building_id)
        if service not in b.services:
            b.services.append(service)
        ids = {a.get("id") for a in b.assets}
        for a in t.get("assets", []):
            if a["id"] not in ids:
                b.assets.append(dict(a))
        for svc, nodes in t.get("dependencies", {}).items():
            b.dependencies.setdefault(svc, nodes)
        self._save(b)
        return b

    # ── Learning mode + validation (baseline tuning) ─────────────────────
    def learning_progress(self, building_id: str, now: Optional["object"] = None) -> Dict[str, Any]:
        from datetime import datetime
        b = self._require(building_id)
        now = now or datetime.now()
        if not b.learning_started_at:
            return {"state": b.state, "in_learning": b.state == CommissioningState.LEARNING.value,
                    "days_elapsed": 0, "days_total": b.learning_days, "ready": False}
        elapsed = (now - datetime.fromisoformat(b.learning_started_at)).total_seconds() / 86400.0
        return {"state": b.state, "in_learning": b.state == CommissioningState.LEARNING.value,
                "days_elapsed": round(elapsed, 2), "days_total": b.learning_days,
                "ready": elapsed >= b.learning_days,
                "pending_validations": sum(1 for v in b.validations if v.get("answer") is None)}

    def add_validation(self, building_id: str, asset_id: str, signal: str, observed,
                       question: str) -> BuildingConfig:
        b = self._require(building_id)
        import uuid as _u
        b.validations.append({"id": f"V-{_u.uuid4().hex[:6]}", "asset_id": asset_id, "signal": signal,
                              "observed": observed, "question": question, "answer": None})
        self._save(b)
        return b

    def answer_validation(self, building_id: str, val_id: str, is_normal: bool) -> BuildingConfig:
        b = self._require(building_id)
        v = next((x for x in b.validations if x["id"] == val_id), None)
        if v is None:
            raise CommissioningError(f"unknown validation {val_id}")
        v["answer"] = "normal" if is_normal else "abnormal"   # tunes the building fingerprint
        self._save(b)
        return b

    # ── data-driven ops-readiness gate (replaces the hardcoded timer) ────
    def evaluate_ops_readiness(self, building_id: str, assets, baselines,
                               auto_advance: bool = True) -> Dict[str, Any]:
        """Decide if a LEARNING building is ready for OPERATIONAL based on whether its
        BASELINES are statistically trustworthy — not just whether learning_days elapsed.
        Approve → advance to operational. Reject → extend learning_days dynamically so the
        building keeps learning until it's actually confident. Returns a verdict dict."""
        from arvisx.readiness import assess_baseline_readiness
        b = self._require(building_id)
        rd = assess_baseline_readiness(assets, baselines)
        verdict: Dict[str, Any] = {
            "building_id": building_id, "state": b.state, "approved": rd.ready,
            "coverage": rd.coverage, "ready_count": rd.ready_count, "total": rd.total,
            "reasons": rd.reasons, "summary": rd.summary()}
        if rd.ready:
            if auto_advance and b.state == CommissioningState.LEARNING.value:
                b.state = CommissioningState.OPERATIONAL.value
                self._save(b)
            verdict["state"] = b.state
        else:
            # dynamically extend the learning window so it stays in LEARNING and keeps going
            b.learning_days = int(b.learning_days) + rd.suggested_extra_days
            self._save(b)
            verdict["extended_learning_days_by"] = rd.suggested_extra_days
            verdict["learning_days"] = b.learning_days
        return verdict

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

    def transition(self, building_id: str, target: str, force: bool = False) -> BuildingConfig:
        from datetime import datetime
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
        # Learning-mode gate: don't go live until the baseline window has elapsed.
        if tgt == CommissioningState.OPERATIONAL and not force:
            if not b.learning_started_at:
                raise CommissioningError("learning has not started")
            elapsed = (datetime.now() - datetime.fromisoformat(b.learning_started_at)).total_seconds() / 86400.0
            if elapsed < b.learning_days:
                raise CommissioningError(
                    f"still learning — {elapsed:.1f}/{b.learning_days} days observed "
                    f"(alerts stay suppressed; pass force=true to override)")
        if tgt == CommissioningState.LEARNING:
            b.learning_started_at = datetime.now().isoformat()
        b.state = tgt.value
        self._save(b)
        return b
