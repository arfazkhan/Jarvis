"""Verify (A) WatchManager wake/sleep loop and (B) ThresholdCalibrator.assess_ops_readiness."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_commercial.watch import WatchManager


class _Pt:
    def __init__(self, pid, val): self.point_id, self.value = pid, val


class _FakeState:
    def __init__(self): self.val = 24.0
    async def get_points_by_equipment(self, eq):
        return [_Pt("AHU-07/MAT", self.val)]


async def test_watch_timeout():
    st = _FakeState()
    wm = WatchManager(bms_state=st)
    await wm.schedule("AHU-07", "AHU-07/MAT", "confirm drift", est_seconds=0.2, kind="drift_confirm")
    async def recheck(w, changed, due): return ("resolved", {"why": "change" if changed else "timeout"})
    ws = await wm.run(recheck, max_cycles=3, poll_cap_seconds=1.0)
    assert ws[0].resolved and "timeout" in ws[0].woke_on
    print("  A1 timeout-wake:", ws[0].woke_on, "PASS")


async def test_watch_change():
    st = _FakeState()
    wm = WatchManager(bms_state=st)
    await wm.schedule("AHU-07", "AHU-07/MAT", "confirm drift", est_seconds=5.0, kind="drift_confirm")
    async def bump():
        await asyncio.sleep(0.3); st.val = 30.8   # telemetry moves → should wake early
    async def recheck(w, changed, due): return ("resolved", {"changed": changed})
    asyncio.ensure_future(bump())
    ws = await wm.run(recheck, max_cycles=4, poll_cap_seconds=0.5)
    assert ws[0].resolved and "change" in ws[0].woke_on
    print("  A2 change-wake (early):", ws[0].woke_on, "PASS")


async def test_readiness():
    import aiosqlite
    from agent_commercial.threshold_calibrator import ThresholdCalibrator
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("CREATE TABLE point_calibrations (building_id TEXT, promoted INTEGER, sample_size_days INTEGER)")
    cal = ThresholdCalibrator(db_conn=conn, event_bus=None, building_id="default")

    # Cold: few promoted, thin days → NOT ready, recommends extension.
    await conn.executemany("INSERT INTO point_calibrations VALUES (?,?,?)",
                           [("default", 0, 5), ("default", 1, 6), ("default", 0, 4)])
    await conn.commit()
    v1 = await cal.assess_ops_readiness()
    assert v1["ready"] is False and v1["suggested_extra_days"] > 0
    print("  B1 cold:", v1["summary"][:80], "PASS")

    # Settled: most scopes promoted, enough days → READY.
    await conn.execute("DELETE FROM point_calibrations")
    await conn.executemany("INSERT INTO point_calibrations VALUES (?,?,?)",
                           [("default", 1, 30), ("default", 1, 31), ("default", 1, 29), ("default", 1, 30)])
    await conn.commit()
    v2 = await cal.assess_ops_readiness()
    assert v2["ready"] is True and v2["coverage"] >= 0.8
    print("  B2 settled:", v2["summary"][:80], "PASS")
    await conn.close()


async def main():
    print("A — WatchManager wake/sleep:")
    await test_watch_timeout(); await test_watch_change()
    print("B — calibration readiness verdict:")
    await test_readiness()
    print("\nRESULT: PASS — commercial watch loop + readiness verdict verified")


if __name__ == "__main__":
    asyncio.run(main())
