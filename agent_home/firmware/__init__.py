"""
ARVIS Firmware Management Module.

Provides OTA (Over-The-Air) firmware update capabilities for connected devices.
"""

from .ota_manager import (
    OTAManager,
    FirmwareVersion,
    FirmwareUpdate,
    UpdateProgress,
    UpdateStatus,
)

__all__ = [
    "OTAManager",
    "FirmwareVersion",
    "FirmwareUpdate",
    "UpdateProgress",
    "UpdateStatus",
]
