"""
Canonical point roles
=====================

One vocabulary for "what does this BMS point measure", so rule-based FDD,
the LLM snapshot and the verifiers stop guessing from point-name substrings
in six different places.

Role names follow the open-fdd / Project Haystack convention (kebab-case,
e.g. ``supply-air-temp``, ``cooling-valve``) so ported ASHRAE Guideline 36
rules map one-to-one. Every role has a physical quantity with one canonical
SI unit; ``to_canonical`` converts from whatever the site reports (including
BACnet engineering-unit names such as ``degreesFahrenheit``) and returns
``None`` for units it cannot convert — it never assumes.

Resolution order (``PointRoleRegistry.resolve``):
  1. explicit role from the commissioning spec / site config  → trusted
  2. suggestion from an exact point-id suffix                  → confidence 0.9
  3. suggestion that depends on the equipment kind             → 0.7, needs confirmation
  4. otherwise unmapped (the point is simply not used by rules)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("arvis.semantics.roles")


class Quantity(str, Enum):
    TEMPERATURE = "temperature"      # °C
    PRESSURE = "pressure"            # Pa
    FRACTION = "fraction"            # 0–1
    BINARY = "binary"                # 0/1
    POWER = "power"                  # kW (electric)
    THERMAL_POWER = "thermal_power"  # kW (cooling/heating rate)
    ENERGY = "energy"                # kWh
    VOLUME = "volume"                # m³
    AIRFLOW = "airflow"              # m³/s
    WATERFLOW = "waterflow"          # L/s
    CO2 = "co2"                      # ppm
    HUMIDITY = "humidity"            # %RH


CANONICAL_UNIT = {
    Quantity.TEMPERATURE: "°C", Quantity.PRESSURE: "Pa", Quantity.FRACTION: "frac",
    Quantity.BINARY: "bool", Quantity.POWER: "kW", Quantity.THERMAL_POWER: "kW",
    Quantity.ENERGY: "kWh", Quantity.VOLUME: "m³", Quantity.AIRFLOW: "m³/s",
    Quantity.WATERFLOW: "L/s", Quantity.CO2: "ppm", Quantity.HUMIDITY: "%RH",
}


class PointRole(str, Enum):
    # ── Air handling unit / FAHU ──────────────────────────────────────────
    SUPPLY_AIR_TEMP = "supply-air-temp"
    SUPPLY_AIR_TEMP_SP = "supply-air-temp-sp"
    MIXED_AIR_TEMP = "mixed-air-temp"
    RETURN_AIR_TEMP = "return-air-temp"
    OUTSIDE_AIR_TEMP = "outside-air-temp"
    OUTSIDE_AIR_WETBULB = "outside-air-wetbulb"
    DUCT_STATIC_PRESSURE = "duct-static-pressure"
    DUCT_STATIC_PRESSURE_SP = "duct-static-pressure-sp"
    SUPPLY_FAN_SPEED = "supply-fan-speed"          # VFD speed (cmd or feedback), 0–1
    SUPPLY_FAN_STATUS = "supply-fan-status"        # proven running, 0/1
    SUPPLY_FAN_CMD = "supply-fan-cmd"              # start/stop command, 0/1
    OUTSIDE_AIR_DAMPER = "outside-air-damper"
    COOLING_VALVE = "cooling-valve"
    HEATING_VALVE = "heating-valve"
    COOLING_COIL_ENTERING_TEMP = "cooling-coil-entering-temp"
    COOLING_COIL_LEAVING_TEMP = "cooling-coil-leaving-temp"
    HEATING_COIL_ENTERING_TEMP = "heating-coil-entering-temp"
    HEATING_COIL_LEAVING_TEMP = "heating-coil-leaving-temp"
    FILTER_DP = "filter-dp"
    SUPPLY_AIRFLOW = "supply-airflow"
    OUTSIDE_AIRFLOW = "outside-airflow"
    # ── Terminal units (VAV / FCU) and zones ──────────────────────────────
    ZONE_TEMP = "zone-temp"
    ZONE_TEMP_SP = "zone-temp-sp"
    ZONE_HUMIDITY = "zone-humidity"
    ZONE_CO2 = "zone-co2"
    OCCUPANCY = "occupancy"
    TERMINAL_DAMPER = "terminal-damper"
    TERMINAL_AIRFLOW = "terminal-airflow"
    TERMINAL_AIRFLOW_SP = "terminal-airflow-sp"
    TERMINAL_DISCHARGE_TEMP = "terminal-discharge-temp"
    TERMINAL_INLET_TEMP = "terminal-inlet-temp"
    REHEAT_VALVE = "reheat-valve"
    # ── Chilled water plant / district cooling ────────────────────────────
    CHW_SUPPLY_TEMP = "chw-supply-temp"
    CHW_RETURN_TEMP = "chw-return-temp"
    CHW_SUPPLY_TEMP_SP = "chw-supply-temp-sp"
    CHW_DP = "chw-dp"
    CHW_DP_SP = "chw-dp-sp"
    CHW_FLOW = "chw-flow"
    PUMP_SPEED = "pump-speed"
    CHILLER_STATUS = "chiller-status"
    CHILLER_LOAD = "chiller-load"
    CONDENSER_WATER_SUPPLY_TEMP = "condenser-water-supply-temp"
    CONDENSER_WATER_RETURN_TEMP = "condenser-water-return-temp"
    COOLING_TOWER_FAN_SPEED = "cooling-tower-fan-speed"
    DC_PRIMARY_SUPPLY_TEMP = "dc-primary-supply-temp"
    DC_PRIMARY_RETURN_TEMP = "dc-primary-return-temp"
    DC_PRIMARY_FLOW = "dc-primary-flow"
    THERMAL_POWER = "thermal-power"
    # ── Meters ────────────────────────────────────────────────────────────
    ELECTRIC_POWER = "electric-power"
    ELECTRIC_ENERGY = "electric-energy"
    WATER_VOLUME = "water-volume"


_Q = Quantity
ROLE_QUANTITY: Dict[PointRole, Quantity] = {
    PointRole.SUPPLY_AIR_TEMP: _Q.TEMPERATURE, PointRole.SUPPLY_AIR_TEMP_SP: _Q.TEMPERATURE,
    PointRole.MIXED_AIR_TEMP: _Q.TEMPERATURE, PointRole.RETURN_AIR_TEMP: _Q.TEMPERATURE,
    PointRole.OUTSIDE_AIR_TEMP: _Q.TEMPERATURE, PointRole.OUTSIDE_AIR_WETBULB: _Q.TEMPERATURE,
    PointRole.DUCT_STATIC_PRESSURE: _Q.PRESSURE, PointRole.DUCT_STATIC_PRESSURE_SP: _Q.PRESSURE,
    PointRole.SUPPLY_FAN_SPEED: _Q.FRACTION, PointRole.SUPPLY_FAN_STATUS: _Q.BINARY,
    PointRole.SUPPLY_FAN_CMD: _Q.BINARY, PointRole.OUTSIDE_AIR_DAMPER: _Q.FRACTION,
    PointRole.COOLING_VALVE: _Q.FRACTION, PointRole.HEATING_VALVE: _Q.FRACTION,
    PointRole.COOLING_COIL_ENTERING_TEMP: _Q.TEMPERATURE,
    PointRole.COOLING_COIL_LEAVING_TEMP: _Q.TEMPERATURE,
    PointRole.HEATING_COIL_ENTERING_TEMP: _Q.TEMPERATURE,
    PointRole.HEATING_COIL_LEAVING_TEMP: _Q.TEMPERATURE,
    PointRole.FILTER_DP: _Q.PRESSURE, PointRole.SUPPLY_AIRFLOW: _Q.AIRFLOW,
    PointRole.OUTSIDE_AIRFLOW: _Q.AIRFLOW,
    PointRole.ZONE_TEMP: _Q.TEMPERATURE, PointRole.ZONE_TEMP_SP: _Q.TEMPERATURE,
    PointRole.ZONE_HUMIDITY: _Q.HUMIDITY, PointRole.ZONE_CO2: _Q.CO2,
    PointRole.OCCUPANCY: _Q.BINARY, PointRole.TERMINAL_DAMPER: _Q.FRACTION,
    PointRole.TERMINAL_AIRFLOW: _Q.AIRFLOW, PointRole.TERMINAL_AIRFLOW_SP: _Q.AIRFLOW,
    PointRole.TERMINAL_DISCHARGE_TEMP: _Q.TEMPERATURE, PointRole.REHEAT_VALVE: _Q.FRACTION,
    PointRole.TERMINAL_INLET_TEMP: _Q.TEMPERATURE,
    PointRole.CHW_SUPPLY_TEMP: _Q.TEMPERATURE, PointRole.CHW_RETURN_TEMP: _Q.TEMPERATURE,
    PointRole.CHW_SUPPLY_TEMP_SP: _Q.TEMPERATURE, PointRole.CHW_DP: _Q.PRESSURE,
    PointRole.CHW_DP_SP: _Q.PRESSURE, PointRole.CHW_FLOW: _Q.WATERFLOW,
    PointRole.PUMP_SPEED: _Q.FRACTION, PointRole.CHILLER_STATUS: _Q.BINARY,
    PointRole.CHILLER_LOAD: _Q.FRACTION,
    PointRole.CONDENSER_WATER_SUPPLY_TEMP: _Q.TEMPERATURE,
    PointRole.CONDENSER_WATER_RETURN_TEMP: _Q.TEMPERATURE,
    PointRole.COOLING_TOWER_FAN_SPEED: _Q.FRACTION,
    PointRole.DC_PRIMARY_SUPPLY_TEMP: _Q.TEMPERATURE,
    PointRole.DC_PRIMARY_RETURN_TEMP: _Q.TEMPERATURE,
    PointRole.DC_PRIMARY_FLOW: _Q.WATERFLOW, PointRole.THERMAL_POWER: _Q.THERMAL_POWER,
    PointRole.ELECTRIC_POWER: _Q.POWER, PointRole.ELECTRIC_ENERGY: _Q.ENERGY,
    PointRole.WATER_VOLUME: _Q.VOLUME,
}
assert set(ROLE_QUANTITY) == set(PointRole), "every role needs a quantity"


def parse_role(value: Any) -> Optional[PointRole]:
    """Accept 'supply-air-temp', 'SUPPLY_AIR_TEMP' or a PointRole; None if unknown."""
    if isinstance(value, PointRole):
        return value
    if not value:
        return None
    s = str(value).strip()
    try:
        return PointRole(s.lower().replace("_", "-"))
    except ValueError:
        return PointRole.__members__.get(s.upper().replace("-", "_"))


# ──────────────────────────────────────────────────────────────────────────
# Equipment kinds
# ──────────────────────────────────────────────────────────────────────────
_KIND_BY_TYPE = {
    "air_handling_unit": "ahu", "variable_air_volume": "vav", "fan_coil_unit": "fcu",
    "chiller": "chiller", "pump": "pump", "cooling_tower": "cooling_tower",
    "electric_meter": "meter", "water_meter": "meter", "gas_meter": "meter",
}
_KIND_BY_PREFIX = (
    ("FAHU", "ahu"), ("MAU", "ahu"), ("AHU", "ahu"), ("PAU", "ahu"), ("VAV", "vav"),
    ("FCU", "fcu"), ("PCHWP", "pump"), ("SCHWP", "pump"), ("CHWP", "pump"),
    ("CDWP", "pump"), ("PUMP", "pump"), ("ETS", "plant"), ("CHW", "plant"),
    ("CH", "chiller"), ("CT", "cooling_tower"), ("METER", "meter"), ("MTR", "meter"),
)


def equipment_kind(equipment_type: Any = None, equipment_id: str = "") -> str:
    """Normalise to: ahu | vav | fcu | chiller | pump | plant | cooling_tower | meter | other."""
    t = getattr(equipment_type, "value", equipment_type)
    if t and str(t).lower() in _KIND_BY_TYPE:
        return _KIND_BY_TYPE[str(t).lower()]
    eid = (equipment_id or "").upper()
    for prefix, kind in _KIND_BY_PREFIX:
        if eid.startswith(prefix):
            return kind
    return "other"


# ──────────────────────────────────────────────────────────────────────────
# Suffix suggestions
# ──────────────────────────────────────────────────────────────────────────
R = PointRole
# Unambiguous regardless of equipment kind → confidence 0.9.
_SUFFIX_EXACT: Dict[str, PointRole] = {}
for _role, _names in {
    R.SUPPLY_AIR_TEMP_SP: ("SAT_SP", "SATSP", "DAT_SP", "SA_TEMP_SP", "SAT_STPT"),
    R.MIXED_AIR_TEMP: ("MAT", "MA_TEMP", "MIXED_AIR_TEMP", "MAT_ACT"),
    R.RETURN_AIR_TEMP: ("RAT", "RA_TEMP", "RETURN_AIR_TEMP"),
    R.OUTSIDE_AIR_TEMP: ("OAT", "OA_TEMP", "OUTSIDE_AIR_TEMP", "OADB"),
    R.OUTSIDE_AIR_WETBULB: ("OAWB", "OA_WB", "WETBULB", "OA_WETBULB"),
    R.DUCT_STATIC_PRESSURE: ("DSP", "DUCT_STATIC", "SA_STATIC", "SSP", "DUCT_SP_ACT"),
    R.DUCT_STATIC_PRESSURE_SP: ("DSP_SP", "DUCT_STATIC_SP", "SSP_SP", "SA_STATIC_SP"),
    R.SUPPLY_FAN_SPEED: ("SF_SPD", "FAN_SPD", "SF_VFD", "SF_SPEED", "SAF_SPD", "SF_VFD_SPD"),
    R.SUPPLY_FAN_STATUS: ("SF_STS", "SF_STATUS", "FAN_STS", "FAN_STATUS", "SF_RUN"),
    R.SUPPLY_FAN_CMD: ("SF_CMD", "FAN_CMD", "SF_SS", "SF_START"),
    R.OUTSIDE_AIR_DAMPER: ("OA_DMPR", "OAD", "OA_DAMPER", "OA_DMP", "OAD_POS"),
    R.COOLING_VALVE: ("CLG_VLV", "CHW_VLV", "CCV", "CLG_VALVE", "COOL_VLV", "CC_VLV"),
    R.HEATING_VALVE: ("HTG_VLV", "HW_VLV", "HCV", "HTG_VALVE", "HEAT_VLV", "HC_VLV"),
    R.COOLING_COIL_ENTERING_TEMP: ("CC_EAT", "CCET", "CC_ENT_T"),
    R.COOLING_COIL_LEAVING_TEMP: ("CC_LAT", "CCLT", "CC_LVG_T"),
    R.HEATING_COIL_ENTERING_TEMP: ("HC_EAT", "HCET", "HC_ENT_T"),
    R.HEATING_COIL_LEAVING_TEMP: ("HC_LAT", "HCLT", "HC_LVG_T"),
    R.FILTER_DP: ("FILTER_DP", "FLT_DP", "FILTER_DIFF", "FILT_DP"),
    R.OUTSIDE_AIRFLOW: ("OA_FLOW", "OAF", "OA_CFM"),
    R.ZONE_TEMP: ("ZONE_TMP", "ZONE_TEMP", "ZN_T", "ZNT", "ZAT", "SPACE_TEMP", "RM_TEMP", "ZN_TEMP"),
    R.ZONE_TEMP_SP: ("ZONE_SP", "ZN_SP", "ZONE_TEMP_SP", "ZAT_SP", "ZN_T_SP", "SPACE_SP"),
    R.ZONE_HUMIDITY: ("ZONE_RH", "SPACE_RH", "ZN_RH"),
    R.ZONE_CO2: ("CO2", "ZONE_CO2", "ZN_CO2"),
    R.OCCUPANCY: ("OCC", "OCC_STS", "OCCUPANCY"),
    R.TERMINAL_DAMPER: ("VAV_DMPR", "DMPR_POS", "DAMPER_POS", "VAV_DAMPER"),
    R.TERMINAL_AIRFLOW_SP: ("AIRFLOW_SP", "FLOW_SP", "VAV_FLOW_SP"),
    R.REHEAT_VALVE: ("RHV", "RH_VLV", "REHEAT", "RHT_VLV", "REHEAT_VLV"),
    R.TERMINAL_INLET_TEMP: ("INLET_TEMP", "INLET_T", "VAV_EAT", "ENT_AIR_T"),
    R.CHW_SUPPLY_TEMP: ("CHWST", "CHWS", "CHW_ST", "CHWS_T", "CHW_SUPPLY_TEMP"),
    R.CHW_RETURN_TEMP: ("CHWRT", "CHWR", "CHW_RT", "CHWR_T", "CHW_RETURN_TEMP"),
    R.CHW_SUPPLY_TEMP_SP: ("CHWST_SP", "CHWS_SP", "CHW_SP", "CHWST_STPT"),
    R.CHW_DP: ("CHW_DP", "CHW_DIFF_P"),
    R.CHW_DP_SP: ("CHW_DP_SP",),
    R.CHW_FLOW: ("CHW_FLOW", "CHW_FLW", "CHW_GPM"),
    R.PUMP_SPEED: ("PUMP_SPD", "PMP_SPD", "CHWP_SPD", "PUMP_VFD"),
    R.CONDENSER_WATER_SUPPLY_TEMP: ("CWS", "CWST", "CDW_ST"),
    R.CONDENSER_WATER_RETURN_TEMP: ("CWR", "CWRT", "CDW_RT"),
    R.COOLING_TOWER_FAN_SPEED: ("CT_FAN_SPD", "CTF_SPD", "CT_VFD"),
    R.DC_PRIMARY_SUPPLY_TEMP: ("DC_PST", "ETS_PST", "PRI_SUP_T", "PRIMARY_SUPPLY_TEMP"),
    R.DC_PRIMARY_RETURN_TEMP: ("DC_PRT", "ETS_PRT", "PRI_RET_T", "PRIMARY_RETURN_TEMP"),
    R.DC_PRIMARY_FLOW: ("DC_FLOW", "PRI_FLOW", "ETS_FLOW"),
    R.THERMAL_POWER: ("BTU_KW", "THERMAL_KW", "CLG_KW_TH", "TONS", "TR"),
    R.ELECTRIC_POWER: ("KW", "POWER_KW", "DEMAND_KW", "TOTAL_KW"),
    R.ELECTRIC_ENERGY: ("KWH", "ENERGY_KWH", "TOTAL_KWH"),
    R.WATER_VOLUME: ("TOTAL_M3",),
}.items():
    for _n in _names:
        _SUFFIX_EXACT[_n] = _role

# Meaning depends on the equipment kind → confidence 0.7 and needs confirmation.
_SUFFIX_BY_KIND: Dict[str, Dict[str, PointRole]] = {
    "SAT": {"ahu": R.SUPPLY_AIR_TEMP, "vav": R.TERMINAL_DISCHARGE_TEMP,
            "fcu": R.TERMINAL_DISCHARGE_TEMP},
    "DAT": {"ahu": R.SUPPLY_AIR_TEMP, "vav": R.TERMINAL_DISCHARGE_TEMP,
            "fcu": R.TERMINAL_DISCHARGE_TEMP},
    "SAF": {"ahu": R.SUPPLY_AIRFLOW, "vav": R.TERMINAL_AIRFLOW},
    "SA_FLOW": {"ahu": R.SUPPLY_AIRFLOW, "vav": R.TERMINAL_AIRFLOW},
    "AIRFLOW": {"ahu": R.SUPPLY_AIRFLOW, "vav": R.TERMINAL_AIRFLOW, "fcu": R.TERMINAL_AIRFLOW},
    "FLOW": {"vav": R.TERMINAL_AIRFLOW, "chiller": R.CHW_FLOW, "pump": R.CHW_FLOW,
             "plant": R.CHW_FLOW},
    "DMPR": {"vav": R.TERMINAL_DAMPER},
    "DP": {"pump": R.CHW_DP, "plant": R.CHW_DP},
    "DP_SP": {"pump": R.CHW_DP_SP, "plant": R.CHW_DP_SP},
    "SPD": {"pump": R.PUMP_SPEED, "ahu": R.SUPPLY_FAN_SPEED, "fcu": R.SUPPLY_FAN_SPEED},
    "VFD_SPD": {"pump": R.PUMP_SPEED, "ahu": R.SUPPLY_FAN_SPEED},
    "STATUS": {"chiller": R.CHILLER_STATUS, "ahu": R.SUPPLY_FAN_STATUS,
               "fcu": R.SUPPLY_FAN_STATUS},
    "STS": {"chiller": R.CHILLER_STATUS, "ahu": R.SUPPLY_FAN_STATUS, "fcu": R.SUPPLY_FAN_STATUS},
    "LOAD": {"chiller": R.CHILLER_LOAD},
}
# On an AHU "SAT" is unambiguous enough to use without confirmation.
_KIND_CONFIDENT = {("SAT", "ahu"), ("DAT", "ahu")}

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _suffix(point_id: str) -> str:
    tail = (point_id or "").upper().replace("\\", "/").rsplit("/", 1)[-1]
    return _NON_ALNUM.sub("_", tail).strip("_")


def suggest_role(point_id: str, kind: str = "other") -> Tuple[Optional[PointRole], float]:
    """Suggest a role from the point-id suffix. Returns (role, confidence)."""
    sfx = _suffix(point_id)
    if sfx in _SUFFIX_EXACT:
        return _SUFFIX_EXACT[sfx], 0.9
    by_kind = _SUFFIX_BY_KIND.get(sfx)
    if by_kind and kind in by_kind:
        return by_kind[kind], (0.9 if (sfx, kind) in _KIND_CONFIDENT else 0.7)
    return None, 0.0


# ──────────────────────────────────────────────────────────────────────────
# Units
# ──────────────────────────────────────────────────────────────────────────
def _norm_unit(unit: Any) -> str:
    u = str(unit or "").strip().lower()
    u = u.replace("°", "").replace("º", "").replace(" ", "").replace("_", "")
    return u


_TEMP_C = {"c", "degc", "degreesc", "celsius", "degreescelsius", "degc."}
_TEMP_F = {"f", "degf", "degreesf", "fahrenheit", "degreesfahrenheit"}
_TEMP_K = {"k", "kelvin", "degreeskelvin"}
_PRESSURE_TO_PA = {
    "pa": 1.0, "pascal": 1.0, "pascals": 1.0, "kpa": 1000.0, "kilopascals": 1000.0,
    "bar": 1e5, "mbar": 100.0, "millibars": 100.0, "psi": 6894.757,
    "poundsforcepersquareinch": 6894.757, "inh2o": 249.0889, "inwc": 249.0889,
    "in.w.c.": 249.0889, "iwc": 249.0889, "inchesofwater": 249.0889,
    "mmh2o": 9.80665, "millimetersofwater": 9.80665, "ftwc": 2989.067,
    "ftofwater": 2989.067, "feetofwater": 2989.067, "mh2o": 9806.65,
}
_POWER_TO_KW = {"kw": 1.0, "kilowatts": 1.0, "w": 0.001, "watts": 0.001,
                "mw": 1000.0, "megawatts": 1000.0}
_THERMAL_TO_KW = {**_POWER_TO_KW, "tr": 3.51685, "ton": 3.51685, "tons": 3.51685,
                  "tonsrefrigeration": 3.51685, "btu/h": 0.000293071,
                  "btuh": 0.000293071, "btuperhour": 0.000293071,
                  "kbtuh": 0.293071, "mbh": 0.293071}
_ENERGY_TO_KWH = {"kwh": 1.0, "kilowatthours": 1.0, "wh": 0.001, "watthours": 0.001,
                  "mwh": 1000.0, "megawatthours": 1000.0}
_VOLUME_TO_M3 = {"m3": 1.0, "m³": 1.0, "cubicmeters": 1.0, "l": 0.001, "liters": 0.001,
                 "gal": 0.00378541, "usgallons": 0.00378541}
_AIRFLOW_TO_M3S = {"m3/s": 1.0, "m³/s": 1.0, "cubicmeterspersecond": 1.0,
                   "m3/h": 1 / 3600, "m³/h": 1 / 3600, "cmh": 1 / 3600,
                   "cubicmetersperhour": 1 / 3600, "l/s": 0.001, "lps": 0.001,
                   "literspersecond": 0.001, "cfm": 0.000471947,
                   "cubicfeetperminute": 0.000471947}
_WATERFLOW_TO_LS = {"l/s": 1.0, "lps": 1.0, "literspersecond": 1.0, "m3/h": 1 / 3.6,
                    "m³/h": 1 / 3.6, "cubicmetersperhour": 1 / 3.6, "m3/s": 1000.0,
                    "cubicmeterspersecond": 1000.0, "gpm": 0.0630902,
                    "usgallonsperminute": 0.0630902, "l/min": 1 / 60, "lpm": 1 / 60,
                    "litersperminute": 1 / 60}
_PERCENT = {"%", "percent", "pct"}
_FRACTION_NOUNIT = {"", "frac", "fraction", "0-1", "nounits", "none"}
_BINARY_UNITS = {"", "bool", "binary", "nounits", "none", "on/off", "0/1", "status"}


def to_canonical(value: Any, unit: Any, role_or_quantity: Any) -> Optional[float]:
    """Convert ``value`` in ``unit`` to the canonical unit of the role's quantity.

    Returns None when the value is not numeric or the unit is not recognised
    for that quantity. Never guesses a unit, with one documented exception:
    fraction-type points reported without a unit are read as 0–1 if ≤ 1.0 and
    as percent otherwise (the same normalisation open-fdd applies to commands).
    """
    q = role_or_quantity
    if isinstance(q, PointRole):
        q = ROLE_QUANTITY[q]
    if not isinstance(q, Quantity):
        q = Quantity(q)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    u = _norm_unit(unit)

    if q is Quantity.TEMPERATURE:
        if u in _TEMP_C:
            return v
        if u in _TEMP_F:
            return (v - 32.0) * 5.0 / 9.0
        if u in _TEMP_K:
            return v - 273.15
        return None
    if q is Quantity.FRACTION:
        if u in _PERCENT:
            return v / 100.0
        if u in _FRACTION_NOUNIT:
            return v if v <= 1.0 else v / 100.0
        return None
    if q is Quantity.BINARY:
        if u in _BINARY_UNITS or u in _PERCENT:
            return 1.0 if v >= 0.5 else 0.0
        return None
    if q is Quantity.HUMIDITY:
        return v if u in _PERCENT | {"%rh", "rh", "percentrelativehumidity"} else None
    if q is Quantity.CO2:
        return v if u in {"ppm", "partspermillion"} else None
    table = {
        Quantity.PRESSURE: _PRESSURE_TO_PA, Quantity.POWER: _POWER_TO_KW,
        Quantity.THERMAL_POWER: _THERMAL_TO_KW, Quantity.ENERGY: _ENERGY_TO_KWH,
        Quantity.VOLUME: _VOLUME_TO_M3, Quantity.AIRFLOW: _AIRFLOW_TO_M3S,
        Quantity.WATERFLOW: _WATERFLOW_TO_LS,
    }[q]
    factor = table.get(u)
    return v * factor if factor is not None else None


# ──────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class RoleAssignment:
    point_id: str
    role: Optional[PointRole]
    source: str                 # "explicit" | "suggested" | "unmapped"
    confidence: float
    needs_confirmation: bool
    unit_override: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"point_id": self.point_id,
                "role": self.role.value if self.role else None,
                "source": self.source, "confidence": self.confidence,
                "needs_confirmation": self.needs_confirmation}


class PointRoleRegistry:
    """Point → role assignments for one building.

    Explicit roles come from the commissioning spec or site BMS config and are
    trusted. Everything else is a suffix suggestion, reported with its
    confidence so callers (rule engine, UI) can decide what to rely on.
    """

    def __init__(self) -> None:
        self._explicit: Dict[str, Tuple[PointRole, Optional[str]]] = {}

    def set_explicit(self, point_id: str, role: Any, unit: Optional[str] = None) -> PointRole:
        r = parse_role(role)
        if r is None:
            raise ValueError(f"Unknown point role '{role}' for {point_id}")
        self._explicit[point_id] = (r, unit or None)
        return r

    def explicit_count(self) -> int:
        return len(self._explicit)

    def resolve(self, point_id: str, kind: str = "other") -> RoleAssignment:
        if point_id in self._explicit:
            role, unit = self._explicit[point_id]
            return RoleAssignment(point_id, role, "explicit", 1.0, False, unit)
        role, conf = suggest_role(point_id, kind)
        if role is None:
            return RoleAssignment(point_id, None, "unmapped", 0.0, True)
        return RoleAssignment(point_id, role, "suggested", conf, conf < 0.9)

    def role_map(self, point_ids: Iterable[str], kind: str = "other",
                 min_confidence: float = 0.9) -> Tuple[Dict[PointRole, RoleAssignment], List[str]]:
        """Pick one point per role for an equipment.

        Returns (role → assignment, conflicts). Explicit beats suggested; two
        points competing for the same role at the same trust level is reported
        as a conflict and the first one is kept.
        """
        chosen: Dict[PointRole, RoleAssignment] = {}
        conflicts: List[str] = []
        for pid in point_ids:
            a = self.resolve(pid, kind)
            if a.role is None or a.confidence < min_confidence:
                continue
            cur = chosen.get(a.role)
            if cur is None or (a.source == "explicit" and cur.source != "explicit"):
                chosen[a.role] = a
            elif cur.source == a.source:
                conflicts.append(f"{a.role.value}: {cur.point_id} vs {pid}")
        return chosen, conflicts


def get_role_registry(bms_state: Any) -> PointRoleRegistry:
    """The building's registry, attached to its state engine (created on demand)."""
    reg = getattr(bms_state, "point_roles", None)
    if not isinstance(reg, PointRoleRegistry):
        reg = PointRoleRegistry()
        try:
            setattr(bms_state, "point_roles", reg)
        except Exception:
            pass
    return reg
