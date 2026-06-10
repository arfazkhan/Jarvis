"""
ArvisX Phase-10 — asset dependency graph + impact propagation.

Turns flat service roll-ups into SYSTEMS-LEVEL reasoning: each service depends on
assets in specific ROLES with specific REDUNDANCY, so a failing asset propagates a
quantified impact up the chain:

    Pump A fault  →  Water Availability (major: no standby)  →  Community Readiness −X

Redundancy matters: a single transfer pump failing is major; one of two parallel
booster pumps is partial. This is what makes the service scores CAUSAL, not just
averages — and it gives the reasoning layer (correlate) a structure to reason over.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from arvisx.models import (
    Asset, AssetType, Risk, ServiceType, Severity, SERVICE_WEIGHT,
)


@dataclass
class DepNode:
    asset_type: AssetType
    role: str            # source/transfer/storage/distribution/generation/treatment/suppression/...
    redundancy: str      # "single" | "standby" | "parallel"


# Which asset roles each service depends on (the dependency graph).
SERVICE_TOPOLOGY: Dict[ServiceType, List[DepNode]] = {
    ServiceType.WATER: [
        DepNode(AssetType.UNDERGROUND_TANK, "source", "single"),
        DepNode(AssetType.TRANSFER_PUMP, "transfer", "standby"),
        DepNode(AssetType.OVERHEAD_TANK, "storage", "single"),
        DepNode(AssetType.BOOSTER_PUMP, "distribution", "parallel"),
    ],
    ServiceType.POWER_BACKUP: [
        DepNode(AssetType.DIESEL_GENERATOR, "generation", "single"),
        DepNode(AssetType.GENERATOR_BATTERY, "start", "single"),
    ],
    ServiceType.STP: [
        DepNode(AssetType.STP_BLOWER, "aeration", "single"),
        DepNode(AssetType.STP_PUMP, "transfer", "single"),
    ],
    ServiceType.POOL: [
        DepNode(AssetType.POOL_FILTRATION_PUMP, "circulation", "single"),
        DepNode(AssetType.POOL_DOSING, "chemistry", "single"),
    ],
    ServiceType.FIRE: [
        DepNode(AssetType.FIRE_PUMP, "suppression", "single"),
        DepNode(AssetType.FIRE_PANEL, "detection", "single"),
    ],
    ServiceType.GAS: [
        DepNode(AssetType.GAS_PLANT, "supply", "single"),
        DepNode(AssetType.GAS_METER, "metering", "parallel"),   # one meter ≠ the service
    ],
}

# Role criticality (how essential the role is to delivering the service).
_ROLE_CRIT = {
    "source": 1.0, "generation": 1.0, "suppression": 1.0, "circulation": 0.9, "aeration": 0.9,
    "transfer": 0.7, "treatment": 0.8, "storage": 0.6, "distribution": 0.6, "detection": 0.7,
    "start": 0.6, "chemistry": 0.6, "supply": 1.0, "metering": 0.2,
}
# Redundancy absorbs impact.
_REDUNDANCY_FACTOR = {"single": 1.0, "standby": 0.5, "parallel": 0.4}


@dataclass
class CascadeImpact:
    asset_id: str
    asset_name: str
    service: ServiceType
    role: str
    redundancy: str
    impact: str            # "partial" | "major" | "critical"
    service_impact: float  # 0..1 share of the service degraded
    readiness_delta: float # approx points off Community Readiness
    note: str


def _role_for(asset: Asset) -> Optional[DepNode]:
    for nodes in SERVICE_TOPOLOGY.values():
        for n in nodes:
            if n.asset_type == asset.asset_type:
                return n
    return None


def impact_analysis(assets: List[Asset], risks: List[Risk]) -> List[CascadeImpact]:
    """For each flagged asset, propagate its risk up to a service + readiness impact."""
    by_id = {a.asset_id: a for a in assets}
    total_w = sum(SERVICE_WEIGHT.values())
    out: List[CascadeImpact] = []
    seen = set()
    for r in risks:
        a = by_id.get(r.asset_id)
        if a is None:
            continue
        node = _role_for(a)
        if node is None or (a.asset_id, r.service) in seen:
            continue
        seen.add((a.asset_id, r.service))
        crit = _ROLE_CRIT.get(node.role, 0.6)
        # Severity scales the impact; redundancy absorbs it.
        sev_w = {Severity.CRITICAL: 1.0, Severity.WARNING: 0.6, Severity.MAINTENANCE: 0.3}.get(r.severity, 0.4)
        service_impact = round(crit * sev_w * _REDUNDANCY_FACTOR.get(node.redundancy, 1.0), 2)
        level = "critical" if service_impact >= 0.7 else "major" if service_impact >= 0.4 else "partial"
        readiness_delta = round(service_impact * 100 * (SERVICE_WEIGHT.get(r.service, 1.0) / total_w), 1)
        red_note = {"single": "no standby", "standby": "standby available",
                    "parallel": "parallel unit available"}.get(node.redundancy, "")
        out.append(CascadeImpact(
            asset_id=a.asset_id, asset_name=a.name, service=r.service, role=node.role,
            redundancy=node.redundancy, impact=level, service_impact=service_impact,
            readiness_delta=readiness_delta,
            note=f"{a.name} ({node.role}, {red_note}) → {r.service.value} {level} impact "
                 f"→ Community Readiness −{readiness_delta:.0f}",
        ))
    out.sort(key=lambda c: c.service_impact, reverse=True)
    return out


def service_graph() -> Dict[str, List[Dict[str, str]]]:
    """The dependency graph for the dashboard."""
    return {st.value: [{"asset_type": n.asset_type.value, "role": n.role, "redundancy": n.redundancy}
                       for n in nodes] for st, nodes in SERVICE_TOPOLOGY.items()}
