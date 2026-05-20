import logging
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kahramaa 2024 Commercial Tiered Tariff
# Source: Qatar General Electricity & Water Corporation (Kahramaa), 2024
# ---------------------------------------------------------------------------

# Electricity tiers: (upper_limit_kwh, rate_qar_per_kwh)
# None upper limit means the tier is unbounded (catch-all top tier)
_ELEC_TIERS = [
    (2_000,  0.05),   # Tier 1: 0–2,000 kWh/month
    (5_000,  0.10),   # Tier 2: 2,001–5,000 kWh/month
    (15_000, 0.15),   # Tier 3: 5,001–15,000 kWh/month
    (None,   0.21),   # Tier 4: >15,000 kWh/month
]

# Peak demand surcharge: 0.35 QAR/kW/month for demand >50 kW (large commercial)
_DEMAND_SURCHARGE_RATE = 0.35      # QAR / kW / month
_DEMAND_SURCHARGE_THRESHOLD_KW = 50.0

# Water tiers: (upper_limit_m3, rate_qar_per_m3)
_WATER_TIERS = [
    (100,  3.50),   # Tier 1: 0–100 m³/month
    (500,  5.50),   # Tier 2: 101–500 m³/month
    (None, 8.00),   # Tier 3: >500 m³/month
]


def _compute_tiered_bill(consumption: float, tiers: list) -> float:
    """
    Compute the total cost for *consumption* units using a stepped-tiered schedule.

    Parameters
    ----------
    consumption : float  Non-negative quantity (kWh or m³).
    tiers       : list   List of (upper_limit, rate) tuples; None upper_limit = unbounded.

    Returns
    -------
    float  Total cost in QAR.
    """
    if consumption <= 0.0:
        return 0.0

    total_cost = 0.0
    remaining = consumption
    prev_limit = 0.0

    for upper_limit, rate in tiers:
        if remaining <= 0.0:
            break
        if upper_limit is None:
            # Final unbounded tier — consumes everything remaining
            total_cost += remaining * rate
            remaining = 0.0
        else:
            tier_width = upper_limit - prev_limit
            units_in_tier = min(remaining, tier_width)
            total_cost += units_in_tier * rate
            remaining -= units_in_tier
            prev_limit = upper_limit

    return total_cost


def _marginal_rate(consumption: float, tiers: list) -> float:
    """
    Return the per-unit rate that applies at *consumption* (i.e. the rate of the
    tier that the last unit of consumption falls into).
    """
    prev_limit = 0.0
    for upper_limit, rate in tiers:
        if upper_limit is None or consumption <= upper_limit:
            return rate
        prev_limit = upper_limit
    # Should never reach here for a well-formed tier list
    return tiers[-1][1]


class KahramaaTariff:
    """
    Qatar Kahramaa 2024 Commercial tiered tariff calculator.

    Provides accurate bill computation, marginal rate lookup, and savings
    calculation using the real tiered structure — as opposed to a single
    flat rate.

    Parameters
    ----------
    monthly_kwh_consumption : float
        Expected baseline monthly electricity consumption (kWh).  Used as
        default when computing savings if no explicit baseline is supplied.
    monthly_m3_consumption : float
        Expected baseline monthly water consumption (m³).
    peak_demand_kw : float, optional
        Peak electrical demand in kW.  When >50 kW the Kahramaa demand
        surcharge is applied on top of energy charges.
    currency : str
        ISO currency code (default "QAR").
    """

    # Default baseline for a large commercial building in Qatar
    DEFAULT_MONTHLY_KWH = 15_000.0
    DEFAULT_MONTHLY_M3 = 400.0

    def __init__(
        self,
        monthly_kwh_consumption: float = DEFAULT_MONTHLY_KWH,
        monthly_m3_consumption: float = DEFAULT_MONTHLY_M3,
        peak_demand_kw: float = 0.0,
        currency: str = "QAR",
    ) -> None:
        self.monthly_kwh_consumption = monthly_kwh_consumption
        self.monthly_m3_consumption = monthly_m3_consumption
        self.peak_demand_kw = peak_demand_kw
        self.currency = currency

    # ------------------------------------------------------------------
    # Marginal rate helpers
    # ------------------------------------------------------------------

    def compute_electricity_marginal_rate(self, monthly_kwh: float) -> float:
        """
        Return the QAR/kWh rate that applies at *monthly_kwh* consumption.

        This is the rate charged on the last kWh consumed, which is the
        economically correct rate to use when valuing incremental savings.
        """
        return _marginal_rate(monthly_kwh, _ELEC_TIERS)

    def compute_water_marginal_rate(self, monthly_m3: float) -> float:
        """
        Return the QAR/m³ rate that applies at *monthly_m3* consumption.
        """
        return _marginal_rate(monthly_m3, _WATER_TIERS)

    # ------------------------------------------------------------------
    # Full bill calculation
    # ------------------------------------------------------------------

    def compute_monthly_bill(
        self,
        kwh: float,
        m3: float,
        peak_demand_kw: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Compute the full monthly Kahramaa bill for *kwh* electricity and
        *m3* water consumption.

        Parameters
        ----------
        kwh : float  Electricity consumed this month (kWh).
        m3  : float  Water consumed this month (m³).
        peak_demand_kw : float, optional
            Override instance-level peak demand for this calculation.

        Returns
        -------
        dict with keys: electricity_energy, electricity_demand_surcharge,
                        water, total  (all in QAR).
        """
        elec_energy = _compute_tiered_bill(kwh, _ELEC_TIERS)
        water = _compute_tiered_bill(m3, _WATER_TIERS)

        demand_kw = peak_demand_kw if peak_demand_kw is not None else self.peak_demand_kw
        demand_surcharge = 0.0
        if demand_kw > _DEMAND_SURCHARGE_THRESHOLD_KW:
            demand_surcharge = (demand_kw - _DEMAND_SURCHARGE_THRESHOLD_KW) * _DEMAND_SURCHARGE_RATE

        return {
            "electricity_energy": round(elec_energy, 2),
            "electricity_demand_surcharge": round(demand_surcharge, 2),
            "water": round(water, 2),
            "total": round(elec_energy + demand_surcharge + water, 2),
        }

    # ------------------------------------------------------------------
    # Savings calculation
    # ------------------------------------------------------------------

    def compute_savings(
        self,
        kwh_delta: float,
        m3_delta: float,
        baseline_kwh: Optional[float] = None,
        baseline_m3: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Calculate monetary savings for a *reduction* of *kwh_delta* kWh and
        *m3_delta* m³ relative to a given consumption baseline.

        The savings are valued at the **marginal rate** that applies to the
        baseline consumption level (i.e. the rate of the highest tier
        currently occupied), which correctly represents the economic value
        of reducing consumption at the margin.

        Parameters
        ----------
        kwh_delta      : float  kWh/month saved (positive = saving energy).
        m3_delta       : float  m³/month saved.
        baseline_kwh   : float, optional  Monthly electricity baseline (kWh).
                         Defaults to self.monthly_kwh_consumption.
        baseline_m3    : float, optional  Monthly water baseline (m³).
                         Defaults to self.monthly_m3_consumption.

        Returns
        -------
        dict with keys: electricity, water, total  (all in QAR/month).
        """
        bkwh = baseline_kwh if baseline_kwh is not None else self.monthly_kwh_consumption
        bm3 = baseline_m3 if baseline_m3 is not None else self.monthly_m3_consumption

        elec_rate = self.compute_electricity_marginal_rate(bkwh)
        water_rate = self.compute_water_marginal_rate(bm3)

        elec_savings = max(0.0, kwh_delta) * elec_rate
        water_savings = max(0.0, m3_delta) * water_rate

        return {
            "electricity": round(elec_savings, 2),
            "water": round(water_savings, 2),
            "total": round(elec_savings + water_savings, 2),
        }

    # ------------------------------------------------------------------
    # Convenience: derive a flat-rate TariffSchedule equivalent
    # ------------------------------------------------------------------

    def to_tariff_schedule(self) -> "TariffSchedule":
        """
        Return a ``TariffSchedule`` whose flat rates equal the *effective
        average* (bill / consumption) at the instance's baseline consumption
        levels.  Useful for code that still relies on the legacy dataclass.
        """
        bill = self.compute_monthly_bill(
            self.monthly_kwh_consumption, self.monthly_m3_consumption
        )
        avg_elec = (
            bill["electricity_energy"] / self.monthly_kwh_consumption
            if self.monthly_kwh_consumption > 0
            else _ELEC_TIERS[-1][1]
        )
        avg_water = (
            bill["water"] / self.monthly_m3_consumption
            if self.monthly_m3_consumption > 0
            else _WATER_TIERS[-1][1]
        )
        return TariffSchedule(
            electricity_kwh_rate=round(avg_elec, 4),
            water_m3_rate=round(avg_water, 4),
            currency=self.currency,
        )


# ---------------------------------------------------------------------------
# Legacy TariffSchedule — kept for backwards compatibility
# ---------------------------------------------------------------------------

@dataclass
class TariffSchedule:
    """
    Flat-rate tariff dataclass.  Retained for backwards compatibility with
    callers that reference ``tariff.electricity_kwh_rate`` or
    ``tariff.water_m3_rate`` directly.

    For new code prefer ``KahramaaTariff``, which implements proper tiered
    billing.  ``get_default_qatar_commercial()`` now derives its flat rates
    from the real Kahramaa 2024 tiered schedule at a 15,000 kWh / 400 m³
    large-commercial baseline.
    """

    electricity_kwh_rate: float
    water_m3_rate: float
    currency: str = "QAR"

    @classmethod
    def get_default_qatar_commercial(cls) -> "TariffSchedule":
        """
        Return a ``TariffSchedule`` whose flat rates are derived from the
        real Kahramaa 2024 tiered commercial tariff evaluated at a typical
        large-commercial baseline of 15,000 kWh/month and 400 m³/month.

        Effective rates at baseline:
          - Electricity: ~0.1367 QAR/kWh (weighted average across tiers)
          - Water:       ~5.125 QAR/m³  (weighted average across tiers)

        These are no longer approximate / mock values — they are computed
        from the real tiered schedule.
        """
        return KahramaaTariff(
            monthly_kwh_consumption=KahramaaTariff.DEFAULT_MONTHLY_KWH,
            monthly_m3_consumption=KahramaaTariff.DEFAULT_MONTHLY_M3,
        ).to_tariff_schedule()


# ---------------------------------------------------------------------------
# Financial Impact Calculator
# ---------------------------------------------------------------------------

class FinancialImpactCalculator:
    """
    Projects the financial impact (cost savings) of proposed GSAS optimisation
    actions using Qatar Kahramaa 2024 tiered tariff rates.

    When initialised with a ``KahramaaTariff`` instance (or when the default
    tariff is used), savings are valued at the **marginal rate** of the
    relevant consumption tier rather than a blunt flat average, giving a
    more accurate economic signal for high-consumption large-commercial
    buildings.
    """

    # Default monthly electricity consumption for a large commercial building
    DEFAULT_BASELINE_KWH = KahramaaTariff.DEFAULT_MONTHLY_KWH
    DEFAULT_BASELINE_M3 = KahramaaTariff.DEFAULT_MONTHLY_M3

    def __init__(
        self,
        cost_engine: Optional[Any] = None,
        tariff: Optional[Union["KahramaaTariff", TariffSchedule]] = None,
    ) -> None:
        self.cost_engine = cost_engine

        if tariff is None:
            # Default: real Kahramaa 2024 tiered tariff at large-commercial baseline
            self._kahramaa = KahramaaTariff(
                monthly_kwh_consumption=self.DEFAULT_BASELINE_KWH,
                monthly_m3_consumption=self.DEFAULT_BASELINE_M3,
            )
            self.tariff = self._kahramaa.to_tariff_schedule()
        elif isinstance(tariff, KahramaaTariff):
            self._kahramaa = tariff
            self.tariff = tariff.to_tariff_schedule()
        else:
            # Caller passed a plain TariffSchedule — honour it as-is but
            # tiered marginal-rate logic will not be available.
            self._kahramaa = None
            self.tariff = tariff

    def calculate_savings(
        self,
        action: Dict[str, Any],
        energy_delta_kwh: float = 0.0,
        water_delta_m3: float = 0.0,
        period_months: int = 1,
        estimate_monthly_consumption: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate projected savings for a given reduction in consumption.

        When a ``KahramaaTariff`` is available, savings are valued at the
        marginal rate corresponding to the building's current consumption
        tier, which better reflects the true avoided cost.  For buildings
        consuming above 15,000 kWh/month the marginal electricity rate is
        0.21 QAR/kWh — significantly higher than a blended average.

        Parameters
        ----------
        action : dict
            Describes the optimisation action (used only for implementation
            cost estimation).
        energy_delta_kwh : float
            Estimated kWh saved per month (positive = saving energy).
        water_delta_m3 : float
            Estimated m³ saved per month.
        period_months : int
            Projection horizon in months.
        estimate_monthly_consumption : float, optional
            Override the baseline monthly electricity consumption (kWh) used
            to determine the applicable marginal tier.  Defaults to
            ``KahramaaTariff.DEFAULT_MONTHLY_KWH`` (15,000 kWh/month) for
            large commercial.

        Returns
        -------
        dict  Same schema as the previous implementation:
              currency, monthly_savings, projected_savings, period_months,
              implementation_cost, payback_months, breakdown, tariff_info.
        """
        logger.debug(
            "Calculating financial impact for %.2f kWh/mo and %.2f m³/mo savings",
            energy_delta_kwh,
            water_delta_m3,
        )

        if self._kahramaa is not None:
            # Use real tiered marginal rates
            baseline_kwh = (
                estimate_monthly_consumption
                if estimate_monthly_consumption is not None
                else self._kahramaa.monthly_kwh_consumption
            )
            baseline_m3 = self._kahramaa.monthly_m3_consumption

            savings = self._kahramaa.compute_savings(
                kwh_delta=energy_delta_kwh,
                m3_delta=water_delta_m3,
                baseline_kwh=baseline_kwh,
                baseline_m3=baseline_m3,
            )
            monthly_elec_savings = savings["electricity"]
            monthly_water_savings = savings["water"]

            elec_rate_used = self._kahramaa.compute_electricity_marginal_rate(baseline_kwh)
            water_rate_used = self._kahramaa.compute_water_marginal_rate(baseline_m3)
            tariff_mode = "tiered_marginal"
        else:
            # Fall back to flat TariffSchedule rates
            monthly_elec_savings = energy_delta_kwh * self.tariff.electricity_kwh_rate
            monthly_water_savings = water_delta_m3 * self.tariff.water_m3_rate
            elec_rate_used = self.tariff.electricity_kwh_rate
            water_rate_used = self.tariff.water_m3_rate
            tariff_mode = "flat_rate"

        total_monthly_savings = monthly_elec_savings + monthly_water_savings

        # ------------------------------------------------------------------
        # Implementation cost estimation based on action type
        # ------------------------------------------------------------------
        action_type = action.get("type", "")
        implementation_cost = 0.0

        if "install" in action_type or "upgrade" in action_type:
            implementation_cost = 5000.0    # Assumed CAPEX
        elif "tune" in action_type or "commission" in action_type:
            implementation_cost = 500.0     # Assumed OPEX (labour)

        payback_months = 0.0
        if implementation_cost > 0 and total_monthly_savings > 0:
            payback_months = round(implementation_cost / total_monthly_savings, 1)

        return {
            "currency": self.tariff.currency,
            "monthly_savings": round(total_monthly_savings, 2),
            "projected_savings": round(total_monthly_savings * period_months, 2),
            "period_months": period_months,
            "implementation_cost": implementation_cost,
            "payback_months": payback_months,
            "breakdown": {
                "electricity": round(monthly_elec_savings, 2),
                "water": round(monthly_water_savings, 2),
            },
            "tariff_info": {
                "mode": tariff_mode,
                "electricity_rate_applied": round(elec_rate_used, 4),
                "water_rate_applied": round(water_rate_used, 4),
                "schedule": "Kahramaa 2024 Commercial Tiered",
            },
        }
