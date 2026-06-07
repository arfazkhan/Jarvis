"""Durable agentic state: investigations, watches, and heartbeat ticks survive restart."""
from __future__ import annotations

import asyncio
import os
import tempfile

from arvisx.persistence import ArvisxDb
from arvisx.simulator import healthy_community
from arvisx.store import AssetStore
from arvisx.watcher import WatchAgent


def _path():
    return os.path.join(tempfile.mkdtemp(prefix="arvisx_persist_"), "a.db")


def test_investigations_and_ticks_survive_restart():
    p = _path()
    db = ArvisxDb(p, building_id="B")
    db.save_investigation("GEN-01", "fuel low", "tank near empty", "refuel", "Medium", "agent",
                          {"steps": ["get_asset_state"], "evidence": ["fuel 8%"]})
    db.save_tick({"readiness": 82.0, "risks": 4, "investigated": 2})

    # Fresh handle on the SAME file — nothing in memory.
    db2 = ArvisxDb(p, building_id="B")
    invs = db2.recent_investigations()
    assert len(invs) == 1 and invs[0]["asset_id"] == "GEN-01" and invs[0]["source"] == "agent"
    assert db2.recent_investigations("GEN-01")[0]["root_cause"] == "tank near empty"
    ticks = db2.recent_ticks()
    assert len(ticks) == 1 and ticks[0]["readiness"] == 82.0


def test_watch_lifecycle_persisted():
    p = _path()
    db = ArvisxDb(p, building_id="B")
    store = AssetStore.from_fleet_definition(healthy_community())

    async def scenario():
        wa = WatchAgent(store, db=db)
        wa.schedule("BOOST-PUMP-01", "power_kw", "confirm sustained", est_seconds=0.1)
        # On schedule it's persisted and OPEN.
        assert len(db.load_open_watches()) == 1

        async def on_check(w, woke_on_update, due):
            return ("resolved", {"status": "done"})

        await wa.run(on_check, max_cycles=2, poll_cap_seconds=1.0)

    asyncio.run(scenario())

    # Fresh handle: the watch resolved → no longer in the open set.
    db2 = ArvisxDb(p, building_id="B")
    assert db2.load_open_watches() == []


def test_open_watch_visible_after_restart():
    p = _path()
    db = ArvisxDb(p, building_id="B")
    store = AssetStore.from_fleet_definition(healthy_community())
    wa = WatchAgent(store, db=db)
    wa.schedule("OH-TANK-01", "tank_level_pct", "await refill", est_seconds=300)

    db2 = ArvisxDb(p, building_id="B")
    open_w = db2.load_open_watches()
    assert len(open_w) == 1 and open_w[0]["asset_id"] == "OH-TANK-01"
    assert open_w[0]["resolved"] is False


if __name__ == "__main__":
    test_investigations_and_ticks_survive_restart()
    test_watch_lifecycle_persisted()
    test_open_watch_visible_after_restart()
    print("PASS — durable investigations, watches, heartbeat ticks verified")
