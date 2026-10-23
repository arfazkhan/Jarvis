"""
The building's working rhythm, in its own timezone.

  work days       ARVIS_WORK_DAYS        default Sun,Mon,Tue,Wed,Thu (Gulf work week)
  occupied hours  ARVIS_OCCUPIED_HOURS   default 7-18
  Ramadan hours   ARVIS_RAMADAN_HOURS    default 9-15 (Ramadan from the Hijri calendar,
                                         agent_advisory/qatar/context.is_ramadan)
  holidays        ARVIS_HOLIDAYS         YYYY-MM-DD,YYYY-MM-DD
  quiet hours     ARVIS_OPS_QUIET_HOURS  default 22-6 (only critical things break them)

Used by the attention gate (when is it worth interrupting someone?) and given to
the engineer as context (a 3 a.m. comfort drift in an empty office can wait).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Set, Tuple

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _hours(raw: str, default: Tuple[int, int]) -> Tuple[int, int]:
    try:
        a, b = (int(x) for x in raw.split("-"))
        return a, b
    except (ValueError, AttributeError):
        return default


def _in(h: int, span: Tuple[int, int]) -> bool:
    a, b = span
    return (a <= h < b) if a <= b else (h >= a or h < b)


class BuildingCalendar:
    def __init__(self):
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(os.getenv("ARVIS_TZ", "Asia/Qatar"))
        except Exception:
            self.tz = datetime.now().astimezone().tzinfo
        self.work_days: Set[int] = {_DAYS[d.strip()[:3].lower()]
                                    for d in os.getenv("ARVIS_WORK_DAYS", "Sun,Mon,Tue,Wed,Thu").split(",")
                                    if d.strip()[:3].lower() in _DAYS}
        self.occupied_hours = _hours(os.getenv("ARVIS_OCCUPIED_HOURS", "7-18"), (7, 18))
        self.ramadan_hours = _hours(os.getenv("ARVIS_RAMADAN_HOURS", "9-15"), (9, 15))
        self.quiet_hours = _hours(os.getenv("ARVIS_OPS_QUIET_HOURS", "22-6"), (22, 6))
        self.holidays: Set[date] = set()
        for d in os.getenv("ARVIS_HOLIDAYS", "").split(","):
            try:
                self.holidays.add(date.fromisoformat(d.strip()))
            except ValueError:
                pass

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def local(self, dt: Optional[datetime] = None) -> datetime:
        dt = dt or datetime.now(timezone.utc)
        return (dt if dt.tzinfo else dt.astimezone()).astimezone(self.tz)

    def ramadan(self, dt: Optional[datetime] = None) -> bool:
        try:
            from agent_advisory.qatar.context import is_ramadan
            return bool(is_ramadan(self.local(dt)))
        except Exception:
            return False

    def day_type(self, dt: Optional[datetime] = None) -> str:
        d = self.local(dt)
        if d.date() in self.holidays:
            return "holiday"
        return "workday" if d.weekday() in self.work_days else "weekend"

    def occupied(self, dt: Optional[datetime] = None) -> bool:
        d = self.local(dt)
        if self.day_type(d) != "workday":
            return False
        return _in(d.hour, self.ramadan_hours if self.ramadan(d) else self.occupied_hours)

    def quiet(self, dt: Optional[datetime] = None) -> bool:
        return _in(self.local(dt).hour, self.quiet_hours)

    def next_hour(self, hour: int, dt: Optional[datetime] = None) -> datetime:
        """The next time the local clock reads `hour`:00 (today if still ahead)."""
        d = self.local(dt)
        t = d.replace(hour=hour, minute=0, second=0, microsecond=0)
        return t if t > d else t + timedelta(days=1)

    def describe(self, dt: Optional[datetime] = None) -> str:
        d = self.local(dt)
        bits = [f"{d:%A %d %B %Y, %H:%M}", self.day_type(d)]
        if self.ramadan(d):
            bits.append("Ramadan")
        bits.append("building occupied" if self.occupied(d) else "building unoccupied")
        if self.quiet(d):
            bits.append("quiet hours")
        return ", ".join(bits)
