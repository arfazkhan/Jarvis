"""
Events from access control, people counters and room bookings → occupancy.

Who is in a zone is the missing half of most energy waste: "floor 5 is cooled at
full power and nobody is there". Access control knows (badge swipes), people
counters know (counts), and the booking calendar knows what's planned. This turns
those events into occupancy points per zone, feeds the event correlator, and
flags a zone that has been empty for a while but is still being cooled.

    sources:
      - id: access
        kind: events
        doors:                                   # door → zone (and direction, if the reader knows it)
          DOOR-L5-E: {zone: L5, direction: in}
          DOOR-L5-X: {zone: L5, direction: out}
          DOOR-L6:   {zone: L6}                  # entries only: presence, not a count
        zones:
          L5: {name: Floor 5, presence_window_min: 120, reset_at: "03:00",
               conditioned_by: [{point: AHU-05/SF_STS}, {point: VAV-5-01/DMPR, above: 20}]}
        rooms: {"Meeting Room 5A": L5}           # calendar LOCATION → zone
        empty_after_min: 45

  Ingest: POST /api/v1/events (header x-arvis-events-token = ARVIS_EVENTS_TOKEN),
          a badge-export CSV, or an .ics calendar file (both via the API).
  Event:  {type: badge | door_open | door_forced | people_count | booking,
           door | zone, direction (in|out), count, at, start, end, id}
  Points: <ZONE>/OCC_COUNT (occupancy-count, when doors have directions or a counter
          reports), <ZONE>/OCCUPIED (occupancy, 0/1), <ZONE>/BOOKED (scheduled-occupancy)

Privacy: only door, zone, direction, count and time are kept. Card numbers,
names and any other field an access-control system sends are dropped at the door
of this module — they are never stored, logged or passed on.
"""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.events")

EVENTS_HEADER = "x-arvis-events-token"
_TYPES = ("badge", "door_open", "door_forced", "people_count", "booking")
_DDL = (
    """CREATE TABLE IF NOT EXISTS occupancy_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, type TEXT, door TEXT, zone TEXT, direction TEXT,
        count REAL, at TEXT, ends_at TEXT, received_at TEXT, ext_id TEXT)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_occ_events_ext ON occupancy_events(source, ext_id) WHERE ext_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_occ_events_zone ON occupancy_events(zone, at)",
)


def events_authorized(headers: Dict[str, str], token: Optional[str] = None) -> bool:
    expected = token if token is not None else os.getenv("ARVIS_EVENTS_TOKEN", "")
    got = headers.get(EVENTS_HEADER) or headers.get(EVENTS_HEADER.title()) or ""
    return bool(expected) and hmac.compare_digest(expected, got)


def _local_naive(v: Any) -> Optional[datetime]:
    """Any timestamp → this host's local clock, naive (how ARVIS stores readings)."""
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        dt = datetime.fromtimestamp(v / 1000.0 if v > 1e11 else float(v), tz=timezone.utc)
    elif isinstance(v, str) and v.strip():
        s = v.strip()
        if re.fullmatch(r"\d{8}T\d{6}Z?", s):                     # iCalendar form
            dt = datetime.strptime(s.rstrip("Z"), "%Y%m%dT%H%M%S")
            if s.endswith("Z"):
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        return None
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


@dataclass
class ZoneState:
    zone: str
    name: str = ""
    count: Optional[int] = None              # people in it, when doors have directions or a counter reports
    last_entry: Optional[datetime] = None
    empty_since: Optional[datetime] = None
    flagged: bool = False                    # an "empty but conditioned" signal is open for this episode
    cfg: Dict[str, Any] = field(default_factory=dict)

    def occupied(self, now: datetime) -> Optional[bool]:
        """Counted zones (doors with exit readers, or a people counter): count > 0.
        Entries-only zones: someone came in within the presence window. Never heard
        from: None — unknown, not "empty"."""
        if self.count is not None:
            return self.count > 0
        if self.last_entry is None:
            return None
        return now - self.last_entry <= timedelta(minutes=float(self.cfg.get("presence_window_min", 120)))

    def empty_from(self, now: datetime) -> datetime:
        if self.count is None and self.last_entry is not None:
            return self.last_entry + timedelta(minutes=float(self.cfg.get("presence_window_min", 120)))
        return now


class EventIngest:
    """Turns events into occupancy, persists them (without identities), and tells ARVIS."""

    def __init__(self, database: Any, emit: Optional[Callable[[Any], Any]] = None,
                 publish: Optional[Callable[[str, Dict[str, Any]], Any]] = None, correlator: Any = None,
                 state_engine: Any = None, clock: Callable[[], datetime] = datetime.now):
        self.database = database
        self.emit = emit
        self.publish = publish
        self.correlator = correlator
        self.state_engine = state_engine
        self.clock = clock
        self.sources: Dict[str, Dict[str, Any]] = {}
        self.zones: Dict[str, ZoneState] = {}

    def configure(self, source_id: str, cfg: Dict[str, Any]) -> None:
        self.sources[source_id] = cfg
        exits = {d.get("zone") for d in (cfg.get("doors") or {}).values() if d.get("direction") == "out"}
        for zid, zcfg in (cfg.get("zones") or {}).items():
            z = self.zones.setdefault(zid, ZoneState(zone=zid))
            z.name = (zcfg or {}).get("name", zid)
            z.cfg = {**(zcfg or {}), "_has_exits": zid in exits, "_source": source_id,
                     "empty_after_min": cfg.get("empty_after_min", 45)}
        for door in (cfg.get("doors") or {}).values():
            if door.get("zone"):
                self.zones.setdefault(door["zone"], ZoneState(zone=door["zone"], name=door["zone"],
                                                             cfg={"_source": source_id,
                                                                  "empty_after_min": cfg.get("empty_after_min", 45)}))

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    # ── intake ────────────────────────────────────────────────────────────
    def _normalise(self, source_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only what occupancy needs. Everything else — card numbers, names — is dropped here."""
        cfg = self.sources.get(source_id) or {}
        typ = str(raw.get("type") or ("people_count" if "count" in raw else "badge")).lower()
        if typ not in _TYPES:
            raise ValueError(f"event type must be one of {', '.join(_TYPES)}, not {typ!r}")
        door = str(raw.get("door") or "") or None
        dmap = (cfg.get("doors") or {}).get(door or "", {}) if door else {}
        zone = raw.get("zone") or dmap.get("zone")
        if typ == "booking" and not zone and raw.get("room"):
            zone = (cfg.get("rooms") or {}).get(raw["room"])
        if not zone:
            raise ValueError(f"event at door {door!r} has no zone (add the door to `doors:` in the events source)")
        direction = str(raw.get("direction") or dmap.get("direction") or "").lower() or None
        if direction not in (None, "in", "out"):
            raise ValueError("direction is in or out")
        at = _local_naive(raw.get("at") or raw.get("start")) or self.clock()
        count = raw.get("count")
        if typ == "people_count" and not isinstance(count, (int, float)):
            raise ValueError("a people_count event needs a numeric count")
        return {"type": typ, "door": door, "zone": str(zone), "direction": direction,
                "count": float(count) if isinstance(count, (int, float)) else None, "at": at,
                "ends_at": _local_naive(raw.get("end")) if typ == "booking" else None,
                "ext_id": str(raw["id"]) if raw.get("id") is not None else None}

    async def ingest(self, source_id: str, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """One event. Returns the normalised event, or None when it was a duplicate."""
        ev = self._normalise(source_id, raw)
        conn = await self._conn()
        try:
            await conn.execute(
                "INSERT INTO occupancy_events (source, type, door, zone, direction, count, at, ends_at, received_at, "
                "ext_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (source_id, ev["type"], ev["door"], ev["zone"], ev["direction"], ev["count"],
                 ev["at"].isoformat(timespec="seconds"),
                 ev["ends_at"].isoformat(timespec="seconds") if ev["ends_at"] else None,
                 self.clock().isoformat(timespec="seconds"), ev["ext_id"]))
            await conn.commit()
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                return None                      # the same event re-sent (webhook retry, re-imported file)
            raise
        z = self.zones.setdefault(ev["zone"], ZoneState(zone=ev["zone"], name=ev["zone"],
                                                        cfg={"_source": source_id, "empty_after_min": 45}))
        if ev["type"] == "people_count":
            z.count = int(ev["count"])
        elif ev["type"] in ("badge", "door_open"):
            counted = z.count is not None or z.cfg.get("_has_exits")
            if ev["direction"] == "out":
                if counted:
                    z.count = max(0, (z.count or 0) - 1)
            else:
                if ev["direction"] == "in" and counted:
                    z.count = (z.count or 0) + 1
                z.last_entry = max(z.last_entry or ev["at"], ev["at"])
        self._feed_correlator(ev)
        if ev["type"] != "booking":
            await self.update_zone(z, ev["at"])
        return ev

    def _feed_correlator(self, ev: Dict[str, Any]) -> None:
        if self.correlator is None:
            return
        try:
            from agent_commercial.event_correlator import Event, EventSource
            src = EventSource.CALENDAR if ev["type"] == "booking" else EventSource.ACCESS_CONTROL
            kind = {"badge": "badge_in" if ev["direction"] != "out" else "badge_out", "door_open": "door_open",
                    "door_forced": "door_forced", "people_count": "people_count", "booking": "booking"}[ev["type"]]
            self.correlator.add_event(Event(event_id=str(uuid.uuid4()), source=src, timestamp=ev["at"],
                                            event_type=kind, description=f"{kind} in {ev['zone']}",
                                            zone_id=ev["zone"], value=ev["count"]))
        except Exception as e:
            logger.warning(f"[Events] correlator feed failed: {e}")

    # ── occupancy points + the empty-but-conditioned check ───────────────
    async def update_zone(self, z: ZoneState, now: Optional[datetime] = None) -> None:
        now = now or self.clock()
        occ = z.occupied(now)
        tag = f"event:{z.cfg.get('_source', 'events')}"
        if z.count is not None:
            await self._point(f"{z.zone}/OCC_COUNT", f"{z.name} people", float(z.count), "", z.zone, tag, now)
        if occ is not None:
            await self._point(f"{z.zone}/OCCUPIED", f"{z.name} occupied", 1.0 if occ else 0.0, "", z.zone, tag, now)
        if occ is False:
            z.empty_since = z.empty_since or z.empty_from(now)
        elif occ:
            z.empty_since = None
        await self._check_conditioned(z, now)

    async def _point(self, pid: str, name: str, value: float, unit: str, zone: str, source: str, ts: datetime) -> None:
        if self.emit is None:
            return
        from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
        out = self.emit(BMSDataPoint(point_id=pid, name=name, value=value, unit=unit, timestamp=ts, source=source,
                                     equipment_id=zone, point_type=PointType.STATUS, quality=PointQuality.GOOD))
        if asyncio.iscoroutine(out):
            await out

    def _running(self, z: ZoneState) -> List[str]:
        """Which of the zone's conditioning points are on right now."""
        pts = getattr(self.state_engine, "_points", {}) or {}
        on = []
        for c in z.cfg.get("conditioned_by") or []:
            p = pts.get(c.get("point"))
            if p is None or p.value is None:
                continue
            if float(p.value) > float(c.get("above", 0.5)):
                on.append(f"{c['point']} at {p.value:g}{(' ' + p.unit) if getattr(p, 'unit', '') else ''}")
        return on

    async def _check_conditioned(self, z: ZoneState, now: datetime) -> None:
        if not z.cfg.get("conditioned_by") or self.publish is None:
            return
        running = self._running(z)
        empty_for = (now - z.empty_since).total_seconds() / 60 if z.empty_since else 0
        if z.empty_since and running and empty_for >= float(z.cfg.get("empty_after_min", 45)):
            if not z.flagged:
                z.flagged = True
                self.publish("zone_empty_but_conditioned", {
                    "zone": z.zone, "name": z.name, "empty_since": z.empty_since.isoformat(timespec="minutes"),
                    "minutes": round(empty_for), "running": running})
        elif z.flagged:
            z.flagged = False
            self.publish("zone_empty_but_conditioned_cleared", {"zone": z.zone, "name": z.name,
                                                                "why": "occupied again" if not z.empty_since
                                                                else "conditioning stopped"})

    async def tick(self, now: Optional[datetime] = None) -> None:
        """Every minute: presence windows run out, bookings start and end, counts reset at night."""
        now = now or self.clock()
        for z in list(self.zones.values()):
            reset = z.cfg.get("reset_at")
            if reset and z.count:
                h, m = (int(x) for x in str(reset).split(":"))
                if now.hour == h and now.minute == m:
                    z.count = 0                  # nobody badges out of a fire exit: stop the count drifting
            await self.update_zone(z, now)
            booked = await self._booked(z.zone, now)
            if booked is not None:
                await self._point(f"{z.zone}/BOOKED", f"{z.name} booked", 1.0 if booked else 0.0, "", z.zone,
                                  f"event:{z.cfg.get('_source', 'events')}", now)

    async def _booked(self, zone: str, now: datetime) -> Optional[bool]:
        conn = await self._conn()
        iso = now.isoformat(timespec="seconds")
        async with conn.execute("SELECT COUNT(*), SUM(CASE WHEN at <= ? AND ends_at > ? THEN 1 ELSE 0 END) "
                                "FROM occupancy_events WHERE zone = ? AND type = 'booking'", (iso, iso, zone)) as cur:
            total, now_on = await cur.fetchone()
        return None if not total else bool(now_on)

    async def run(self, every_s: float = 60.0) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Events] tick failed: {e}")
            await asyncio.sleep(every_s)

    # ── files ─────────────────────────────────────────────────────────────
    async def import_csv(self, source_id: str, text: str) -> Dict[str, Any]:
        """A badge-export CSV. Columns used: time (or timestamp / date_time), door, direction,
        type, count. Any name / card / user column is ignored and never stored."""
        result = {"ingested": 0, "duplicates": 0, "errors": []}
        for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            raw = {"type": row.get("type") or "badge", "door": row.get("door") or row.get("reader"),
                   "zone": row.get("zone") or None, "direction": row.get("direction") or None,
                   "at": row.get("time") or row.get("timestamp") or row.get("date_time"),
                   "id": f"csv:{row.get('time') or row.get('timestamp')}:{row.get('door') or row.get('reader')}:{i}"}
            if row.get("count"):
                raw["count"] = float(row["count"])
            try:
                ev = await self.ingest(source_id, raw)
                result["ingested" if ev else "duplicates"] += 1
            except (ValueError, TypeError) as e:
                result["errors"].append({"line": i, "error": str(e)})
        return result

    async def import_ics(self, source_id: str, text: str) -> Dict[str, Any]:
        """Room bookings from an .ics export: each VEVENT's LOCATION is matched to a zone via `rooms:`."""
        result = {"ingested": 0, "duplicates": 0, "skipped": 0}
        unfolded = re.sub(r"\r?\n[ \t]", "", text)
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.DOTALL):
            fields: Dict[str, str] = {}
            for line in block.strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fields[k.split(";")[0].upper()] = v.strip()
            try:
                ev = await self.ingest(source_id, {"type": "booking", "room": fields.get("LOCATION", ""),
                                                   "start": fields.get("DTSTART"), "end": fields.get("DTEND"),
                                                   "id": f"ics:{fields.get('UID') or fields.get('DTSTART')}"})
                result["ingested" if ev else "duplicates"] += 1
            except (ValueError, TypeError):
                result["skipped"] += 1           # a room ARVIS has no zone for
        return result


class EventsSource:
    """The DataSource face of event feeds: declares doors, zones and rooms from the site
    config. Events arrive through EventIngest (webhook / files), not a poll."""
    watch = False

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "events")

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        doors = config.get("doors") or {}
        for did, d in doors.items():
            if not isinstance(d, dict) or not d.get("zone"):
                raise ValueError(f"door {did} needs a zone")
            if d.get("direction") not in (None, "in", "out"):
                raise ValueError(f"door {did}: direction is in or out")
        return len(doors) + len(config.get("zones") or {})

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def start_polling(self, interval_seconds: float = 60) -> None:
        return None

    async def stop_polling(self) -> None:
        return None

    def on_point_update(self, cb: Callable[..., Any]) -> None:
        return None

    @property
    def is_connected(self) -> bool:
        return True

    def get_stats(self) -> Dict[str, Any]:
        return {"is_connected": True, "polling_active": True, "stale_points": [], "watch": False,
                "doors": len(self.cfg.get("doors") or {}), "zones": len(self.cfg.get("zones") or {})}


async def _events_post_wire(ops: Any, adapter: EventsSource, cfg: Dict[str, Any], connected: bool) -> None:
    ingest = getattr(ops, "event_ingest", None)
    if ingest is None:
        raise RuntimeError("events source needs ops.event_ingest")
    ingest.configure(adapter.source_id, cfg)


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("events", build=EventsSource, points_config=lambda cfg: cfg,
                    point_entries=lambda cfg: [], post_wire=_events_post_wire, default_poll=60.0)
