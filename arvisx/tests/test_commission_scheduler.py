"""Tests for commissioning-anomaly detection/narration + the heartbeat scheduler."""
from __future__ import annotations

import asyncio

from arvisx.commission_check import detect_commissioning_anomalies, narrate_anomalies
from arvisx.commissioning import BuildingConfig
from arvisx.scheduler import Heartbeat


def _cfg():
    return BuildingConfig(
        building_id="B", name="Tower A", services=["water", "pool"],
        assets=[{"id": "BP", "type": "booster_pump", "name": "Booster", "service": "water"},
                {"id": "PUMP2", "type": "", "name": "Pump 2", "service": "water"}],   # untyped + unsignaled
        signal_maps=[{"source": "arvisx/BP/power_kw", "asset_id": "BP", "signal": "power_kw"}])


def test_detect_commissioning_anomalies():
    anoms = detect_commissioning_anomalies(_cfg(), observed_topics=["arvisx/CHILLER7/power_kw"])
    kinds = {a.kind for a in anoms}
    assert "untyped_asset" in kinds          # PUMP2 has no type
    assert "unsignaled_asset" in kinds       # PUMP2 has no signals
    assert "service_without_assets" in kinds # 'pool' has no assets
    assert "unmapped_topic" in kinds         # CHILLER7 publishing but not commissioned
    sub = {a.subject for a in anoms if a.kind == "unmapped_topic"}
    assert "arvisx/CHILLER7/power_kw" in sub


def test_narrate_anomalies_deterministic_without_llm():
    anoms = detect_commissioning_anomalies(_cfg(), observed_topics=["arvisx/CHILLER7/power_kw"])
    narrated = asyncio.run(narrate_anomalies(anoms, _cfg(), llm=None))
    assert len(narrated) == len(anoms)
    assert all(n["explanation"] and n["recommended_action"] for n in narrated)


def test_heartbeat_fires_then_stops():
    async def scenario():
        hits = []

        async def tick(n):
            hits.append(n)

        hb = Heartbeat(tick, interval_s=0.01)
        n = await hb.run(max_ticks=3)
        return hits, n

    hits, n = asyncio.run(scenario())
    assert hits == [1, 2, 3] and n == 3


def test_heartbeat_stop_event():
    async def scenario():
        async def tick(n):
            if n == 1:
                hb.stop()          # request stop during the first tick

        nonlocal_hb = {}
        hb = Heartbeat(tick, interval_s=5.0)
        nonlocal_hb["hb"] = hb
        return await hb.run(max_ticks=100)

    n = asyncio.run(scenario())
    assert n == 1, "stop() during tick 1 should end the loop right after"


if __name__ == "__main__":
    test_detect_commissioning_anomalies()
    test_narrate_anomalies_deterministic_without_llm()
    test_heartbeat_fires_then_stops()
    test_heartbeat_stop_event()
    print("PASS — commissioning anomalies + heartbeat verified")
