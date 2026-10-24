"""
Many data sources at once.

A real building is mixed: a BACnet BMS for HVAC, Modbus meters and generators,
IoT sensors, vendor clouds, readings taken by hand. The site config lists them:

    sources:
      - {id: plant_bms, kind: bacnet,  required: true,  local_address: ..., points: [...]}
      - {id: meters,    kind: modbus,  required: false, host: 10.0.0.20, registers: [...]}
      - {id: lighting,  kind: opcua,   endpoint: ..., points: [...]}

SourceManager starts each one the same way — load points (refuse zero in
production), connect, wire into ARVIS, then poll — and reports them all to the
monitoring watcher:

  required: true   (default) it failing to connect stops startup, unless
                   allow_offline: true; it going down makes the building "blind"
  required: false  its failure is logged and ARVIS runs without it; it going
                   down makes the building "degraded", never "blind"

New kinds register with `register_source`; their modules import lazily, so a
site only needs the packages for the sources it actually uses. No simulator
fallback anywhere: a source that cannot connect serves no data, never made-up data.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("arvis.sources")


@dataclass
class SourceKind:
    build: Callable[[Dict[str, Any]], Any]                  # cfg -> adapter (not connected)
    points_config: Callable[[Dict[str, Any]], Dict[str, Any]]   # cfg -> what load_points_from_config takes
    point_entries: Callable[[Dict[str, Any]], List[Dict[str, Any]]]  # cfg -> point dicts (roles, catalog)
    post_wire: Optional[Callable[[Any, Any, Dict[str, Any], bool], Awaitable[None]]] = None
    default_poll: float = 30.0


KINDS: Dict[str, SourceKind] = {}


def register_source(kind: str, **spec: Any) -> None:
    KINDS[kind] = SourceKind(**spec)


@dataclass
class SourceHandle:
    id: str
    kind: str
    adapter: Any
    cfg: Dict[str, Any] = field(default_factory=dict)
    required: bool = True
    connected_at_start: bool = False


class SourceManager:
    def __init__(self) -> None:
        self.handles: List[SourceHandle] = []

    # ── bookkeeping ───────────────────────────────────────────────────────
    def adopt(self, kind: str, adapter: Any, source_id: Optional[str] = None, required: bool = True,
              cfg: Optional[Dict[str, Any]] = None) -> SourceHandle:
        """Track a source started elsewhere (the legacy single-protocol modes)."""
        h = SourceHandle(id=source_id or kind, kind=kind, adapter=adapter, cfg=cfg or {}, required=required,
                         connected_at_start=bool(getattr(adapter, "is_connected", False)))
        self.handles.append(h)
        return h

    def first(self, kind: str) -> Optional[Any]:
        return next((h.adapter for h in self.handles if h.kind == kind), None)

    def any_connected(self) -> bool:
        return any(bool(getattr(h.adapter, "is_connected", False)) for h in self.handles)

    def point_entries(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for h in self.handles:
            k = KINDS.get(h.kind)
            if k is not None and h.cfg:
                out += [e for e in k.point_entries(h.cfg) if isinstance(e, dict)]
        return out

    def stats(self) -> List[Dict[str, Any]]:
        out = []
        for h in self.handles:
            try:
                st = h.adapter.get_stats() if hasattr(h.adapter, "get_stats") else {}
            except Exception as e:
                st = {"error": f"{type(e).__name__}: {e}"}
            out.append({"id": h.id, "kind": h.kind, "required": h.required, **st})
        return out

    # ── starting ──────────────────────────────────────────────────────────
    async def start(self, specs: List[Dict[str, Any]], ops: Any) -> None:
        production = os.getenv("ARVIS_ENV", "development").lower() == "production"
        seen = set()
        for spec in specs:
            sid, kind = str(spec.get("id") or spec.get("kind")), str(spec.get("kind") or "")
            if kind not in KINDS:
                raise RuntimeError(f"source {sid!r}: unknown kind {kind!r} (known: {', '.join(sorted(KINDS))})")
            if sid in seen:
                raise RuntimeError(f"source id {sid!r} is used twice")
            seen.add(sid)
            required = bool(spec.get("required", True))
            k = KINDS[kind]
            try:
                await self._start_one(sid, kind, k, spec, required, production, ops)
            except Exception as e:
                if required:
                    raise
                logger.error(f"[Sources] optional source {sid} ({kind}) not started: {type(e).__name__}: {e}")

    async def _start_one(self, sid: str, kind: str, k: SourceKind, cfg: Dict[str, Any], required: bool,
                         production: bool, ops: Any) -> None:
        adapter = k.build(cfg)
        if hasattr(adapter, "source_id"):
            adapter.source_id = sid
        n = adapter.load_points_from_config(k.points_config(cfg))
        if n == 0 and production:
            raise RuntimeError(f"source {sid} ({kind}) has no points configured — refusing to report a live "
                               "building with zero points")
        ok = await adapter.connect()
        if not ok:
            if required and not cfg.get("allow_offline"):
                raise RuntimeError(f"source {sid} ({kind}) could not connect. Fix the connection, or set "
                                   "allow_offline: true to start degraded (no data until it connects).")
            logger.warning(f"[Sources] {sid} ({kind}) unreachable — starting without its data, retrying in the background")
        handle = SourceHandle(id=sid, kind=kind, adapter=adapter, cfg=cfg, required=required, connected_at_start=ok)
        self.handles.append(handle)
        if ok:
            # Before the first poll: a reading from a connected source is what makes the
            # building LIVE (ops._on_point_update), so the flag must already be up.
            ops._bms_connected = True
        ops._wire_adapter(adapter)                       # ingestion wired BEFORE the first poll
        if k.post_wire is not None:
            await k.post_wire(ops, adapter, cfg, ok)
        interval = float(cfg.get("poll_interval", k.default_poll))
        await adapter.start_polling(interval)
        logger.info(f"[Sources] {sid} ({kind}) started: {n} points, polling every {interval:g}s"
                    + ("" if ok else " (degraded)"))

    async def stop(self) -> None:
        for h in self.handles:
            for name in ("stop_polling", "disconnect"):
                fn = getattr(h.adapter, name, None)
                if fn is None:
                    continue
                try:
                    await fn()
                except Exception as e:
                    logger.warning(f"[Sources] {h.id}.{name} failed: {e}")


# ── built-in kinds: the three protocol adapters ARVIS already has ────────────
def _bacnet_build(cfg: Dict[str, Any]) -> Any:
    from agent_commercial.bacnet_adapter import BACnetAdapter
    return BACnetAdapter(
        local_address=cfg.get("local_address", "0.0.0.0"), port=cfg.get("port", 47808),
        device_id=cfg.get("device_id", 999), check_status_flags=bool(cfg.get("check_status_flags", True)),
        max_per_request=int(cfg.get("max_per_request", 20)),
        rediscover_interval_s=float(cfg.get("rediscover_interval", 600)),
        read_timeout_s=float(cfg.get("read_timeout", 5.0)))


async def _bacnet_post_wire(ops: Any, adapter: Any, cfg: Dict[str, Any], connected: bool) -> None:
    import asyncio
    if connected:
        devices = await adapter.discover_devices(timeout_seconds=int(cfg.get("discovery_timeout", 5)))
        logger.info(f"[Sources] discovered {len(devices)} BACnet devices")
    # The BMS's own alarms (statusFlags inAlarm) become ARVIS alarms.
    adapter.on_alarm(lambda alarm: asyncio.get_running_loop().create_task(ops.state_engine.add_alarm(alarm)))
    adapter.on_alarm_cleared(
        lambda alarm_id: asyncio.get_running_loop().create_task(ops.state_engine.resolve_alarm(alarm_id)))


def _modbus_build(cfg: Dict[str, Any]) -> Any:
    from agent_commercial.modbus_adapter import ModbusAdapter
    return ModbusAdapter(host=cfg.get("host", "127.0.0.1"), port=cfg.get("port", 502), unit_id=cfg.get("unit_id", 1))


def _opcua_build(cfg: Dict[str, Any]) -> Any:
    from agent_commercial.opcua_adapter import opcua_adapter_from_config
    return opcua_adapter_from_config(cfg)


register_source("bacnet", build=_bacnet_build, points_config=lambda cfg: cfg.get("points_config") or {"points": []},
                point_entries=lambda cfg: list((cfg.get("points_config") or {}).get("points") or []),
                post_wire=_bacnet_post_wire, default_poll=60.0)
register_source("modbus", build=_modbus_build, points_config=lambda cfg: cfg,
                point_entries=lambda cfg: list(cfg.get("registers") or []))
register_source("opcua", build=_opcua_build, points_config=lambda cfg: cfg,
                point_entries=lambda cfg: list(cfg.get("points") or []))
