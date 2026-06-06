"""
ArvisX Phase-11b — discovery assist.

Connect the edge node, let it sniff which MQTT topics are publishing, and ArvisX
SUGGESTS the asset + signal mappings — the technician confirms instead of typing. The
other half-day lever (with templates). Inference is conservative: it proposes from the
topic/asset-id naming; the technician owns the final mapping (same propose-not-assert
discipline as the commercial discovery bridge).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from arvisx.ingest.topics import parse

# asset-id keyword → (AssetType value, human name) — order matters (specific first).
_TYPE_HINTS = [
    ("ugt", "underground_tank", "Underground Tank"),
    ("underground", "underground_tank", "Underground Tank"),
    ("oht", "overhead_tank", "Overhead Tank"),
    ("overhead", "overhead_tank", "Overhead Tank"),
    ("xfer", "transfer_pump", "Transfer Pump"),
    ("transfer", "transfer_pump", "Transfer Pump"),
    ("boost", "booster_pump", "Booster Pump"),
    ("pool-filt", "pool_filtration_pump", "Pool Filtration Pump"),
    ("filt", "pool_filtration_pump", "Pool Filtration Pump"),
    ("dose", "pool_dosing", "Pool Doser"),
    ("blower", "stp_blower", "STP Blower"),
    ("stp-pump", "stp_pump", "STP Pump"),
    ("gen-batt", "generator_battery", "Generator Battery"),
    ("batt", "generator_battery", "Generator Battery"),
    ("gen", "diesel_generator", "Diesel Generator"),
    ("fire-pump", "fire_pump", "Fire Pump"),
    ("fire-panel", "fire_panel", "Fire Panel"),
    ("panel", "fire_panel", "Fire Panel"),
    ("ac", "ac_unit", "AC Unit"),
    ("fcu", "fan_coil_unit", "FCU"),
    ("tank", "overhead_tank", "Tank"),
    ("pump", "booster_pump", "Pump"),
]


def _infer_type(asset_id: str):
    a = asset_id.lower()
    for kw, t, name in _TYPE_HINTS:
        if kw in a:
            return t, name
    return None, None


def suggest_from_topics(topics: List[str], prefix: str = "arvisx") -> Dict[str, Any]:
    """Given observed topics, propose assets + signal maps for the wizard to confirm."""
    assets: Dict[str, Dict[str, Any]] = {}
    signal_maps: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for topic in topics:
        readings = parse(topic, "0", prefix)        # dummy payload — we only need the structure
        if not readings:
            unknown.append(topic)
            continue
        asset_id, signal, _ = readings[0]
        if asset_id not in assets:
            t, name = _infer_type(asset_id)
            assets[asset_id] = {"id": asset_id, "type": t, "name": name or asset_id,
                                "type_inferred": t is not None}
        signal_maps.append({"source": topic, "asset_id": asset_id, "signal": signal})
    return {
        "assets": list(assets.values()),
        "signal_maps": signal_maps,
        "unmapped_topics": unknown,
        "note": "Suggested from topic naming — confirm/edit each before applying. "
                "Assets with type_inferred=false need a type chosen.",
    }
