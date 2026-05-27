"""
Unit and Integration Test Suite for ARVIS ThresholdCalibrator Service
===================================================================
"""

import os
import sqlite3
import pytest
import asyncio
import aiosqlite
from datetime import datetime, timedelta

from agent_commercial.digest_builder import DailyDigestBuilder
from agent_commercial.threshold_calibrator import ThresholdCalibrator
from agent_commercial.anomaly_watchdog import AnomalyWatchdog


class MockEventBus:
    def __init__(self):
        self.published = []
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event):
        self.published.append(event)
        event_type = event.get("type")
        if event_type in self.subscribers:
            for cb in self.subscribers[event_type]:
                cb(event)


import pytest_asyncio

@pytest_asyncio.fixture
async def temp_db():
    """Create a temporary in-memory database with the required schemas."""
    db_path = ":memory:"
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row

    # Execute schemas
    schema_queries = [
        # data_points table
        """
        CREATE TABLE IF NOT EXISTS data_points (
            point_id         TEXT NOT NULL,
            timestamp        TEXT NOT NULL,
            equipment_id     TEXT,
            value            REAL,
            unit             TEXT,
            PRIMARY KEY (point_id, timestamp)
        );
        """,
        # alarms table
        """
        CREATE TABLE IF NOT EXISTS alarms (
            alarm_id         TEXT PRIMARY KEY,
            equipment_id     TEXT NOT NULL,
            source_point_id  TEXT,
            message          TEXT,
            severity         TEXT,
            state            TEXT,
            triggered_at     TEXT,
            acknowledged_at  TEXT,
            acknowledged_by  TEXT,
            resolved_at      TEXT,
            cluster_id       TEXT,
            metadata         TEXT
        );
        """,
        # point_baselines
        """
        CREATE TABLE IF NOT EXISTS point_baselines (
            building_id      TEXT NOT NULL,
            point_id         TEXT NOT NULL,
            equipment_id     TEXT NOT NULL,
            equipment_type   TEXT NOT NULL,
            point_type       TEXT NOT NULL,
            location         TEXT,
            date             TEXT NOT NULL,
            sample_count     INTEGER NOT NULL,
            mean_val         REAL NOT NULL,
            std_val          REAL NOT NULL,
            median_val       REAL NOT NULL,
            mad_val          REAL NOT NULL,
            p05_val          REAL NOT NULL,
            p95_val          REAL NOT NULL,
            min_val          REAL NOT NULL,
            max_val          REAL NOT NULL,
            alarm_duration_s INTEGER NOT NULL,
            is_healthy       INTEGER NOT NULL,
            PRIMARY KEY (building_id, point_id, date)
        );
        """,
        # point_calibrations
        """
        CREATE TABLE IF NOT EXISTS point_calibrations (
            building_id          TEXT NOT NULL,
            scope_key            TEXT NOT NULL,
            scope_level          TEXT NOT NULL, -- point, equipment, type, bootstrap
            point_type           TEXT NOT NULL,
            equipment_type       TEXT NOT NULL,
            calibrated_floor     REAL NOT NULL,
            calibrated_z_thresh  REAL NOT NULL,
            prev_floor           REAL,
            prev_z_thresh        REAL,
            sample_size_days     INTEGER NOT NULL,
            rejection_rate_7d    REAL NOT NULL,
            fp_target            REAL NOT NULL,
            promoted             INTEGER NOT NULL DEFAULT 0,
            change_reason        TEXT,
            last_calibrated_at   TEXT NOT NULL,
            last_promoted_at     TEXT,
            next_due_at          TEXT NOT NULL,
            PRIMARY KEY (building_id, scope_key)
        );
        """,
        # calibration_runs
        """
        CREATE TABLE IF NOT EXISTS calibration_runs (
            run_id               TEXT PRIMARY KEY,
            building_id          TEXT NOT NULL,
            started_at           TEXT NOT NULL,
            finished_at          TEXT NOT NULL,
            trigger_source       TEXT NOT NULL,
            window_days          INTEGER NOT NULL,
            rows_scanned         INTEGER NOT NULL,
            rows_rejected_alarm  INTEGER NOT NULL,
            rows_rejected_hampel INTEGER NOT NULL,
            scopes_updated       INTEGER NOT NULL,
            scopes_rolled_back   INTEGER NOT NULL,
            notes                TEXT
        );
        """
    ]
    for q in schema_queries:
        await conn.execute(q)
    await conn.commit()

    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_digest_builder_calculations(temp_db):
    """Verify DailyDigestBuilder correctly aggregates raw telemetry and calculates stats."""
    builder = DailyDigestBuilder(temp_db, building_id="default")
    
    # 1. Insert raw telemetry for a day: ZONE_TEMP room heating up
    date_str = "2026-05-24"
    point_id = "ZONE1_TEMP"
    eq_id = "VAV-01"
    
    # Generate 60 raw readings modulating around 22.0 °C
    readings = []
    base_val = 22.0
    for min_idx in range(60):
        # Sine modulation
        val = base_val + 1.5 * (min_idx % 10 - 5) / 5.0
        ts = f"{date_str}T12:{min_idx:02d}:00"
        readings.append((point_id, ts, eq_id, val, "°c"))

    await temp_db.executemany(
        "INSERT INTO data_points (point_id, timestamp, equipment_id, value, unit) VALUES (?, ?, ?, ?, ?)",
        readings
    )
    await temp_db.commit()

    # 2. Build digest
    inserted, rejected = await builder.build_digest_for_date(date_str)
    assert inserted == 1
    assert rejected == 0

    # 3. Retrieve digest from db and assert values
    async with temp_db.execute("SELECT * FROM point_baselines WHERE point_id = ?", (point_id,)) as cursor:
        digest = await cursor.fetchone()
        assert digest is not None
        assert digest["sample_count"] == 60
        assert abs(digest["mean_val"] - 22.0) < 0.25
        assert digest["std_val"] > 0.0
        assert digest["p95_val"] > digest["mean_val"]
        assert digest["p05_val"] < digest["mean_val"]
        assert digest["is_healthy"] == 1


@pytest.mark.asyncio
async def test_digest_builder_health_filtering(temp_db):
    """Verify DailyDigestBuilder marks a day unhealthy if active alarm duration is >= 5%."""
    builder = DailyDigestBuilder(temp_db, building_id="default")
    
    date_str = "2026-05-24"
    point_id = "CHW_FLOW"
    eq_id = "CH-03"

    # 1. Insert telemetry
    readings = [(point_id, f"{date_str}T10:{m:02d}:00", eq_id, 100.0, "gpm") for m in range(60)]
    await temp_db.executemany(
        "INSERT INTO data_points (point_id, timestamp, equipment_id, value, unit) VALUES (?, ?, ?, ?, ?)",
        readings
    )

    # 2. Insert active alarm that lasted for 2 hours (7200 seconds) which is > 5% of a day (4320 seconds)
    await temp_db.execute("""
        INSERT INTO alarms (alarm_id, equipment_id, state, triggered_at, resolved_at)
        VALUES ('al01', 'CH-03', 'resolved', '2026-05-24T10:00:00', '2026-05-24T12:00:00')
    """)
    await temp_db.commit()

    # 3. Build digest
    inserted, rejected = await builder.build_digest_for_date(date_str)
    assert inserted == 0
    assert rejected == 1

    async with temp_db.execute("SELECT * FROM point_baselines WHERE point_id = ?", (point_id,)) as cursor:
        digest = await cursor.fetchone()
        assert digest["is_healthy"] == 0
        assert digest["alarm_duration_s"] == 7200


@pytest.mark.asyncio
async def test_hampel_filter():
    """Verify Hampel outlier filter removes standard deviation spikes."""
    calibrator = ThresholdCalibrator(None, building_id="default")

    # A stable standard deviation history of 1.0, with a sudden huge spike of 25.0 due to a fault
    stds = [1.0, 1.1, 0.9, 1.05, 0.95, 25.0, 1.0, 1.02, 0.98]
    filtered = calibrator.hampel_filter(stds)

    assert 25.0 not in filtered
    assert len(filtered) == 8


@pytest.mark.asyncio
async def test_threshold_calibrator_hierarchical_resolution(temp_db):
    """Verify hierarchical scope fallback rules: point -> equipment -> type."""
    calibrator = ThresholdCalibrator(temp_db, building_id="default")

    # Insert 15 days of healthy digests for VAV-01 flow point
    point_id = "VAV01_FLOW"
    eq_id = "VAV-01"
    
    digests = []
    for day in range(15):
        date_str = f"2026-05-{day+1:02d}"
        digests.append((
            "default", point_id, eq_id, "vav", "airflow", None, date_str,
            60, 200.0, 10.0, 200.0, 8.0, 185.0, 215.0, 170.0, 230.0, 0, 1
        ))

    await temp_db.executemany("""
        INSERT INTO point_baselines (
            building_id, point_id, equipment_id, equipment_type, point_type, location, date,
            sample_count, mean_val, std_val, median_val, mad_val, p05_val, p95_val, min_val, max_val,
            alarm_duration_s, is_healthy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, digests)
    await temp_db.commit()

    # 1. Point Level Resolution (has >= 14 days)
    scope, digests_found = await calibrator._resolve_hierarchical_digests(point_id, eq_id, "vav", "airflow", 28)
    assert scope == "point"
    assert len(digests_found) == 15

    # 2. Equipment Level Fallback: Delete query point's digests and insert digests
    # for >=3 OTHER distinct points on the same equipment. Spec §4.2 requires
    # ≥3 distinct points before equipment-scope calibration to avoid overfit.
    await temp_db.execute("DELETE FROM point_baselines WHERE point_id = ?", (point_id,))

    other_digests = []
    for sibling in ("VAV01_TEMP", "VAV01_DMPR", "VAV01_CO2"):
        for day in range(15):
            date_str = f"2026-05-{day+1:02d}"
            other_digests.append((
                "default", sibling, eq_id, "vav", "zone_temp", None, date_str,
                60, 22.0, 1.0, 22.0, 0.8, 20.5, 23.5, 19.0, 25.0, 0, 1
            ))
    await temp_db.executemany("""
        INSERT INTO point_baselines (
            building_id, point_id, equipment_id, equipment_type, point_type, location, date,
            sample_count, mean_val, std_val, median_val, mad_val, p05_val, p95_val, min_val, max_val,
            alarm_duration_s, is_healthy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, other_digests)
    await temp_db.commit()

    scope, digests_found = await calibrator._resolve_hierarchical_digests(point_id, eq_id, "vav", "airflow", 28)
    assert scope == "equipment"
    # 3 sibling points × 15 days = 45 raw rows; _query_digests applies LIMIT window_days=28.
    assert len(digests_found) == 28
    # Verify ≥3 distinct point_ids actually made it through the LIMIT
    assert len({d["point_id"] for d in digests_found}) >= 3

    # 2b. Equipment scope must REFUSE if <3 distinct sibling points
    await temp_db.execute("DELETE FROM point_baselines WHERE equipment_id = ?", (eq_id,))
    sparse_digests = []
    for day in range(15):
        date_str = f"2026-05-{day+1:02d}"
        sparse_digests.append((
            "default", "VAV01_TEMP", eq_id, "vav", "zone_temp", None, date_str,
            60, 22.0, 1.0, 22.0, 0.8, 20.5, 23.5, 19.0, 25.0, 0, 1
        ))
    await temp_db.executemany("""
        INSERT INTO point_baselines (
            building_id, point_id, equipment_id, equipment_type, point_type, location, date,
            sample_count, mean_val, std_val, median_val, mad_val, p05_val, p95_val, min_val, max_val,
            alarm_duration_s, is_healthy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sparse_digests)
    await temp_db.commit()

    scope, _ = await calibrator._resolve_hierarchical_digests(point_id, eq_id, "vav", "airflow", 28)
    assert scope != "equipment", "equipment scope must fall through with <3 distinct points"


@pytest.mark.asyncio
async def test_threshold_calibrator_runs_and_promotes(temp_db):
    """Verify calibrator executes full runs, shadow validates, and promotes calibrations."""
    event_bus = MockEventBus()
    calibrator = ThresholdCalibrator(temp_db, event_bus=event_bus, building_id="default")

    # Insert 15 days of healthy digests
    point_id = "CH3_TEMP"
    eq_id = "CH-03"
    digests = []
    for day in range(15):
        date_str = f"2026-05-{day+1:02d}"
        digests.append((
            "default", point_id, eq_id, "chiller", "chw_supply", None, date_str,
            60, 6.0, 0.2, 6.0, 0.15, 5.7, 6.3, 5.5, 6.5, 0, 1
        ))

    await temp_db.executemany("""
        INSERT INTO point_baselines (
            building_id, point_id, equipment_id, equipment_type, point_type, location, date,
            sample_count, mean_val, std_val, median_val, mad_val, p05_val, p95_val, min_val, max_val,
            alarm_duration_s, is_healthy
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, digests)
    await temp_db.commit()

    # Run calibration
    run_id = await calibrator.run_calibration_cycle(trigger_source="manual")
    assert run_id.startswith("cal_")

    # Check that a calibration was saved
    async with temp_db.execute("SELECT * FROM point_calibrations WHERE building_id = ?", ("default",)) as cursor:
        cal = await cursor.fetchone()
        assert cal is not None
        assert cal["scope_level"] == "point"
        assert cal["promoted"] == 1
        # The floor should be at least the bootstrap physics floor of 1.0 for chw_supply
        assert cal["calibrated_floor"] >= 1.0

    # Check EventBus notification was dispatched
    assert len(event_bus.published) == 1
    assert event_bus.published[0]["type"] == "thresholds_recalibrated"


@pytest.mark.asyncio
async def test_watchdog_hot_reload_and_lookup(temp_db):
    """Verify AnomalyWatchdog loads calibrations, registers subscriptions, and performs lookups."""
    event_bus = MockEventBus()
    watchdog = AnomalyWatchdog(
        event_bus=event_bus,
        db_conn=temp_db
    )

    # 1. Insert a mock calibration
    await temp_db.execute("""
        INSERT INTO point_calibrations (
            building_id, scope_key, scope_level, point_type, equipment_type,
            calibrated_floor, calibrated_z_thresh, sample_size_days, rejection_rate_7d,
            fp_target, promoted, last_calibrated_at, next_due_at
        ) VALUES (
            'default', 'point:VAV01_FLOW', 'point', 'airflow', 'vav',
            120.0, 3.5, 28, 0.02, 0.0004, 1, '2026-05-24', '2026-06-24'
        )
    """)
    await temp_db.commit()

    # 2. Force a reload
    await watchdog.reload_thresholds()

    # Assert watchdog has loaded it into its cache
    assert "point:VAV01_FLOW" in watchdog.calibrated_thresholds
    floor, z = watchdog.calibrated_thresholds["point:VAV01_FLOW"]
    assert z == 3.5
    assert floor == 120.0

    # Test lookup
    class DummyPoint:
        def __init__(self, pid, eqid):
            self.point_id = pid
            self.equipment_id = eqid
            self.unit = "cfm"

    point = DummyPoint("VAV01_FLOW", "VAV-01")
    std_floor, z_thresh = watchdog._get_threshold_and_floor(point)
    assert z_thresh == 3.5
    assert std_floor == 120.0

    # 3. Simulate an event-driven hot reload by publishing the recalibration event
    event_bus.publish({
        "type": "thresholds_recalibrated",
        "payload": {"run_id": "cal_123"}
    })

    # Wait for the async task inside watchdog callback to finish
    await asyncio.sleep(0.1)
    assert "point:VAV01_FLOW" in watchdog.calibrated_thresholds


@pytest.mark.asyncio
async def test_calibrator_benchmark_12k_points(temp_db):
    """
    Spec acceptance #6: full calibration on 12,386 distinct points × 28 days
    must complete in <30s. Validates batch-loading optimization holds.

    Seeds synthetic baselines so the calibrator must process realistic
    Marina-scale fanout without per-point query thrashing.
    """
    import time
    import random

    random.seed(42)
    event_bus = MockEventBus()
    calibrator = ThresholdCalibrator(temp_db, event_bus=event_bus, building_id="default")

    eq_types = ["chiller", "ahu", "vav", "fcu", "ct"]
    pt_types_by_eq = {
        "chiller": ["chw_supply", "cop", "load", "power"],
        "ahu": ["sat", "static_pa", "valve", "damper"],
        "vav": ["airflow", "zone_temp", "damper", "co2"],
        "fcu": ["zone_temp", "valve", "airflow"],
        "ct": ["condenser", "power"],
    }
    target_count = 12386
    base_day = datetime(2026, 4, 1)

    digests = []
    for i in range(target_count):
        eq_t = eq_types[i % len(eq_types)]
        pt_t = pt_types_by_eq[eq_t][i % len(pt_types_by_eq[eq_t])]
        point_id = "P{:05d}_{}".format(i, pt_t)
        eq_id = "{}-{:03d}".format(eq_t.upper(), i % 200)
        for day in range(28):
            date_str = (base_day + timedelta(days=day)).strftime("%Y-%m-%d")
            mean = 50.0 + (i % 30)
            std = 2.0 + (i % 5) * 0.3
            digests.append((
                "default", point_id, eq_id, eq_t, pt_t, None, date_str,
                1440, mean, std, mean, std * 0.67,
                mean - 1.6 * std, mean + 1.6 * std,
                mean - 3.0 * std, mean + 3.0 * std,
                0, 1,
            ))

    print("\n[bench] Inserting {} baseline rows...".format(len(digests)))
    t_insert = time.perf_counter()
    chunk = 5000
    for i in range(0, len(digests), chunk):
        await temp_db.executemany("""
            INSERT INTO point_baselines (
                building_id, point_id, equipment_id, equipment_type, point_type,
                location, date, sample_count, mean_val, std_val, median_val, mad_val,
                p05_val, p95_val, min_val, max_val, alarm_duration_s, is_healthy
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, digests[i:i+chunk])
    await temp_db.commit()
    print("[bench] Insert took {:.2f}s".format(time.perf_counter() - t_insert))

    print("[bench] Running calibration cycle on {} points...".format(target_count))
    t_calib = time.perf_counter()
    run_id = await calibrator.run_calibration_cycle(trigger_source="benchmark")
    elapsed = time.perf_counter() - t_calib
    print("[bench] Calibration cycle took {:.2f}s for {} points".format(elapsed, target_count))

    assert elapsed < 30.0, "Calibration took {:.2f}s, spec requires <30s for 12k points".format(elapsed)

    async with temp_db.execute(
        "SELECT scopes_updated, rows_scanned FROM calibration_runs WHERE run_id = ?",
        (run_id,),
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None
        assert row["rows_scanned"] > 0

