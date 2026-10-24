"""
Regression: BMSStateEngine.get_point_history must compare INSTANTS.

Live protocol adapters (BACnet/Modbus/OPC UA) stamp readings with
datetime.now(timezone.utc); the simulator and most internal code stamp naive
local datetime.now(). The old window stripped tzinfo and called .timestamp(),
which reads UTC wall-time as LOCAL — on a site box set to Asia/Qatar (UTC+3)
every live reading moved 3 h into the future, dragging the reference "now"
with it, so "last N minutes" dropped real readings and kept stale ones.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from agent_commercial.bms_data_model import BMSDataPoint
from agent_commercial.bms_state_engine import BMSStateEngine

# Fixed instant far from the wall clock, so the reference "now" must come from
# the point timestamps (simulator behaviour). Mid-January noon UTC keeps clear
# of DST transitions, so naive-local stamps round-trip to the same instant.
BASE = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _naive_local(instant):
    """The instant as the simulator stamps it: naive local wall-time."""
    return instant.astimezone().replace(tzinfo=None)


def _utc(instant):
    """The instant as a live adapter stamps it: UTC-aware."""
    return instant.astimezone(timezone.utc)


def _ahead_of_host(instant):
    """The instant, aware, in a zone 3 h ahead of this host — stripping its
    tzinfo misplaces it on EVERY host, including a UTC one."""
    host_offset = instant.astimezone().utcoffset()
    return instant.astimezone(timezone(host_offset + timedelta(hours=3)))


async def _feed(engine, point_id, stamps):
    for i, ts in enumerate(stamps):
        await engine.update_point(BMSDataPoint(
            point_id=point_id, name=point_id, value=float(i),
            equipment_id=point_id.split("/")[0], timestamp=ts,
        ))


async def _assert_window(stamp_kinds):
    """Readings at -90/-50/-20/-5/0 min; a 30-min window keeps the last three."""
    offsets = [-90, -50, -20, -5, 0]
    engine = BMSStateEngine()
    await _feed(engine, "AHU-01/SAT", [
        kind(BASE + timedelta(minutes=m)) for kind, m in zip(stamp_kinds, offsets)
    ])
    # A second point stamped the other way: the reference "now" is the max over
    # ALL points, so aware and naive stamps must be comparable there too.
    await _feed(engine, "AHU-01/RAT", [_naive_local(BASE - timedelta(minutes=1))])

    history = await engine.get_point_history("AHU-01/SAT", minutes=30)

    assert [v for _, v in history] == [2.0, 3.0, 4.0]


@pytest.mark.asyncio
async def test_window_mixes_aware_and_naive_on_any_host():
    await _assert_window([_ahead_of_host, _naive_local, _naive_local, _utc, _ahead_of_host])


@pytest.mark.asyncio
async def test_naive_only_simulator_window_unchanged():
    await _assert_window([_naive_local] * 5)


@pytest.fixture
def host_tz_qatar(monkeypatch):
    """Pin this process's local zone to UTC+3 (Asia/Qatar) — POSIX only."""
    monkeypatch.setenv("TZ", "AST-3")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.asyncio
@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX-only")
async def test_utc_adapter_stamps_on_utc_plus_3_site_box(host_tz_qatar):
    assert datetime.now().astimezone().utcoffset() == timedelta(hours=3)
    await _assert_window([_utc, _naive_local, _naive_local, _utc, _utc])
