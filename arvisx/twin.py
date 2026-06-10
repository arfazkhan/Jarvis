"""
ArvisX digital twin — a continuously-running physics simulation of the community's
devices, publishing live telemetry over MQTT exactly like a deployed edge gateway.

The static simulator (simulator.py) produces snapshots for demos/tests. This twin is
for DEPLOYMENT-FIDELITY testing: tank levels actually drain with a diurnal demand
curve, the transfer pump cycles on hysteresis, the generator runs its weekly test and
its battery sags between charges, runtime hours accumulate — so the full production
path (broker → ingest → store → learning → drift → watcher → alerts) runs against
evolving data, not a posed scene.

Design mirrors the ingest layer: a PURE core (`CommunityTwin.step(dt_hours)` returns
(topic, payload) messages — fully testable, no network) + a thin paho publisher shell
(`TwinPublisher`). Faults are injected as gradual physical processes (power creep,
tank leak, battery decay, stuck sensor), not instant scene changes — because that's
what ArvisX must catch in the field.

Time model: `step(dt_hours)` advances the sim clock by dt sim-hours; the runner picks
the real-time pacing (e.g. 1 sim-hour per 0.5s ≈ a week of building life in ~84s).
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

Msg = Tuple[str, str]   # (topic, payload)


def _diurnal_demand(hour: float) -> float:
    """Residential water-demand multiplier over the day (morning + evening peaks)."""
    morning = math.exp(-((hour - 7.5) ** 2) / 4.0)
    evening = math.exp(-((hour - 19.5) ** 2) / 6.0)
    return 0.25 + 1.1 * morning + 0.9 * evening


def _cooking_demand(hour: float) -> float:
    """Cooking-gas demand multiplier (breakfast/lunch/dinner peaks)."""
    bkfst = math.exp(-((hour - 7.0) ** 2) / 1.5)
    lunch = math.exp(-((hour - 12.5) ** 2) / 2.0)
    dinner = math.exp(-((hour - 19.5) ** 2) / 2.5)
    return 0.05 + 1.0 * bkfst + 0.7 * lunch + 1.2 * dinner


@dataclass
class Faults:
    """Active fault processes — gradual, physical, the way real equipment degrades."""
    boost_power_creep_pct_per_day: float = 0.0   # bearing wear → power climbs
    oh_tank_leak_lph: float = 0.0                # overhead tank losing water
    gen_battery_decay_v_per_day: float = 0.0     # battery aging
    stuck_oh_level: bool = False                 # OH level sensor frozen (sensor fault)
    gas_leak_ppm: float = 0.0                    # gas concentration at the plant
    gas_pressure_drift_bar_per_day: float = 0.0  # regulator drifting out of band


class CommunityTwin:
    """Physics state for the 12-asset community. step() advances time and emits the
    MQTT messages a real edge gateway would publish that interval."""

    def __init__(self, start: Optional[datetime] = None, seed: int = 11, prefix: str = "arvisx"):
        self.rng = random.Random(seed)
        self.prefix = prefix
        self.now = start or datetime(2026, 6, 1, 0, 0)
        self.faults = Faults()

        # ── Water ────────────────────────────────────────────────────────
        self.ug_capacity_l, self.oh_capacity_l = 50_000.0, 20_000.0
        self.ug_level = 0.80 * self.ug_capacity_l       # litres
        self.oh_level = 0.70 * self.oh_capacity_l
        self.municipal_inflow_lph = 2_500.0             # refills UG tank
        self.base_demand_lph = 1_400.0                  # community average draw from OH
        self.xfer_on = False                            # transfer pump UG→OH (hysteresis)
        self.xfer_flow_lph = 6_000.0
        self.xfer_power_kw, self.boost_power_kw = 5.4, 3.1
        self.xfer_runtime_h, self.boost_runtime_h = 4200.0, 6100.0
        self.xfer_starts = self.boost_starts = 0
        self.boost_creep_factor = 1.0                   # grows under the creep fault

        # ── Power backup ─────────────────────────────────────────────────
        self.gen_fuel_pct = 78.0
        self.gen_battery_v = 12.8
        self.gen_runtime_h = 910.0
        self.gen_test_weekday, self.gen_test_hour = 2, 10   # Wednesday 10:00, 0.5h test
        self.gen_running = False

        # ── Gas plant + per-apartment meters ─────────────────────────────
        self.gas_level_pct = 82.0                       # LPG bank
        self.gas_pressure_bar = 0.5                     # regulated line pressure
        self.n_apartments = 12                          # twin-scale flat count
        # cumulative meter index (m³) per flat, with per-flat usage personality
        self.gas_meters = {f"APT-{100 + i}": 150.0 + self.rng.uniform(0, 400)
                           for i in range(1, self.n_apartments + 1)}
        self._gas_usage_factor = {k: self.rng.uniform(0.6, 1.6) for k in self.gas_meters}

        # ── STP / Pool / Fire ────────────────────────────────────────────
        self.stp_runtime_today = 0.0
        self.stp_blower_runtime_h = 12_000.0
        self.pool_runtime_today = 0.0
        self.pool_window = (6, 14)                      # filtration schedule 06:00–14:00
        self.fire_next_test = self.now + timedelta(days=20)
        self._day = self.now.date()
        self._frozen_oh_pct: Optional[float] = None     # captured when the sensor sticks

    # ── fault injection (gradual processes) ──────────────────────────────
    def inject(self, **kwargs):
        for k, v in kwargs.items():
            if not hasattr(self.faults, k):
                raise ValueError(f"unknown fault '{k}'")
            setattr(self.faults, k, v)

    # ── physics step ─────────────────────────────────────────────────────
    def step(self, dt_hours: float = 1.0) -> List[Msg]:
        f, rng = self.faults, self.rng
        self.now += timedelta(hours=dt_hours)
        hour = self.now.hour + self.now.minute / 60.0
        if self.now.date() != self._day:                 # midnight rollover
            self._day = self.now.date()
            self.stp_runtime_today = self.pool_runtime_today = 0.0
            self.xfer_starts = self.boost_starts = 0
            self.boost_creep_factor *= (1 + f.boost_power_creep_pct_per_day / 100.0)
            self.gen_battery_v = max(10.5, self.gen_battery_v - f.gen_battery_decay_v_per_day)

        # Water: community drains OH tank; UG refills from municipal line.
        demand = self.base_demand_lph * _diurnal_demand(hour) * rng.uniform(0.92, 1.08)
        self.oh_level -= (demand + f.oh_tank_leak_lph) * dt_hours
        self.ug_level = min(self.ug_capacity_l, self.ug_level + self.municipal_inflow_lph * dt_hours)

        # Transfer pump hysteresis: ON below 45% OH, OFF above 85%.
        oh_pct = self.oh_level / self.oh_capacity_l
        if not self.xfer_on and oh_pct < 0.45:
            self.xfer_on = True
            self.xfer_starts += 1
        elif self.xfer_on and oh_pct > 0.85:
            self.xfer_on = False
        if self.xfer_on:
            moved = min(self.xfer_flow_lph * dt_hours, self.ug_level)
            self.ug_level -= moved
            self.oh_level = min(self.oh_capacity_l, self.oh_level + moved)
            self.xfer_runtime_h += dt_hours
        self.oh_level = max(0.0, self.oh_level)

        # Booster runs whenever there is demand; its power carries the creep fault.
        boosting = demand > 300
        if boosting:
            self.boost_runtime_h += dt_hours
            if rng.random() < 0.25 * dt_hours:
                self.boost_starts += 1
        boost_kw = self.boost_power_kw * self.boost_creep_factor * rng.uniform(0.98, 1.02)

        # Generator: weekly 30-min test; battery floats back up after a healthy test.
        was_running = self.gen_running
        self.gen_running = (self.now.weekday() == self.gen_test_weekday
                            and self.gen_test_hour <= hour < self.gen_test_hour + 0.5)
        if self.gen_running:
            self.gen_runtime_h += dt_hours
            self.gen_fuel_pct = max(5.0, self.gen_fuel_pct - 1.2 * dt_hours)
            if f.gen_battery_decay_v_per_day == 0:
                self.gen_battery_v = min(12.9, self.gen_battery_v + 0.05)
        _ = was_running

        # Gas: each flat cooks on the breakfast/lunch/dinner curve; the bank drains
        # with total consumption; line pressure holds unless the regulator drifts.
        cook = _cooking_demand(hour)
        total_m3 = 0.0
        for k in self.gas_meters:
            used = 0.012 * cook * self._gas_usage_factor[k] * rng.uniform(0.85, 1.15) * dt_hours
            self.gas_meters[k] += used
            total_m3 += used
        self.gas_level_pct = max(2.0, self.gas_level_pct - total_m3 * 0.06)   # bank drain
        self.gas_pressure_bar += f.gas_pressure_drift_bar_per_day * dt_hours / 24.0

        # STP: aeration tracks waste-water (follows demand); Pool: fixed schedule.
        if demand > 400:
            self.stp_runtime_today += dt_hours
            self.stp_blower_runtime_h += dt_hours
        if self.pool_window[0] <= hour < self.pool_window[1]:
            self.pool_runtime_today += dt_hours

        return self._emit(boosting, boost_kw)

    # ── telemetry emission (what the edge gateway would publish) ─────────
    def _emit(self, boosting: bool, boost_kw: float) -> List[Msg]:
        rng, p = self.rng, self.prefix
        oh_true = round(100 * self.oh_level / self.oh_capacity_l, 1)
        if self.faults.stuck_oh_level:
            if self._frozen_oh_pct is None:
                self._frozen_oh_pct = oh_true        # sensor dies: freezes at its last reading
            oh_reported = self._frozen_oh_pct
        else:
            self._frozen_oh_pct = None
            oh_reported = oh_true

        def m(asset, signal, value) -> Msg:
            return (f"{p}/{asset}/{signal}",
                    json.dumps(value) if isinstance(value, bool) else str(value))

        return [
            m("UG-TANK-01", "tank_level_pct", round(100 * self.ug_level / self.ug_capacity_l, 1)),
            m("UG-TANK-01", "tank_capacity_l", self.ug_capacity_l),
            m("OH-TANK-01", "tank_level_pct", oh_reported),
            m("OH-TANK-01", "tank_capacity_l", self.oh_capacity_l),
            m("XFER-PUMP-01", "power_kw", round(self.xfer_power_kw * rng.uniform(0.97, 1.03), 2)
              if self.xfer_on else 0.0),
            m("XFER-PUMP-01", "starts_today", self.xfer_starts),
            m("XFER-PUMP-01", "runtime_hours", round(self.xfer_runtime_h, 1)),
            m("BOOST-PUMP-01", "power_kw", round(boost_kw, 2) if boosting else 0.0),
            m("BOOST-PUMP-01", "starts_today", self.boost_starts),
            m("BOOST-PUMP-01", "runtime_hours", round(self.boost_runtime_h, 1)),
            m("GEN-01", "fuel_level_pct", round(self.gen_fuel_pct, 1)),
            m("GEN-01", "fault", False),
            m("GEN-01", "runtime_hours", round(self.gen_runtime_h, 1)),
            m("GEN-BATT-01", "battery_voltage", round(self.gen_battery_v + rng.uniform(-0.03, 0.03), 2)),
            m("STP-BLOWER-01", "runtime_today_hours", round(self.stp_runtime_today, 1)),
            m("STP-BLOWER-01", "power_kw", round(7.5 * rng.uniform(0.97, 1.03), 2)),
            m("STP-PUMP-01", "runtime_today_hours", round(self.stp_runtime_today * 0.5, 1)),
            m("POOL-FILT-01", "runtime_today_hours", round(self.pool_runtime_today, 1)),
            m("POOL-FILT-01", "expected_runtime_hours", 8.0),
            m("POOL-DOSE-01", "water_quality_ph", round(7.4 + rng.uniform(-0.05, 0.05), 2)),
            m("FIRE-PANEL-01", "active_faults", 0),
            m("FIRE-PUMP-01", "next_test_due", self.fire_next_test.isoformat()),
            m("GAS-PLANT-01", "tank_level_pct", round(self.gas_level_pct, 1)),
            m("GAS-PLANT-01", "line_pressure_bar",
              round(self.gas_pressure_bar + rng.uniform(-0.01, 0.01), 3)),
            m("GAS-PLANT-01", "leak_ppm", round(self.faults.gas_leak_ppm, 1)),
        ] + [
            m(meter_id, "meter_total_m3", round(idx, 3))
            for meter_id, idx in self.gas_meters.items()
        ]


class TwinPublisher:
    """Thin paho shell: pushes each step's messages to a real broker."""

    def __init__(self, twin: CommunityTwin, broker: str = "127.0.0.1", port: int = 1883):
        import paho.mqtt.client as mqtt
        self.twin = twin
        self.client = mqtt.Client(client_id="arvisx-twin")
        self.client.connect(broker, port, 30)
        self.client.loop_start()
        self.published = 0

    def publish_step(self, dt_hours: float = 1.0) -> int:
        msgs = self.twin.step(dt_hours)
        for topic, payload in msgs:
            self.client.publish(topic, payload, qos=1)
        self.published += len(msgs)
        return len(msgs)

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
