"""
SNMP: UPS, PDUs, server-room cooling (CRAC), network-attached plant.

Most UPSs and many IT-room devices have a network card that answers SNMP. ARVIS
only GETs; it never SETs (read-only, enforced by test).

    sources:
      - id: ups
        kind: snmp
        host: 10.10.0.30
        version: 2c                       # or 3
        community_env: ARVIS_SNMP_COMMUNITY
        # v3: user: arvis, auth_key_env: ..., priv_key_env: ..., auth_protocol: sha, priv_protocol: aes
        poll_interval: 60
        devices:
          - {template: ups_mib, equipment_id: UPS-1}          # RFC 1628 UPS-MIB: charge, load, voltages, alarms
        points:
          - {point_id: CRAC-1/RAT, oid: 1.3.6.1.4.1.476.1.42.3.4.1.2.3.1.3.1, unit: "°C", scale: 0.1}

Templates live in config/templates/snmp/*.yaml (an OID list with roles and
scaling per standard MIB); `points` adds any OID by hand.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
from agent_commercial.sources.base import source_tag
from agent_commercial.sources.common import number, refuse_inline_secrets, secret

logger = logging.getLogger("arvis.sources.snmp")
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "templates" / "snmp"


@dataclass
class SnmpPoint:
    point_id: str
    oid: str
    unit: str = ""
    name: str = ""
    equipment_id: str = ""
    scale: float = 1.0
    offset: float = 0.0
    role: Optional[str] = None


def expand_devices(devices: List[Dict[str, Any]], directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    """`devices: [{template, equipment_id}]` → point entries (same shape as `points`)."""
    import yaml
    out = []
    for d in devices or []:
        path = (directory or TEMPLATE_DIR) / f"{d.get('template')}.yaml"
        if not path.exists():
            known = sorted(p.stem for p in (directory or TEMPLATE_DIR).glob("*.yaml"))
            raise ValueError(f"unknown SNMP template {d.get('template')!r} (known: {', '.join(known)})")
        if not d.get("equipment_id"):
            raise ValueError(f"SNMP device {d.get('template')}: needs an equipment_id")
        t = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for o in t.get("oids") or []:
            e = {k: v for k, v in o.items() if k != "suffix"}
            e.update(point_id=f"{d['equipment_id']}/{o['suffix']}", equipment_id=d["equipment_id"])
            out.append(e)
    return out


def snmp_point_entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(cfg.get("points") or []) + expand_devices(cfg.get("devices") or [])


class SnmpSource:
    def __init__(self, cfg: Dict[str, Any]):
        refuse_inline_secrets(cfg, f"snmp source {cfg.get('id', '')}")
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "snmp")
        self.host = cfg.get("host", "")
        self.port = int(cfg.get("port", 161))
        self.version = str(cfg.get("version", "2c"))
        if self.version not in ("1", "2c", "3"):
            raise ValueError(f"snmp source {self.source_id}: version is 1, 2c or 3")
        if not self.host:
            raise ValueError(f"snmp source {self.source_id}: needs a host")
        self.timeout = float(cfg.get("timeout", 3.0))
        self.max_per_request = int(cfg.get("max_per_request", 20))
        self.points: List[SnmpPoint] = []
        self._cbs: List[Callable[[BMSDataPoint], Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._interval = 60.0
        self._freshness = PointFreshness()
        self._last: Dict[str, BMSDataPoint] = {}
        self.get = self._snmp_get              # tests: a scripted transport
        self.stats = {"reads_total": 0, "reads_failed": 0, "last_read": None}

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        self.points = []
        for e in snmp_point_entries(config):
            if not e.get("point_id") or not e.get("oid"):
                raise ValueError(f"an SNMP point needs point_id and oid: {e}")
            self.points.append(SnmpPoint(point_id=e["point_id"], oid=str(e["oid"]).lstrip("."), unit=e.get("unit", ""),
                                         name=e.get("name") or e["point_id"],
                                         equipment_id=e.get("equipment_id") or e["point_id"].split("/")[0],
                                         scale=float(e.get("scale", 1.0)), offset=float(e.get("offset", 0.0)),
                                         role=e.get("role")))
            self._freshness.register(e["point_id"])
        return len(self.points)

    # ── the wire (pysnmp, GET only) ──────────────────────────────────────
    def _auth(self):
        from pysnmp.hlapi.v3arch.asyncio import (CommunityData, UsmUserData, usmAesCfb128Protocol,
                                                  usmDESPrivProtocol, usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol)
        if self.version == "3":
            auth = {"sha": usmHMACSHAAuthProtocol, "md5": usmHMACMD5AuthProtocol}[self.cfg.get("auth_protocol", "sha")]
            priv = {"aes": usmAesCfb128Protocol, "des": usmDESPrivProtocol}[self.cfg.get("priv_protocol", "aes")]
            return UsmUserData(self.cfg.get("user", ""), authKey=secret(self.cfg, "auth_key"),
                               privKey=secret(self.cfg, "priv_key"), authProtocol=auth, privProtocol=priv)
        community = secret(self.cfg, "community")
        if community is None:
            raise ValueError(f"snmp source {self.source_id}: set community_env (the community string is a secret)")
        return CommunityData(community, mpModel=0 if self.version == "1" else 1)

    async def _snmp_get(self, oids: List[str]) -> Dict[str, Any]:
        from pysnmp.hlapi.v3arch.asyncio import ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, get_cmd
        engine = SnmpEngine()
        target = await UdpTransportTarget.create((self.host, self.port), timeout=self.timeout, retries=1)
        err_ind, err_stat, err_idx, binds = await get_cmd(engine, self._auth(), target, ContextData(),
                                                         *[ObjectType(ObjectIdentity(o)) for o in oids])
        if err_ind:
            raise ConnectionError(str(err_ind))
        if err_stat:
            raise ConnectionError(f"{err_stat.prettyPrint()} at {err_idx}")
        out = {}
        for name, val in binds:
            cls = type(val).__name__
            if cls in ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null"):
                continue
            out[str(name)] = int(val) if hasattr(val, "__int__") and cls not in ("OctetString",) else str(val)
        return out

    # ── lifecycle ─────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        try:
            await self.get([self.points[0].oid] if self.points else ["1.3.6.1.2.1.1.3.0"])   # sysUpTime
            self._connected = True
        except Exception as e:
            logger.error(f"[SNMP] {self.source_id}: {self.host} not answering: {type(e).__name__}: {e}")
            self._connected = False
        return self._connected

    async def disconnect(self) -> None:
        await self.stop_polling()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def on_point_update(self, cb: Callable[[BMSDataPoint], Any]) -> None:
        self._cbs.append(cb)

    async def start_polling(self, interval_seconds: float = 60) -> None:
        self._interval = float(interval_seconds)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop_polling(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self.read_all()
            await asyncio.sleep(self._interval)

    async def read_all(self) -> int:
        n = 0
        by_oid = {p.oid: p for p in self.points}
        oids = list(by_oid)
        for i in range(0, len(oids), self.max_per_request):
            batch = oids[i:i + self.max_per_request]
            self.stats["reads_total"] += 1
            try:
                got = await self.get(batch)
                self._connected = True
            except Exception as e:
                self.stats["reads_failed"] += 1
                self._connected = False
                logger.warning(f"[SNMP] {self.source_id}: read failed: {type(e).__name__}: {e}")
                continue
            for oid in batch:
                v = number(got.get(oid))
                if v is None:
                    continue
                p = by_oid[oid]
                pt = BMSDataPoint(point_id=p.point_id, name=p.name, value=v * p.scale + p.offset, unit=p.unit,
                                  timestamp=datetime.now(), source=source_tag("snmp", self.source_id),
                                  equipment_id=p.equipment_id, point_type=PointType.SENSOR, quality=PointQuality.GOOD)
                self._freshness.mark_ok(p.point_id)
                self._last[p.point_id] = pt
                await self._emit(pt)
                n += 1
        for pid in self._freshness.newly_stale({p.point_id: self._interval for p in self.points}):
            last = self._last.get(pid)
            if last is not None:
                await self._emit(BMSDataPoint(point_id=pid, name=last.name, value=last.value, unit=last.unit,
                                              timestamp=last.timestamp, source=last.source,
                                              equipment_id=last.equipment_id, quality=PointQuality.STALE))
        self.stats["last_read"] = datetime.now().isoformat(timespec="seconds")
        return n

    async def _emit(self, pt: BMSDataPoint) -> None:
        for cb in self._cbs:
            out = cb(pt)
            if inspect.isawaitable(out):
                await out

    def get_stats(self) -> Dict[str, Any]:
        return {**self.stats, "is_connected": self._connected, "polling_active": bool(self._task and not self._task.done()),
                "points_configured": len(self.points), "stale_points": self._freshness.stale_points,
                "host": f"{self.host}:{self.port}"}


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("snmp", build=SnmpSource, points_config=lambda cfg: cfg, point_entries=snmp_point_entries,
                    default_poll=60.0)
