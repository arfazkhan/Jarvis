"""
GSAS Data Validator
===================

Validates the freshness, completeness, and consistency of BMS data
that feeds GSAS certification metrics.

Operates synchronously against the live BMSStateEngine internal state
(``_points`` dict) so it can be called from non-async code paths such
as the GSAS reporter and audit-readiness checks.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agent_commercial.bms_data_model import BMSDataPoint, PointQuality

logger = logging.getLogger(__name__)

# ── Point-category keyword matchers ──────────────────────────────────────────

_ENERGY_KEYWORDS   = ("KW",)
_WATER_KEYWORDS    = ("TOTAL_M3", "FLOW")
_COMFORT_KEYWORDS  = ("SAT", "RAT", "CO2")
_CRITICAL_KEYWORDS = ("KW", "SAT", "CHWST", "CO2")

# ── Sanity bounds ─────────────────────────────────────────────────────────────

_TEMP_KEYWORDS   = ("SAT", "RAT", "CHWST")
_TEMP_MIN        = -5.0    # °C
_TEMP_MAX        = 60.0    # °C
_CO2_FAULT_PPM   = 2000.0  # above this = sensor fault likely
_KW_MIN          = 0.0     # kW must never be negative


def _point_matches(point_id: str, keywords: tuple) -> bool:
    """Return True if any keyword appears in the point_id (case-insensitive)."""
    upper = point_id.upper()
    return any(kw in upper for kw in keywords)


class GSASDataValidator:
    """
    Checks the freshness, completeness, and consistency of BMS data
    feeding GSAS and returns a health report.

    Parameters
    ----------
    bms_state:
        A ``BMSStateEngine`` instance.  The validator accesses the internal
        ``_points`` dict directly so that it can remain synchronous.
    stale_threshold_minutes:
        Age (in minutes) above which a non-STALE quality point is
        considered stale by wall-clock age.  Default: 15.
    """

    def __init__(
        self,
        bms_state: Any,
        stale_threshold_minutes: int = 15,
    ) -> None:
        self.bms_state = bms_state
        self.stale_threshold_minutes = stale_threshold_minutes

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def validate(self) -> Dict[str, Any]:
        """
        Run freshness, completeness, and consistency checks against the live
        BMS state.

        Returns
        -------
        dict with keys:
            health_score        float  0–100
            issues              List[str]
            is_healthy          bool   (score > 80)
            stale_points        List[str]  point_ids flagged as stale
            missing_categories  List[str]  GSAS categories with no data
            point_count         int    total points examined
        """
        logger.info("Running GSAS Data Validation")

        issues: List[str] = []
        stale_points: List[str] = []
        missing_categories: List[str] = []
        health_score = 100.0

        # ── Guard: no BMS state at all ────────────────────────────────────────
        if not self.bms_state:
            return {
                "health_score": 0.0,
                "issues": ["BMS state engine is entirely unavailable."],
                "is_healthy": False,
                "stale_points": [],
                "missing_categories": list(_GSAS_REQUIRED_CATEGORIES),
                "point_count": 0,
            }

        # ── Obtain the live point dict synchronously ──────────────────────────
        points: Optional[Dict[str, BMSDataPoint]] = getattr(
            self.bms_state, "_points", None
        )

        if points is None:
            # BMSStateEngine not yet initialised or wrong object type
            return {
                "health_score": 0.0,
                "issues": [
                    "BMS state engine has no _points store — cannot validate."
                ],
                "is_healthy": False,
                "stale_points": [],
                "missing_categories": list(_GSAS_REQUIRED_CATEGORIES),
                "point_count": 0,
            }

        if not points:
            return {
                "health_score": 20.0,
                "issues": ["BMS state engine contains no data points yet."],
                "is_healthy": False,
                "stale_points": [],
                "missing_categories": list(_GSAS_REQUIRED_CATEGORIES),
                "point_count": 0,
            }

        # Determine simulated reference time from max timestamp of points
        now = datetime.now()
        if points:
            valid_ts = []
            for p in points.values():
                ts = getattr(p, 'timestamp', None)
                if ts:
                    if ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None)
                    valid_ts.append(ts)
            if valid_ts:
                now = max(valid_ts)
                
        stale_cutoff = now - timedelta(minutes=self.stale_threshold_minutes)

        # ── 1. Freshness check ────────────────────────────────────────────────
        health_score = self._check_freshness(
            points, stale_cutoff, stale_points, issues, health_score
        )

        # ── 2. Completeness check ─────────────────────────────────────────────
        health_score = self._check_completeness(
            points, missing_categories, issues, health_score
        )

        # ── 3. Consistency check ──────────────────────────────────────────────
        health_score = self._check_consistency(points, issues, health_score)

        health_score = max(0.0, health_score)

        return {
            "health_score": round(health_score, 1),
            "issues": issues,
            "is_healthy": health_score > 80.0,
            "stale_points": stale_points,
            "missing_categories": missing_categories,
            "point_count": len(points),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _check_freshness(
        self,
        points: Dict[str, BMSDataPoint],
        stale_cutoff: datetime,
        stale_points: List[str],
        issues: List[str],
        health_score: float,
    ) -> float:
        """
        Flag points whose quality is already STALE, plus points whose
        wall-clock timestamp is older than ``stale_cutoff`` regardless of
        the quality field.  Critical points (KW, SAT, CHWST, CO2) carry
        double the penalty.
        """
        for point_id, point in points.items():
            is_stale = False

            if point.quality == PointQuality.STALE:
                # Already marked stale by the BMS driver
                is_stale = True
            elif point.timestamp is not None and point.timestamp < stale_cutoff:
                # Quality says GOOD/UNCERTAIN but the data is old
                is_stale = True

            if not is_stale:
                continue

            stale_points.append(point_id)
            is_critical = _point_matches(point_id, _CRITICAL_KEYWORDS)

            if is_critical:
                deduction = 5.0
                issues.append(
                    f"Critical point '{point_id}' is stale "
                    f"(last seen {_age_str(point.timestamp)})."
                )
            else:
                deduction = 2.0
                issues.append(
                    f"Point '{point_id}' is stale "
                    f"(last seen {_age_str(point.timestamp)})."
                )

            health_score -= deduction

        return health_score

    def _check_completeness(
        self,
        points: Dict[str, BMSDataPoint],
        missing_categories: List[str],
        issues: List[str],
        health_score: float,
    ) -> float:
        """
        GSAS requires at least one live point in each of three categories:
        Energy (KW), Water (TOTAL_M3 / FLOW), Comfort (SAT / RAT / CO2).
        Absence of a category deducts 10 from the health score.
        """
        category_checks = {
            "Energy (KW meter)": _ENERGY_KEYWORDS,
            "Water (flow/volume meter)": _WATER_KEYWORDS,
            "Comfort (temperature/CO2)": _COMFORT_KEYWORDS,
        }

        for category, keywords in category_checks.items():
            found = any(
                _point_matches(pid, keywords) and p.value is not None
                for pid, p in points.items()
            )
            if not found:
                missing_categories.append(category)
                issues.append(
                    f"GSAS completeness gap: no live '{category}' data point found."
                )
                health_score -= 10.0

        return health_score

    def _check_consistency(
        self,
        points: Dict[str, BMSDataPoint],
        issues: List[str],
        health_score: float,
    ) -> float:
        """
        Apply sanity bounds to temperature, power, and CO2 readings.

        - Temperature (SAT, RAT, CHWST) must be in [_TEMP_MIN, _TEMP_MAX] °C
        - KW readings must be >= 0
        - CO2 readings above _CO2_FAULT_PPM indicate a sensor fault
        """
        for point_id, point in points.items():
            if point.value is None:
                continue

            val = point.value

            # Temperature range check
            if _point_matches(point_id, _TEMP_KEYWORDS):
                if not (_TEMP_MIN <= val <= _TEMP_MAX):
                    issues.append(
                        f"Consistency error: '{point_id}' temperature {val:.1f} °C "
                        f"is outside plausible range [{_TEMP_MIN}, {_TEMP_MAX}] °C."
                    )
                    health_score -= 5.0

            # Negative power check
            if _point_matches(point_id, _ENERGY_KEYWORDS):
                if val < _KW_MIN:
                    issues.append(
                        f"Consistency error: '{point_id}' power reading is "
                        f"negative ({val:.2f} kW) — impossible value."
                    )
                    health_score -= 10.0

            # CO2 sensor fault check
            if "CO2" in point_id.upper():
                if val > _CO2_FAULT_PPM:
                    issues.append(
                        f"Consistency warning: '{point_id}' CO2 reading "
                        f"{val:.0f} ppm exceeds {_CO2_FAULT_PPM:.0f} ppm — "
                        "likely sensor fault."
                    )
                    health_score -= 3.0

        return health_score


# ── Module-level constant (used in guard-return missing_categories) ───────────
_GSAS_REQUIRED_CATEGORIES = (
    "Energy (KW meter)",
    "Water (flow/volume meter)",
    "Comfort (temperature/CO2)",
)


# ── Utility ───────────────────────────────────────────────────────────────────

def _age_str(ts: Optional[datetime]) -> str:
    """Human-readable age of a timestamp, e.g. '23 min ago' or 'unknown'."""
    if ts is None:
        return "unknown"
    delta = datetime.now() - ts
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "future timestamp"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    if total_seconds < 3600:
        return f"{total_seconds // 60} min ago"
    return f"{total_seconds // 3600} h ago"
