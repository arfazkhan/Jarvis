"""
CAFM Integration Adapter
========================

Connects ARVIS to Computer-Aided Facility Management (CAFM) systems.

Responsibilities:
- Push work orders when ARVIS recommendations are accepted by operator
- Pull maintenance history to enrich predictive maintenance models
- Sync asset registry (equipment IDs, specs, warranty dates)

Supported backends:
  - REST (generic webhook / OpenAPI)
  - IBM Maximo (REST API v7.6+)
  - Planon (REST API)

Usage:
    # Generic REST CAFM
    cafm = RestCAFMAdapter(base_url="https://cafm.example.com", api_key="...")
    await cafm.push_work_order("AHU-01", "Filter replacement required", priority="high")

    # Maximo
    cafm = MaximoCAFMAdapter(base_url="https://maximo.example.com", username="...", password="...")
    history = await cafm.get_maintenance_history("AHU-01", days=90)
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger("arvis.bms.cafm")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class WorkOrder:
    """Represents a CAFM work order."""
    equipment_id: str
    description: str
    priority: str = "medium"         # low | medium | high | emergency
    work_type: str = "preventive"    # preventive | corrective | inspection
    scheduled_date: Optional[datetime] = None
    arvis_recommendation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    work_order_id: Optional[str] = None   # Assigned by CAFM on creation
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "equipment_id": self.equipment_id,
            "description": self.description,
            "priority": self.priority,
            "work_type": self.work_type,
            "scheduled_date": self.scheduled_date.isoformat() if self.scheduled_date else None,
            "arvis_recommendation_id": self.arvis_recommendation_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MaintenanceRecord:
    """A maintenance history record pulled from CAFM."""
    work_order_id: str
    equipment_id: str
    description: str
    work_type: str
    completed_date: Optional[datetime]
    technician: str = ""
    parts_replaced: List[str] = field(default_factory=list)
    labor_hours: float = 0.0
    cost: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "equipment_id": self.equipment_id,
            "description": self.description,
            "work_type": self.work_type,
            "completed_date": self.completed_date.isoformat() if self.completed_date else None,
            "technician": self.technician,
            "parts_replaced": self.parts_replaced,
            "labor_hours": self.labor_hours,
            "cost": self.cost,
        }


@dataclass
class AssetRecord:
    """Equipment asset record from CAFM."""
    equipment_id: str
    name: str
    equipment_type: str
    location: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    install_date: Optional[datetime] = None
    warranty_expiry: Optional[datetime] = None
    rated_capacity: Optional[float] = None
    rated_capacity_unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "name": self.name,
            "equipment_type": self.equipment_type,
            "location": self.location,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial_number": self.serial_number,
            "install_date": self.install_date.isoformat() if self.install_date else None,
            "warranty_expiry": self.warranty_expiry.isoformat() if self.warranty_expiry else None,
            "rated_capacity": self.rated_capacity,
            "rated_capacity_unit": self.rated_capacity_unit,
        }


# ═══════════════════════════════════════════════════════════════════════════
# BASE INTERFACE
# ═══════════════════════════════════════════════════════════════════════════

class CAFMAdapter(ABC):
    """Abstract base for all CAFM adapters."""

    @abstractmethod
    async def push_work_order(self, work_order: WorkOrder) -> Optional[str]:
        """
        Create a work order in CAFM.
        Returns the CAFM-assigned work order ID, or None on failure.
        """

    @abstractmethod
    async def get_maintenance_history(
        self, equipment_id: str, days: int = 90
    ) -> List[MaintenanceRecord]:
        """Pull maintenance history for equipment."""

    @abstractmethod
    async def sync_asset_registry(self) -> List[AssetRecord]:
        """Pull full asset list from CAFM."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify connectivity to CAFM system."""


# ═══════════════════════════════════════════════════════════════════════════
# REST (GENERIC) ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class RestCAFMAdapter(CAFMAdapter):
    """
    Generic REST adapter for any CAFM system with an OpenAPI endpoint.

    Expects the target CAFM to accept:
      POST /work-orders       { equipment_id, description, priority, ... }
      GET  /work-orders?equipment_id=X&from=ISO8601
      GET  /assets

    Configure field_map to remap ARVIS field names to CAFM's schema.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        field_map: Optional[Dict[str, str]] = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.password = password
        self.field_map = field_map or {}
        self.timeout = timeout
        self._session: Optional[Any] = None

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _remap(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply field_map renaming for CAFM-specific schema differences."""
        result = {}
        for k, v in data.items():
            mapped_key = self.field_map.get(k, k)
            result[mapped_key] = v
        return result

    async def _ensure_session(self):
        if self._session is None:
            try:
                import aiohttp
                auth = None
                if self.username and self.password:
                    auth = aiohttp.BasicAuth(self.username, self.password)
                self._session = aiohttp.ClientSession(
                    headers=self._get_headers(),
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                )
            except ImportError:
                raise RuntimeError("aiohttp not installed. Run: pip install aiohttp")

    async def push_work_order(self, work_order: WorkOrder) -> Optional[str]:
        await self._ensure_session()
        payload = self._remap(work_order.to_dict())
        try:
            async with self._session.post(
                f"{self.base_url}/work-orders", json=payload
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    wo_id = str(data.get("id") or data.get("work_order_id") or "")
                    logger.info(f"CAFM work order created: {wo_id} for {work_order.equipment_id}")
                    return wo_id
                else:
                    text = await resp.text()
                    logger.error(f"CAFM push failed {resp.status}: {text[:200]}")
                    return None
        except Exception as e:
            logger.error(f"CAFM push_work_order error: {e}")
            return None

    async def get_maintenance_history(
        self, equipment_id: str, days: int = 90
    ) -> List[MaintenanceRecord]:
        await self._ensure_session()
        from_date = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            async with self._session.get(
                f"{self.base_url}/work-orders",
                params={"equipment_id": equipment_id, "from": from_date, "status": "completed"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    records = []
                    for item in (data if isinstance(data, list) else data.get("results", [])):
                        records.append(MaintenanceRecord(
                            work_order_id=str(item.get("id", "")),
                            equipment_id=equipment_id,
                            description=item.get("description", ""),
                            work_type=item.get("work_type", "corrective"),
                            completed_date=datetime.fromisoformat(item["completed_date"])
                                if item.get("completed_date") else None,
                            technician=item.get("technician", ""),
                            labor_hours=float(item.get("labor_hours", 0)),
                            cost=float(item.get("cost", 0)),
                        ))
                    return records
                else:
                    logger.error(f"CAFM history fetch failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"CAFM get_maintenance_history error: {e}")
            return []

    async def sync_asset_registry(self) -> List[AssetRecord]:
        await self._ensure_session()
        try:
            async with self._session.get(f"{self.base_url}/assets") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    assets = []
                    for item in (data if isinstance(data, list) else data.get("results", [])):
                        assets.append(AssetRecord(
                            equipment_id=str(item.get("equipment_id") or item.get("asset_id", "")),
                            name=item.get("name", ""),
                            equipment_type=item.get("type", ""),
                            location=item.get("location", ""),
                            manufacturer=item.get("manufacturer", ""),
                            model=item.get("model", ""),
                            serial_number=item.get("serial_number", ""),
                        ))
                    return assets
                else:
                    logger.error(f"CAFM asset sync failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"CAFM sync_asset_registry error: {e}")
            return []

    async def health_check(self) -> bool:
        await self._ensure_session()
        try:
            async with self._session.get(f"{self.base_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# IBM MAXIMO ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class MaximoCAFMAdapter(CAFMAdapter):
    """
    IBM Maximo Application Suite (REST API v7.6+).

    Uses OSLC/JSON API:
      POST /maximo/oslc/os/mxwo                  → create work order
      GET  /maximo/oslc/os/mxwo?oslc.where=...   → query history
      GET  /maximo/oslc/os/mxasset                → asset registry
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        site_id: str = "BEDFORD",
        org_id: str = "EAGLENA",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.site_id = site_id
        self.org_id = org_id
        self.timeout = timeout
        self._session: Optional[Any] = None
        self._api_key: Optional[str] = None

    async def _ensure_session(self) -> None:
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                # Authenticate via Maximo API key endpoint
                async with self._session.get(
                    f"{self.base_url}/maximo/oslc/login",
                    auth=aiohttp.BasicAuth(self.username, self.password),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._api_key = data.get("apikey", "")
                        if self._api_key:
                            self._session.headers.update({"apikey": self._api_key})
                        logger.info("Maximo authentication successful")
                    else:
                        logger.warning(f"Maximo auth returned {resp.status}, using basic auth")
            except ImportError:
                raise RuntimeError("aiohttp not installed. Run: pip install aiohttp")

    async def push_work_order(self, work_order: WorkOrder) -> Optional[str]:
        await self._ensure_session()

        priority_map = {"low": 3, "medium": 2, "high": 1, "emergency": 1}
        payload = {
            "description": work_order.description,
            "assetnum": work_order.equipment_id,
            "siteid": self.site_id,
            "orgid": self.org_id,
            "worktype": "CM" if work_order.work_type == "corrective" else "PM",
            "wopriority": priority_map.get(work_order.priority, 2),
            "schedstart": (work_order.scheduled_date or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "description_longdescription": f"Generated by ARVIS. Recommendation ID: {work_order.arvis_recommendation_id}",
        }
        try:
            async with self._session.post(
                f"{self.base_url}/maximo/oslc/os/mxwo",
                json=payload,
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    wo_id = str(data.get("wonum", ""))
                    logger.info(f"Maximo WO created: {wo_id}")
                    return wo_id
                else:
                    text = await resp.text()
                    logger.error(f"Maximo WO create failed {resp.status}: {text[:200]}")
                    return None
        except Exception as e:
            logger.error(f"Maximo push_work_order error: {e}")
            return None

    async def get_maintenance_history(
        self, equipment_id: str, days: int = 90
    ) -> List[MaintenanceRecord]:
        await self._ensure_session()
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00+00:00")
        where = f'assetnum="{equipment_id}" and status="COMP" and schedstart>="{from_date}"'
        try:
            async with self._session.get(
                f"{self.base_url}/maximo/oslc/os/mxwo",
                params={"oslc.where": where, "oslc.select": "*", "oslc.pageSize": "100"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("rdfs:member", [])
                    records = []
                    for item in items:
                        completed_str = item.get("actfinish") or item.get("schedfinish")
                        records.append(MaintenanceRecord(
                            work_order_id=str(item.get("wonum", "")),
                            equipment_id=equipment_id,
                            description=item.get("description", ""),
                            work_type=item.get("worktype", "CM"),
                            completed_date=datetime.fromisoformat(completed_str.replace("Z", "+00:00"))
                                if completed_str else None,
                            technician=item.get("supervisor", ""),
                            labor_hours=float(item.get("actlabhrs", 0) or 0),
                            cost=float(item.get("actcost", 0) or 0),
                        ))
                    return records
                else:
                    logger.error(f"Maximo history fetch failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Maximo get_maintenance_history error: {e}")
            return []

    async def sync_asset_registry(self) -> List[AssetRecord]:
        await self._ensure_session()
        try:
            async with self._session.get(
                f"{self.base_url}/maximo/oslc/os/mxasset",
                params={"oslc.select": "*", "oslc.pageSize": "500"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("rdfs:member", [])
                    assets = []
                    for item in items:
                        install_str = item.get("installdate")
                        warranty_str = item.get("warrantyexpdate")
                        assets.append(AssetRecord(
                            equipment_id=str(item.get("assetnum", "")),
                            name=item.get("description", ""),
                            equipment_type=item.get("assettype", ""),
                            location=item.get("location", ""),
                            manufacturer=item.get("manufacturer", ""),
                            model=item.get("model", ""),
                            serial_number=item.get("serialnum", ""),
                            install_date=datetime.fromisoformat(install_str) if install_str else None,
                            warranty_expiry=datetime.fromisoformat(warranty_str) if warranty_str else None,
                        ))
                    return assets
                else:
                    logger.error(f"Maximo asset sync failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Maximo sync_asset_registry error: {e}")
            return []

    async def health_check(self) -> bool:
        await self._ensure_session()
        try:
            async with self._session.get(f"{self.base_url}/maximo/oslc/os/mxwo?oslc.pageSize=1") as resp:
                return resp.status == 200
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# PLANON ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class PlanonCAFMAdapter(CAFMAdapter):
    """
    Planon Universe REST API adapter.

    Uses Planon BAS REST API:
      POST /PlanonRESTService/PlanonAPIService/WorkOrder
      GET  /PlanonRESTService/PlanonAPIService/WorkOrder?filter=...
      GET  /PlanonRESTService/PlanonAPIService/Asset
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session: Optional[Any] = None
        self._token: Optional[str] = None

    async def _ensure_session(self) -> None:
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                # Planon token auth
                async with self._session.post(
                    f"{self.base_url}/PlanonRESTService/authentication/login",
                    json={"username": self.username, "password": self.password},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._token = data.get("token", "")
                        if self._token:
                            self._session.headers.update({"Authorization": f"Bearer {self._token}"})
                        logger.info("Planon authentication successful")
                    else:
                        logger.warning(f"Planon auth returned {resp.status}")
            except ImportError:
                raise RuntimeError("aiohttp not installed. Run: pip install aiohttp")

    async def push_work_order(self, work_order: WorkOrder) -> Optional[str]:
        await self._ensure_session()
        payload = {
            "Code": work_order.equipment_id,
            "Description": work_order.description,
            "Priority": {"Code": work_order.priority.upper()},
            "WorkOrderType": {"Code": "CORRECTIVE" if work_order.work_type == "corrective" else "PREVENTIVE"},
            "PlannedStartDate": (work_order.scheduled_date or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"),
            "Remarks": f"ARVIS recommendation: {work_order.arvis_recommendation_id}",
        }
        try:
            async with self._session.post(
                f"{self.base_url}/PlanonRESTService/PlanonAPIService/WorkOrder",
                json=payload,
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    wo_id = str(data.get("Code", data.get("Id", "")))
                    logger.info(f"Planon WO created: {wo_id}")
                    return wo_id
                else:
                    text = await resp.text()
                    logger.error(f"Planon WO create failed {resp.status}: {text[:200]}")
                    return None
        except Exception as e:
            logger.error(f"Planon push_work_order error: {e}")
            return None

    async def get_maintenance_history(
        self, equipment_id: str, days: int = 90
    ) -> List[MaintenanceRecord]:
        await self._ensure_session()
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
        try:
            async with self._session.get(
                f"{self.base_url}/PlanonRESTService/PlanonAPIService/WorkOrder",
                params={
                    "filter": f"Code eq '{equipment_id}' and Status eq 'Completed' and PlannedStartDate gt '{from_date}'",
                    "top": 100,
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("value", [])
                    records = []
                    for item in items:
                        completed_str = item.get("ActualEndDate")
                        records.append(MaintenanceRecord(
                            work_order_id=str(item.get("Code", "")),
                            equipment_id=equipment_id,
                            description=item.get("Description", ""),
                            work_type=item.get("WorkOrderType", {}).get("Code", "CORRECTIVE"),
                            completed_date=datetime.fromisoformat(completed_str) if completed_str else None,
                            technician=item.get("Technician", {}).get("FullName", ""),
                            labor_hours=float(item.get("ActualHours", 0) or 0),
                            cost=float(item.get("ActualCosts", 0) or 0),
                        ))
                    return records
                else:
                    logger.error(f"Planon history fetch failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Planon get_maintenance_history error: {e}")
            return []

    async def sync_asset_registry(self) -> List[AssetRecord]:
        await self._ensure_session()
        try:
            async with self._session.get(
                f"{self.base_url}/PlanonRESTService/PlanonAPIService/Asset",
                params={"top": 500},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("value", [])
                    assets = []
                    for item in items:
                        assets.append(AssetRecord(
                            equipment_id=str(item.get("Code", "")),
                            name=item.get("Description", ""),
                            equipment_type=item.get("AssetType", {}).get("Code", ""),
                            location=item.get("Location", {}).get("Description", ""),
                            manufacturer=item.get("Manufacturer", ""),
                            model=item.get("Model", ""),
                            serial_number=item.get("SerialNumber", ""),
                        ))
                    return assets
                else:
                    logger.error(f"Planon asset sync failed: {resp.status}")
                    return []
        except Exception as e:
            logger.error(f"Planon sync_asset_registry error: {e}")
            return []

    async def health_check(self) -> bool:
        await self._ensure_session()
        try:
            async with self._session.get(
                f"{self.base_url}/PlanonRESTService/PlanonAPIService/WorkOrder",
                params={"top": 1},
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════

def create_cafm_adapter(config: Dict[str, Any]) -> CAFMAdapter:
    """
    Factory: instantiate correct CAFM adapter from config dict.

    Config keys:
        type: "rest" | "maximo" | "planon"
        base_url: str
        api_key: str (for REST)
        username / password: str (for Maximo, Planon)
        site_id / org_id: str (Maximo only)
    """
    adapter_type = config.get("type", "rest").lower()

    if adapter_type == "maximo":
        return MaximoCAFMAdapter(
            base_url=config["base_url"],
            username=config["username"],
            password=config["password"],
            site_id=config.get("site_id", "BEDFORD"),
            org_id=config.get("org_id", "EAGLENA"),
        )
    elif adapter_type == "planon":
        return PlanonCAFMAdapter(
            base_url=config["base_url"],
            username=config["username"],
            password=config["password"],
        )
    else:
        return RestCAFMAdapter(
            base_url=config["base_url"],
            api_key=config.get("api_key"),
            username=config.get("username"),
            password=config.get("password"),
            field_map=config.get("field_map", {}),
        )


# ═══════════════════════════════════════════════════════════════════════════
# ARVIS INTEGRATION HELPER
# ═══════════════════════════════════════════════════════════════════════════

class CAFMIntegration:
    """
    Bridges ARVIS recommendations to CAFM work orders.

    Wires into the operator approval flow:
      operator approves recommendation → auto-creates CAFM work order
      CAFM history → enriches predictive maintenance model

    Usage:
        integration = CAFMIntegration(adapter=create_cafm_adapter(config))
        # Called when operator approves a recommendation
        wo_id = await integration.on_recommendation_approved(recommendation)
    """

    def __init__(self, adapter: CAFMAdapter):
        self.adapter = adapter
        self._pending: List[WorkOrder] = []

    async def on_recommendation_approved(
        self,
        recommendation: Dict[str, Any],
    ) -> Optional[str]:
        """
        Convert an approved ARVIS recommendation into a CAFM work order.
        Returns CAFM work order ID on success.
        """
        priority_map = {
            "critical": "emergency",
            "high": "high",
            "medium": "medium",
            "low": "low",
        }

        wo = WorkOrder(
            equipment_id=recommendation.get("equipment_id", "UNKNOWN"),
            description=recommendation.get("title") or recommendation.get("description", ""),
            priority=priority_map.get(recommendation.get("priority", "medium"), "medium"),
            work_type="corrective" if recommendation.get("domain") == "maintenance" else "preventive",
            arvis_recommendation_id=recommendation.get("recommendation_id"),
            metadata={"arvis_source": True, "confidence": recommendation.get("confidence", 0)},
        )

        wo_id = await self.adapter.push_work_order(wo)
        if wo_id:
            wo.work_order_id = wo_id
            logger.info(f"CAFM work order {wo_id} created for recommendation {wo.arvis_recommendation_id}")
        else:
            self._pending.append(wo)
            logger.warning(f"CAFM push failed, queued for retry ({len(self._pending)} pending)")

        return wo_id

    async def enrich_maintenance_model(
        self,
        predictive_engine: Any,
        equipment_id: str,
        days: int = 90,
    ) -> int:
        """
        Pull CAFM history and feed into predictive maintenance engine.
        Returns number of records loaded.
        """
        records = await self.adapter.get_maintenance_history(equipment_id, days)
        count = 0
        for record in records:
            if record.completed_date and hasattr(predictive_engine, "record_maintenance_event"):
                predictive_engine.record_maintenance_event(
                    equipment_id=equipment_id,
                    completed_at=record.completed_date,
                    work_type=record.work_type,
                    parts_replaced=record.parts_replaced,
                )
                count += 1
        logger.info(f"Loaded {count} CAFM maintenance records for {equipment_id}")
        return count

    async def retry_pending(self) -> int:
        """Retry any queued work orders that failed on first push."""
        if not self._pending:
            return 0
        succeeded = []
        for wo in self._pending:
            wo_id = await self.adapter.push_work_order(wo)
            if wo_id:
                wo.work_order_id = wo_id
                succeeded.append(wo)
        self._pending = [wo for wo in self._pending if wo not in succeeded]
        return len(succeeded)
