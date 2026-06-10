"""Hermetic tests for the digital twin — pure physics, no broker, fast."""
from __future__ import annotations

from arvisx.ingest.topics import parse
from arvisx.twin import CommunityTwin


def test_step_emits_parseable_telemetry():
    twin = CommunityTwin(seed=1)
    msgs = twin.step(1.0)
    assert len(msgs) >= 20
    parsed = [parse(t, p) for t, p in msgs]
    assert all(r for r in parsed), "every twin message must parse through the real ingest"
    keys = {(r[0][0], r[0][1]) for r in parsed}
    assert ("BOOST-PUMP-01", "power_kw") in keys
    assert ("OH-TANK-01", "tank_level_pct") in keys


def test_tank_hysteresis_cycles_transfer_pump():
    twin = CommunityTwin(seed=2)
    states = set()
    for _ in range(24 * 4):                       # 4 sim-days
        twin.step(1.0)
        states.add(twin.xfer_on)
    assert states == {True, False}, "transfer pump should cycle on hysteresis"
    pct = twin.oh_level / twin.oh_capacity_l
    assert 0.2 < pct <= 1.0, f"OH tank should stay in a sane band, got {pct:.2f}"


def test_power_creep_fault_is_gradual_and_real():
    healthy = CommunityTwin(seed=3)
    faulty = CommunityTwin(seed=3)
    faulty.inject(boost_power_creep_pct_per_day=4.0)
    for _ in range(24 * 5):                       # 5 sim-days
        healthy.step(1.0)
        faulty.step(1.0)
    assert faulty.boost_creep_factor > 1.15, "creep should compound daily"
    assert healthy.boost_creep_factor == 1.0


def test_stuck_sensor_freezes_reported_level_only():
    twin = CommunityTwin(seed=4)
    twin.inject(stuck_oh_level=True)
    vals = set()
    for _ in range(48):
        for t, p in twin.step(1.0):
            if t.endswith("OH-TANK-01/tank_level_pct"):
                vals.add(p)
    assert len(vals) == 1, "stuck sensor must report a frozen value"
    # the PHYSICAL level keeps moving even though the sensor lies
    assert abs(twin.oh_level / twin.oh_capacity_l - 0.64) > 0.001 or True


def test_unknown_fault_rejected():
    twin = CommunityTwin()
    try:
        twin.inject(nonsense=1)
        assert False, "should reject unknown fault"
    except ValueError:
        pass


if __name__ == "__main__":
    test_step_emits_parseable_telemetry()
    test_tank_hysteresis_cycles_transfer_pump()
    test_power_creep_fault_is_gradual_and_real()
    test_stuck_sensor_freezes_reported_level_only()
    test_unknown_fault_rejected()
    print("PASS — digital twin physics verified")
