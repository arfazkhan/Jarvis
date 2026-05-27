"""
Building Domain Aliases
========================

Comprehensive synonym and alias mapping for building automation systems.
Used to expand queries and improve RAG topic matching.

Covers:
- HVAC (heating, ventilation, air conditioning)
- Electrical systems
- Plumbing & water systems
- Fire & life safety
- Building automation & controls
- Energy management
"""

from typing import Dict, List, Set


# ============================================================================
# CORE ALIAS DICTIONARY
# ============================================================================

BUILDING_ALIASES: Dict[str, List[str]] = {
    
    # ═══════════════════════════════════════════════════════════════════════
    # HVAC - COOLING
    # ═══════════════════════════════════════════════════════════════════════
    "chiller": ["chilled water plant", "CWP", "water chiller", "centrifugal chiller", "screw chiller", "absorption chiller"],
    "cooling": ["chiller", "refrigeration", "AC", "air conditioning", "USRT", "tons", "TR"],
    "cooling tower": ["CT", "condenser water", "heat rejection", "evaporative cooler"],
    "AHU": ["air handling unit", "air handler", "central air", "rooftop unit", "RTU", "package unit"],
    "FCU": ["fan coil unit", "fan coil", "terminal unit", "cassette"],
    "VRF": ["VRV", "variable refrigerant flow", "variable refrigerant volume", "multi-split"],
    "DX": ["direct expansion", "split system", "packaged AC"],
    "evaporator": ["cooling coil", "chilled water coil", "DX coil"],
    "condenser": ["heat exchanger", "condenser coil", "rejection coil"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # HVAC - HEATING
    # ═══════════════════════════════════════════════════════════════════════
    "boiler": ["hot water plant", "HWP", "steam boiler", "heating plant"],
    "furnace": ["gas heater", "oil furnace", "heating unit"],
    "heat pump": ["HP", "reversible", "geothermal", "GSHP", "ASHP"],
    "heating coil": ["hot water coil", "steam coil", "electric heater", "reheat"],
    "radiant": ["radiant floor", "radiant panel", "underfloor heating", "ceiling radiant"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # HVAC - VENTILATION
    # ═══════════════════════════════════════════════════════════════════════
    "ventilation": ["fresh air", "outside air", "OA", "makeup air", "MAU"],
    "exhaust": ["exhaust fan", "EF", "extraction", "fume hood"],
    "ERV": ["HRV", "energy recovery", "heat recovery", "enthalpy wheel", "rotary exchanger"],
    "damper": ["OA damper", "RA damper", "EA damper", "fire damper", "smoke damper", "VAV damper"],
    "VAV": ["variable air volume", "VAV box", "terminal box"],
    "CAV": ["constant air volume", "fixed volume"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # COMPRESSORS & MOTORS
    # ═══════════════════════════════════════════════════════════════════════
    "compressor": ["screw compressor", "scroll compressor", "reciprocating", "centrifugal compressor"],
    "motor": ["fan motor", "pump motor", "VFD motor", "ECM"],
    "VFD": ["variable frequency drive", "inverter", "speed drive", "ASD", "variable speed"],
    "starter": ["soft starter", "DOL", "star-delta", "motor starter"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # REFRIGERANTS & FLUIDS
    # ═══════════════════════════════════════════════════════════════════════
    "refrigerant": ["R-134a", "R-410A", "R-32", "R-1234yf", "freon", "coolant", "charge"],
    "glycol": ["antifreeze", "ethylene glycol", "propylene glycol", "brine"],
    "chilled water": ["CHW", "supply water", "return water", "CHWS", "CHWR"],
    "condenser water": ["CW", "tower water", "CWS", "CWR"],
    "hot water": ["HW", "heating water", "HWS", "HWR"],
    "steam": ["condensate", "steam supply", "steam return"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # FLOW & PRESSURE
    # ═══════════════════════════════════════════════════════════════════════
    "flow rate": ["GPM", "L/s", "m³/h", "CFM", "L/min", "volume flow"],
    "water flow": ["evaporator flow", "condenser flow", "chilled water flow", "pump flow"],
    "air flow": ["CFM", "m³/h", "supply air", "return air", "airflow"],
    "pressure": ["PSI", "kPa", "bar", "head", "static pressure", "differential pressure", "DP"],
    "pressure drop": ["head loss", "friction loss", "delta P", "ΔP"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # TEMPERATURE
    # ═══════════════════════════════════════════════════════════════════════
    "temperature": ["temp", "°F", "°C", "Fahrenheit", "Celsius"],
    "setpoint": ["SP", "target", "set point", "desired", "setting"],
    "delta T": ["ΔT", "temperature difference", "supply-return", "approach"],
    "leaving water temperature": ["LWT", "supply temp", "CHWST", "HWST"],
    "entering water temperature": ["EWT", "return temp", "CHWRT", "HWRT"],
    "supply air temperature": ["SAT", "discharge temp", "leaving air"],
    "return air temperature": ["RAT", "mixed air", "entering air"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # EFFICIENCY & PERFORMANCE
    # ═══════════════════════════════════════════════════════════════════════
    "COP": ["coefficient of performance", "efficiency ratio"],
    "EER": ["energy efficiency ratio", "cooling efficiency"],
    "SEER": ["seasonal EER", "seasonal efficiency"],
    "IPLV": ["integrated part load value", "part load efficiency", "NPLV"],
    "kW/ton": ["power per ton", "energy intensity"],
    "capacity": ["tons", "TR", "kW", "BTU", "cooling capacity", "heating capacity"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # CONTROLS & AUTOMATION
    # ═══════════════════════════════════════════════════════════════════════
    "BMS": ["BAS", "building management", "building automation", "DDC", "SCADA"],
    "controller": ["DDC controller", "programmable controller", "PLC", "BCU"],
    "sensor": ["probe", "transmitter", "transducer", "detector"],
    "thermostat": ["room controller", "zone controller", "space sensor"],
    "actuator": ["valve actuator", "damper actuator", "motor actuator"],
    "PID": ["proportional", "integral", "derivative", "control loop", "PI", "P-only"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # VALVES & PIPING
    # ═══════════════════════════════════════════════════════════════════════
    "valve": ["control valve", "isolation valve", "balancing valve", "check valve", "PRV"],
    "2-way valve": ["modulating valve", "throttling valve"],
    "3-way valve": ["mixing valve", "diverting valve", "bypass valve"],
    "pump": ["circulation pump", "booster pump", "primary pump", "secondary pump"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # FAULTS & ALARMS
    # ═══════════════════════════════════════════════════════════════════════
    "fault": ["alarm", "trip", "error", "failure", "malfunction", "issue"],
    "high pressure": ["HP trip", "high head", "discharge pressure", "condenser pressure"],
    "low pressure": ["LP trip", "suction pressure", "evaporator pressure"],
    "safety": ["safety cutout", "limit", "lockout", "protection", "interlock"],
    "troubleshoot": ["diagnose", "debug", "fix", "repair", "service"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # ELECTRICAL
    # ═══════════════════════════════════════════════════════════════════════
    "voltage": ["V", "volts", "line voltage", "phase voltage"],
    "current": ["amps", "A", "amperage", "FLA", "RLA", "LRA"],
    "power": ["kW", "watts", "electrical load", "demand"],
    "electrical": ["electrical panel", "breaker", "disconnect", "MCC"],
    "phase": ["3-phase", "single phase", "three phase", "1-phase"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # FIRE & LIFE SAFETY
    # ═══════════════════════════════════════════════════════════════════════
    "fire alarm": ["FA", "smoke detector", "heat detector", "fire panel"],
    "sprinkler": ["fire suppression", "wet system", "dry system", "pre-action"],
    "smoke control": ["pressurization", "smoke exhaust", "stair pressurization"],
    "emergency": ["life safety", "egress", "exit", "evacuation"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # LIGHTING
    # ═══════════════════════════════════════════════════════════════════════
    "lighting": ["lights", "luminaire", "fixture", "lamp"],
    "dimmer": ["dimming", "0-10V", "DALI", "phase dimming"],
    "occupancy": ["motion sensor", "presence", "vacancy", "PIR"],
    "daylight": ["photocell", "daylight harvesting", "lux sensor"],
    
    # ═══════════════════════════════════════════════════════════════════════
    # SCHEDULES & MODES
    # ═══════════════════════════════════════════════════════════════════════
    "schedule": ["time schedule", "occupancy schedule", "calendar", "holiday"],
    "occupied": ["daytime", "normal hours", "working hours"],
    "unoccupied": ["night mode", "setback", "after hours", "weekend"],
    "standby": ["idle", "off mode", "shutdown"],
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_all_synonyms(term: str) -> Set[str]:
    """
    Get all synonyms for a term, including the term itself.
    Case-insensitive matching.
    """
    term_lower = term.lower()
    synonyms = {term_lower}
    
    # Check if term is a key
    if term_lower in BUILDING_ALIASES:
        synonyms.update(alias.lower() for alias in BUILDING_ALIASES[term_lower])
    
    # Check if term is in any alias list
    for key, aliases in BUILDING_ALIASES.items():
        aliases_lower = [a.lower() for a in aliases]
        if term_lower in aliases_lower or term_lower == key.lower():
            synonyms.add(key.lower())
            synonyms.update(aliases_lower)
    
    return synonyms


def expand_query(query: str) -> str:
    """
    Expand a query with domain synonyms.
    Returns the original query with key synonyms appended.
    """
    if not query or not isinstance(query, str):
        return ""
    query_lower = query.lower()
    expansions = set()
    
    for key, aliases in BUILDING_ALIASES.items():
        # Check if any alias appears in the query
        all_terms = [key] + aliases
        for term in all_terms:
            if term.lower() in query_lower:
                # Add a few key synonyms
                expansions.add(key)
                expansions.update(aliases[:3])  # Limit to avoid bloat
                break
    
    if expansions:
        expansion_str = " ".join(expansions)
        return f"{query} {expansion_str}"
    return query


def check_topic_coverage(content: str, topics: List[str]) -> Dict[str, bool]:
    """
    Check topic coverage with synonym expansion.
    Returns dict of topic -> found status.
    """
    content_lower = content.lower()
    coverage = {}
    
    for topic in topics:
        # Get all synonyms for this topic
        synonyms = get_all_synonyms(topic)
        
        # Check if any synonym appears in content
        found = any(syn in content_lower for syn in synonyms)
        coverage[topic] = found
    
    return coverage


# ============================================================================
# QUICK LOOKUP FUNCTIONS
# ============================================================================

def is_temperature_term(term: str) -> bool:
    """Check if a term relates to temperature."""
    temp_keys = ["temperature", "setpoint", "delta T", "leaving water temperature", 
                 "entering water temperature", "supply air temperature", "return air temperature"]
    for key in temp_keys:
        if term.lower() in get_all_synonyms(key):
            return True
    return False


def is_fault_term(term: str) -> bool:
    """Check if a term relates to faults/alarms."""
    fault_keys = ["fault", "high pressure", "low pressure", "safety", "troubleshoot"]
    for key in fault_keys:
        if term.lower() in get_all_synonyms(key):
            return True
    return False


def is_efficiency_term(term: str) -> bool:
    """Check if a term relates to efficiency/performance."""
    eff_keys = ["COP", "EER", "SEER", "IPLV", "kW/ton", "capacity"]
    for key in eff_keys:
        if term.lower() in get_all_synonyms(key):
            return True
    return False


# ============================================================================
# MODULE INFO
# ============================================================================

def get_stats() -> Dict[str, int]:
    """Get statistics about the alias dictionary."""
    total_aliases = sum(len(v) for v in BUILDING_ALIASES.values())
    return {
        "categories": len(BUILDING_ALIASES),
        "total_aliases": total_aliases,
        "avg_aliases_per_term": round(total_aliases / len(BUILDING_ALIASES), 1)
    }


if __name__ == "__main__":
    # Demo
    print("Building Domain Aliases")
    print("=" * 40)
    stats = get_stats()
    print(f"Categories: {stats['categories']}")
    print(f"Total aliases: {stats['total_aliases']}")
    
    print("\nExample expansions:")
    test_queries = [
        "water flow rate",
        "compressor fault",
        "chiller COP",
        "temperature setpoint"
    ]
    for q in test_queries:
        expanded = expand_query(q)
        print(f"  '{q}' → '{expanded[:80]}...'")
