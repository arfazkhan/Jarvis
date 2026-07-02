"""
Hermetic tests for the active-monitoring watcher — proves the agent SLEEPS and WAKES
on either a telemetry update or a timeout (no LLM, no network, fast).
"""
from __future__ import annotations

import asyncio
import time

from arvisx.simulator import healthy_community
from arvisx.store import AssetStore
from arvisx.watcher import WatchAgent


def test_watch_wakes_early_on_telemetry_update():
    store = AssetStore.from_fleet_definition(healthy_community())

    async def scenario():
        wa = WatchAgent(store)
        # Long deadline — should be cut short by an incoming reading.
        wa.schedule("BOOST-PUMP-01", "power_kw", "confirm creep is sustained", est_seconds=5.0)

        async def push_update():
            await asyncio.sleep(0.3)
            store.apply_reading("BOOST-PUMP-01", "power_kw", 3.1)   # fires the wake

        async def on_check(w, woke_on_update, due):
            return ("resolved", {"woke_on_update": woke_on_update, "due": due})

        t0 = time.monotonic()
        asyncio.create_task(push_update())
        watches = await wa.run(on_check, max_cycles=4, poll_cap_seconds=5.0)
        return watches[0], time.monotonic() - t0

    w, elapsed = asyncio.run(scenario())
    assert w.resolved
    assert "update" in w.woke_on, "should have woken on the telemetry update"
    assert elapsed < 4.0, "should wake on the update, well before the 5s deadline"
    assert w.result["woke_on_update"] is True


def test_watch_wakes_on_timeout_without_update():
    store = AssetStore.from_fleet_definition(healthy_community())

    async def scenario():
        wa = WatchAgent(store)
        wa.schedule("GEN-01", "fuel_level_pct", "await refuel", est_seconds=0.4)

        async def on_check(w, woke_on_update, due):
            return ("resolved", {"woke_on_update": woke_on_update, "due": due})

        watches = await wa.run(on_check, max_cycles=4, poll_cap_seconds=2.0)
        return watches[0]

    w = asyncio.run(scenario())
    assert w.resolved
    assert "timeout" in w.woke_on, "no update → should wake on the deadline"
    assert w.result["due"] is True


def test_watch_reschedules_then_resolves():
    """First check says keep waiting; second resolves — proves the agent can extend."""
    store = AssetStore.from_fleet_definition(healthy_community())

    async def scenario():
        wa = WatchAgent(store)
        wa.schedule("OH-TANK-01", "tank_level_pct", "watch refill progress", est_seconds=0.2)
        state = {"n": 0}

        async def on_check(w, woke_on_update, due):
            state["n"] += 1
            if state["n"] == 1:
                return ("wait", 0.2)        # not done yet — recheck soon
            return ("resolved", {"checks": state["n"]})

        return await wa.run(on_check, max_cycles=6, poll_cap_seconds=2.0)

    watches = asyncio.run(scenario())
    assert watches[0].resolved
    assert watches[0].checks >= 2, "should have rechecked at least twice before resolving"


if __name__ == "__main__":
    test_watch_wakes_early_on_telemetry_update()
    test_watch_wakes_on_timeout_without_update()
    test_watch_reschedules_then_resolves()
    print("PASS — watcher sleep/wake (update + timeout + reschedule) verified")
