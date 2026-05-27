"""
Daily Digest Builder
====================

Consolidates raw 1-minute BMS telemetry into 24-hour daily statistical digests.
Filters out active alarm/maintenance periods to keep baseline calibrations clean.
"""

import math
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import aiosqlite

logger = logging.getLogger("arvis.calibration.digest")


def calculate_mad(values: List[float], median_val: float) -> float:
    """Calculate Median Absolute Deviation (MAD) as a robust scale estimator."""
    if not values:
        return 0.0
    abs_deviations = [abs(x - median_val) for x in values]
    return statistics.median(abs_deviations)


def get_percentile(sorted_values: List[float], pct: float) -> float:
    """Calculate linear interpolation percentile of sorted values."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return d0 + d1


class DailyDigestBuilder:
    """
    Builds the daily consolidated statistics (mean, std, median, MAD, percentiles)
    for every point and determines baseline health by checking alarm active durations.
    """

    def __init__(self, db_conn: aiosqlite.Connection, building_id: str = "default"):
        self.conn = db_conn
        self.building_id = building_id

    def classify_point_type(self, point_id: str, unit: str = "") -> str:
        """Standalone classification matching AnomalyWatchdog _classify_point order."""
        pid = point_id.lower()
        unit = (unit or "").lower()

        # Sorted longest matches first to prevent substring collision
        known_keys = [
            "vibration", "chw_supply", "filter_dp", "zone_temp", "condenser",
            "static_pa", "pressure", "power", "airflow", "valve", "damper",
            "load", "cop", "sat", "temp", "co2", "dp", "kw"
        ]
        
        # Check explicit point_id keys
        for key in sorted(known_keys, key=len, reverse=True):
            normalized_key = key.replace("_", "")
            normalized_pid = pid.replace("_", "").replace("/", "").replace("-", "")
            if normalized_key in normalized_pid:
                return key

        # Fallback unit checks
        if "static_pa" in pid or "staticpa" in pid:
            return "static_pa"
        if "°c" in unit or "temp" in pid:
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

    def classify_equipment_type(self, equipment_id: str) -> str:
        """Deduce equipment type from equipment ID."""
        eid = equipment_id.lower()
        if "ch" in eid:
            return "chiller"
        if "ahu" in eid:
            return "ahu"
        if "vav" in eid:
            return "vav"
        if "fcu" in eid:
            return "fcu"
        if "ct" in eid:
            return "ct"
        if "pump" in eid or "pchwp" in eid or "schwp" in eid or "cdwp" in eid:
            return "pump"
        return "generic"

    async def get_equipment_alarm_duration(self, equipment_id: str, date_str: str) -> int:
        """Calculate total seconds any alarm was active for this equipment on the given date."""
        start_day = f"{date_str}T00:00:00"
        end_day = f"{date_str}T23:59:59.999"

        # Fetch all alarms affecting this equipment that overlap with this day
        query = """
            SELECT triggered_at, resolved_at FROM alarms
            WHERE equipment_id = ? AND triggered_at <= ? AND (resolved_at IS NULL OR resolved_at >= ?)
        """
        total_overlap_seconds = 0
        try:
            async with self.conn.execute(query, (equipment_id, end_day, start_day)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    t_at = row[0]
                    r_at = row[1]

                    # Compute overlap with start/end of the day
                    start_time = max(start_day, t_at)
                    end_time = min(end_day, r_at) if r_at else end_day

                    try:
                        dt_start = datetime.fromisoformat(start_time.split(".")[0])
                        dt_end = datetime.fromisoformat(end_time.split(".")[0])
                        overlap = (dt_end - dt_start).total_seconds()
                        if overlap > 0:
                            total_overlap_seconds += int(overlap)
                    except Exception as e:
                        logger.debug(f"Error parsing alarm timestamps: {e}")
        except Exception as e:
            logger.error(f"Failed to query alarm duration for {equipment_id}: {e}")

        return total_overlap_seconds

    async def build_digest_for_date(self, date_str: str) -> Tuple[int, int]:
        """
        Process raw telemetry for a single date, calculate stats, and upsert digests.
        Returns: Tuple of (inserted_count, rejected_count)
        """
        start_day = f"{date_str}T00:00:00"
        end_day = f"{date_str}T23:59:59.999"

        logger.info(f"Building daily digest for building={self.building_id} date={date_str}...")

        # Query all raw readings for this date
        query = """
            SELECT point_id, equipment_id, value, unit FROM data_points
            WHERE timestamp >= ? AND timestamp <= ?
        """
        
        # Group values in-memory
        point_groups: Dict[str, Dict[str, Any]] = {}
        try:
            async with self.conn.execute(query, (start_day, end_day)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    pid = row[0]
                    eqid = row[1] or "Unknown"
                    val = row[2]
                    unit = row[3] or ""

                    if val is None:
                        continue

                    if pid not in point_groups:
                        point_groups[pid] = {
                            "equipment_id": eqid,
                            "unit": unit,
                            "values": []
                        }
                    point_groups[pid]["values"].append(val)
        except Exception as e:
            logger.error(f"Error querying telemetry history: {e}")
            return 0, 0

        if not point_groups:
            logger.warning(f"No telemetry found for date {date_str}")
            return 0, 0

        inserted = 0
        rejected = 0
        digest_rows = []

        # Get unique equipment IDs to query alarm durations in batch or cache
        unique_equipments = {g["equipment_id"] for g in point_groups.values()}
        eq_alarm_durations: Dict[str, int] = {}
        for eqid in unique_equipments:
            if eqid != "Unknown":
                eq_alarm_durations[eqid] = await self.get_equipment_alarm_duration(eqid, date_str)
            else:
                eq_alarm_durations[eqid] = 0

        # Calculate statistics
        for pid, data in point_groups.items():
            vals = data["values"]
            eqid = data["equipment_id"]
            unit = data["unit"]

            n = len(vals)
            if n < 5:  # Require at least 5 samples to make a valid digest
                continue

            sorted_vals = sorted(vals)
            
            # Pure standard statistics calculation
            mean_val = sum(vals) / n
            variance = sum((x - mean_val) ** 2 for x in vals) / n
            std_val = math.sqrt(variance)
            median_val = statistics.median(sorted_vals)
            mad_val = calculate_mad(vals, median_val)
            p05_val = get_percentile(sorted_vals, 0.05)
            p95_val = get_percentile(sorted_vals, 0.95)
            min_val = sorted_vals[0]
            max_val = sorted_vals[-1]

            # Classification
            ptype = self.classify_point_type(pid, unit)
            eqtype = self.classify_equipment_type(eqid)

            alarm_s = eq_alarm_durations.get(eqid, 0)
            
            # is_healthy rule: alarm duration < 5% of a full day (4320 seconds)
            is_healthy = 1 if alarm_s < 4320 else 0

            if is_healthy:
                inserted += 1
            else:
                rejected += 1

            digest_rows.append((
                self.building_id,
                pid,
                eqid,
                eqtype,
                ptype,
                None,  # location, nullable
                date_str,
                n,
                mean_val,
                std_val,
                median_val,
                mad_val,
                p05_val,
                p95_val,
                min_val,
                max_val,
                alarm_s,
                is_healthy
            ))

        # Perform transactional bulk upsert
        if digest_rows:
            try:
                await self.conn.executemany("""
                    INSERT OR REPLACE INTO point_baselines (
                        building_id, point_id, equipment_id, equipment_type, point_type, location, date,
                        sample_count, mean_val, std_val, median_val, mad_val, p05_val, p95_val, min_val, max_val,
                        alarm_duration_s, is_healthy
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, digest_rows)
                await self.conn.commit()
                logger.info(f"Successfully committed daily digests for {len(digest_rows)} points. healthy={inserted} unhealthy={rejected}")
            except Exception as e:
                logger.error(f"Failed to upsert daily digests to DB: {e}")
                return 0, 0

        return inserted, rejected
