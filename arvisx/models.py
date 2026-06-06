"""
ArvisX domain model — residential community infrastructure.

Deliberately its OWN model (not commercial ARVIS's BMS Equipment/BMSDataPoint) so
the residential prototype stays clean and domain-fit. The shape still mirrors the
ARVIS contract (asset + signals + faults + health) so a later phase can map it onto
arvis_core for grounded RCA without reshaping the domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Service domains (the Community Health roll-up tiles) ──────────────────
class ServiceType(str, Enum):
    WATER = "water"
    POWER_BACKUP = "power_backup"
    POOL = "pool"
    STP = "stp"
    FIRE = "fire"
    ENERGY = "energy"          # efficiency / ghost-operation (Phase 5b)


class ZoneKind(str, Enum):
    FLOOR = "floor"
    COMMON = "common_area"     # corridor, lobby, parking
    AMENITY = "amenity"        # gym, clubhouse, pool deck, party hall


class OccupancyLevel(str, Enum):
    OCCUPIED = "occupied"
    LIKELY_EMPTY = "likely_empty"
    EMPTY = "empty"
    UNKNOWN = "unknown"        # insufficient sensing → abstain


# ── Asset taxonomy (residential, fragmented infrastructure) ──────────────
class AssetType(str, Enum):
    UNDERGROUND_TANK = "underground_tank"
    OVERHEAD_TANK = "overhead_tank"
    TRANSFER_PUMP = "transfer_pump"
    BOOSTER_PUMP = "booster_pump"
    DIESEL_GENERATOR = "diesel_generator"
    GENERATOR_BATTERY = "generator_battery"
    STP_BLOWER = "stp_blower"
    STP_PUMP = "stp_pump"
    POOL_FILTRATION_PUMP = "pool_filtration_pump"
    POOL_DOSING = "pool_dosing"
    FIRE_PANEL = "fire_panel"
    FIRE_PUMP = "fire_pump"
    AC_UNIT = "ac_unit"            # split/package AC (Phase 6 — fusion)
    FCU = "fan_coil_unit"


# Which service each asset type rolls up into.
ASSET_SERVICE: Dict[AssetType, ServiceType] = {
    AssetType.UNDERGROUND_TANK: ServiceType.WATER,
    AssetType.OVERHEAD_TANK: ServiceType.WATER,
    AssetType.TRANSFER_PUMP: ServiceType.WATER,
    AssetType.BOOSTER_PUMP: ServiceType.WATER,
    AssetType.DIESEL_GENERATOR: ServiceType.POWER_BACKUP,
    AssetType.GENERATOR_BATTERY: ServiceType.POWER_BACKUP,
    AssetType.STP_BLOWER: ServiceType.STP,
    AssetType.STP_PUMP: ServiceType.STP,
    AssetType.POOL_FILTRATION_PUMP: ServiceType.POOL,
    AssetType.POOL_DOSING: ServiceType.POOL,
    AssetType.FIRE_PANEL: ServiceType.FIRE,
    AssetType.FIRE_PUMP: ServiceType.FIRE,
    AssetType.AC_UNIT: ServiceType.ENERGY,      # cooling effectiveness / comfort
    AssetType.FCU: ServiceType.ENERGY,
}


class Severity(str, Enum):
    CRITICAL = "critical"       # immediate action — service at risk now
    WARNING = "warning"         # potential operational issue
    MAINTENANCE = "maintenance" # upcoming service activity
    INFO = "info"


class HealthBand(str, Enum):
    HEALTHY = "Healthy"
    ATTENTION = "Attention Required"
    CRITICAL = "Critical"

    @staticmethod
    def from_score(score: float) -> "HealthBand":
        if score >= 80:
            return HealthBand.HEALTHY
        if score >= 50:
            return HealthBand.ATTENTION
        return HealthBand.CRITICAL


@dataclass
class Asset:
    """A piece of residential infrastructure and its latest operational footprint."""
    asset_id: str
    name: str
    asset_type: AssetType
    # Latest signal readings (the "operational footprint"). Free-form so different
    # asset types carry different metrics (tank_level_pct, fuel_level_pct, fault, …).
    signals: Dict[str, Any] = field(default_factory=dict)
    # Maintenance metadata.
    runtime_hours: float = 0.0
    runtime_threshold_hours: Optional[float] = None     # PM: flag when exceeded
    last_maintenance: Optional[datetime] = None
    next_maintenance_due: Optional[datetime] = None
    online: bool = True

    @property
    def service(self) -> ServiceType:
        return ASSET_SERVICE[self.asset_type]


@dataclass
class Zone:
    """A conditioned area watched for ghost operation (empty but running)."""
    zone_id: str
    name: str
    kind: ZoneKind
    signals: Dict[str, Any] = field(default_factory=dict)   # co2_ppm, motion_events_15m, ac_on, light_on
    served_by: List[str] = field(default_factory=list)      # equipment conditioning it
    conditioned_load_kw: float = 0.0                         # for the waste estimate
    always_on: bool = False                                  # conditioned on a fixed schedule
    tariff_qar_per_kwh: float = 0.40


@dataclass
class GhostAlert:
    zone_id: str
    zone_name: str
    occupancy: "OccupancyLevel"
    confidence: float
    waste_kw: float
    waste_qar_per_day: float
    note: str


# Outcome language — committees think in outcomes, not 'health'.
OUTCOME_LABEL = {
    ServiceType.WATER: "Water Availability",
    ServiceType.POWER_BACKUP: "Backup Readiness",
    ServiceType.POOL: "Pool Availability",
    ServiceType.STP: "STP Compliance",
    ServiceType.FIRE: "Fire Readiness",
    ServiceType.ENERGY: "Energy & Waste",
}
# Readiness weighting — essentials/safety count more toward the parent score.
SERVICE_WEIGHT = {
    ServiceType.WATER: 1.5, ServiceType.FIRE: 1.5, ServiceType.POWER_BACKUP: 1.2,
    ServiceType.STP: 1.0, ServiceType.POOL: 0.8, ServiceType.ENERGY: 0.6,
}


def confidence_band(n_sources: int) -> str:
    """Every insight carries confidence = number of independent evidence sources."""
    return "High" if n_sources >= 3 else "Medium" if n_sources == 2 else "Low"


@dataclass
class Risk:
    """An active risk surfaced to the dashboard (the 'Active Risks' list)."""
    asset_id: str
    asset_name: str
    service: ServiceType
    severity: Severity
    message: str
    detail: str = ""
    confidence: str = "Low"                 # Low | Medium | High (from # evidence sources)
    evidence: List[str] = field(default_factory=list)


@dataclass
class AssetHealth:
    asset_id: str
    name: str
    asset_type: AssetType
    status: str               # human status line
    score: float              # 0..100
    band: HealthBand
    runtime_hours: float
    last_maintenance: Optional[datetime]
    next_maintenance_due: Optional[datetime]
    alerts: List[str] = field(default_factory=list)


@dataclass
class ServiceHealth:
    service: ServiceType
    score: float
    band: HealthBand
    contributing_assets: int
    worst_asset: Optional[str] = None
    outcome: str = ""                       # operational-outcome label (e.g. "Water Availability")


@dataclass
class Hypothesis:
    """One competing root-cause hypothesis in the ranked differential."""
    label: str
    probability: float
    rationale: str
    evidence: List[str] = field(default_factory=list)        # cited asset signals/risks
    discriminating_test: str = ""                            # what confirms/refutes it
    recommended_action: str = ""


@dataclass
class Advisory:
    """Grounded root-cause advisory for one flagged asset. Same discipline as
    commercial ARVIS: evidence-bound, never confirmed without physical inspection,
    honest when the signals are thin."""
    asset_id: str
    asset_name: str
    headline: str
    root_cause: str
    confidence_band: str                 # Low | Medium | High
    confirmed: bool                      # almost always False (read-only advisory)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    recommended_action: str = ""
    plain_summary: str = ""
    source: str = "rules"                # "rules" (offline floor) | "llm+rules"


class Priority(str, Enum):
    P1 = "P1"   # critical — immediate
    P2 = "P2"   # warning
    P3 = "P3"   # maintenance / scheduled
    P4 = "P4"   # informational


class WorkOrderStatus(str, Enum):
    OPEN = "open"
    ACK = "acknowledged"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class WorkOrder:
    """A trackable maintenance ticket generated from a risk, carrying the grounded
    advisory so whoever acts on it has the cause + the field check, not just an alert."""
    wo_id: str
    asset_id: str
    asset_name: str
    service: ServiceType
    title: str
    priority: Priority
    severity: Severity
    cause: str                      # from the grounded (rules-floor) advisory
    recommended_action: str
    status: WorkOrderStatus
    signature: str                  # (asset, risk-kind) — for dedup / auto-close
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime          # last cycle the underlying risk was still active
    asset_type: str = ""            # equipment class — outcome feedback → skillbook scope
    assignee: Optional[str] = None  # FM / vendor
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CommunityReport:
    generated_at: datetime
    services: List[ServiceHealth]
    risks: List[Risk]
    assets: List[AssetHealth]
    readiness: float = 0.0                   # Community Readiness — the headline parent score
    readiness_band: str = "Healthy"
