"""
ARVIS Ops Copilot - BMS Integration Module
==========================================

Commercial Building Management System integration layer for ARVIS.
Provides intelligent advisory for facility operations:
- BACnet/Modbus protocol adapters
- Intelligent alarm processing
- Energy anomaly detection (Isolation Forest)
- Predictive maintenance (XGBoost + Weibull + LSTM)
- GSAS compliance reporting

This module coexists alongside ARVIS home automation.
"""

from agent_commercial.bms_data_model import (
    BMSDataPoint,
    Equipment,
    EquipmentType,
    PointType,
    Alarm,
    AlarmSeverity,
    EnergyReading,
)

__version__ = "0.1.0"
__all__ = [
    "BMSDataPoint",
    "Equipment", 
    "EquipmentType",
    "PointType",
    "Alarm",
    "AlarmSeverity",
    "EnergyReading",
]
