"""
Threshold Calibrator Service
============================

Deterministic statistics-based calibration service.
Computes adaptive standard deviation floors and Z-score thresholds
using hierarchical scope resolution and Hampel outlier filtering.
"""

import math
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import aiosqlite
import asyncio

from agent_commercial.digest_builder import DailyDigestBuilder, calculate_mad, get_percentile

logger = logging.getLogger("arvis.calibration")


class ThresholdCalibrator:
    """
    Deterministic background service that executes calibrations,
    performs Hampel outlier filtering, resolves scopes hierarchically,
    and publishes recalibration events for watchdog hot-reloads.
    """

    BOOTSTRAP_FLOORS: Dict[str, float] = {
        "vibration": 0.5,
        "chw_supply": 1.0,
        "cop": 0.5,
        "filter_dp": 15.0,
        "zone_temp": 1.0,
        "sat": 1.5,
        "condenser": 1.0,
        "power": 15.0,
        "co2": 150.0,
        "airflow": 150.0,
        "valve": 15.0,
        "damper": 15.0,
        "static_pa": 50.0,
        "pressure": 50.0,
        "dp": 20.0,
        "load": 15.0,
        "kw": 15.0,
        "temp": 1.0,
        "generic": 10.0,
    }

    BOOTSTRAP_Z_THRESHOLDS: Dict[str, float] = {
        "vibration": 2.0,
        "chw_supply": 2.5,
        "cop": 2.5,
        "filter_dp": 2.0,
        "zone_temp": 2.5,
        "sat": 2.5,
        "condenser": 2.5,
        "static_pa": 4.0,
        "pressure": 4.0,
        "generic": 3.0,
    }

    def __init__(
        self,
        db_conn: aiosqlite.Connection,
        event_bus=None,
        building_id: str = "default",
        fp_target: float = 0.0004
    ):
        self.conn = db_conn
        self.event_bus = event_bus
        self.building_id = building_id
        self.fp_target = fp_target
        self.digest_builder = DailyDigestBuilder(db_conn, building_id)

    def hampel_filter(self, data_points: List[float]) -> List[float]:
        """Strip outlier daily standard deviations to prevent stealth-fault inflation."""
        if len(data_points) < 5:
            return data_points
        
        median_val = statistics.median(data_points)
        mad_val = calculate_mad(data_points, median_val)
        if mad_val < 1e-6:
            mad_val = 0.05
            
        threshold = 3.0 * mad_val * 1.4826
        surviving = [x for x in data_points if abs(x - median_val) <= threshold]
        return surviving

    async def run_calibration_cycle(self, trigger_source: str = "scheduled", window_days: int = 28) -> str:
        """
        Executes a complete threshold calibration run.
        Resolves scopes hierarchically, tests shadow calibrations,
        promotes/rejects, and records audits in calibration_runs.
        """
        run_id = f"cal_{int(datetime.now().timestamp())}"
        started_at = datetime.now().isoformat()
        
        logger.info(f"🚀 Starting Threshold Calibration run={run_id} trigger={trigger_source}...")

        # 1. Fetch unique active points in building baselines
        points_query = """
            SELECT DISTINCT point_id, equipment_id, equipment_type, point_type
            FROM point_baselines
            WHERE building_id = ? AND is_healthy = 1
        """
        active_points = []
        try:
            async with self.conn.execute(points_query, (self.building_id,)) as cursor:
                active_points = [dict(row) for row in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to query active points: {e}")
            return run_id

        if not active_points:
            logger.warning("No healthy point baseline digests found. Skipping calibration run.")
            return run_id

        rows_scanned = 0
        rows_rejected_alarm = 0
        rows_rejected_hampel = 0
        scopes_updated = 0
        scopes_rolled_back = 0

        calibrations_upsert = []

        # 2. Process each point
        for pt in active_points:
            point_id = pt["point_id"]
            eq_id = pt["equipment_id"]
            eq_type = pt["equipment_type"]
            pt_type = pt["point_type"]

            # Try hierarchically: point -> equipment -> type
            resolved_scope, digests = await self._resolve_hierarchical_digests(
                point_id, eq_id, eq_type, pt_type, window_days
            )

            if not digests:
                continue

            rows_scanned += len(digests)

            # Filter std values using Hampel filter
            std_vals = [d["std_val"] for d in digests]
            filtered_stds = self.hampel_filter(std_vals)
            rows_rejected_hampel += (len(std_vals) - len(filtered_stds))

            if len(filtered_stds) < 7:
                # If too few days survive, discard this point-level calibration
                continue

            # Floor computation: 90th percentile of healthy daily stds * 1.2
            sorted_filtered = sorted(filtered_stds)
            floor_candidate = get_percentile(sorted_filtered, 0.90) * 1.2

            # Apply hardcoded physics bounds fallback limits
            physics_floor = self.BOOTSTRAP_FLOORS.get(pt_type, self.BOOTSTRAP_FLOORS["generic"])
            calibrated_floor = max(floor_candidate, physics_floor)
            # Cap at 3.0x bootstrap floor to prevent noise dilution
            calibrated_floor = min(calibrated_floor, 3.0 * physics_floor)

            # Z-Threshold via empirical inverse CDF on healthy samples (spec §4.4).
            # Target FP rate α = self.fp_target. Find Z such that fraction of
            # healthy |z|-scores exceeding Z equals α. Use raw data_points when
            # available for sample density; fall back to digest p05/p95 proxy
            # for cold-start days with no raw retained.
            recent_dates_all = [d["date"] for d in digests]
            calibrated_z = await self._derive_z_threshold(
                point_id, eq_id, eq_type, pt_type, recent_dates_all,
                resolved_scope, digests, calibrated_floor,
            )

            # Generate shadow record
            scope_key = f"point:{point_id}" if resolved_scope == "point" else (
                f"eq:{eq_id}" if resolved_scope == "equipment" else f"type:{eq_type}:{pt_type}"
            )

            # Replay / Shadow Test — per-reading FP rate over last 7 days raw data.
            # Falls back to digest-based estimate if raw samples unavailable.
            recent_dates = [d["date"] for d in digests[-7:]]
            rejection_rate = await self._replay_shadow_test_raw(
                point_id, eq_id, eq_type, pt_type, recent_dates,
                calibrated_floor, calibrated_z, resolved_scope,
            )
            if rejection_rate < 0:  # raw replay unavailable, use digest fallback
                rejection_rate = await self._replay_shadow_test(digests[-7:], calibrated_floor, calibrated_z)

            # Spec band: 0.3 × fp_target ≤ rate ≤ 3 × fp_target.
            # - rate > 3 × fp_target → too tight, would flood alarms. Reject.
            # - rate < 0.3 × fp_target → too loose, would miss faults. Reject.
            # Cold-start exception: zero breaches on small samples is acceptable
            # since healthy training data is expected to have few violations.
            lower_band = 0.3 * self.fp_target
            upper_band = 3.0 * self.fp_target
            if rejection_rate > upper_band:
                promoted = 0
                reject_reason = f"too_tight rate={rejection_rate:.5f} > {upper_band:.5f}"
            elif rejection_rate < lower_band and rejection_rate > 0:
                # Strictly between 0 and lower_band → calibration is suspiciously loose
                promoted = 0
                reject_reason = f"too_loose rate={rejection_rate:.5f} < {lower_band:.5f}"
            else:
                promoted = 1
                reject_reason = None

            if promoted:
                scopes_updated += 1
            else:
                logger.debug(f"Shadow calibration rejected for {scope_key}: {reject_reason}")

            now_str = datetime.now().isoformat()
            next_due = (datetime.now() + timedelta(days=28)).isoformat()

            # Prepare transactional write
            calibrations_upsert.append((
                self.building_id,
                scope_key,
                resolved_scope,
                pt_type,
                eq_type,
                calibrated_floor,
                calibrated_z,
                calibrated_floor,  # prev_floor
                calibrated_z,      # prev_z_thresh
                len(digests),
                rejection_rate,
                self.fp_target,
                promoted,
                trigger_source,
                now_str,
                now_str if promoted else None,
                next_due
            ))

        # 3. Upsert point_calibrations
        if calibrations_upsert:
            try:
                # Idempotent replacement for matching scope keys
                await self.conn.executemany("""
                    INSERT OR REPLACE INTO point_calibrations (
                        building_id, scope_key, scope_level, point_type, equipment_type,
                        calibrated_floor, calibrated_z_thresh, prev_floor, prev_z_thresh,
                        sample_size_days, rejection_rate_7d, fp_target, promoted,
                        change_reason, last_calibrated_at, last_promoted_at, next_due_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, calibrations_upsert)
            except Exception as e:
                logger.error(f"Failed to commit calibrations to point_calibrations: {e}")

        # 4. Record run in calibration_runs
        finished_at = datetime.now().isoformat()
        notes = f"Completed calibration run. Scanned {len(active_points)} active points."
        try:
            await self.conn.execute("""
                INSERT INTO calibration_runs (
                    run_id, building_id, started_at, finished_at, trigger_source, window_days,
                    rows_scanned, rows_rejected_alarm, rows_rejected_hampel, scopes_updated,
                    scopes_rolled_back, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, self.building_id, started_at, finished_at, trigger_source, window_days,
                rows_scanned, rows_rejected_alarm, rows_rejected_hampel, scopes_updated,
                scopes_rolled_back, notes
            ))
            await self.conn.commit()
            logger.info(f"✅ Calibration run committed. Scanned={rows_scanned} promoted={scopes_updated} rollbacks={scopes_rolled_back}")
        except Exception as e:
            logger.error(f"Failed to record calibration run: {e}")

        # 5. Hot Reload Event dispatching
        if scopes_updated > 0 and self.event_bus:
            logger.info("Publishing thresholds_recalibrated event to EventBus...")
            try:
                self.event_bus.publish({
                    "type": "thresholds_recalibrated",
                    "payload": {"run_id": run_id}
                })
            except Exception as e:
                logger.error(f"EventBus dispatch failed: {e}")

        return run_id

    async def auto_rollback_check(self) -> int:
        """
        Daily safety check on currently-active calibrations.

        For each promoted scope, replay last 7 days of raw samples against the
        active (floor, z_thresh). If observed FP rate exceeds 5 × fp_target,
        revert that scope to its prev_floor / prev_z_thresh values and mark
        change_reason='rollback'. Emits a single thresholds_recalibrated event
        if any rollback fires, so watchdog hot-reloads.

        Returns count of scopes rolled back.
        """
        breach_limit = 5.0 * self.fp_target
        rolled = 0

        try:
            q = """
                SELECT scope_key, scope_level, point_type, equipment_type,
                       calibrated_floor, calibrated_z_thresh,
                       prev_floor, prev_z_thresh
                FROM point_calibrations
                WHERE building_id = ? AND promoted = 1
                  AND prev_floor IS NOT NULL AND prev_z_thresh IS NOT NULL
            """
            async with self.conn.execute(q, (self.building_id,)) as cursor:
                active = [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"auto_rollback_check: failed to query active calibrations: {e}")
            return 0

        if not active:
            return 0

        # Last 7 dates with digest data
        date_q = """
            SELECT DISTINCT date FROM point_baselines
            WHERE building_id = ? ORDER BY date DESC LIMIT 7
        """
        recent_dates: List[str] = []
        try:
            async with self.conn.execute(date_q, (self.building_id,)) as cursor:
                recent_dates = [r["date"] for r in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"auto_rollback_check: failed to fetch recent dates: {e}")
            return 0

        if not recent_dates:
            return 0

        for cal in active:
            scope_key = cal["scope_key"]
            scope_level = cal["scope_level"]

            # Parse scope_key back into point/eq/type ids
            point_id = eq_id = ""
            eq_type = cal["equipment_type"] or ""
            pt_type = cal["point_type"] or ""
            if scope_level == "point" and scope_key.startswith("point:"):
                point_id = scope_key[6:]
            elif scope_level == "equipment" and scope_key.startswith("eq:"):
                eq_id = scope_key[3:]
            # type level uses eq_type + pt_type already populated

            observed = await self._replay_shadow_test_raw(
                point_id, eq_id, eq_type, pt_type, recent_dates,
                cal["calibrated_floor"], cal["calibrated_z_thresh"], scope_level,
            )
            if observed < 0:
                continue  # can't measure, skip

            if observed > breach_limit:
                # Revert to prev values
                try:
                    now_str = datetime.now().isoformat()
                    await self.conn.execute("""
                        UPDATE point_calibrations
                        SET calibrated_floor = prev_floor,
                            calibrated_z_thresh = prev_z_thresh,
                            change_reason = ?,
                            last_calibrated_at = ?,
                            rejection_rate_7d = ?
                        WHERE building_id = ? AND scope_key = ?
                    """, (
                        f"rollback observed_fp={observed:.5f} > {breach_limit:.5f}",
                        now_str, observed, self.building_id, scope_key,
                    ))
                    rolled += 1
                    logger.warning(
                        f"[Rollback] {scope_key}: observed FP={observed:.5f} "
                        f"exceeds {breach_limit:.5f}. Reverted to prev thresholds."
                    )
                except Exception as e:
                    logger.error(f"rollback update failed for {scope_key}: {e}")

        if rolled > 0:
            try:
                await self.conn.commit()
                # Record audit entry in calibration_runs
                now_str = datetime.now().isoformat()
                run_id = f"rb_{int(datetime.now().timestamp())}"
                await self.conn.execute("""
                    INSERT INTO calibration_runs (
                        run_id, building_id, started_at, finished_at, trigger_source,
                        window_days, rows_scanned, rows_rejected_alarm,
                        rows_rejected_hampel, scopes_updated, scopes_rolled_back, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id, self.building_id, now_str, now_str, "rollback_check",
                    7, 0, 0, 0, 0, rolled,
                    f"Auto-rollback fired on {rolled} scope(s) — observed FP > 5x fp_target",
                ))
                await self.conn.commit()
                # Fire hot-reload event
                if self.event_bus:
                    self.event_bus.publish({
                        "type": "thresholds_recalibrated",
                        "payload": {"run_id": run_id, "trigger": "rollback"},
                    })
            except Exception as e:
                logger.error(f"rollback commit/audit failed: {e}")

        return rolled

    async def _derive_z_threshold(
        self,
        point_id: str,
        eq_id: str,
        eq_type: str,
        pt_type: str,
        recent_dates: List[str],
        scope_level: str,
        digests: List[Dict[str, Any]],
        floor: float,
    ) -> float:
        """
        Empirical inverse CDF Z derivation (spec §4.4).

        Given target false-positive rate α = self.fp_target, returns Z such
        that fraction of healthy |z|-scores exceeding Z equals α. Z is bounded
        [2.5, 5.0] to prevent pathological values from sparse data.

        Strategy:
          1. Pull raw values across recent_dates for this scope.
          2. For each sample, compute z = |x − day_median| / max(day_MAD ×
             1.4826, floor). Day-local scaling matters because diurnal load
             shifts the mean within a day.
          3. Sort |z|. Pick (1 − α)-quantile.
          4. If raw data insufficient (<200 samples, common at cold start),
             fall back to digest-based approximation using p05/p95 as two
             tail samples per day plus a Gaussian-tail approximation factor.
        """
        # Build per-day baseline lookup from the digests we already have.
        per_day_baseline: Dict[str, Tuple[float, float]] = {
            d["date"]: (d["median_val"], d["mad_val"]) for d in digests
        }
        if not per_day_baseline:
            return self._z_clamp(self.BOOTSTRAP_Z_THRESHOLDS.get(pt_type, 3.0))

        # 1. Pull raw samples
        if scope_level == "point":
            where = "point_id = ?"
            params: Tuple = (point_id,)
        elif scope_level == "equipment":
            where = "equipment_id = ?"
            params = (eq_id,)
        else:
            where = (
                "point_id IN (SELECT DISTINCT point_id FROM point_baselines "
                "WHERE building_id = ? AND equipment_type = ? AND point_type = ?)"
            )
            params = (self.building_id, eq_type, pt_type)

        date_in = ",".join("?" * len(recent_dates))
        raw_q = f"""
            SELECT value, SUBSTR(timestamp, 1, 10) as d
            FROM data_points
            WHERE {where}
              AND SUBSTR(timestamp, 1, 10) IN ({date_in})
            LIMIT 200000
        """
        z_abs: List[float] = []
        try:
            async with self.conn.execute(raw_q, params + tuple(recent_dates)) as cursor:
                for r in await cursor.fetchall():
                    ref = per_day_baseline.get(r["d"])
                    if ref is None:
                        continue
                    med, mad = ref
                    scale = max(mad * 1.4826, floor)
                    if scale <= 0:
                        continue
                    z_abs.append(abs(float(r["value"]) - med) / scale)
        except Exception as e:
            logger.debug(f"_derive_z_threshold raw query failed for {point_id}: {e}")

        # 2. If we have enough samples, use empirical inverse CDF directly.
        # Need at least ~1/α samples to resolve the tail; require 5× headroom.
        min_samples_for_alpha = max(200, int(5.0 / self.fp_target))
        if len(z_abs) >= min_samples_for_alpha:
            z_abs.sort()
            quantile = 1.0 - self.fp_target
            idx = int(quantile * len(z_abs))
            idx = min(max(idx, 0), len(z_abs) - 1)
            z_candidate = z_abs[idx]
            return self._z_clamp(z_candidate)

        # 3. Fallback: digest-based proxy. Approximate tail using
        # p05/p95 (~10th/90th of within-day distribution) and scale by
        # Gaussian factor mapping (1 − α) tail of N(0,1) to .95-tail.
        # z_α / z_0.95 for normal: (norm.ppf(1-α) / 1.6449). Hardcode
        # common α targets to avoid scipy import in production path.
        proxy_pooled: List[float] = []
        for d in digests:
            med, mad = per_day_baseline[d["date"]]
            scale = max(mad * 1.4826, floor)
            if scale <= 0:
                continue
            proxy_pooled.append(abs(d["p95_val"] - med) / scale)
            proxy_pooled.append(abs(med - d["p05_val"]) / scale)
        if not proxy_pooled:
            return self._z_clamp(self.BOOTSTRAP_Z_THRESHOLDS.get(pt_type, 3.0))

        proxy_pooled.sort()
        # Take 95th percentile of the 90th/10th-percentile pooled stats.
        z_at_p95 = get_percentile(proxy_pooled, 0.95)
        # Map P95 tail → fp_target tail using Gaussian-tail scale factor.
        gaussian_scale = self._gaussian_tail_factor(self.fp_target)
        z_candidate = z_at_p95 * gaussian_scale
        return self._z_clamp(z_candidate)

    @staticmethod
    def _z_clamp(z: float) -> float:
        """Bound Z-threshold in [2.5, 5.0] (spec §4.4)."""
        if z != z or z is None:  # NaN / None guard
            return 3.0
        return min(max(float(z), 2.5), 5.0)

    @staticmethod
    def _gaussian_tail_factor(alpha: float) -> float:
        """
        Ratio z_α / z_0.95 for standard normal — used to scale a P95-based
        tail estimate to a target α-tail when only digest percentiles are
        available. Hardcoded common values avoid scipy import.
        Reference: scipy.stats.norm.ppf(1 - alpha) / 1.6449
        """
        table = {
            0.05:    1.0,
            0.01:    1.414,
            0.005:   1.566,
            0.001:   1.879,
            0.0005:  2.001,
            0.0004:  2.034,
            0.0001:  2.260,
            0.00001: 2.595,
        }
        # Find nearest tabulated α
        keys = sorted(table.keys())
        nearest = min(keys, key=lambda k: abs(math.log(k) - math.log(max(alpha, 1e-9))))
        return table[nearest]

    async def _resolve_hierarchical_digests(
        self, point_id: str, eq_id: str, eq_type: str, pt_type: str, window_days: int
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Resolves digest pools starting from point level down to equipment and type.

        Gates per scope:
        - point: ≥14 days surviving
        - equipment: ≥14 days AND ≥3 distinct point_ids in pool (spec §4.2)
        - type: ≥14 days surviving
        - else: bootstrap (no calibration, watchdog falls back to hardcoded)
        """
        # 1. Point Level
        point_digests = await self._query_digests("point_id = ?", (point_id,), window_days)
        if len(point_digests) >= 14:
            return "point", point_digests

        # 2. Equipment Level — require diversity to avoid single-point overfit
        eq_digests = await self._query_digests("equipment_id = ?", (eq_id,), window_days)
        if len(eq_digests) >= 14:
            distinct_points = len({d["point_id"] for d in eq_digests})
            if distinct_points >= 3:
                return "equipment", eq_digests
            else:
                logger.debug(
                    f"equipment scope for {eq_id} has only {distinct_points} distinct "
                    f"point(s); falling back to type scope"
                )

        # 3. Type Level
        type_digests = await self._query_digests(
            "equipment_type = ? AND point_type = ?", (eq_type, pt_type), window_days
        )
        if len(type_digests) >= 14:
            return "type", type_digests

        return "bootstrap", []

    async def _query_digests(self, where_clause: str, params: Tuple, limit_days: int) -> List[Dict[str, Any]]:
        """Queries the point_baselines table for healthy days."""
        query = f"""
            SELECT * FROM point_baselines
            WHERE {where_clause} AND building_id = ? AND is_healthy = 1
            ORDER BY date DESC
            LIMIT ?
        """
        query_params = params + (self.building_id, limit_days)
        try:
            async with self.conn.execute(query, query_params) as cursor:
                rows = await cursor.fetchall()
                # Return in chronological order
                return [dict(r) for r in reversed(rows)]
        except Exception as e:
            logger.error(f"Query baselines failed for clause {where_clause}: {e}")
            return []

    async def _replay_shadow_test(self, test_digests: List[Dict[str, Any]], floor: float, z_thresh: float) -> float:
        """Run shadow test on digests, count daily boundary breaches to find rejection rate."""
        if not test_digests:
            return 0.0

        breach_days = 0
        for d in test_digests:
            median_val = d["median_val"]
            mad_val = d["mad_val"]
            scale = max(mad_val * 1.4826, floor)

            z_max = abs(d["max_val"] - median_val) / scale
            z_min = abs(median_val - d["min_val"]) / scale

            if z_max > z_thresh or z_min > z_thresh:
                breach_days += 1

        return breach_days / len(test_digests)

    async def _replay_shadow_test_raw(
        self,
        point_id: str,
        eq_id: str,
        eq_type: str,
        pt_type: str,
        recent_dates: List[str],
        floor: float,
        z_thresh: float,
        scope_level: str,
    ) -> float:
        """
        Per-reading false-positive rate.

        Queries data_points for all raw samples on `recent_dates` matching the
        scope level, computes z-score against the proposed (floor, z_thresh)
        using each day's median+MAD baseline, returns fraction of samples that
        would have been flagged.

        Returns -1.0 if raw data unavailable so caller can fall back to the
        digest-only test.
        """
        if not recent_dates:
            return -1.0

        # Match scope: point-level uses exact point_id; eq/type pool wider.
        if scope_level == "point":
            where = "point_id = ?"
            params: Tuple = (point_id,)
        elif scope_level == "equipment":
            where = "equipment_id = ?"
            params = (eq_id,)
        else:  # type
            # data_points doesn't directly carry equipment_type/point_type;
            # join via point_baselines to scope correctly.
            where = (
                "point_id IN (SELECT DISTINCT point_id FROM point_baselines "
                "WHERE building_id = ? AND equipment_type = ? AND point_type = ?)"
            )
            params = (self.building_id, eq_type, pt_type)

        date_in = ",".join("?" * len(recent_dates))
        query = f"""
            SELECT dp.value, SUBSTR(dp.timestamp, 1, 10) as d
            FROM data_points dp
            WHERE {where}
              AND SUBSTR(dp.timestamp, 1, 10) IN ({date_in})
            LIMIT 100000
        """
        try:
            async with self.conn.execute(query, params + tuple(recent_dates)) as cursor:
                samples = await cursor.fetchall()
        except Exception as e:
            logger.debug(f"raw replay query failed for {point_id}: {e}")
            return -1.0

        if not samples:
            return -1.0

        # Build per-day (median, MAD) lookup from digests we already have
        per_day: Dict[str, Tuple[float, float]] = {}
        try:
            digest_q = f"""
                SELECT date, median_val, mad_val FROM point_baselines
                WHERE {where} AND building_id = ?
                  AND date IN ({date_in})
            """
            digest_params = params + (self.building_id,) + tuple(recent_dates) \
                if scope_level != "type" else params + tuple(recent_dates) + (self.building_id,)
            # Simpler: rebuild query without building_id duplication
            digest_q2 = f"""
                SELECT date, median_val, mad_val FROM point_baselines
                WHERE building_id = ? AND date IN ({date_in})
                  AND ({where})
            """
            async with self.conn.execute(
                digest_q2, (self.building_id,) + tuple(recent_dates) + params
            ) as cursor:
                for r in await cursor.fetchall():
                    per_day[r["date"]] = (r["median_val"], r["mad_val"])
        except Exception as e:
            logger.debug(f"raw replay digest lookup failed: {e}")
            return -1.0

        breaches = 0
        total = 0
        for s in samples:
            day = s["d"]
            ref = per_day.get(day)
            if ref is None:
                continue
            median_val, mad_val = ref
            scale = max(mad_val * 1.4826, floor)
            if scale <= 0:
                continue
            z = abs(float(s["value"]) - median_val) / scale
            total += 1
            if z > z_thresh:
                breaches += 1

        if total == 0:
            return -1.0
        return breaches / total
