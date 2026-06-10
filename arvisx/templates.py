"""
ArvisX Phase-11b — service templates.

Picking a service ("Water") auto-loads its standard assets + dependency graph so the
technician CONFIRMS instead of typing. This is a core half-day enabler: most residential
communities have the same shape (UGT → pumps → OHT → booster), so a template gets 80% of
the structure in one click; the technician edits the exceptions.
"""
from __future__ import annotations

from typing import Any, Dict

SERVICE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "water": {
        "assets": [
            {"id": "UGT-01", "type": "underground_tank", "name": "Underground Tank",
             "signals": {"tank_capacity_l": 50000}},
            {"id": "XFER-A", "type": "transfer_pump", "name": "Transfer Pump A"},
            {"id": "XFER-B", "type": "transfer_pump", "name": "Transfer Pump B"},
            {"id": "OHT-A", "type": "overhead_tank", "name": "Overhead Tank A",
             "signals": {"tank_capacity_l": 20000}},
            {"id": "BOOST-01", "type": "booster_pump", "name": "Booster Pump"},
        ],
        "dependencies": {"water": [
            {"asset_id": "UGT-01", "role": "source", "redundancy": "single"},
            {"asset_id": "XFER-A", "role": "transfer", "redundancy": "standby"},
            {"asset_id": "OHT-A", "role": "storage", "redundancy": "single"},
            {"asset_id": "BOOST-01", "role": "distribution", "redundancy": "single"},
        ]},
    },
    "power_backup": {
        "assets": [
            {"id": "GEN-01", "type": "diesel_generator", "name": "Diesel Generator"},
            {"id": "GEN-BATT-01", "type": "generator_battery", "name": "Generator Battery"},
        ],
        "dependencies": {"power_backup": [
            {"asset_id": "GEN-01", "role": "generation", "redundancy": "single"},
            {"asset_id": "GEN-BATT-01", "role": "start", "redundancy": "single"},
        ]},
    },
    "stp": {
        "assets": [
            {"id": "STP-BLOWER-A", "type": "stp_blower", "name": "STP Blower A"},
            {"id": "STP-BLOWER-B", "type": "stp_blower", "name": "STP Blower B"},
            {"id": "STP-PUMP-01", "type": "stp_pump", "name": "STP Feed Pump"},
        ],
        "dependencies": {"stp": [
            {"asset_id": "STP-BLOWER-A", "role": "aeration", "redundancy": "standby"},
            {"asset_id": "STP-PUMP-01", "role": "transfer", "redundancy": "single"},
        ]},
    },
    "pool": {
        "assets": [
            {"id": "POOL-FILT-01", "type": "pool_filtration_pump", "name": "Pool Filtration Pump"},
            {"id": "POOL-DOSE-01", "type": "pool_dosing", "name": "Chemical Doser"},
        ],
        "dependencies": {"pool": [
            {"asset_id": "POOL-FILT-01", "role": "circulation", "redundancy": "single"},
            {"asset_id": "POOL-DOSE-01", "role": "chemistry", "redundancy": "single"},
        ]},
    },
    "fire": {
        "assets": [
            {"id": "FIRE-PANEL-01", "type": "fire_panel", "name": "Fire Alarm Panel"},
            {"id": "FIRE-PUMP-01", "type": "fire_pump", "name": "Fire Pump"},
        ],
        "dependencies": {"fire": [
            {"asset_id": "FIRE-PUMP-01", "role": "suppression", "redundancy": "single"},
            {"asset_id": "FIRE-PANEL-01", "role": "detection", "redundancy": "single"},
        ]},
    },
    "gas": {
        # Basement gas plant feeding apartment lines. Per-apartment meters are added
        # via discovery (one per flat) — the template carries the plant itself.
        "assets": [
            {"id": "GAS-PLANT-01", "type": "gas_plant", "name": "Gas Plant (Basement)"},
        ],
        "dependencies": {"gas": [
            {"asset_id": "GAS-PLANT-01", "role": "supply", "redundancy": "single"},
        ]},
    },
}


def template_for(service: str) -> Dict[str, Any]:
    return SERVICE_TEMPLATES.get(service, {"assets": [], "dependencies": {}})
