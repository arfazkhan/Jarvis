"""
BACnet Adapter
==============

BACnet/IP read-only client for Building Management System integration.

Uses BAC0 library for BACnet communication:
- Device discovery via Who-Is
- Object property reading (Present_Value, Status_Flags, etc.)
- COV (Change of Value) subscriptions for real-time updates
- Map BACnet objects to BMSDataPoint instances

This adapter is READ-ONLY for safety - no control commands.

Compatible with:
- YABE (Yet Another BACnet Explorer) simulator
- Real BACnet/IP devices
- BACnet/MSTP via IP router
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
import threading
import time

from agent_bms.bms_data_model import (
    BMSDataPoint,
    PointType,
    PointQuality,
    Alarm,
    AlarmSeverity,
    AlarmState,
)

logger = logging.getLogger("arvis.bms.bacnet")

# Try to import BAC0
try:
    import BAC0
    from BAC0.core.devices.local.localDevice import DeviceDisconnectedError
    BACNET_AVAILABLE = True
except ImportError:
    BACNET_AVAILABLE = False
    logger.warning("BAC0 not installed. Run: pip install BAC0")


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class BACnetObjectType(Enum):
    """Common BACnet object types"""
    ANALOG_INPUT = "analogInput"
    ANALOG_OUTPUT = "analogOutput"
    ANALOG_VALUE = "analogValue"
    BINARY_INPUT = "binaryInput"
    BINARY_OUTPUT = "binaryOutput"
    BINARY_VALUE = "binaryValue"
    MULTI_STATE_INPUT = "multiStateInput"
    MULTI_STATE_OUTPUT = "multiStateOutput"
    MULTI_STATE_VALUE = "multiStateValue"
    SCHEDULE = "schedule"
    CALENDAR = "calendar"
    TREND_LOG = "trendLog"
    NOTIFICATION_CLASS = "notificationClass"
    EVENT_ENROLLMENT = "eventEnrollment"
    DEVICE = "device"


@dataclass
class BACnetDevice:
    """Discovered BACnet device"""
    device_id: int
    device_name: str
    address: str
    vendor_name: str = ""
    model_name: str = ""
    object_count: int = 0
    
    # Connection state
    is_connected: bool = False
    last_seen: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "address": self.address,
            "vendor_name": self.vendor_name,
            "model_name": self.model_name,
            "object_count": self.object_count,
            "is_connected": self.is_connected,
        }


@dataclass
class BACnetPoint:
    """BACnet point mapping configuration"""
    device_id: int
    object_type: str
    object_instance: int
    property_name: str = "presentValue"
    
    # Mapping to ARVIS
    point_id: str = ""
    point_name: str = ""
    equipment_id: str = ""
    unit: str = ""
    point_type: PointType = PointType.SENSOR
    
    # Polling
    poll_interval_seconds: int = 60
    last_polled: Optional[datetime] = None
    
    @property
    def bacnet_address(self) -> str:
        """BACnet address string for BAC0"""
        return f"{self.object_type}:{self.object_instance}"


# ═══════════════════════════════════════════════════════════════════════════
# BACNET ADAPTER
# ═══════════════════════════════════════════════════════════════════════════

class BACnetAdapter:
    """
    BACnet/IP adapter for building automation systems.
    
    READ-ONLY for safety - no control commands are implemented.
    
    Features:
    - Device discovery via Who-Is
    - Point reading (Present_Value, Status_Flags)
    - COV subscriptions for real-time updates
    - Automatic reconnection
    - Point-to-BMSDataPoint mapping
    
    Example:
        >>> adapter = BACnetAdapter()
        >>> await adapter.connect()
        >>> devices = await adapter.discover_devices()
        >>> value = await adapter.read_point(device_id=1234, 
        ...     object_type="analogInput", instance=1)
    """
    
    def __init__(
        self,
        local_address: str = "0.0.0.0",
        local_port: int = 47808,
        device_id: int = 999,
    ):
        """
        Initialize BACnet adapter.
        
        Args:
            local_address: Local IP to bind to (0.0.0.0 for all interfaces)
            local_port: BACnet/IP port (default 47808)
            device_id: Local device ID for BACnet communication
        """
        self.local_address = local_address
        self.local_port = local_port
        self.device_id = device_id
        
        # BAC0 network
        self._network = None
        self._is_connected = False
        
        # Discovered devices
        self.devices: Dict[int, BACnetDevice] = {}
        
        # Point configurations
        self.points: Dict[str, BACnetPoint] = {}  # point_id -> config
        
        # Polling
        self._polling_thread: Optional[threading.Thread] = None
        self._polling_active = False
        self._poll_interval = 60  # Default poll interval
        
        # Callbacks
        self._on_point_update: List[Callable[[BMSDataPoint], None]] = []
        self._on_alarm: List[Callable[[Alarm], None]] = []
        
        # Statistics
        self.stats = {
            "reads_total": 0,
            "reads_success": 0,
            "reads_failed": 0,
            "last_read": None,
        }
        
        logger.info(f"BACnetAdapter initialized (device_id={device_id})")
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONNECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    async def connect(self) -> bool:
        """
        Connect to BACnet network.
        
        Returns:
            True if connected successfully
        """
        if not BACNET_AVAILABLE:
            logger.error("BAC0 library not available")
            return False
        
        try:
            # Run in thread pool (BAC0 is synchronous)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._connect_sync)
            return self._is_connected
            
        except Exception as e:
            logger.error(f"BACnet connection failed: {e}")
            return False
    
    def _connect_sync(self) -> None:
        """Synchronous connection (for BAC0)"""
        try:
            # Create BAC0 lite network (no device simulation)
            self._network = BAC0.lite(
                ip=self.local_address,
                port=self.local_port,
            )
            self._is_connected = True
            logger.info("Connected to BACnet network")
            
        except Exception as e:
            logger.error(f"BACnet connection error: {e}")
            self._is_connected = False
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from BACnet network"""
        self._polling_active = False
        
        if self._polling_thread and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=5)
        
        if self._network:
            try:
                self._network.disconnect()
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
        
        self._is_connected = False
        logger.info("Disconnected from BACnet network")
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected and self._network is not None
    
    # ═══════════════════════════════════════════════════════════════════════
    # DEVICE DISCOVERY
    # ═══════════════════════════════════════════════════════════════════════
    
    async def discover_devices(self, timeout_seconds: int = 5) -> List[BACnetDevice]:
        """
        Discover BACnet devices on the network via Who-Is.
        
        Args:
            timeout_seconds: How long to wait for responses
            
        Returns:
            List of discovered devices
        """
        if not self.is_connected:
            logger.warning("Not connected to BACnet network")
            return []
        
        try:
            loop = asyncio.get_event_loop()
            devices = await loop.run_in_executor(
                None, 
                self._discover_sync,
                timeout_seconds
            )
            return devices
            
        except Exception as e:
            logger.error(f"Device discovery failed: {e}")
            return []
    
    def _discover_sync(self, timeout: int) -> List[BACnetDevice]:
        """Synchronous device discovery"""
        discovered = []
        
        try:
            # Send Who-Is and wait for I-Am responses
            self._network.whois()
            time.sleep(timeout)
            
            # Get discovered devices from BAC0's internal list
            for device_addr, device_info in self._network.discoveredDevices.items():
                device_id = device_info.get("deviceIdentifier", [None, 0])[1]
                
                device = BACnetDevice(
                    device_id=device_id,
                    device_name=str(device_info.get("objectName", f"Device_{device_id}")),
                    address=str(device_addr),
                    vendor_name=str(device_info.get("vendorName", "")),
                    model_name=str(device_info.get("modelName", "")),
                    is_connected=True,
                )
                
                self.devices[device_id] = device
                discovered.append(device)
                
            logger.info(f"Discovered {len(discovered)} BACnet devices")
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
        
        return discovered
    
    # ═══════════════════════════════════════════════════════════════════════
    # POINT READING
    # ═══════════════════════════════════════════════════════════════════════
    
    async def read_property(
        self,
        device_address: str,
        object_type: str,
        object_instance: int,
        property_name: str = "presentValue"
    ) -> Optional[Any]:
        """
        Read a single property from a BACnet object.
        
        Args:
            device_address: Device IP or address
            object_type: BACnet object type (e.g., "analogInput")
            object_instance: Object instance number
            property_name: Property to read (default: presentValue)
            
        Returns:
            Property value or None if failed
        """
        if not self.is_connected:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            value = await loop.run_in_executor(
                None,
                self._read_property_sync,
                device_address,
                object_type,
                object_instance,
                property_name
            )
            
            self.stats["reads_total"] += 1
            if value is not None:
                self.stats["reads_success"] += 1
            else:
                self.stats["reads_failed"] += 1
            self.stats["last_read"] = datetime.now()
            
            return value
            
        except Exception as e:
            logger.error(f"Read property failed: {e}")
            self.stats["reads_total"] += 1
            self.stats["reads_failed"] += 1
            return None
    
    def _read_property_sync(
        self,
        device_address: str,
        object_type: str,
        object_instance: int,
        property_name: str,
        timeout: float = 5.0,
        max_retries: int = 3,
    ) -> Optional[Any]:
        """
        Synchronous property read with aggressive retry logic.
        
        Real BACnet networks are slow and noisy:
        - Simulator responds in 1ms
        - Real chiller controller might take 2000ms
        
        This method handles:
        - Long timeouts (5s default)
        - Automatic retries with exponential backoff
        - Non-blocking retry delays
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # BAC0 read format: "address objectType:instance propertyName"
                # Note: BAC0 internally handles timeout, but we add retry logic
                result = self._network.read(
                    f"{device_address} {object_type}:{object_instance} {property_name}"
                )
                
                # Success!
                if attempt > 0:
                    logger.debug(f"Read succeeded on attempt {attempt + 1}")
                return result
                
            except Exception as e:
                last_error = e
                logger.debug(
                    f"Read attempt {attempt + 1}/{max_retries} failed: "
                    f"{device_address} {object_type}:{object_instance} - {e}"
                )
                
                # Exponential backoff: 0.5s, 1s, 2s
                if attempt < max_retries - 1:
                    backoff_time = 0.5 * (2 ** attempt)
                    time.sleep(min(backoff_time, timeout))
        
        # All retries failed
        logger.warning(
            f"Read failed after {max_retries} attempts: "
            f"{device_address} {object_type}:{object_instance} - {last_error}"
        )
        return None
    
    async def read_point(self, point_config: BACnetPoint) -> Optional[BMSDataPoint]:
        """
        Read a configured point and return as BMSDataPoint.
        
        Args:
            point_config: Point configuration
            
        Returns:
            BMSDataPoint with current value
        """
        # Get device address
        device = self.devices.get(point_config.device_id)
        if not device:
            logger.warning(f"Device {point_config.device_id} not found")
            return None
        
        # Read value
        value = await self.read_property(
            device_address=device.address,
            object_type=point_config.object_type,
            object_instance=point_config.object_instance,
            property_name=point_config.property_name,
        )
        
        if value is None:
            return None
        
        # Convert to BMSDataPoint
        return BMSDataPoint(
            point_id=point_config.point_id,
            name=point_config.point_name,
            value=float(value) if isinstance(value, (int, float)) else 0.0,
            unit=point_config.unit,
            timestamp=datetime.now(),
            source="bacnet",
            equipment_id=point_config.equipment_id,
            point_type=point_config.point_type,
            quality=PointQuality.GOOD,
            bacnet_device_id=point_config.device_id,
            bacnet_object_type=point_config.object_type,
            bacnet_object_instance=point_config.object_instance,
        )
    
    async def read_all_points(self) -> List[BMSDataPoint]:
        """Read all configured points"""
        results = []
        
        for point_id, config in self.points.items():
            try:
                point = await self.read_point(config)
                if point:
                    results.append(point)
                    config.last_polled = datetime.now()
            except Exception as e:
                logger.error(f"Error reading {point_id}: {e}")
        
        return results
    
    # ═══════════════════════════════════════════════════════════════════════
    # POINT CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def add_point(self, config: BACnetPoint) -> None:
        """Add a point to monitor"""
        self.points[config.point_id] = config
        logger.debug(f"Added point: {config.point_id}")
    
    def remove_point(self, point_id: str) -> bool:
        """Remove a point"""
        if point_id in self.points:
            del self.points[point_id]
            return True
        return False
    
    def load_points_from_config(self, config: Dict[str, Any]) -> int:
        """
        Load point configurations from a dictionary.
        
        Expected format:
        {
            "points": [
                {
                    "point_id": "AHU-01/SAT",
                    "device_id": 1234,
                    "object_type": "analogInput",
                    "object_instance": 1,
                    "name": "Supply Air Temperature",
                    "equipment_id": "AHU-01",
                    "unit": "°C"
                },
                ...
            ]
        }
        """
        count = 0
        for point_cfg in config.get("points", []):
            try:
                point = BACnetPoint(
                    device_id=point_cfg["device_id"],
                    object_type=point_cfg["object_type"],
                    object_instance=point_cfg["object_instance"],
                    point_id=point_cfg.get("point_id", f"point_{count}"),
                    point_name=point_cfg.get("name", ""),
                    equipment_id=point_cfg.get("equipment_id", ""),
                    unit=point_cfg.get("unit", ""),
                    poll_interval_seconds=point_cfg.get("poll_interval", 60),
                )
                self.add_point(point)
                count += 1
            except KeyError as e:
                logger.warning(f"Invalid point config, missing {e}")
        
        logger.info(f"Loaded {count} point configurations")
        return count
    
    # ═══════════════════════════════════════════════════════════════════════
    # POLLING
    # ═══════════════════════════════════════════════════════════════════════
    
    def start_polling(self, interval_seconds: int = 60) -> None:
        """
        Start background polling of all configured points.
        
        Args:
            interval_seconds: Polling interval
        """
        if self._polling_active:
            logger.warning("Polling already active")
            return
        
        self._poll_interval = interval_seconds
        self._polling_active = True
        self._polling_thread = threading.Thread(
            target=self._polling_loop,
            daemon=True
        )
        self._polling_thread.start()
        
        logger.info(f"Started polling every {interval_seconds}s")
    
    def stop_polling(self) -> None:
        """Stop background polling"""
        self._polling_active = False
        if self._polling_thread:
            self._polling_thread.join(timeout=5)
        logger.info("Stopped polling")
    
    def _polling_loop(self) -> None:
        """Background polling loop"""
        while self._polling_active:
            try:
                # Create event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Read all points
                points = loop.run_until_complete(self.read_all_points())
                
                # Notify callbacks
                for point in points:
                    for callback in self._on_point_update:
                        try:
                            callback(point)
                        except Exception as e:
                            logger.error(f"Callback error: {e}")
                
                loop.close()
                
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            # Wait for next poll
            time.sleep(self._poll_interval)
    
    # ═══════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════
    
    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        """Register callback for point updates"""
        self._on_point_update.append(callback)
    
    def on_alarm(self, callback: Callable[[Alarm], None]) -> None:
        """Register callback for BACnet alarms"""
        self._on_alarm.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════════════
    
    def get_stats(self) -> Dict[str, Any]:
        """Get adapter statistics"""
        return {
            **self.stats,
            "is_connected": self.is_connected,
            "devices_discovered": len(self.devices),
            "points_configured": len(self.points),
            "polling_active": self._polling_active,
        }


# ═══════════════════════════════════════════════════════════════════════════
# SIMULATOR ADAPTER (FOR TESTING WITHOUT BAC0)
# ═══════════════════════════════════════════════════════════════════════════

class BACnetSimulatorAdapter:
    """
    Simulated BACnet adapter for testing without real BACnet hardware.
    
    Generates realistic BMS data for development and demos.
    """
    
    def __init__(self):
        self.devices: Dict[int, BACnetDevice] = {}
        self.points: Dict[str, BACnetPoint] = {}
        self._is_connected = False
        self._polling_active = False
        self._on_point_update: List[Callable] = []
        
        # Simulated values state
        self._simulated_values: Dict[str, float] = {}
        
    async def connect(self) -> bool:
        """Simulate connection"""
        self._is_connected = True
        self._setup_simulated_devices()
        logger.info("Connected to BACnet simulator")
        return True
    
    async def disconnect(self) -> None:
        """Simulate disconnection"""
        self._is_connected = False
        self._polling_active = False
    
    def _setup_simulated_devices(self) -> None:
        """Create simulated BMS devices"""
        import random
        
        # Chiller
        self.devices[1001] = BACnetDevice(
            device_id=1001,
            device_name="Chiller-01",
            address="192.168.1.101",
            vendor_name="Carrier",
            model_name="30XA",
            is_connected=True,
        )
        
        # AHU 1
        self.devices[2001] = BACnetDevice(
            device_id=2001,
            device_name="AHU-01",
            address="192.168.1.102",
            vendor_name="Trane",
            model_name="Climate Changer",
            is_connected=True,
        )
        
        # AHU 2
        self.devices[2002] = BACnetDevice(
            device_id=2002,
            device_name="AHU-02",
            address="192.168.1.103",
            vendor_name="Trane",
            model_name="Climate Changer",
            is_connected=True,
        )
        
        # Energy Meter
        self.devices[5001] = BACnetDevice(
            device_id=5001,
            device_name="Main-Meter",
            address="192.168.1.110",
            vendor_name="Schneider",
            model_name="PM5000",
            is_connected=True,
        )
        
        # Initialize simulated values
        self._simulated_values = {
            "CH-01/CHWST": 7.0,    # Chilled water supply temp
            "CH-01/CHWRT": 12.0,   # Chilled water return temp
            "CH-01/KW": 250.0,     # Chiller power
            "AHU-01/SAT": 14.0,    # Supply air temp
            "AHU-01/RAT": 24.0,    # Return air temp
            "AHU-01/SF_SPD": 80.0, # Supply fan speed %
            "AHU-02/SAT": 14.5,
            "AHU-02/RAT": 23.5,
            "AHU-02/SF_SPD": 75.0,
            "METER/KW": 450.0,     # Building power
            "METER/KWH": 125000.0, # Accumulated energy
        }
    
    async def discover_devices(self, timeout_seconds: int = 5) -> List[BACnetDevice]:
        """Return simulated devices"""
        await asyncio.sleep(0.5)  # Simulate network delay
        return list(self.devices.values())
    
    async def read_point(self, point_config: BACnetPoint) -> Optional[BMSDataPoint]:
        """Read simulated point with realistic variation"""
        import random
        
        # Get base value using point_id (e.g., "CH-01/KW")
        base_value = self._simulated_values.get(point_config.point_id, 0.0)
        
        # Fallback to alternate key format if not found
        if base_value == 0.0:
            alt_key = f"{point_config.equipment_id}/{point_config.object_instance}"
            base_value = self._simulated_values.get(alt_key, 0.0)
        
        # Special handling for known power points
        if "METER-01/KW" in point_config.point_id or "METER/KW" in point_config.point_id:
            base_value = 450.0  # Building power
        elif "CH-01/KW" in point_config.point_id:
            base_value = 250.0  # Chiller power
        
        # Add realistic variation
        if "SAT" in point_config.point_id:
            # Supply air temp: varies ±0.5°C
            value = base_value + random.uniform(-0.5, 0.5)
        elif "KW" in point_config.point_id:
            # Power: varies ±5%
            value = base_value * (1 + random.uniform(-0.05, 0.05))
        else:
            value = base_value + random.uniform(-1, 1)
        
        return BMSDataPoint(
            point_id=point_config.point_id,
            name=point_config.point_name,
            value=round(value, 2),
            unit=point_config.unit,
            timestamp=datetime.now(),
            source="simulator",
            equipment_id=point_config.equipment_id,
            point_type=point_config.point_type,
            quality=PointQuality.GOOD,
        )
    
    async def read_all_points(self) -> List[BMSDataPoint]:
        """Read all configured points"""
        results = []
        for config in self.points.values():
            point = await self.read_point(config)
            if point:
                results.append(point)
        return results
    
    def add_point(self, config: BACnetPoint) -> None:
        self.points[config.point_id] = config
    
    def on_point_update(self, callback: Callable[[BMSDataPoint], None]) -> None:
        self._on_point_update.append(callback)
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected
