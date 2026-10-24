"""
REST: vendor APIs (lifts, VRF, solar portals, access control, gateways with a JSON API).

When a vendor offers an API, ARVIS polls it — GET only, nothing is ever sent
back (read-only, enforced by test). When a vendor pushes instead, it posts to
ARVIS's push endpoint and the same mapping applies.

    sources:
      - id: lifts
        kind: rest
        base_url: https://api.lift-vendor.example
        headers_env: {Authorization: ARVIS_LIFT_API_AUTH}     # header values come from the environment
        push_token_env: ARVIS_LIFT_PUSH_TOKEN                  # optional: vendor pushes to POST /api/v1/push/lifts
        poll_interval: 120
        points:
          - {point_id: LIFT-2/INSVC, path: /v1/units/2/status, value: "$.inService"}
          - {point_id: LIFT-2/FAULT, path: /v1/units/2/status, value: "$.fault", alarm_when: {op: "==", value: 1}}
          - {point_id: PV-1/KW, path: /v2/plants/77/now, value: "$.power_kw", unit: kW}

Points sharing a path are read with one GET. A cloud API means traffic leaves the
site: its host must be on the site's approved list (ARVIS_EGRESS_ALLOW) — this
source refuses to start against a host the site hasn't approved. Without an API,
staff report the same things on WhatsApp (manual readings / events).
"""

from __future__ import annotations

import asyncio
import hmac
import inspect
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType
from agent_commercial.sources.base import source_tag
from agent_commercial.sources.common import json_path, number, refuse_inline_secrets, secret, timestamp

logger = logging.getLogger("arvis.sources.rest")
ALLOWED_METHODS = ("GET",)


class RestSource:
    def __init__(self, cfg: Dict[str, Any]):
        refuse_inline_secrets(cfg, f"rest source {cfg.get('id', '')}")
        if cfg.get("headers"):
            raise ValueError("rest source: header values (API keys) go in the environment — use headers_env")
        self.cfg = cfg
        self.source_id = str(cfg.get("id") or "rest")
        self.base_url = str(cfg.get("base_url") or "").rstrip("/")
        host = urlparse(self.base_url).hostname
        if not host:
            raise ValueError(f"rest source {self.source_id}: base_url must be a full URL")
        from agent_commercial import egress_policy
        policy = egress_policy.active()
        if policy is not None:
            ok, why = policy.allows(host)
            if not ok:
                raise ValueError(f"rest source {self.source_id}: {host} is not approved for outbound traffic "
                                 f"({why}) — add it to ARVIS_EGRESS_ALLOW once the site signs it off")
        self.headers = {h: secret({"v_env": var}, "v") for h, var in (cfg.get("headers_env") or {}).items()}
        self.push_token = secret(cfg, "push_token")
        self.timeout = float(cfg.get("timeout", 10.0))
        self.points: List[Dict[str, Any]] = []
        self._cbs: List[Callable[[BMSDataPoint], Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._interval = 120.0
        self._freshness = PointFreshness()
        self.transport = None                   # tests: httpx.MockTransport
        self.stats = {"requests": 0, "failed": 0, "pushes": 0, "last_read": None}

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        self.points = []
        for e in config.get("points") or []:
            if not e.get("point_id") or not (e.get("path") or e.get("push")):
                raise ValueError(f"a REST point needs point_id and path (or push: true): {e}")
            self.points.append({**e, "equipment_id": e.get("equipment_id") or e["point_id"].split("/")[0]})
            self._freshness.register(e["point_id"])
        return len(self.points)

    def _client(self):
        import httpx
        kw = {"timeout": self.timeout, "headers": self.headers, "follow_redirects": False}
        if self.transport is not None:
            kw["transport"] = self.transport
        return httpx.AsyncClient(**kw)

    async def _get(self, client: Any, path: str) -> Any:
        """The only request this source makes."""
        method = "GET"
        assert method in ALLOWED_METHODS
        r = await client.get(f"{self.base_url}{path}")
        r.raise_for_status()
        return r.json()

    async def connect(self) -> bool:
        paths = sorted({p["path"] for p in self.points if p.get("path")})
        if not paths:
            self._connected = True               # push-only
            return True
        try:
            async with self._client() as c:
                await self._get(c, paths[0])
            self._connected = True
        except Exception as e:
            logger.error(f"[REST] {self.source_id}: {self.base_url} not answering: {type(e).__name__}: {e}")
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

    async def start_polling(self, interval_seconds: float = 120) -> None:
        self._interval = float(interval_seconds)
        if any(p.get("path") for p in self.points) and (self._task is None or self._task.done()):
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
        by_path: Dict[str, List[Dict[str, Any]]] = {}
        for p in self.points:
            if p.get("path"):
                by_path.setdefault(p["path"], []).append(p)
        n = 0
        async with self._client() as c:
            for path, pts in by_path.items():
                self.stats["requests"] += 1
                try:
                    doc = await self._get(c, path)
                    self._connected = True
                except Exception as e:
                    self.stats["failed"] += 1
                    self._connected = False
                    logger.warning(f"[REST] {self.source_id} GET {path} failed: {type(e).__name__}: {e}")
                    continue
                n += await self._apply(doc, pts)
        for pid in self._freshness.newly_stale({p["point_id"]: self._interval for p in self.points if p.get("path")}):
            logger.info(f"[REST] {self.source_id}: {pid} has not been read for a while (stale)")
        self.stats["last_read"] = datetime.now().isoformat(timespec="seconds")
        return n

    async def push(self, doc: Any, token: str) -> int:
        """A vendor pushed data: same mapping, for points marked push: true."""
        if not self.push_token or not hmac.compare_digest(self.push_token, token or ""):
            raise PermissionError("wrong or missing push token")
        self.stats["pushes"] += 1
        return await self._apply(doc, [p for p in self.points if p.get("push")])

    async def _apply(self, doc: Any, pts: List[Dict[str, Any]]) -> int:
        n = 0
        for p in pts:
            v = number(json_path(doc, p.get("value")))
            if v is None:
                continue
            ts = timestamp(json_path(doc, p["ts"])) if p.get("ts") else None
            pt = BMSDataPoint(point_id=p["point_id"], name=p.get("name") or p["point_id"],
                              value=v * float(p.get("scale", 1.0)) + float(p.get("offset", 0.0)), unit=p.get("unit", ""),
                              timestamp=ts or datetime.now(), source=source_tag("rest", self.source_id),
                              equipment_id=p["equipment_id"], point_type=PointType.SENSOR, quality=PointQuality.GOOD)
            self._freshness.mark_ok(p["point_id"])
            for cb in self._cbs:
                out = cb(pt)
                if inspect.isawaitable(out):
                    await out
            n += 1
        return n

    def get_stats(self) -> Dict[str, Any]:
        return {**self.stats, "is_connected": self._connected, "polling_active": bool(self._task and not self._task.done()),
                "points_configured": len(self.points), "stale_points": self._freshness.stale_points,
                "base_url": self.base_url}


def _register() -> None:
    from agent_commercial.sources.registry import register_source
    register_source("rest", build=RestSource, points_config=lambda cfg: cfg,
                    point_entries=lambda cfg: list(cfg.get("points") or []), default_poll=120.0)
