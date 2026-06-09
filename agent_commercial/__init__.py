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

# ── Native OpenMP guard (faiss + torch + numpy/MKL coexistence) ──────────────
# faiss-cpu, torch and numpy/MKL each bundle an OpenMP runtime; loading more than
# one into the same process segfaults intermittently — seen as EXIT 139 on the BGE
# reranker / sentence-transformers (CrossEncoder) load. Force a single, sequential
# OpenMP BEFORE any native lib is imported so reranking stays ON by default without
# a per-run env or disabling the feature. setdefault → deployments can still override.
import os as _os
_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("OMP_NUM_THREADS", "1")
_os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
_os.environ.setdefault("KMP_INIT_AT_FORK", "FALSE")

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
