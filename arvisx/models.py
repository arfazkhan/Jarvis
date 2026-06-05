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
class Risk:
    """An active risk surfaced to the dashboard (the 'Active Risks' list)."""
    asset_id: str
    asset_name: str
    service: ServiceType
    severity: Severity
    message: str
    detail: str = ""


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


@dataclass
class CommunityReport:
    generated_at: datetime
    services: List[ServiceHealth]
    risks: List[Risk]
    assets: List[AssetHealth]
