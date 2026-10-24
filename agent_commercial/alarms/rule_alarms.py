"""
Alarms for every source, from a rule on the point.

Only BACnet devices report their own alarm state. A Modbus genset, a lift's fault
contact on an I/O module, an MQTT tank sensor or a hand-read gauge can still
alarm: the point's config says when.

    - {point_id: LIFT-1/FAULT, ..., alarm_when: {op: "==", value: 1, severity: high,
                                                 message: "Lift 1 is in fault"}}
    - {point_id: TX-1/TEMP, ..., alarm_when: {op: ">", value: 110, for_s: 300, clear_below: 100,
                                              severity: high, message: "Transformer 1 running hot"}}
    - {point_id: TANK-1/LVL, ..., alarm_when: {op: "<", value: 20, clear_above: 30, severity: medium}}

  op          >  >=  <  <=  ==  !=
  for_s       the condition must hold this long (by reading time) before it alarms
  clear_below / clear_above   hysteresis: where it clears (default: where it started)
  severity    critical | high | medium | low | info  (default medium)

Raised alarms go through BMSStateEngine.add_alarm / resolve_alarm — the same path
as BACnet alarms — so the event bus, attention gate and WhatsApp handle them unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("arvis.alarms.rules")

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}


@dataclass
class AlarmRule:
    point_id: str
    equipment_id: str
    op: str
    value: float
    for_s: float = 0.0
    clear_at: Optional[float] = None
    severity: str = "medium"
    message: str = ""

    def triggered(self, v: float) -> bool:
        return _OPS[self.op](v, self.value)

    def cleared(self, v: float) -> bool:
        if self.clear_at is None or self.op in ("==", "!="):
            return not self.triggered(v)
        return v <= self.clear_at if self.op in (">", ">=") else v >= self.clear_at


def rule_from_config(entry: Dict[str, Any]) -> Optional[AlarmRule]:
    spec = entry.get("alarm_when")
    if not spec:
        return None
    op = str(spec.get("op", ">")).strip()
    if op not in _OPS:
        raise ValueError(f"{entry.get('point_id')}: alarm_when op must be one of {', '.join(_OPS)}")
    if "value" not in spec:
        raise ValueError(f"{entry.get('point_id')}: alarm_when needs a value")
    sev = str(spec.get("severity", "medium")).lower()
    if sev not in ("critical", "high", "medium", "low", "info"):
        raise ValueError(f"{entry.get('point_id')}: severity must be critical, high, medium, low or info")
    clear = spec.get("clear_below", spec.get("clear_above"))
    pid = entry["point_id"]
    return AlarmRule(point_id=pid, equipment_id=entry.get("equipment_id") or pid.split("/")[0], op=op,
                     value=float(spec["value"]), for_s=float(spec.get("for_s", 0)),
                     clear_at=float(clear) if clear is not None else None, severity=sev,
                     message=spec.get("message") or f"{pid} {op} {spec['value']:g}".strip())


class RuleAlarms:
    """Watches points through the state engine and raises / clears their rule alarms."""

    def __init__(self, state_engine: Any):
        self.state_engine = state_engine
        self.rules: Dict[str, AlarmRule] = {}
        self._since: Dict[str, datetime] = {}         # point → when the condition started holding
        self._active: Dict[str, str] = {}             # point → open alarm id
        self._tasks: set = set()

    def load(self, entries: Iterable[Dict[str, Any]]) -> int:
        for e in entries:
            if isinstance(e, dict) and e.get("alarm_when") and e.get("point_id"):
                self.rules[e["point_id"]] = rule_from_config(e)
        return len(self.rules)

    def attach(self) -> None:
        self.state_engine.on_point_update(self.on_point)

    def on_point(self, point: Any) -> None:
        rule = self.rules.get(getattr(point, "point_id", ""))
        if rule is None or point.value is None:
            return
        q = str(getattr(getattr(point, "quality", ""), "value", getattr(point, "quality", ""))).lower()
        if q in ("bad", "stale"):
            return                                     # a dead sensor is not an alarm condition
        coro = self.evaluate(rule, float(point.value), getattr(point, "timestamp", None) or datetime.now())
        try:
            task = asyncio.get_running_loop().create_task(coro)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except RuntimeError:
            coro.close()
            logger.warning(f"[RuleAlarms] {rule.point_id}: no event loop to raise the alarm on")

    async def evaluate(self, rule: AlarmRule, v: float, ts: datetime) -> Optional[str]:
        """Returns 'raised', 'cleared' or None."""
        pid = rule.point_id
        if pid in self._active:
            if rule.cleared(v):
                alarm_id = self._active.pop(pid)
                self._since.pop(pid, None)
                await self.state_engine.resolve_alarm(alarm_id)
                return "cleared"
            return None
        if not rule.triggered(v):
            self._since.pop(pid, None)
            return None
        start = self._since.setdefault(pid, ts)
        if (ts - start).total_seconds() < rule.for_s:
            return None
        from agent_commercial.bms_data_model import Alarm, AlarmSeverity
        alarm = Alarm(alarm_id=f"rule:{pid}:{int(ts.timestamp())}", source_point_id=pid,
                      equipment_id=rule.equipment_id, message=f"{rule.message} ({v:g})",
                      severity=AlarmSeverity(rule.severity))
        await self.state_engine.add_alarm(alarm)
        self._active[pid] = alarm.alarm_id
        return "raised"
