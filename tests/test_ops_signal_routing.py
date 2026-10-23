"""
Phase 1 — every monitoring signal reaches the one event bus, in one shape.

Real: BMSStateEngine, EventBus, AnomalyWatchdog buffer, WatchManager service loop,
InvestigationDispatcher, TerminalAdvisoryStore (temp SQLite), FieldCheckService,
BACnetAdapter status-flag handling, MonitoringHealthWatcher. Scripted: the Queen
(the multi-agent LLM run) and adapter get_stats().
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_commercial.bms_data_model import Alarm, AlarmSeverity, BMSDataPoint, Equipment
from agent_commercial.bms_state_engine import BMSStateEngine
from agent_commercial.main import OpsCopilot
from agent_commercial.ops_engineer.signals import to_signals
from arvis_core.event_bus.event_bus import EventBus


class Recorder:
    """Subscribes to every event type on a real bus."""
    def __init__(self, bus):
        self.events = []
        bus.subscribe("*", self.events.append)

    def of(self, t):
        return [e for e in self.events if e["type"] == t]


def _ops(bus, **kw):
    ns = SimpleNamespace(_event_bus=bus, **kw)
    ns._publish = lambda t, p: OpsCopilot._publish(ns, t, p)
    return ns


# ── alarms ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bms_alarms_are_published_and_life_safety_is_recognised():
    bus, state = EventBus(), BMSStateEngine()
    rec = Recorder(bus)
    ops = _ops(bus)
    state.on_alarm(lambda a: OpsCopilot._publish_alarm_raised(ops, a))
    state.on_alarm_resolved(lambda e: OpsCopilot._publish_alarm_cleared(ops, e))

    smoke = Alarm(equipment_id="L3", message="Smoke detected level 3 corridor", severity=AlarmSeverity.HIGH)
    hot = Alarm(equipment_id="AHU-07", message="High supply air temperature", severity=AlarmSeverity.MEDIUM)
    await state.add_alarm(smoke)
    await state.add_alarm(hot)
    await state.resolve_alarm(hot.alarm_id)

    (s_smoke,) = to_signals(rec.of("bms_alarm_raised")[0])
    assert s_smoke.safety and s_smoke.severity == "critical" and s_smoke.topic == f"alarm:{smoke.alarm_id}"
    (s_hot,) = to_signals(rec.of("bms_alarm_raised")[1])
    assert not s_hot.safety and s_hot.severity == "medium"
    (s_clear,) = to_signals(rec.of("bms_alarm_cleared")[0])
    assert s_clear.clears == f"alarm:{hot.alarm_id}"


def test_bacnet_in_alarm_flag_raises_and_clears_after_confirmation():
    from agent_commercial.bacnet_adapter import BACnetAdapter, BACnetPoint
    ad = BACnetAdapter()
    raised, cleared = [], []
    ad.on_alarm(raised.append)
    ad.on_alarm_cleared(cleared.append)
    cfg = BACnetPoint(device_id=1, object_type="analogInput", object_instance=1, point_id="AHU-07/SAT",
                      point_name="Supply air temp", equipment_id="AHU-07", unit="°C", alarm_severity="high")
    on, off = [1, 0, 0, 0], [0, 0, 0, 0]
    ad._make_point(cfg, 19.5, on)
    assert raised == []                                         # one read is not enough (flicker)
    ad._make_point(cfg, 19.6, on)
    ad._make_point(cfg, 19.7, on)
    assert len(raised) == 1 and raised[0].severity == AlarmSeverity.HIGH and raised[0].equipment_id == "AHU-07"
    ad._make_point(cfg, 14.0, off)
    assert cleared == []
    ad._make_point(cfg, 13.9, off)
    assert cleared == [raised[0].alarm_id]
    ad._make_point(cfg, 13.9, None)                             # flags unavailable: no claim
    assert len(raised) == 1


# ── autonomous investigations ────────────────────────────────────────────────
class ScriptedQueen:
    def __init__(self, abstained=False):
        self.queries = []
        self.abstained = abstained

    async def execute_swarm(self, query, context=None, channel="chat"):
        self.queries.append(query)
        return {"advice": "Chilled-water valve on AHU-07 is not opening; check the actuator.",
                "confidence": 0.7, "abstained": self.abstained, "plan": SimpleNamespace(id="plan-1"),
                "context": {}}


def _dispatcher(bus, queen, **kw):
    from agent_commercial.investigation_dispatcher import InvestigationDispatcher
    return InvestigationDispatcher(queen=queen, bms_state=BMSStateEngine(), event_bus=bus, **kw)


@pytest.mark.asyncio
async def test_investigation_conclusion_is_published_not_lost():
    bus = EventBus()
    rec = Recorder(bus)
    d = _dispatcher(bus, ScriptedQueen())
    await d.investigate_alarm(Alarm(equipment_id="AHU-07", message="High SAT", severity=AlarmSeverity.HIGH))
    (ev,) = rec.of("investigation_concluded")
    assert ev["payload"]["confidence"] == 0.7 and ev["payload"]["plan_id"] == "plan-1"
    (sig,) = to_signals(ev)
    assert sig.llm_origin and "actuator" in sig.facts

    bus2 = EventBus()
    rec2 = Recorder(bus2)
    await _dispatcher(bus2, ScriptedQueen(abstained=True)).investigate_alarm(
        Alarm(equipment_id="AHU-07", message="High SAT", severity=AlarmSeverity.HIGH))
    assert to_signals(rec2.of("investigation_concluded")[0]) == []                # abstained: nothing to say


@pytest.mark.asyncio
async def test_daily_cap_and_busy_anomalies_are_watched_not_dropped(monkeypatch):
    from agent_commercial.anomaly_watchdog import AnomalyEvent
    monkeypatch.setenv("ARVIS_DISPATCH_MAX_PER_DAY", "1")
    queen = ScriptedQueen()
    d = _dispatcher(EventBus(), queen, cooldown_per_equipment=0)
    a = AnomalyEvent(point_id="AHU-07/SAT", equipment_id="AHU-07", current_value=19, expected_value=13,
                     deviation_pct=46, z_score=5, severity="critical")
    await d.investigate_anomaly(a)
    await d.investigate_anomaly(a)
    assert len(queen.queries) == 1                                                  # capped
    assert d.get_stats()["open_watches"] == 1                                       # …but watched


@pytest.mark.asyncio
async def test_drift_is_confirmed_only_by_repeats(monkeypatch):
    from agent_commercial.anomaly_watchdog import AnomalyEvent, AnomalyWatchdog
    monkeypatch.setenv("ARVIS_DRIFT_MIN_REPEATS", "3")
    bus = EventBus()
    rec = Recorder(bus)
    wd = AnomalyWatchdog()
    queen = ScriptedQueen()
    d = _dispatcher(bus, queen, watchdog=wd)
    d.start_watch_loop()

    def anomaly(pid):
        return AnomalyEvent(point_id=pid, equipment_id="AHU-07", current_value=17, expected_value=13,
                            deviation_pct=30, z_score=3.2, severity="significant")
    try:
        await d.schedule_drift_confirmation(anomaly("AHU-07/SAT"), window_seconds=0.3)   # will repeat
        await d.schedule_drift_confirmation(anomaly("AHU-07/RAT"), window_seconds=0.3)   # one-off
        for _ in range(3):
            wd._anomaly_buffer.append(anomaly("AHU-07/SAT"))
        wd._anomaly_buffer.append(anomaly("AHU-07/RAT"))
        for _ in range(60):
            if len(rec.of("drift_watch_outcome")) >= 2:
                break
            await asyncio.sleep(0.05)
        outcomes = {e["payload"]["point_id"]: e["payload"]["status"] for e in rec.of("drift_watch_outcome")}
        assert outcomes == {"AHU-07/SAT": "confirmed", "AHU-07/RAT": "cleared"}
        assert len(queen.queries) == 1 and "AHU-07/SAT" in queen.queries[0]           # only the real drift
        assert rec.of("investigation_concluded")[0]["payload"]["trigger"] == "watch_drift_confirm"
    finally:
        d.stop_watch_loop()


# ── advisories, field checks, FDD cleared ────────────────────────────────────
@pytest.mark.asyncio
async def test_new_terminal_advisory_fires_hook_once(tmp_path):
    from agent_commercial.terminal_advisory_store import TerminalAdvisoryStore
    store = TerminalAdvisoryStore(db_path=str(tmp_path / "ta.db"))
    fired = []
    store.on_fired = fired.append
    for _ in range(2):
        await store.fire(equipment_id="CH-01", advisory_type="predictive_failure", severity="critical",
                         title="CH-01 compressor at risk", message="Bearing temperature rising 2 °C/day")
    assert len(fired) == 1                                                          # dedupe bump is not news
    (sig,) = to_signals({"type": "terminal_advisory_fired", "payload": fired[0]})
    assert sig.llm_origin and sig.severity == "critical"


@pytest.mark.asyncio
async def test_expired_check_tells_whoever_asked(tmp_path):
    from agent_commercial.database import BMSDatabase
    from agent_commercial.fdd.diagnosis import process_findings
    from agent_commercial.field_checks import FieldCheckService
    from tests.test_field_checks import RecordingTransport, _f, ALI
    db = BMSDatabase(db_path=str(tmp_path / "fc.db"))
    (case,) = await process_findings(db, [_f("FAHU-1", "FC14")])
    svc = FieldCheckService(db, RecordingTransport(), roster={ALI: "Ali"})
    changes = []
    svc.on_change = lambda c, status: changes.append({**c.to_dict(), "status": status})
    check = await svc.request(case.id, ALI, requested_by="+974 5550 1111")
    conn = await svc._conn()
    await conn.execute("UPDATE field_checks SET created_at='2000-01-01T00:00:00' WHERE id=?", (check.id,))
    await conn.commit()
    await svc.list_checks()
    (sig,) = to_signals({"type": "field_check_changed", "payload": changes[0]})
    assert sig.audience == ["97455501111"] and "no answer in time" in sig.facts
    await db.close()


def test_cleared_fault_ends_the_fault_topic():
    (sig,) = to_signals({"type": "fdd_fault_cleared", "payload": {"cleared": [
        {"equipment_id": "AHU-07", "rule_id": "FC13", "title": "SAT high", "headline": "AHU-07: SAT high"}]}})
    assert sig.clears == "fault:AHU-07:FC13" and sig.severity == "info"


# ── monitoring health ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_monitoring_blind_then_restored_and_data_source_follows(monkeypatch):
    from agent_commercial.monitoring_health import MonitoringHealthWatcher
    monkeypatch.setenv("ARVIS_BLIND_CONFIRM_S", "120")
    bus, state = EventBus(), BMSStateEngine()
    rec = Recorder(bus)
    await state.register_equipment(Equipment(equipment_id="AHU-07", name="AHU-07"))
    t0 = datetime.now(timezone.utc)

    async def reading(at):
        await state.update_point(BMSDataPoint(point_id="AHU-07/SAT", name="SAT", value=13.0,
                                              equipment_id="AHU-07", timestamp=at))
    stats = {"is_connected": True, "polling_active": True, "stale_points": []}
    adapter = SimpleNamespace(get_stats=lambda: stats)
    ops = _ops(bus, mode="bacnet", state_engine=state, bacnet_adapter=adapter, data_source="LIVE")
    w = MonitoringHealthWatcher(ops, ops._publish)

    await reading(t0)
    assert w.check_once(t0) is None and w.state == "ok"
    stats["is_connected"] = False                                    # link drops; no new readings
    late = t0 + timedelta(minutes=15)
    assert w.check_once(late) is None                                # not confirmed yet (hysteresis)
    assert w.check_once(late + timedelta(minutes=3)) == "monitoring_blind"
    assert ops.data_source == "UNAVAILABLE" and w.check_once(late + timedelta(minutes=4)) is None   # once
    (blind,) = to_signals(rec.of("monitoring_blind")[0])
    assert blind.safety and blind.severity == "critical" and "DISCONNECTED" in blind.facts

    stats["is_connected"] = True
    back = late + timedelta(minutes=30)
    await reading(back)
    assert w.check_once(back) is None                                # one healthy check is not enough
    assert w.check_once(back + timedelta(minutes=1)) == "monitoring_restored"
    assert ops.data_source == "LIVE"
    (restored,) = to_signals(rec.of("monitoring_restored")[0])
    assert restored.clears == "monitoring:blind" and "restored after" in restored.facts


def test_simulator_is_not_watched():
    from agent_commercial.monitoring_health import MonitoringHealthWatcher
    ops = _ops(EventBus(), mode="simulator", state_engine=BMSStateEngine())
    assert MonitoringHealthWatcher(ops, ops._publish).check_once() is None
