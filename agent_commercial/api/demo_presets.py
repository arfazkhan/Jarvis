"""
ARVIS Demo Presets
==================

Curated building presets and scenario catalogs for the ARVIS Live Capabilities API.
"""

from typing import Dict, Any, List

MARINA_HEIGHTS_PRESET: Dict[str, Any] = {
    "building_id": "DOHA-TOWER-001",
    "equipment": [
        # Chillers (Carrier 30XA)
        {"id": "chiller_01", "type": "chiller", "name": "Chiller 01 (800TR)", "location": "Basement, Plant Room"},
        {"id": "chiller_02", "type": "chiller", "name": "Chiller 02 (800TR)", "location": "Basement, Plant Room"},
        {"id": "chiller_03", "type": "chiller", "name": "Chiller 03 (800TR)", "location": "Basement, Plant Room"},
        {"id": "chiller_04", "type": "chiller", "name": "Chiller 04 (800TR)", "location": "Basement, Plant Room"},
        
        # Major AHUs
        {"id": "ahu_01", "type": "ahu", "name": "AHU Floor 1 (Lobby)", "location": "Floor 1, Zone A"},
        {"id": "ahu_02", "type": "ahu", "name": "AHU Floor 2 (Retail)", "location": "Floor 2, Zone A"},
        {"id": "ahu_03", "type": "ahu", "name": "AHU Floor 3 (Office)", "location": "Floor 3, Zone A"},
        {"id": "ahu_04", "type": "ahu", "name": "AHU Floor 4 (Office)", "location": "Floor 4, Zone A"},
        {"id": "ahu_05", "type": "ahu", "name": "AHU Floor 5 (Office)", "location": "Floor 5, Zone A"},
        {"id": "ahu_06", "type": "ahu", "name": "AHU Floor 6 (Office)", "location": "Floor 6, Zone A"},
        {"id": "ahu_07", "type": "ahu", "name": "AHU Floor 12 (Mechanical)", "location": "Floor 12, Zone A"},
        {"id": "ahu_08", "type": "ahu", "name": "AHU Floor 19 (Executive)", "location": "Floor 19, Zone A"},
        
        # Pumps
        {"id": "pump_01", "type": "pump", "name": "Primary Chilled Water Pump 1", "location": "Basement, Plant Room"},
        {"id": "pump_02", "type": "pump", "name": "Primary Chilled Water Pump 2", "location": "Basement, Plant Room"},
        {"id": "pump_03", "type": "pump", "name": "Condenser Water Pump 1", "location": "Basement, Plant Room"},
        {"id": "pump_04", "type": "pump", "name": "Condenser Water Pump 2", "location": "Basement, Plant Room"},
        
        # Cooling Towers
        {"id": "ct_01", "type": "cooling_tower", "name": "Cooling Tower 1", "location": "Roof, North Wing"},
        {"id": "ct_02", "type": "cooling_tower", "name": "Cooling Tower 2", "location": "Roof, South Wing"},
    ]
}

SCENARIO_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "chiller_vibration",
        "name": "Chiller Compressor Mechanical Vibration",
        "description": "Injects severe compressor vibration in Chiller 01, simulating mechanical bearing wear. Evaluates ARVIS's ability to trigger early warning safety alerts before mechanical failure.",
        "affected_equipment": "chiller_01",
        "severity": "high",
        "fault_payload": {
            "type": "EQUIPMENT_FAULT",
            "target": "chiller_01",
            "parameter": "VIBRATION",
            "value": 5.8,
            "duration_hours": 3
        },
        "expected_detection": "ARVIS detects Chiller 01 vibration spike (5.8 mm/s vs 0.8 baseline). Swarm rules it a safety risk and issues a T3 advisory recommending load transfer and bearing maintenance."
    },
    {
        "id": "ahu_temp_drift",
        "name": "AHU Dampers/Coil Fouling (Loss of Cooling)",
        "description": "Simulates a cooling discharge temperature drift in the Floor 3 AHU, representing a stuck damper or fouled chilled-water coil. Floor space begins overheating.",
        "affected_equipment": "ahu_03",
        "severity": "medium",
        "fault_payload": {
            "type": "EQUIPMENT_FAULT",
            "target": "ahu_03",
            "parameter": "SAT",
            "value": 29.5,
            "duration_hours": 4
        },
        "expected_detection": "ARVIS detects supply air temperature mismatch (29.5°C vs 24.5°C design). Diagnoses airflow imbalance and recommends damper recalibration to avoid tenant comfort complaints."
    },
    {
        "id": "ghost_operation",
        "name": "AHU Ghost Schedule Overtime Operation",
        "description": "Forces the Floor 19 Executive AHU to remain in 100% operation state in the middle of the night (2:00 AM) when zone occupancy is completely zero. Evaluates energy efficiency detection.",
        "affected_equipment": "ahu_08",
        "severity": "low",
        "fault_payload": {
            "type": "EQUIPMENT_FAULT",
            "target": "ahu_08",
            "parameter": "STATUS",
            "value": 1.0,
            "duration_hours": 6
        },
        "expected_detection": "ARVIS detects AHU 08 active state (STATUS=1.0) during unoccupied night hours (sim_time = 02:00). Swarm tags it as Ghost Operation, computes +14% energy overhead, and recommends night setback schedule."
    },
    {
        "id": "sensor_corruption",
        "name": "Sensor Fault & Reading Implosion",
        "description": "Corrupts the return air temperature sensor for the Floor 12 Mechanical Room AHU to report an unrealistic reading of 12.0°C. Tests ARVIS's validation logic against faulty sensor data.",
        "affected_equipment": "ahu_07",
        "severity": "medium",
        "fault_payload": {
            "type": "EQUIPMENT_FAULT",
            "target": "ahu_07",
            "parameter": "RAT",
            "value": 12.0,
            "duration_hours": 2
        },
        "expected_detection": "ARVIS detects Return Air Temp (12°C) is below Supply Air Temp (24.5°C) — a physical impossibility. Swarm flags the sensor as 'Faulty/Corrupted', and abstains from initiating physical cooling override."
    },
    {
        "id": "extreme_ambient_surge",
        "name": "Qatar Extreme Summer Ambient Heatwave",
        "description": "Simulates an extreme Doha weather event where the outdoor temperature surges to 51.5°C, creating massive thermal loads on the chiller plant.",
        "affected_equipment": "plant_room",
        "severity": "high",
        "fault_payload": {
            "type": "WEATHER_EVENT",
            "target": "WEATHER",
            "parameter": "OAT",
            "value": 51.5,
            "duration_hours": 5
        },
        "expected_detection": "ARVIS identifies outdoor ambient heatwave. Performs system-wide comfort vs plant load balance analysis, and issues optimized setpoint strategies to avoid chiller high-pressure trips."
    }
]
