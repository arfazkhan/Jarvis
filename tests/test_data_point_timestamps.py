"""
Regression: data_points.timestamp has ONE canonical storage format.

save_data_point / save_data_points_batch used to store raw isoformat(): live
adapters' UTC-aware readings landed as '...+00:00' beside naive-local rows, so
the lexicographic history windows (`timestamp > ?`, `MAX(timestamp)`) and the
`split("+")` reference-time parse were off by the host's UTC offset. Every
writer now stores naive local ISO (what digests/calibrator/FDD already compare),
and legacy rows are rewritten when the schema is verified.
"""
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from agent_commercial.database import BMSDatabase

# Fixed instant far from the wall clock, so history windows must take their
# reference "now" from the stored readings. Mid-January noon UTC keeps clear of
# DST transitions, so local wall-time round-trips exactly.
BASE = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
CANONICAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?$")


def _canonical(instant):
    return instant.astimezone().replace(tzinfo=None).isoformat()


def _ahead_of_host(instant):
    """Aware, in a zone 3 h ahead of this host — raw storage misorders it on
    EVERY host, including a UTC one."""
    host_offset = instant.astimezone().utcoffset()
    return instant.astimezone(timezone(host_offset + timedelta(hours=3)))


# Every way a caller hands over an instant.
REPRESENTATIONS = {
    "aware_utc": lambda i: i.astimezone(timezone.utc),
    "aware_ahead_of_host": _ahead_of_host,
    "naive_local": lambda i: i.astimezone().replace(tzinfo=None),
    "iso_offset_string": lambda i: _ahead_of_host(i).isoformat(),
    "iso_z_string": lambda i: i.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    "space_separated_local_string": lambda i: i.astimezone().replace(tzinfo=None).isoformat(sep=" "),
}


def _stored(path, table="data_points"):
    with closing(sqlite3.connect(path)) as c:
        return [r[0] for r in c.execute(f"SELECT timestamp FROM {table} ORDER BY timestamp")]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", sorted(REPRESENTATIONS))
async def test_save_data_point_stores_canonical_local(tmp_path, kind):
    path = str(tmp_path / "t.db")
    db = BMSDatabase(db_path=path)
    await db.save_data_point("AHU-01/SAT", 14.0, "°C", "AHU-01", timestamp=REPRESENTATIONS[kind](BASE))
    await db.close()

    assert _stored(path) == [_canonical(BASE)]


@pytest.mark.asyncio
async def test_batch_stores_canonical_and_skips_only_bad_rows(tmp_path):
    path = str(tmp_path / "t.db")
    db = BMSDatabase(db_path=path)
    instants = [BASE - timedelta(minutes=m) for m in range(len(REPRESENTATIONS))]
    rows = [{"point_id": "AHU-01/SAT", "equipment_id": "AHU-01", "value": 14.0,
             "timestamp": rep(i)} for rep, i in zip(REPRESENTATIONS.values(), instants)]
    rows.append({"point_id": "AHU-01/SAT", "equipment_id": "AHU-01", "value": 99.0,
                 "timestamp": "not a time"})
    await db.save_data_points_batch(rows)
    await db.close()

    stored = _stored(path)
    assert stored == sorted(_canonical(i) for i in instants)
    assert all(CANONICAL.match(s) for s in stored)


@pytest.mark.asyncio
async def test_point_history_window_with_mixed_writers(tmp_path):
    """Readings at -90/-50/-20/-5/0 min written every which way; a 1 h window
    keeps exactly the last four, whatever the host timezone."""
    db = BMSDatabase(db_path=str(tmp_path / "t.db"))
    reps = ["naive_local", "aware_ahead_of_host", "iso_offset_string", "naive_local", "aware_utc"]
    await db.save_data_points_batch([
        {"point_id": "AHU-01/SAT", "equipment_id": "AHU-01", "value": float(n),
         "timestamp": REPRESENTATIONS[kind](BASE + timedelta(minutes=m))}
        for n, (kind, m) in enumerate(zip(reps, [-90, -50, -20, -5, 0]))
    ])
    history = await db.get_point_history("AHU-01/SAT", hours=1)
    await db.close()

    assert sorted(h["value"] for h in history) == [1.0, 2.0, 3.0, 4.0]


def _legacy_db(path, timestamps):
    """A data_points table written by the old raw-isoformat() writers."""
    with closing(sqlite3.connect(path)) as c:
        c.execute("""CREATE TABLE data_points (point_id TEXT, equipment_id TEXT, value REAL,
                     unit TEXT, quality TEXT DEFAULT 'good', timestamp TEXT,
                     PRIMARY KEY (point_id, timestamp))""")
        c.executemany("INSERT INTO data_points VALUES ('AHU-01/SAT', 'AHU-01', ?, '°C', 'good', ?)",
                      [(float(n), ts) for n, ts in enumerate(timestamps)])
        c.commit()


@pytest.mark.asyncio
async def test_schema_init_canonicalizes_legacy_rows(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path, [
        (BASE - timedelta(minutes=90)).isoformat(),                      # '+00:00'
        _ahead_of_host(BASE - timedelta(minutes=30)).isoformat(),        # foreign offset
        REPRESENTATIONS["space_separated_local_string"](BASE - timedelta(minutes=20)),
        (BASE - timedelta(minutes=10)).astimezone().replace(tzinfo=None, microsecond=123000)
            .isoformat(timespec="milliseconds"),                         # 3-digit fraction
        _canonical(BASE),                                                # already canonical
        BASE.isoformat(),                                                # same instant, legacy copy
        "garbage",
    ])

    db = BMSDatabase(db_path=path)
    history = await db.get_point_history("AHU-01/SAT", hours=1)
    await db.close()

    assert _stored(path) == [
        _canonical(BASE - timedelta(minutes=90)),
        _canonical(BASE - timedelta(minutes=30)),
        _canonical(BASE - timedelta(minutes=20)),
        _canonical((BASE - timedelta(minutes=10)).replace(microsecond=123000)),
        _canonical(BASE),                    # legacy duplicate collapsed into one row
    ]
    assert _stored(path, "data_points_quarantine") == ["garbage"]   # kept, not deleted
    # Window measured from the newest real reading: -30/-20/-10/0 min.
    assert len(history) == 4 and all(CANONICAL.match(h["timestamp"]) for h in history)

    # Idempotent: a second schema verification changes nothing.
    db = BMSDatabase(db_path=path)
    await db._get_async_connection()
    await db.close()
    assert len(_stored(path)) == 5 and _stored(path, "data_points_quarantine") == ["garbage"]


@pytest.mark.asyncio
async def test_historical_telemetry_window_with_mixed_writers(tmp_path):
    from agent_commercial.bms_state_engine import BMSStateEngine
    db = BMSDatabase(db_path=str(tmp_path / "t.db"))
    reps = ["naive_local", "aware_ahead_of_host", "iso_z_string", "aware_utc"]
    hours_back = [30, 20, 2, 0]
    await db.save_data_points_batch([
        {"point_id": "CH-01/CHWST", "equipment_id": "CH-01", "value": float(n),
         "timestamp": REPRESENTATIONS[kind](BASE - timedelta(hours=h))}
        for n, (kind, h) in enumerate(zip(reps, hours_back))
    ])
    engine = BMSStateEngine()
    engine.db = db
    df = await engine.get_historical_telemetry("CH-01", days=1)
    await db.close()

    assert list(df["CHWST"]) == [1.0, 2.0, 3.0]
    assert list(df["timestamp"]) == [_canonical(BASE - timedelta(hours=h)) for h in (20, 2, 0)]
