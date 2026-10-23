"""
OPC UA Adapter — read-only
==========================

Async OPC UA client for ARVIS BMS integration (asyncua). Mirrors the
ModbusAdapter interface: connect / load_points_from_config / on_point_update /
start_polling / get_stats, with the same per-point STALE handling.

Read-only by design: the adapter reads the Value attribute and browses the
address space. It never writes attributes and never calls OPC UA methods
(methods can actuate equipment). tests/test_deployment_security.py fails the
build if a write or method call is added anywhere in runtime code. Give ARVIS
a read-only user on the OPC UA server as well — defence in depth.

Site config (ARVIS_BMS_CONFIG, key ``opcua``):

    opcua:
      endpoint: opc.tcp://10.0.5.20:4840
      # Optional. asyncua security string: "Policy,Mode,client_cert,client_key[,server_cert]"
      security: Basic256Sha256,SignAndEncrypt,certs/arvis.der,certs/arvis.pem
      poll_interval: 30
      timeout: 5
      max_per_request: 500        # servers cap MaxNodesPerRead
      points:
        - node_id: "nsu=http://vendor.com/bms;s=AHU-03.SupplyAirTemp"
          point_id: AHU-03/SAT
          point_name: Supply Air Temp
          equipment_id: AHU-03
          unit: "°C"
          scale: 1.0
          offset: 0.0
          point_type: sensor
          poll_interval: 60       # optional per-point interval (s)

Credentials come only from the environment (ARVIS_OPCUA_USERNAME /
ARVIS_OPCUA_PASSWORD), never from the config file.

Node ids: prefer the namespace-URI form ``nsu=<uri>;s=...``. Namespace
*indexes* (``ns=2``) can change when the server restarts or is reconfigured;
the URI cannot. URI forms are resolved to the current index on every connect.

Egress: with ARVIS_EGRESS_POLICY=enforce only site-LAN IPs and allow-listed
hosts resolve. Use an IP endpoint, or add the server's hostname to
ARVIS_EGRESS_ALLOW — servers often hand back endpoint URLs with their hostname.
"""

import asyncio
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
import warnings

try:
    from asyncua import Client, ua
    ASYNCUA_AVAILABLE = True
except ImportError:
    ASYNCUA_AVAILABLE = False
    warnings.warn("asyncua not installed. Run: pip install asyncua")

from agent_commercial.adapter_health import PointFreshness
from agent_commercial.bms_data_model import BMSDataPoint, PointQuality, PointType

logger = logging.getLogger("arvis.bms.opcua")

_NSU = re.compile(r"^nsu=(?P<uri>.*?);(?P<ident>[isgb]=.*)$", re.DOTALL)


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OpcUaPoint:
    """Configuration for a single OPC UA variable."""
    node_id: str                 # "ns=2;s=..." or (preferred) "nsu=<uri>;s=..."
    point_id: str
    point_name: str = ""
    equipment_id: str = ""
    unit: str = ""
    scale: float = 1.0
    offset: float = 0.0
    point_type: PointType = PointType.SENSOR
    poll_interval_seconds: Optional[int] = None   # None → adapter interval
    last_polled: Optional[datetime] = None

    def __post_init__(self):
        if not self.node_id or not self.point_id:
            raise ValueError("node_id and point_id are required")

    def to_number(self, value: Any) -> Optional[float]:
        """OPC UA value → engineering value, or None if it is not a finite number.
        Booleans become 1/0 (status points); strings, arrays, structures are not numbers."""
        if isinstance(value, bool):
            raw = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            raw = float(value)
        else:
            return None
        if not math.isfinite(raw):
            return None
        return raw * self.scale + self.offset


def _point_from_config(p: Dict[str, Any]) -> OpcUaPoint:
    return OpcUaPoint(
        node_id=str(p["node_id"]).strip(),
        point_id=p["point_id"],
        point_name=p.get("point_name", p["point_id"]),
        equipment_id=p.get("equipment_id", ""),
        unit=p.get("unit", ""),
        scale=float(p.get("scale", 1.0)),
        offset=float(p.get("offset", 0.0)),
        point_type=PointType(str(p.get("point_type", "sensor")).lower()),
        poll_interval_seconds=int(p["poll_interval"]) if p.get("poll_interval") else None,
    )


# ═══════════════════════════════════════════════════════════════════════════
# OPC UA ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class OpcUaAdapter:
    """
    Async read-only OPC UA adapter.

    Example:
        adapter = OpcUaAdapter("opc.tcp://10.0.5.20:4840")
        await adapter.connect()
        adapter.load_points_from_config(site_cfg["opcua"])
        adapter.on_point_update(state_engine.update_point_sync)
        await adapter.start_polling(interval_seconds=30)
    """

    def __init__(
        self,
        endpoint: str,
        security: Optional[str] = None,
        timeout: float = 5.0,
        max_per_request: int = 500,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.endpoint = endpoint
        self.security = security or None
        self.timeout = timeout
        self.max_per_request = max(1, int(max_per_request))
        self._username = username if username is not None else os.getenv("ARVIS_OPCUA_USERNAME") or None
        self._password = password if password is not None else os.getenv("ARVIS_OPCUA_PASSWORD") or None

        self._client: Optional[Any] = None
        self._is_connected = False
        self._points: Dict[str, OpcUaPoint] = {}
        self._nodes: Dict[str, Any] = {}           # point_id → asyncua Node (resolved per connection)
        self._unresolved: Dict[str, str] = {}      # point_id → reason its node id could not be resolved
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 30
        self._on_point_update: List[Callable[[BMSDataPoint], None]] = []
        self._last_value: Dict[str, float] = {}
        self._freshness = PointFreshness()
        self._reconnect_delay = 5.0
        self._non_numeric_warned: set = set()

        self.stats = {
            "reads_total": 0,
            "reads_success": 0,
            "reads_failed": 0,
            "reads_uncertain": 0,
            "reconnects": 0,
            "last_read": None,
        }

        if self.security is None and os.getenv("ARVIS_ENV", "development").lower() == "production":
            logger.warning(f"OPC UA {endpoint}: no security configured — traffic is unsigned and "
                           "unencrypted. Use Basic256Sha256,SignAndEncrypt where the server supports it.")
        logger.info(f"OpcUaAdapter initialized ({endpoint})")

    # ── connection ────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        if not ASYNCUA_AVAILABLE:
            logger.error("asyncua not installed. Cannot connect.")
            return False
        try:
            client = Client(url=self.endpoint, timeout=self.timeout)
            if self._username:
                client.set_user(self._username)
                if self._password:
                    client.set_password(self._password)
            if self.security:
                await client.set_security_string(self.security)
            await client.connect()
            self._client = client
            self._is_connected = True
            await self._resolve_nodes()
            logger.info(f"OPC UA connected to {self.endpoint} "
                        f"({len(self._nodes)}/{len(self._points)} points resolved)")
            return True
        except Exception as e:
            logger.error(f"OPC UA connect error ({self.endpoint}): {type(e).__name__}: {e}")
            self._client = None
            self._is_connected = False
            return False

    async def disconnect(self) -> None:
        await self.stop_polling()
        await self._drop_client()
        logger.info("OPC UA adapter disconnected")

    async def _drop_client(self) -> None:
        client, self._client = self._client, None
        self._is_connected = False
        self._nodes.clear()
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def _resolve_nodes(self) -> None:
        """Map each point to a Node for this connection. URI-form ids are resolved
        against the server's current namespace array, so a renumbered namespace
        does not silently point ARVIS at the wrong variable."""
        self._nodes.clear()
        self._unresolved.clear()
        ns_cache: Dict[str, int] = {}
        for p in self._points.values():
            node_id = p.node_id
            m = _NSU.match(node_id)
            if m:
                uri = m.group("uri")
                if uri not in ns_cache:
                    try:
                        ns_cache[uri] = await self._client.get_namespace_index(uri)
                    except Exception:
                        ns_cache[uri] = -1
                if ns_cache[uri] < 0:
                    self._unresolved[p.point_id] = f"namespace {uri!r} not on server"
                    continue
                node_id = f"ns={ns_cache[uri]};{m.group('ident')}"
            try:
                self._nodes[p.point_id] = self._client.get_node(node_id)
            except Exception as e:
                self._unresolved[p.point_id] = f"invalid node id {p.node_id!r}: {e}"
        for pid, why in self._unresolved.items():
            logger.warning(f"OPC UA point {pid} unresolved: {why}")

    async def _ensure_connected(self) -> bool:
        """Reconnect with exponential backoff after the session drops."""
        if self._is_connected and self._client is not None:
            return True
        await self._drop_client()
        ok = await self.connect()
        self.stats["reconnects"] += 1
        if ok:
            self._reconnect_delay = 5.0
            return True
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 300.0)
        return False

    # ── reading ───────────────────────────────────────────────────────────
    def _datapoint(self, point: OpcUaPoint, value: float, quality: PointQuality) -> BMSDataPoint:
        return BMSDataPoint(
            point_id=point.point_id, name=point.point_name, value=value, unit=point.unit,
            timestamp=datetime.now(timezone.utc), source="opcua", equipment_id=point.equipment_id,
            point_type=point.point_type, quality=quality)

    def _interval(self, point: OpcUaPoint) -> float:
        return float(point.poll_interval_seconds or self._poll_interval)

    def _due(self, point: OpcUaPoint, now: datetime) -> bool:
        return point.last_polled is None or \
            (now - point.last_polled).total_seconds() >= self._interval(point) - 0.5

    async def read_all_points(self, only_due: bool = False) -> List[BMSDataPoint]:
        """One batched Read per `max_per_request` points. Good values are emitted
        GOOD, Uncertain values UNCERTAIN; Bad status, non-numeric values and
        unresolved nodes produce nothing and age the point into STALE."""
        results: List[BMSDataPoint] = []
        now = datetime.now()
        due = [p for p in self._points.values() if not only_due or self._due(p, now)]
        for p in due:
            p.last_polled = now
        readable = [p for p in due if p.point_id in self._nodes] if self._is_connected else []
        self.stats["reads_total"] += len(due)
        self.stats["reads_failed"] += len(due) - len(readable)

        for i in range(0, len(readable), self.max_per_request):
            chunk = readable[i:i + self.max_per_request]
            try:
                data_values = await self._client.read_attributes([self._nodes[p.point_id] for p in chunk])
            except Exception as e:
                # Service-level failure: the session is gone or unusable. Reconnect next tick.
                self.stats["reads_failed"] += len(readable) - i
                logger.warning(f"OPC UA read failed ({self.endpoint}): {type(e).__name__}: {e}")
                self._is_connected = False
                break
            for p, dv in zip(chunk, data_values):
                dp = self._to_datapoint(p, dv)
                if dp is None:
                    self.stats["reads_failed"] += 1
                    continue
                self.stats["reads_success"] += 1
                results.append(dp)
        if results:
            self.stats["last_read"] = datetime.now()

        # Points that stopped answering go STALE once (last value, clearly flagged).
        for pid in self._freshness.newly_stale({p.point_id: self._interval(p) for p in self._points.values()}):
            p = self._points[pid]
            if pid in self._last_value:
                results.append(self._datapoint(p, self._last_value[pid], PointQuality.STALE))
            logger.warning(f"OPC UA point {pid} is stale (no good read for "
                           f"{self._freshness.stale_factor:g}× its poll interval)")
        return results

    def _to_datapoint(self, p: OpcUaPoint, dv: Any) -> Optional[BMSDataPoint]:
        status = getattr(dv, "StatusCode", None)
        if status is not None and status.is_bad():
            logger.debug(f"OPC UA {p.point_id}: bad status {status.name}")
            return None
        variant = getattr(dv, "Value", None)
        value = p.to_number(getattr(variant, "Value", None))
        if value is None:
            if p.point_id not in self._non_numeric_warned:
                self._non_numeric_warned.add(p.point_id)
                logger.warning(f"OPC UA {p.point_id} ({p.node_id}) is not a finite number "
                               f"({type(getattr(variant, 'Value', None)).__name__}) — not ingested")
            return None
        self._last_value[p.point_id] = value
        self._freshness.mark_ok(p.point_id)
        if status is not None and status.is_uncertain():
            self.stats["reads_uncertain"] += 1
            return self._datapoint(p, value, PointQuality.UNCERTAIN)
        return self._datapoint(p, value, PointQuality.GOOD)

    # ── discovery (read-only browse) ──────────────────────────────────────
    async def discover_variables(self, start_node: Optional[str] = None, max_depth: int = 6,
                                 max_nodes: int = 5000) -> List[Dict[str, Any]]:
        """Browse the address space for Variables, to build a site point map.

        Returns dicts with a stable ``node_id`` (namespace-URI form), the browse
        path, display name, data type and engineering unit (from the standard
        EngineeringUnits property, when the server publishes it). The Server
        diagnostics subtree is skipped. Browsing is read-only.
        """
        if not self._client or not self._is_connected:
            raise RuntimeError("not connected")
        ns_array = await self._client.get_namespace_array()
        root = self._client.get_node(start_node) if start_node else self._client.get_objects_node()
        server_node = ua.NodeId(ua.ObjectIds.Server, 0)
        mask = ua.NodeClass.Object | ua.NodeClass.Variable
        out: List[Dict[str, Any]] = []
        seen = set()
        queue = [(root, [], 0)]
        while queue and len(out) < max_nodes:
            node, path, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            try:
                refs = await node.get_children_descriptions(nodeclassmask=mask)
            except Exception as e:
                logger.debug(f"OPC UA browse {node}: {e}")
                continue
            for ref in refs:
                nid = ref.NodeId
                key = nid.to_string()
                if key in seen or nid == server_node:
                    continue
                seen.add(key)
                name = ref.DisplayName.Text or ref.BrowseName.Name
                child = self._client.get_node(nid)
                child_path = path + [name]
                if ref.NodeClass == ua.NodeClass.Variable:
                    out.append(await self._describe_variable(child, nid, child_path, ns_array))
                    if len(out) >= max_nodes:
                        break
                queue.append((child, child_path, depth + 1))
        return out

    async def _describe_variable(self, node: Any, nid: Any, path: List[str], ns_array: List[str]) -> Dict[str, Any]:
        ident = nid.to_string().split(";", 1)[-1] if nid.NamespaceIndex else nid.to_string()
        stable = (f"nsu={ns_array[nid.NamespaceIndex]};{ident}"
                  if 0 < nid.NamespaceIndex < len(ns_array) else nid.to_string())
        entry: Dict[str, Any] = {"node_id": stable, "browse_path": "/".join(path),
                                 "point_name": path[-1], "data_type": None, "unit": ""}
        try:
            entry["data_type"] = (await node.read_data_type_as_variant_type()).name
        except Exception:
            pass
        try:
            eu = await node.get_child("0:EngineeringUnits")
            info = await eu.read_value()
            entry["unit"] = getattr(getattr(info, "DisplayName", None), "Text", "") or ""
        except Exception:
            pass
        return entry

    # ── configuration ─────────────────────────────────────────────────────
    def add_point(self, point: OpcUaPoint) -> None:
        self._points[point.point_id] = point
        self._freshness.register(point.point_id)

    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        count = 0
        for p in config.get("points", []):
            try:
                self.add_point(_point_from_config(p))
                count += 1
            except (KeyError, ValueError) as e:
                logger.warning(f"Invalid OPC UA point config, skipping: {e}")
        logger.info(f"Loaded {count} OPC UA point configurations")
        return count

    # ── polling ───────────────────────────────────────────────────────────
    async def start_polling(self, interval_seconds: int = 30) -> None:
        if self._poll_task and not self._poll_task.done():
            logger.warning("Polling already active")
            return
        self._poll_interval = interval_seconds
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"OPC UA polling started every {interval_seconds}s")

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        tick = max(1.0, min([self._poll_interval] + [
            float(p.poll_interval_seconds) for p in self._points.values() if p.poll_interval_seconds]))
        while True:
            try:
                await self._ensure_connected()
                # Read even when the session is down: failed reads age points into STALE.
                for point in await self.read_all_points(only_due=True):
                    for cb in self._on_point_update:
                        try:
                            result = cb(point)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"OPC UA poll error: {e}")
            await asyncio.sleep(tick)

    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "endpoint": self.endpoint,
            "secured": self.security is not None,
            "is_connected": self._is_connected,
            "points_configured": len(self._points),
            "points_unresolved": dict(self._unresolved),
            "stale_points": self._freshness.stale_points,
            "polling_active": self._poll_task is not None and not self._poll_task.done(),
        }


def opcua_adapter_from_config(config: Dict[str, Any]) -> OpcUaAdapter:
    """Build an adapter from the site config's ``opcua`` section."""
    if not config.get("endpoint"):
        raise ValueError("opcua.endpoint is required (e.g. opc.tcp://10.0.5.20:4840)")
    if "password" in config or "username" in config:
        raise ValueError("Put OPC UA credentials in ARVIS_OPCUA_USERNAME / ARVIS_OPCUA_PASSWORD, "
                         "not in the site config file.")
    return OpcUaAdapter(
        endpoint=config["endpoint"],
        security=config.get("security"),
        timeout=float(config.get("timeout", 5.0)),
        max_per_request=int(config.get("max_per_request", 500)),
    )
