"""
Readings taken by people: the rung of the ladder that works in every building.

A dial gauge, a mechanical meter, a standalone split's display, a tank sight
glass — no protocol reaches them, but a technician walking past does. This turns
what they report into ordinary data points ARVIS can trend, learn from and alarm on:

  typed      "tank 1 62%", "CHWP-1 discharge 4,2 bar"          (WhatsApp, or record_reading)
  photo      a gauge photo; the vision model proposes a value; the person confirms it
  round      ARVIS asks for a set of readings at set times; replies fill them in
  logbook    a CSV of past log-sheet entries, or the API

Every reading keeps who took it, how (method) and how sure it is (confidence:
typed 0.9, photo at most 0.7 and always confirmed). A reading is only used once it
is confirmed; one that is implausible (outside the point's min/max, or a big jump
from the last one) or read off a photo waits for a yes, a no or the right number.

A reading on a point that is ALSO read live by an instrument is not written over
the live value: it is kept as a verification, and the gap between the two is a
free check on that sensor.

Manual points are declared like any other source in the site config:

    sources:
      - id: rounds
        kind: manual
        points:
          - {point_id: TANK-1/LVL, name: Tank 1 level, equipment_id: TANK-1, unit: "%",
             min: 0, max: 100, expected_interval_h: 12, aliases: [tank 1, roof tank]}
          - {point_id: CHWP-1/DP, name: CHW pump 1 discharge, equipment_id: CHWP-1, unit: bar,
             min: 0, max: 10, capture: photo}
        rounds:
          - {name: Morning plant round, at: ["07:30"], to: "+97455501234",
             points: [TANK-1/LVL, CHWP-1/DP]}
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.manual_readings")

CONFIDENCE = {"whatsapp_text": .9, "round": .9, "api": .9, "logbook_csv": .85, "photo_ocr": .7}
JUMP_FRACTION = .5             # a change of more than half the point's range (or of the last value) needs a yes

_DDL = (
    """CREATE TABLE IF NOT EXISTS manual_points (
        point_id TEXT PRIMARY KEY, name TEXT, equipment_id TEXT, role TEXT, unit TEXT,
        expected_interval_h REAL, min REAL, max REAL, capture TEXT, aliases TEXT, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS manual_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, point_id TEXT NOT NULL, value REAL, unit TEXT,
        observed_at TEXT, recorded_at TEXT, method TEXT, technician TEXT, confidence REAL,
        status TEXT, media_ref TEXT, raw_text TEXT, live_value REAL, note TEXT, idempotency_key TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_manual_readings_point ON manual_readings(point_id, id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_readings_idem ON manual_readings(idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    # `at` / last_sent_slot are the building's local time (when the round is due);
    # last_sent_at is this host's clock, like every stored reading.
    """CREATE TABLE IF NOT EXISTS reading_rounds (
        name TEXT PRIMARY KEY, at TEXT, recipient TEXT, point_ids TEXT, last_sent_slot TEXT, last_sent_at TEXT)""",
)

# ── parsing what people type ─────────────────────────────────────────────────
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_NUM = re.compile(r"(?<![\w.])([-+]?\d+(?:[.,]\d+)*)\s*([^\s\d,;:]+)?")
# What can follow a number as its unit. Anything else after a number is a word ("CHWP-1 discharge").
_UNITS = {"%", "pct", "percent", "°c", "c", "degc", "°f", "f", "degf", "k", "bar", "mbar", "kpa", "pa", "psi",
          "kw", "w", "mw", "kwh", "mwh", "wh", "m3", "m³", "l", "litre", "litres", "liter", "liters", "l/s", "lps",
          "l/min", "lpm", "gpm", "m3/h", "m³/h", "ppm", "%rh", "rh", "hz", "a", "amp", "amps", "v", "volt", "volts",
          "rpm", "m", "mm", "cm", "lux", "h", "hr", "hrs", "hours", "min", "kva", "kvar", "pf", "ton", "tr", "btu"}
_UNSURE = re.compile(r"\b(not\s*sure|unsure|don'?t\s*know|can'?t\s*(read|see|tell)|no\s*idea)\b", re.IGNORECASE)


@dataclass
class Parsed:
    value: float
    unit: str = ""
    label: str = ""                      # the words before the number ("tank 1"), for matching a point


def _to_float(raw: str) -> Optional[float]:
    """'4,2' → 4.2 (decimal comma) · '1,250' and '12,500,000' → thousands · '1,250.5' → 1250.5."""
    s = raw.replace(" ", "")
    if "," in s and "." not in s:
        tail = s.rsplit(",", 1)[1]
        thousands = s.count(",") > 1 or len(tail) == 3
        s = s.replace(",", "") if thousands else s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_numbers(text: str) -> List[Parsed]:
    """Every 'label number unit' in a message: 'tank 1 62%, CHWP-1 4,2 bar' → two readings.
    Numbers that are part of a name (the 1 in 'tank 1', the 07 in 'AHU-07') are labels, not values."""
    t = (text or "").translate(_ARABIC_DIGITS)
    out: List[Parsed] = []
    for chunk in re.split(r"[;\n]|,\s+(?=[A-Za-z])", t):
        matches = list(_NUM.finditer(chunk))
        if not matches:
            continue
        m = matches[-1]                                  # the value comes last: "tank 1 62%"
        value = _to_float(m.group(1))
        if value is None:
            continue
        unit = (m.group(2) or "").strip().rstrip(".")
        if unit.lower() not in _UNITS:
            unit = ""
        label = chunk[:m.start()].strip(" :=-—")
        # "62 and 63", "4.1 or 4.2 bar": two values in one breath — ask, don't pick one.
        # (A number inside a name — "tank 1", "AHU-07" — follows a word and has no unit or decimal.)
        first = label.split()[0] if label.split() else ""
        if re.match(r"[-+]?\d", first) or any((mm.group(2) or "").lower() in _UNITS or re.search(r"[.,]\d", mm.group(1))
                                                for mm in matches[:-1]):
            continue
        out.append(Parsed(value=value, unit=unit, label=label))
    return out


def parse_numeric(text: str) -> Any:
    """One reading: Parsed, 'unsure', or None (no single clear number — ask again, never guess)."""
    if _UNSURE.search(text or ""):
        return "unsure"
    found = parse_numbers(text)
    return found[0] if len(found) == 1 else None


def convert(value: float, from_unit: str, to_unit: str) -> Optional[float]:
    """value in from_unit → to_unit, through the canonical units in semantics.point_roles.
    Same or missing unit → unchanged; units of different quantities → None."""
    from agent_commercial.semantics.point_roles import Quantity, _norm_unit, to_canonical
    if not from_unit or _norm_unit(from_unit) == _norm_unit(to_unit or ""):
        return float(value)
    if not to_unit:
        return None
    for q in Quantity:
        if q in (Quantity.BINARY, Quantity.FRACTION):
            continue
        a = to_canonical(value, from_unit, q)
        one, zero = to_canonical(1.0, to_unit, q), to_canonical(0.0, to_unit, q)
        if a is not None and one is not None and zero is not None and one != zero:
            return (a - zero) / (one - zero)
    return None


# ── the store ────────────────────────────────────────────────────────────────
@dataclass
class ManualPoint:
    point_id: str
    name: str = ""
    equipment_id: str = ""
    role: Optional[str] = None
    unit: str = ""
    expected_interval_h: float = 24.0
    min: Optional[float] = None
    max: Optional[float] = None
    capture: str = "either"              # typed | photo | either
    aliases: List[str] = field(default_factory=list)

    def matches(self, label: str) -> float:
        """How well a typed label names this point (0..1)."""
        lab = re.sub(r"[\s_\-/]+", " ", (label or "").lower()).strip()
        if not lab:
            return 0.0
        names = [self.point_id, self.name, self.equipment_id, *self.aliases]
        best = 0.0
        for n in names:
            n = re.sub(r"[\s_\-/]+", " ", (n or "").lower()).strip()
            if not n:
                continue
            if n == lab:
                return 1.0
            if n in lab or lab in n:
                best = max(best, .8)
            else:
                lw, nw = set(lab.split()), set(n.split())
                if lw and nw:
                    best = max(best, .6 * len(lw & nw) / len(nw))
        return best


@dataclass
class Reading:
    id: int
    point_id: str
    value: float
    unit: str
    observed_at: str
    method: str
    technician: Optional[str]
    confidence: float
    status: str                          # confirmed | pending_confirm | rejected | verification
    note: Optional[str] = None
    live_value: Optional[float] = None
    raw_text: Optional[str] = None
    media_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_local() -> datetime:
    return datetime.now()


class ManualReadingStore:
    def __init__(self, database: Any, emit: Optional[Callable[[Any], Any]] = None, state_engine: Any = None,
                 clock: Callable[[], datetime] = _now_local, tz: Optional[str] = None):
        self.database = database
        self.emit = emit                     # BMSDataPoint → ARVIS (ops._on_point_update)
        self.state_engine = state_engine     # to tell a live point from a manual one
        self.clock = clock                   # naive local, like the rest of the ops store
        self.tz = tz or os.getenv("ARVIS_TZ", "Asia/Qatar")

    async def _conn(self):
        conn = await self.database._get_async_connection()
        for stmt in _DDL:
            await conn.execute(stmt)
        return conn

    def _iso(self, dt: Optional[datetime] = None) -> str:
        return (dt or self.clock()).replace(tzinfo=None).isoformat(timespec="seconds")

    # ── points ────────────────────────────────────────────────────────────
    async def define_point(self, spec: Dict[str, Any]) -> ManualPoint:
        p = ManualPoint(point_id=spec["point_id"], name=spec.get("name") or spec["point_id"],
                        equipment_id=spec.get("equipment_id") or spec["point_id"].split("/")[0],
                        role=spec.get("role"), unit=spec.get("unit", ""),
                        expected_interval_h=float(spec.get("expected_interval_h", 24)),
                        min=spec.get("min"), max=spec.get("max"), capture=spec.get("capture", "either"),
                        aliases=list(spec.get("aliases") or []))
        if p.capture not in ("typed", "photo", "either"):
            raise ValueError(f"{p.point_id}: capture must be typed, photo or either")
        conn = await self._conn()
        await conn.execute(
            "INSERT OR REPLACE INTO manual_points (point_id, name, equipment_id, role, unit, expected_interval_h, "
            "min, max, capture, aliases, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (p.point_id, p.name, p.equipment_id, p.role, p.unit, p.expected_interval_h, p.min, p.max, p.capture,
             json.dumps(p.aliases), self._iso()))
        await conn.commit()
        return p

    async def points(self, equipment_id: Optional[str] = None) -> List[ManualPoint]:
        conn = await self._conn()
        q, args = "SELECT point_id, name, equipment_id, role, unit, expected_interval_h, min, max, capture, aliases " \
                  "FROM manual_points", ()
        if equipment_id:
            q, args = q + " WHERE equipment_id = ?", (equipment_id,)
        async with conn.execute(q + " ORDER BY point_id", args) as cur:
            rows = await cur.fetchall()
        return [ManualPoint(*r[:9], aliases=json.loads(r[9] or "[]")) for r in rows]

    async def point(self, point_id: str) -> Optional[ManualPoint]:
        return next((p for p in await self.points() if p.point_id == point_id), None)

    async def find_point(self, label: str, candidates: Optional[List[ManualPoint]] = None) -> Optional[ManualPoint]:
        """The manual point a label names, when exactly one fits clearly."""
        pts = candidates if candidates is not None else await self.points()
        scored = sorted(((p.matches(label), p) for p in pts), key=lambda x: -x[0])
        if not scored or scored[0][0] < .5:
            return None
        if len(scored) > 1 and scored[1][0] >= scored[0][0] - .05:
            return None                      # two points fit as well: ask, don't guess
        return scored[0][1]

    # ── readings ──────────────────────────────────────────────────────────
    async def last(self, point_id: str, status: str = "confirmed") -> Optional[Reading]:
        rows = await self._readings("WHERE point_id = ? AND status = ? ORDER BY id DESC LIMIT 1", (point_id, status))
        return rows[0] if rows else None

    async def _readings(self, where: str, args: tuple = ()) -> List[Reading]:
        conn = await self._conn()
        async with conn.execute(
                "SELECT id, point_id, value, unit, observed_at, method, technician, confidence, status, note, "
                f"live_value, raw_text, media_ref FROM manual_readings {where}", args) as cur:
            return [Reading(*r) for r in await cur.fetchall()]

    def _live_value(self, point_id: str) -> Optional[float]:
        """The current instrument value of this point, when an instrument reads it and is fresh."""
        pts = getattr(self.state_engine, "_points", None) or {}
        p = pts.get(point_id)
        if p is None or str(getattr(p, "source", "") or "").lower() in ("manual", "import", "commission"):
            return None
        ts = getattr(p, "timestamp", None)
        if ts is None or p.value is None:
            return None
        aware = ts if ts.tzinfo else ts.astimezone()
        if datetime.now(timezone.utc) - aware > timedelta(hours=1):
            return None
        return float(p.value)

    async def record(self, point_id: str, value: float, *, unit: str = "", method: str = "whatsapp_text",
                     technician: Optional[str] = None, observed_at: Optional[datetime] = None,
                     confidence: Optional[float] = None, raw_text: Optional[str] = None,
                     media_ref: Optional[str] = None, idempotency_key: Optional[str] = None,
                     force_confirm: bool = False) -> Reading:
        """Take a reading. Confirmed readings are emitted at once; doubtful ones wait."""
        if idempotency_key:
            dup = await self._readings("WHERE idempotency_key = ?", (idempotency_key,))
            if dup:
                return dup[0]
        mp = await self.point(point_id)
        live = self._live_value(point_id)
        target_unit = mp.unit if mp else (getattr((getattr(self.state_engine, "_points", {}) or {}).get(point_id), "unit", "")
                                          if live is not None else "")
        if mp is None and live is None:
            raise ValueError(f"{point_id} is not a manual point (add it under a `kind: manual` source)")
        v = convert(float(value), unit, target_unit)
        if v is None:
            raise ValueError(f"{point_id} is in {target_unit or 'no unit'}; can't use a value in {unit}")
        conf = float(confidence if confidence is not None else CONFIDENCE.get(method, .8))
        status, note = "confirmed", None
        if live is not None:
            status = "verification"
            note = f"instrument reads {live:g}; difference {v - live:+.3g} {target_unit}".strip()
        elif not force_confirm:
            if method == "photo_ocr":
                status, note = "pending_confirm", "read off a photo"
            elif mp.min is not None and v < float(mp.min) or mp.max is not None and v > float(mp.max):
                status, note = "pending_confirm", f"outside {mp.min:g}–{mp.max:g} {mp.unit}".strip() \
                    if mp.min is not None and mp.max is not None else "outside the expected range"
            else:
                prev = await self.last(point_id)
                span = (float(mp.max) - float(mp.min)) if mp.min is not None and mp.max is not None else None
                limit = JUMP_FRACTION * (span if span else max(abs(prev.value), 1.0)) if prev else None
                if prev and abs(v - prev.value) > limit:
                    status, note = "pending_confirm", f"a big change from the last reading ({prev.value:g})"
        obs = observed_at or self.clock()
        conn = await self._conn()
        cur = await conn.execute(
            "INSERT INTO manual_readings (point_id, value, unit, observed_at, recorded_at, method, technician, "
            "confidence, status, media_ref, raw_text, live_value, note, idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (point_id, v, target_unit, self._iso(obs), self._iso(), method, technician, conf, status, media_ref,
             raw_text, live, note, idempotency_key))
        await conn.commit()
        r = Reading(id=int(cur.lastrowid), point_id=point_id, value=v, unit=target_unit, observed_at=self._iso(obs),
                    method=method, technician=technician, confidence=conf, status=status, note=note, live_value=live,
                    raw_text=raw_text, media_ref=media_ref)
        if status == "confirmed":
            await self._emit(r, mp)
        return r

    async def confirm(self, reading_id: int, value: Optional[float] = None, by: Optional[str] = None) -> Reading:
        """A yes (or the corrected number) for a reading that was waiting."""
        (r,) = await self._readings("WHERE id = ?", (reading_id,))
        if r.status != "pending_confirm":
            return r
        if value is not None:
            r.value = float(value)
            r.confidence = max(r.confidence, CONFIDENCE["whatsapp_text"])   # a person typed the number
        elif r.method == "photo_ocr":
            r.confidence = max(r.confidence, CONFIDENCE["logbook_csv"])     # read by the model, checked by a person
        conn = await self._conn()
        await conn.execute("UPDATE manual_readings SET status='confirmed', value=?, confidence=?, note=COALESCE(note,'') || ? "
                           "WHERE id = ?", (r.value, r.confidence, f" · confirmed by {by}" if by else "", reading_id))
        await conn.commit()
        r.status = "confirmed"
        await self._emit(r, await self.point(r.point_id))
        return r

    async def reject(self, reading_id: int) -> None:
        conn = await self._conn()
        await conn.execute("UPDATE manual_readings SET status='rejected' WHERE id = ? AND status='pending_confirm'",
                           (reading_id,))
        await conn.commit()

    async def pending_for(self, technician: str, within_hours: float = 2.0) -> Optional[Reading]:
        cutoff = self._iso(self.clock() - timedelta(hours=within_hours))
        rows = await self._readings("WHERE technician = ? AND status = 'pending_confirm' AND recorded_at >= ? "
                                    "ORDER BY id DESC LIMIT 1", (technician, cutoff))
        return rows[0] if rows else None

    async def history(self, point_id: str, limit: int = 20) -> List[Reading]:
        return await self._readings("WHERE point_id = ? ORDER BY id DESC LIMIT ?", (point_id, limit))

    async def _emit(self, r: Reading, mp: Optional[ManualPoint]) -> None:
        if self.emit is None:
            return
        from agent_commercial.bms_data_model import BMSDataPoint, PointQuality
        pt = BMSDataPoint(point_id=r.point_id, name=(mp.name if mp else r.point_id), value=r.value, unit=r.unit,
                          timestamp=datetime.fromisoformat(r.observed_at), source="manual",
                          equipment_id=(mp.equipment_id if mp else r.point_id.split("/")[0]),
                          quality=PointQuality.GOOD if r.confidence >= .8 else PointQuality.UNCERTAIN,
                          confidence=r.confidence)
        out = self.emit(pt)
        if hasattr(out, "__await__"):
            await out

    async def overdue(self) -> List[Tuple[ManualPoint, Optional[Reading]]]:
        """Manual points whose last confirmed reading is older than they should be."""
        now = self.clock()
        out = []
        for p in await self.points():
            last = await self.last(p.point_id)
            if last is None or now - datetime.fromisoformat(last.observed_at) > timedelta(hours=p.expected_interval_h):
                out.append((p, last))
        return out

    # ── reading rounds ────────────────────────────────────────────────────
    async def define_round(self, spec: Dict[str, Any]) -> None:
        at = spec.get("at") or []
        at = [at] if isinstance(at, str) else list(at)
        for hhmm in at:
            if not re.fullmatch(r"\d{1,2}:\d{2}", str(hhmm)):
                raise ValueError(f"round {spec.get('name')!r}: times are HH:MM, not {hhmm!r}")
        to = str(spec.get("to") or "").strip()
        if to.lower() != "group":
            to = re.sub(r"\D", "", to)                  # the same number form the WhatsApp gateway uses
        if not to:
            raise ValueError(f"round {spec.get('name')!r}: `to` is a phone number or 'group'")
        conn = await self._conn()
        # A config reload keeps what was already sent (so a round isn't sent twice).
        await conn.execute(
            "INSERT INTO reading_rounds (name, at, recipient, point_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET at = excluded.at, recipient = excluded.recipient, "
            "point_ids = excluded.point_ids",
            (spec["name"], json.dumps(at), to, json.dumps(list(spec.get("points") or []))))
        await conn.commit()

    async def rounds_due(self, now_local: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Rounds whose time has come today (building local time) and that haven't been
        sent for that slot. Up to 3 h late (e.g. after a restart) they still go out."""
        now = (now_local or self.clock()).replace(tzinfo=None)
        conn = await self._conn()
        async with conn.execute("SELECT name, at, recipient, point_ids, last_sent_slot FROM reading_rounds") as cur:
            rows = await cur.fetchall()
        due = []
        for name, at, recipient, pids, last in rows:
            for hhmm in json.loads(at or "[]"):
                h, m = (int(x) for x in hhmm.split(":"))
                slot_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                slot = f"{now:%Y-%m-%d} {hhmm}"
                if slot_time <= now < slot_time + timedelta(hours=3) and (last or "") < slot:
                    due.append({"name": name, "slot": slot, "recipient": recipient, "point_ids": json.loads(pids or "[]")})
        return due

    async def mark_round_sent(self, name: str, slot: str) -> None:
        conn = await self._conn()
        await conn.execute("UPDATE reading_rounds SET last_sent_slot = ?, last_sent_at = ? WHERE name = ?",
                           (slot, self._iso(), name))
        await conn.commit()

    async def open_round_points(self, technician: str, within_hours: float = 6.0) -> List[ManualPoint]:
        """Points of rounds sent to this person recently that still have no reading since."""
        conn = await self._conn()
        async with conn.execute("SELECT point_ids, last_sent_at FROM reading_rounds WHERE recipient = ? "
                                "AND last_sent_at IS NOT NULL", (technician,)) as cur:
            rows = await cur.fetchall()
        now = self.clock()
        out: List[ManualPoint] = []
        for pids, sent_at in rows:
            sent = datetime.fromisoformat(sent_at)
            if now - sent > timedelta(hours=within_hours):
                continue
            for pid in json.loads(pids or "[]"):
                mp = await self.point(pid)
                last = await self.last(pid)
                if mp and (last is None or datetime.fromisoformat(last.observed_at) < sent):
                    out.append(mp)
        return out


# ── the `manual` source kind ─────────────────────────────────────────────────
class ManualSource:
    """The DataSource face of manual readings: declares the points and rounds from the
    site config. Readings reach ARVIS through ManualReadingStore (emit), not a poll."""
    watch = False                           # monitoring: people don't go "offline"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.specs: List[Dict[str, Any]] = []
        self.rounds: List[Dict[str, Any]] = []
        self.store: Optional[ManualReadingStore] = None
        self._overdue = 0

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        self.specs = [p for p in (config.get("points") or []) if isinstance(p, dict) and p.get("point_id")]
        self.rounds = list(config.get("rounds") or [])
        known = {p["point_id"] for p in self.specs}
        for r in self.rounds:
            missing = [pid for pid in (r.get("points") or []) if pid not in known]
            if missing:
                raise ValueError(f"round {r.get('name')!r} asks for points not declared here: {missing}")
        return len(self.specs)

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def start_polling(self, interval_seconds: float = 30) -> None:
        return None

    async def stop_polling(self) -> None:
        return None

    def on_point_update(self, callback: Callable[..., Any]) -> None:
        return None

    @property
    def is_connected(self) -> bool:
        return True

    def get_stats(self) -> Dict[str, Any]:
        return {"is_connected": True, "polling_active": True, "stale_points": [], "watch": False,
                "points_configured": len(self.specs), "rounds": len(self.rounds)}


async def _manual_post_wire(ops: Any, adapter: ManualSource, cfg: Dict[str, Any], connected: bool) -> None:
    store = getattr(ops, "manual_readings", None)
    if store is None:
        raise RuntimeError("manual source needs ops.manual_readings")
    adapter.store = store
    for spec in adapter.specs:
        await store.define_point(spec)
    for r in adapter.rounds:
        await store.define_round(r)


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("manual", build=ManualSource, points_config=lambda cfg: cfg,
                    point_entries=lambda cfg: list(cfg.get("points") or []), post_wire=_manual_post_wire,
                    default_poll=3600.0)
