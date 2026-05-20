"""
GSAS Occupancy Context Provider
================================

Aggregates real occupancy signals from BMS data points (CO2, VAV damper, lighting)
via VirtualOccupancySensor to support GSAS optimisation decisions.

Fallback strategy
-----------------
When bms_state_engine is None or a required point is absent, every method returns
a dict that is clearly marked with ``"confidence": 0.0`` and
``"data_source": "unavailable"`` — no hardcoded fake numbers are ever surfaced as
real measurements.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from agent_commercial.virtual_sensors import VirtualOccupancySensor

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_CO2_LOW_OCCUPANCY = VirtualOccupancySensor.CO2_LOW_OCCUPANCY  # 500 ppm
_PERSONS_PER_OCCUPIED_ZONE = 5  # rough estimate for building headcount


def _try_get_value(bms, *candidate_ids: str) -> Optional[float]:
    """
    Try each point_id in order; return the first non-None value found.
    Uses get_point_sync when available, falls back to direct _points lookup.
    """
    for pid in candidate_ids:
        try:
            if hasattr(bms, "get_point_sync"):
                pt = bms.get_point_sync(pid)
            else:
                pt = bms._points.get(pid)  # type: ignore[attr-defined]
            if pt is not None and pt.value is not None:
                return float(pt.value)
        except Exception:
            pass
    return None


def _co2_candidates(zone_id: str) -> List[str]:
    """Return candidate CO2 point-ID strings for a zone."""
    normalised = zone_id.replace("-", "").replace(" ", "_").upper()
    return [
        f"{zone_id}/CO2",
        f"{normalised}/CO2",
        f"{zone_id.upper()}/CO2",
    ]


def _vav_candidates(zone_id: str) -> List[str]:
    normalised = zone_id.replace("-", "").replace(" ", "_").upper()
    return [
        f"{zone_id}/DAMPER",
        f"{normalised}/DAMPER",
        f"{zone_id.upper()}/DAMPER",
    ]


def _light_candidates(zone_id: str) -> List[str]:
    normalised = zone_id.replace("-", "").replace(" ", "_").upper()
    return [
        f"{zone_id}/LIGHT",
        f"{normalised}/LIGHT",
        f"{zone_id.upper()}/LIGHT",
    ]


def _discover_zone_ids(bms) -> List[str]:
    """
    Enumerate zone IDs by scanning _points for keys that end with '/CO2'.
    Falls back to an empty list when the engine is unavailable.
    """
    try:
        points: Dict = getattr(bms, "_points", {})
        zone_ids: List[str] = []
        for pid in points:
            if pid.upper().endswith("/CO2"):
                zone_id = pid[: pid.upper().rindex("/CO2")]
                if zone_id and zone_id not in zone_ids:
                    zone_ids.append(zone_id)
        return zone_ids
    except Exception as exc:
        logger.debug("_discover_zone_ids failed: %s", exc)
        return []


def _build_schedule_fallback(zone_id: str) -> Dict[str, Any]:
    """
    Returns a conservative schedule-based pattern when BMS data is absent.
    All fields clearly indicate the data source and zero confidence.
    """
    return {
        "zone_id": zone_id,
        "predominant_state": "unknown",
        "average_daily_occupancy_hours": None,
        "peak_occupancy_time": None,
        "lowest_occupancy_time": None,
        "unoccupied_after": "19:00",
        "unoccupied_before": "07:00",
        "signals_used": ["schedule_default"],
        "confidence": 0.0,
        "data_source": "unavailable",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class OccupancyContextProvider:
    """
    Aggregates occupancy signals from BMS CO2/VAV/lighting points via
    VirtualOccupancySensor and exposes them for GSAS contextual reasoning.

    Constructor
    -----------
    bms_state_engine : BMSStateEngine | None
        Live BMS state store.  When None every method degrades gracefully.
    event_correlator : EventCorrelator | None
        Optional; reserved for future enrichment (not used today).
    """

    def __init__(
        self,
        bms_state_engine: Optional[Any] = None,
        event_correlator: Optional[Any] = None,
    ) -> None:
        self.bms_state_engine = bms_state_engine
        self.event_correlator = event_correlator
        self._sensor = VirtualOccupancySensor()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_zone_occupancy(self, zone_id: str, hours: int = 336) -> Dict[str, Any]:
        """
        Return the current occupancy pattern for *zone_id* inferred from live
        BMS points over the requested *hours* window (default 336 h = 14 days).

        The ``period_hours`` key reflects the requested window; actual data
        depth is limited to what the BMS history buffer holds (~24 h by
        default).  Falls back to a schedule-based skeleton when BMS data is
        absent.
        """
        logger.debug("Analysing occupancy for zone %s over %d hours", zone_id, hours)

        if self.bms_state_engine is None:
            return {**_build_schedule_fallback(zone_id), "period_hours": hours}

        # ── Read live BMS points ─────────────────────────────────────────────
        co2 = _try_get_value(self.bms_state_engine, *_co2_candidates(zone_id))
        damper = _try_get_value(self.bms_state_engine, *_vav_candidates(zone_id))
        light_raw = _try_get_value(self.bms_state_engine, *_light_candidates(zone_id))

        if co2 is None:
            # No CO2 data at all — return graceful fallback
            logger.debug("No CO2 point found for zone %s; returning fallback", zone_id)
            return {**_build_schedule_fallback(zone_id), "period_hours": hours}

        light_on: bool = bool(light_raw) if light_raw is not None else True
        damper_pct: float = damper if damper is not None else 50.0

        # ── Estimate current occupancy ───────────────────────────────────────
        estimate = self._sensor.estimate_occupancy(
            zone_id=zone_id,
            co2_ppm=co2,
            vav_damper_pct=damper_pct,
            light_status=light_on,
        )

        # ── Derive pattern from sensor history ───────────────────────────────
        history: List[Tuple[datetime, float]] = self._sensor.zone_history.get(zone_id, [])
        avg_prob = (
            sum(p for _, p in history) / len(history) if history else estimate.probability
        )

        # Determine predominant occupancy state label from average probability
        if avg_prob >= 0.65:
            predominant = "occupied_business_hours"
        elif avg_prob >= 0.35:
            predominant = "partially_occupied"
        else:
            predominant = "mostly_unoccupied"

        # Rough daily occupancy hours: scale average probability × 24 h
        avg_daily_hours = round(avg_prob * 24.0, 1)

        return {
            "zone_id": zone_id,
            "period_hours": hours,
            "predominant_state": predominant,
            "average_daily_occupancy_hours": avg_daily_hours,
            "current_occupancy_probability": round(estimate.probability, 2),
            "current_occupancy_level": estimate.level.value,
            "peak_occupancy_time": None,       # requires time-series DB; not available
            "lowest_occupancy_time": None,
            "unoccupied_after": "19:00",        # conservative schedule default
            "unoccupied_before": "07:00",
            "signals_used": list(estimate.contributing_factors.keys()),
            "confidence": round(estimate.confidence, 2),
            "co2_ppm": round(co2, 1),
            "data_source": "bms_live",
        }

    def detect_unoccupied_patterns(self) -> Dict[str, Dict[str, Any]]:
        """
        Scan all zones present in the BMS state and return those whose current
        occupancy probability is below 0.20 (strongly unoccupied).

        Returns an empty dict — not mock data — when the BMS is unavailable.
        """
        if self.bms_state_engine is None:
            logger.debug("detect_unoccupied_patterns: bms_state_engine is None; returning {}")
            return {}

        zone_ids = _discover_zone_ids(self.bms_state_engine)
        if not zone_ids:
            logger.debug("detect_unoccupied_patterns: no CO2 points discovered in BMS state")
            return {}

        result: Dict[str, Dict[str, Any]] = {}

        for zone_id in zone_ids:
            co2 = _try_get_value(self.bms_state_engine, *_co2_candidates(zone_id))
            if co2 is None:
                continue  # skip — cannot assess without CO2

            damper = _try_get_value(self.bms_state_engine, *_vav_candidates(zone_id))
            light_raw = _try_get_value(self.bms_state_engine, *_light_candidates(zone_id))
            light_on = bool(light_raw) if light_raw is not None else True
            damper_pct = damper if damper is not None else 50.0

            try:
                estimate = self._sensor.estimate_occupancy(
                    zone_id=zone_id,
                    co2_ppm=co2,
                    vav_damper_pct=damper_pct,
                    light_status=light_on,
                )
            except Exception as exc:
                logger.warning("estimate_occupancy failed for zone %s: %s", zone_id, exc)
                continue

            if estimate.probability < 0.20:
                result[zone_id] = {
                    "occupancy_probability": round(estimate.probability, 2),
                    "occupancy_level": estimate.level.value,
                    "confidence": round(estimate.confidence, 2),
                    "co2_ppm": round(co2, 1),
                    "primary_signal": "co2_virtual_sensor",
                    "data_source": "bms_live",
                    "timestamp": datetime.utcnow().isoformat(),
                }

        return result

    def get_occupancy_summary(self) -> Dict[str, Any]:
        """
        Return a building-wide occupancy summary derived from live CO2 readings.

        - zones_active   : zones with CO2 > CO2_LOW_OCCUPANCY (500 ppm)
        - zones_inactive : zones with CO2 <= CO2_LOW_OCCUPANCY
        - current_building_occupancy_est : rough headcount (active zones × 5)

        Returns an "unavailable" summary — not fake numbers — when BMS is absent.
        """
        if self.bms_state_engine is None:
            return {
                "current_building_occupancy_est": None,
                "zones_active": None,
                "zones_inactive": None,
                "data_source": "unavailable",
                "confidence": 0.0,
                "timestamp": datetime.utcnow().isoformat(),
            }

        zone_ids = _discover_zone_ids(self.bms_state_engine)

        zones_active = 0
        zones_inactive = 0
        zones_no_data = 0

        for zone_id in zone_ids:
            co2 = _try_get_value(self.bms_state_engine, *_co2_candidates(zone_id))
            if co2 is None:
                zones_no_data += 1
                continue
            if co2 > _CO2_LOW_OCCUPANCY:
                zones_active += 1
            else:
                zones_inactive += 1

        total_with_data = zones_active + zones_inactive
        if total_with_data == 0 and zones_no_data == 0:
            # No zones at all in BMS
            return {
                "current_building_occupancy_est": None,
                "zones_active": 0,
                "zones_inactive": 0,
                "zones_no_data": 0,
                "data_source": "bms_live",
                "confidence": 0.0,
                "timestamp": datetime.utcnow().isoformat(),
            }

        confidence = (
            round(total_with_data / max(1, total_with_data + zones_no_data), 2)
        )

        return {
            "current_building_occupancy_est": zones_active * _PERSONS_PER_OCCUPIED_ZONE,
            "zones_active": zones_active,
            "zones_inactive": zones_inactive,
            "zones_no_data": zones_no_data,
            "data_source": "bms_live",
            "confidence": confidence,
            "timestamp": datetime.utcnow().isoformat(),
        }
