"""
ArvisX Phase-0 community simulator.

Builds a realistic residential community's fragmented infrastructure as Asset
objects with operational footprints. Stands in for the future ingest layer (MQTT /
Modbus / REST edge gateway) so the intelligence layer can be proven with zero
hardware. `inject_prd_scenario()` reproduces the PRD's MVP dashboard exactly:
Power Backup = Attention Required, plus the four named Active Risks.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from arvisx.models import Asset, AssetType, Zone, ZoneKind


def healthy_community(now: datetime | None = None) -> List[Asset]:
    """A nominal community — everything operating normally."""
    now = now or datetime.now()
    d = lambda days: now + timedelta(days=days)
    return [
        # ── Water ────────────────────────────────────────────────────────
        Asset("UG-TANK-01", "Underground Tank 1", AssetType.UNDERGROUND_TANK,
              signals={"tank_level_pct": 78.0, "tank_capacity_l": 50000.0}, next_maintenance_due=d(95)),
        Asset("OH-TANK-01", "Overhead Tank 1", AssetType.OVERHEAD_TANK,
              signals={"tank_level_pct": 64.0, "tank_capacity_l": 20000.0}, next_maintenance_due=d(110)),
        Asset("XFER-PUMP-01", "Transfer Pump 1", AssetType.TRANSFER_PUMP,
              signals={"power_kw": 5.4, "starts_today": 6}, runtime_hours=4200,
              runtime_threshold_hours=8000, next_maintenance_due=d(60)),
        Asset("BOOST-PUMP-01", "Booster Pump 1", AssetType.BOOSTER_PUMP,
              signals={"power_kw": 3.1, "starts_today": 22}, runtime_hours=6100,
              runtime_threshold_hours=8000, next_maintenance_due=d(40)),
        # ── Power backup ─────────────────────────────────────────────────
        Asset("GEN-01", "Diesel Generator 1", AssetType.DIESEL_GENERATOR,
              signals={"fuel_level_pct": 72.0, "fault": False}, runtime_hours=910,
              next_maintenance_due=d(70)),
        Asset("GEN-BATT-01", "Generator Battery 1", AssetType.GENERATOR_BATTERY,
              signals={"battery_voltage": 12.8}),
        # ── STP ──────────────────────────────────────────────────────────
        Asset("STP-BLOWER-01", "STP Blower 1", AssetType.STP_BLOWER,
              signals={"runtime_today_hours": 18.0, "power_kw": 7.5}, runtime_hours=12000,
              runtime_threshold_hours=20000, next_maintenance_due=d(50)),
        Asset("STP-PUMP-01", "STP Pump 1", AssetType.STP_PUMP,
              signals={"runtime_today_hours": 9.0}, next_maintenance_due=d(80)),
        # ── Pool ─────────────────────────────────────────────────────────
        Asset("POOL-FILT-01", "Pool Filtration Pump 1", AssetType.POOL_FILTRATION_PUMP,
              signals={"runtime_today_hours": 8.0, "expected_runtime_hours": 8.0,
                       "backwash_today": 1}, next_maintenance_due=d(55)),
        Asset("POOL-DOSE-01", "Pool Dosing System 1", AssetType.POOL_DOSING,
              signals={"dosing_events_today": 4, "water_quality_ph": 7.4}),
        # ── Fire (supplementary view only) ───────────────────────────────
        Asset("FIRE-PANEL-01", "Fire Alarm Panel 1", AssetType.FIRE_PANEL,
              signals={"active_faults": 0}),
        Asset("FIRE-PUMP-01", "Fire Pump 1", AssetType.FIRE_PUMP,
              signals={"next_test_due": d(20)}, next_maintenance_due=d(120)),
    ]


def community_zones(scenario: str = "prd") -> List[Zone]:
    """Conditioned areas watched for ghost operation (Phase 5b). Needs cheap CO2 +
    motion sensors per zone. 'prd' makes the clubhouse + parking ghost (empty, running)."""
    occupied = {"co2_ppm": 720.0, "motion_events_15m": 6, "ac_on": True, "light_on": True}
    empty = {"co2_ppm": 430.0, "motion_events_15m": 0, "ac_on": True, "light_on": True}
    zones = [
        Zone("ZONE-GYM", "Gym", ZoneKind.AMENITY, dict(occupied),
             served_by=["FCU-GYM"], conditioned_load_kw=6.0),
        Zone("ZONE-CLUB", "Clubhouse", ZoneKind.AMENITY, dict(occupied),
             served_by=["FCU-CLUB"], conditioned_load_kw=8.0),
        Zone("ZONE-LOBBY", "Lobby", ZoneKind.COMMON,
             {"co2_ppm": 520.0, "motion_events_15m": 2, "ac_on": True, "light_on": True},
             served_by=["FCU-LOBBY"], conditioned_load_kw=4.0),
        Zone("ZONE-PARK", "Parking Level B2", ZoneKind.COMMON,
             {"motion_events_15m": 1, "light_on": True}, conditioned_load_kw=3.0),
    ]
    if scenario != "healthy":
        by = {z.zone_id: z for z in zones}
        by["ZONE-CLUB"].signals = dict(empty)      # empty but AC + lights on → ghost
        by["ZONE-PARK"].signals = {"motion_events_15m": 0, "light_on": True}  # empty, lit 24/7
    return zones


def inject_prd_scenario(now: datetime | None = None) -> List[Asset]:
    """Healthy community + the exact faults from the PRD's MVP dashboard:
       - Generator service due in 12 days
       - Booster Pump runtime above threshold
       - Fire Pump test overdue
       - Pool filtration runtime below normal
       → Power Backup = Attention Required, the rest Healthy."""
    now = now or datetime.now()
    assets = healthy_community(now)
    by_id = {a.asset_id: a for a in assets}

    # Generator service due in 12 days (PM).
    by_id["GEN-01"].next_maintenance_due = now + timedelta(days=12)
    # Booster pump runtime above threshold.
    by_id["BOOST-PUMP-01"].runtime_hours = 8600  # > 8000 threshold
    # Fire pump test overdue (3 days).
    by_id["FIRE-PUMP-01"].signals["next_test_due"] = now - timedelta(days=3)
    # Pool filtration runtime below normal (3h vs expected 8h).
    by_id["POOL-FILT-01"].signals["runtime_today_hours"] = 3.0

    return assets
