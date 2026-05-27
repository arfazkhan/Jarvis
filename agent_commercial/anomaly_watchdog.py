"""
Anomaly Watchdog
================

Continuous 24/7 monitoring of ALL BMS data points.
Registers on state_engine.on_point_update() — fires on every reading.
Uses per-point rolling Z-score + physics hard limits to detect deviations.
Emits AnomalyEvent to EventBus for InvestigationDispatcher to action.

No I/O, no LLM calls — pure math. Non-blocking.
"""

import time
import logging
import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("arvis.monitoring.watchdog")


@dataclass
class AnomalyEvent:
    point_id: str
    equipment_id: str
    current_value: float
    expected_value: float
    deviation_pct: float
    z_score: float
    severity: str           # "significant" | "critical"
    point_name: str = ""
    unit: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class AnomalyWatchdog:
    """
    Continuous BMS monitoring — detects anomalies in ANY reading.

    Registers with BMSStateEngine.on_point_update(). For each incoming
    reading, computes deviation from the point's own 24h rolling history.
    Emits to EventBus when z-score exceeds per-type threshold.

    Two detection paths:
      1. Z-score from rolling history (adaptive to day/night cycles)
      2. Physics hard-limit check for near-constant signals
    """

    # Default Z-score threshold for investigation trigger
    INVESTIGATE_ABOVE: float = 3.0

    # Per-point-type tighter thresholds (safety/comfort critical)
    TYPE_THRESHOLDS: Dict[str, float] = {
        "vibration": 2.0,      # Early bearing failure detection
        "chw_supply": 2.5,     # Chiller supply = comfort critical
        "cop": 2.5,            # Efficiency drop = energy waste
        "filter_dp": 2.0,      # Filter DP rise = maintenance
        "zone_temp": 2.5,      # Comfort
        "sat": 2.5,            # Supply air temp
        "condenser": 2.5,      # Condenser water
        "static_pa": 4.0,      # Static pressure (highly dynamic, high threshold)
        "pressure": 4.0,       # Generic pressure (highly dynamic)
    }

    # Min standard deviation floor to prevent deflation-induced Z-score explosion
    # Calibrated to actual physical units and 0-100% ranges in the Desigo CC BACnet emulator.
    MIN_STD_FLOORS: Dict[str, float] = {
        "vibration": 0.5,      # mm/s
        "chw_supply": 1.0,     # °C (chiller supply temp)
        "cop": 0.5,            # dimensionless
        "filter_dp": 15.0,     # Pa
        "zone_temp": 1.0,      # °C (room comfort temp)
        "sat": 1.5,            # °C (supply air temp)
        "condenser": 1.0,      # °C
        "power": 15.0,         # kW (floor total electrical power)
        "co2": 150.0,          # ppm (occupancy CO2 shifts)
        "airflow": 150.0,      # CFM (VAV airflow modulation)
        "valve": 15.0,         # % (cooling/heating valve position 0-100)
        "damper": 15.0,        # % (damper position 0-100)
        "static_pa": 50.0,     # Pa (AHU static pressure)
        "pressure": 50.0,      # Pa/kPa generic pressure
        "dp": 20.0,            # kPa/Pa differential pressure
        "load": 15.0,          # % / kW chiller load
        "kw": 15.0,            # kW chiller electrical power
        "temp": 1.0,           # °C general temperature fallback
        "generic": 10.0,       # safe fallback default floor for all other points
    }


    def __init__(
        self,
        event_bus=None,
        physics_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
        min_history: int = 10,
        cooldown_seconds: int = 180,
        db_conn=None,
    ):
        self.event_bus = event_bus
        self._physics_bounds: Dict[str, Tuple[float, float]] = physics_bounds or {}
        self._min_history = min_history      # Need N readings before alerting
        self._cooldown = cooldown_seconds    # Per-point alert cooldown
        self._last_alert: Dict[str, float] = {}
        self._anomaly_buffer: deque = deque(maxlen=500)
        self._callbacks: List[Callable[[AnomalyEvent], None]] = []
        self._stats = {"total_processed": 0, "total_anomalies": 0, "suppressed": 0}
        self.paused = False

        self.db_conn = db_conn
        self.calibrated_thresholds: Dict[str, Tuple[float, float]] = {}

        if self.event_bus:
            try:
                self.event_bus.subscribe("thresholds_recalibrated", self._on_recalibration_event)
            except Exception as e:
                logger.error(f"[Watchdog] Subscription to thresholds_recalibrated failed: {e}")

        if self.db_conn:
            asyncio.create_task(self.reload_thresholds())

    def pause(self) -> None:
        """Pause monitoring anomalies."""
        self.paused = True
        logger.info("[Watchdog] AnomalyWatchdog monitoring PAUSED.")

    def resume(self) -> None:
        """Resume monitoring anomalies."""
        self.paused = False
        logger.info("[Watchdog] AnomalyWatchdog monitoring RESUMED.")

    def on_anomaly(self, callback: Callable[[AnomalyEvent], None]) -> None:
        """Register external callback for anomaly events (in addition to EventBus)."""
        self._callbacks.append(callback)

    def on_point_update(self, point) -> None:
        """
        Callback for BMSStateEngine.on_point_update().
        Fires on EVERY point reading — must be fast and non-blocking.
        """
        if getattr(self, "paused", False):
            return

        # Filter out ghost chillers CH-05 to CH-08 based on physical topology limits
        eq_id = str(getattr(point, "equipment_id", "") or "").upper()
        pid = str(getattr(point, "point_id", "") or "").upper()
        if any(ghost in eq_id or ghost in pid for ghost in ["CH-05", "CH-06", "CH-07", "CH-08"]):
            return

        try:
            self._stats["total_processed"] += 1
            self._check_point(point)
        except Exception as e:
            logger.debug(f"[Watchdog] Error checking {getattr(point, 'point_id', '?')}: {e}")

    def _check_point(self, point) -> None:
        value = getattr(point, "value", None)
        if value is None:
            return

        # Skip bad/stale quality readings
        quality = getattr(point, "quality", None)
        quality_val = getattr(quality, "value", str(quality)).lower() if quality else ""
        if quality_val in ("bad", "stale"):
            return

        history = getattr(point, "history", [])
        if len(history) < self._min_history:
            return  # Not enough baseline data yet

        # Compute rolling stats (last 2 hours = ~120 readings @ 1/min)
        recent = history[-120:] if len(history) > 120 else history
        values = [v for _, v in recent if v is not None]
        if len(values) < self._min_history:
            return

        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        std = variance ** 0.5

        if std < 1e-6:
            # Near-constant signal — fall through to physics bounds check
            self._check_physics_bounds(point, value)
            return

        # Get threshold and floor from hierarchical database calibrations or defaults
        threshold, std_floor = self._get_threshold_and_floor(point)

        # Apply standard deviation floor to prevent deflation-induced Z-score explosion
        std = max(std, std_floor)

        z_score = abs(value - mean) / std
        deviation_pct = abs(value - mean) / abs(mean) * 100 if abs(mean) > 1e-9 else 0.0

        if z_score >= threshold:
            self._emit_anomaly(point, value, mean, deviation_pct, z_score)

    def _check_physics_bounds(self, point, value: float) -> None:
        """Hard-limit check for near-constant signals or as backstop."""
        point_type_key = self._classify_point(point)
        bounds = self._physics_bounds.get(point_type_key)
        if not bounds:
            return
        lo, hi = bounds
        if value < lo or value > hi:
            mid = (lo + hi) / 2.0
            deviation_pct = abs(value - mid) / abs(mid) * 100 if abs(mid) > 1e-9 else 100.0
            self._emit_anomaly(point, value, mid, deviation_pct, z_score=5.0)

    def _classify_point(self, point) -> str:
        """Map point_id/unit to a TYPE_THRESHOLDS or MIN_STD_FLOORS key."""
        pid = getattr(point, "point_id", "").lower()
        unit = (getattr(point, "unit", "") or "").lower()

        # Check all distinct keys in both TYPE_THRESHOLDS and MIN_STD_FLOORS against point_id substrings
        all_keys = set(self.TYPE_THRESHOLDS.keys()) | set(self.MIN_STD_FLOORS.keys())
        for key in sorted(all_keys, key=len, reverse=True):  # Longest match first
            if key == "generic":
                continue
            normalized_key = key.replace("_", "")
            normalized_pid = pid.replace("_", "").replace("/", "").replace("-", "")
            if normalized_key in normalized_pid:
                return key

        # Unit/substring-based robust fallback
        if "static_pa" in pid or "staticpa" in pid:
            return "static_pa"
        if "°c" in unit or "temp" in pid or any(t in pid for t in ["chw", "sat", "rat", "oat", "znt", "temp", "cond"]):
            if "chw" in pid:
                return "chw_supply"
            if "sat" in pid:
                return "sat"
            if "cond" in pid:
                return "condenser"
            return "zone_temp"
        if "kw" in unit or "power" in pid:
            return "power"
        if "pa" in unit or "pressure" in pid:
            return "filter_dp"
        if "mm/s" in unit or "vibr" in pid:
            return "vibration"
        if "ppm" in unit or "co2" in pid:
            return "co2"
        if "cfm" in unit or "airflow" in pid or "flow" in pid:
            return "airflow"
        if "vlv" in pid or "valve" in pid:
            return "valve"
        if "dmpr" in pid or "damper" in pid or "pos" in pid:
            return "damper"
        return "generic"

    def _emit_anomaly(
        self,
        point,
        current_value: float,
        expected_value: float,
        deviation_pct: float,
        z_score: float,
    ) -> None:
        """Rate-limited anomaly event emission."""
        now = time.time()
        point_id = getattr(point, "point_id", "unknown")
        last = self._last_alert.get(point_id, 0)
        if (now - last) < self._cooldown:
            self._stats["suppressed"] += 1
            return

        self._last_alert[point_id] = now
        self._stats["total_anomalies"] += 1

        severity = "critical" if z_score >= 4.0 else "significant"

        event = AnomalyEvent(
            point_id=point_id,
            equipment_id=getattr(point, "equipment_id", "unknown"),
            current_value=round(current_value, 3),
            expected_value=round(expected_value, 3),
            deviation_pct=round(deviation_pct, 1),
            z_score=round(z_score, 2),
            severity=severity,
            point_name=getattr(point, "name", point_id),
            unit=getattr(point, "unit", ""),
            timestamp=getattr(point, "timestamp", datetime.now()),
        )

        self._anomaly_buffer.append(event)
        logger.info(
            f"[Watchdog] ANOMALY {severity.upper()}: {point_id} = {current_value} "
            f"(expected ~{expected_value:.2f}, z={z_score:.1f}, dev={deviation_pct:.1f}%)"
        )

        # Notify EventBus subscribers
        if self.event_bus:
            try:
                self.event_bus.publish({"type": "anomaly_detected", "payload": event})
            except Exception as e:
                logger.error(f"[Watchdog] EventBus publish failed: {e}")

        # Notify direct callbacks
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"[Watchdog] Callback error: {e}")

    def get_recent_anomalies(self, minutes: int = 60) -> List[AnomalyEvent]:
        """Return anomalies detected within the last N minutes."""
        cutoff = time.time() - minutes * 60
        return [
            a for a in self._anomaly_buffer
            if a.timestamp.timestamp() > cutoff
        ]

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "buffer_size": len(self._anomaly_buffer),
            "tracked_points": len(self._last_alert),
        }

    async def reload_thresholds(self) -> None:
        """Query promoted calibrations from point_calibrations and cache in memory."""
        if not self.db_conn:
            return
        try:
            logger.info("[Watchdog] Loading active threshold calibrations from database...")
            query = "SELECT scope_key, calibrated_floor, calibrated_z_thresh FROM point_calibrations WHERE promoted = 1"
            async with self.db_conn.execute(query) as cursor:
                rows = await cursor.fetchall()
                new_calibs = {}
                for r in rows:
                    new_calibs[r["scope_key"]] = (r["calibrated_floor"], r["calibrated_z_thresh"])
                self.calibrated_thresholds = new_calibs
                logger.info(f"[Watchdog] Loaded {len(new_calibs)} active calibrations into memory.")
        except Exception as e:
            logger.debug(f"[Watchdog] Calibration table not ready or loading failed: {e}")

    def _on_recalibration_event(self, event) -> None:
        """Triggered when EventBus receives thresholds_recalibrated."""
        logger.info("[Watchdog] thresholds_recalibrated event received! Scheduling hot reload...")
        asyncio.create_task(self.reload_thresholds())

    def _get_threshold_and_floor(self, point) -> Tuple[float, float]:
        """Return (z_threshold, std_floor) for the point using hierarchical lookup."""
        point_id = getattr(point, "point_id", "")
        eq_id = getattr(point, "equipment_id", "")
        pt_type = self._classify_point(point)

        # Deduce eq_type
        eq_id_lower = eq_id.lower() if eq_id else ""
        if "ch" in eq_id_lower:
            eq_type = "chiller"
        elif "ahu" in eq_id_lower:
            eq_type = "ahu"
        elif "vav" in eq_id_lower:
            eq_type = "vav"
        elif "fcu" in eq_id_lower:
            eq_type = "fcu"
        elif "ct" in eq_id_lower:
            eq_type = "ct"
        elif "pump" in eq_id_lower or "pchwp" in eq_id_lower or "schwp" in eq_id_lower or "cdwp" in eq_id_lower:
            eq_type = "pump"
        else:
            eq_type = "generic"

        # Determine bootstrap floor limit
        default_floor = self.MIN_STD_FLOORS.get(pt_type, self.MIN_STD_FLOORS.get("generic", 2.0))

        # Hierarchical lookup in cached calibrations
        # 1. Point level
        p_key = f"point:{point_id}"
        if p_key in self.calibrated_thresholds:
            z_thresh, std_floor = self.calibrated_thresholds[p_key]
            # Cap learned floor to prevent noise dilution
            std_floor = min(std_floor, 3.0 * default_floor)
            return z_thresh, std_floor

        # 2. Equipment level
        e_key = f"eq:{eq_id}"
        if e_key in self.calibrated_thresholds:
            z_thresh, std_floor = self.calibrated_thresholds[e_key]
            std_floor = min(std_floor, 3.0 * default_floor)
            return z_thresh, std_floor

        # 3. Type level
        t_key = f"type:{eq_type}:{pt_type}"
        if t_key in self.calibrated_thresholds:
            z_thresh, std_floor = self.calibrated_thresholds[t_key]
            std_floor = min(std_floor, 3.0 * default_floor)
            return z_thresh, std_floor

        # 4. Fallback to bootstrap defaults
        z_thresh = self.TYPE_THRESHOLDS.get(pt_type, self.INVESTIGATE_ABOVE)
        return z_thresh, default_floor
