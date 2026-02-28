"""
OTA (Over-The-Air) Firmware Update Manager for ARVIS.

Handles firmware updates for Matter devices, including:
- Update discovery and validation
- Download and verification
- Installation with rollback support
- Status tracking and reporting
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime

logger = logging.getLogger("arvis.firmware.ota")


class UpdateStatus(Enum):
    """Firmware update status"""
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    REBOOTING = "rebooting"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


@dataclass
class FirmwareVersion:
    """Firmware version information"""
    major: int
    minor: int
    patch: int
    build: Optional[str] = None
    
    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.build:
            version += f"-{self.build}"
        return version
    
    def __lt__(self, other: "FirmwareVersion") -> bool:
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
    
    def __le__(self, other: "FirmwareVersion") -> bool:
        return (self.major, self.minor, self.patch) <= (other.major, other.minor, other.patch)
    
    def __gt__(self, other: "FirmwareVersion") -> bool:
        return (self.major, self.minor, self.patch) > (other.major, other.minor, other.patch)
    
    def __ge__(self, other: "FirmwareVersion") -> bool:
        return (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return False
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)
    
    @classmethod
    def parse(cls, version_str: str) -> "FirmwareVersion":
        """Parse version string like '1.2.3' or '1.2.3-beta'"""
        build = None
        if "-" in version_str:
            version_str, build = version_str.split("-", 1)
        
        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        
        return cls(major=major, minor=minor, patch=patch, build=build)


@dataclass
class FirmwareUpdate:
    """Firmware update information"""
    device_id: str
    device_name: str
    current_version: FirmwareVersion
    available_version: FirmwareVersion
    release_notes: str = ""
    download_url: str = ""
    file_size: int = 0
    checksum: str = ""
    checksum_algorithm: str = "sha256"
    release_date: Optional[datetime] = None
    critical: bool = False
    downloaded: bool = False
    download_progress: float = 0.0
    local_path: Optional[Path] = None


@dataclass
class UpdateProgress:
    """Update progress tracking"""
    device_id: str
    status: UpdateStatus
    progress: float = 0.0
    message: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    rollback_available: bool = False
    previous_version: Optional[FirmwareVersion] = None


class OTAManager:
    """
    Over-The-Air Firmware Update Manager.
    
    Manages firmware updates for connected devices with support for:
    - Update discovery from manufacturer servers
    - Secure download with checksum verification
    - Staged installation with automatic rollback
    - Progress tracking and status reporting
    """
    
    def __init__(
        self,
        firmware_dir: str = "./firmware",
        max_concurrent_updates: int = 3,
        auto_rollback_timeout: int = 300,  # 5 minutes
        event_bus: Any = None,
    ):
        self.firmware_dir = Path(firmware_dir)
        self.max_concurrent_updates = max_concurrent_updates
        self.auto_rollback_timeout = auto_rollback_timeout
        self.event_bus = event_bus
        
        # State tracking
        self._updates: Dict[str, FirmwareUpdate] = {}
        self._progress: Dict[str, UpdateProgress] = {}
        self._update_tasks: Dict[str, asyncio.Task] = {}
        self._rollback_data: Dict[str, bytes] = {}
        
        # Callbacks
        self._on_progress: Optional[Callable] = None
        self._on_complete: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        
        # Ensure firmware directory exists
        self.firmware_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"OTA Manager initialized with firmware dir: {self.firmware_dir}")
    
    def set_callbacks(
        self,
        on_progress: Optional[Callable] = None,
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ):
        """Set callback functions for update events"""
        self._on_progress = on_progress
        self._on_complete = on_complete
        self._on_error = on_error
    
    async def check_for_updates(
        self,
        device_id: str,
        current_version: str,
        device_name: str = "",
        manufacturer: str = "",
        model: str = "",
    ) -> Optional[FirmwareUpdate]:
        """
        Check for available firmware updates for a device.
        
        Args:
            device_id: Unique device identifier
            current_version: Current firmware version string
            device_name: Human-readable device name
            manufacturer: Device manufacturer
            model: Device model number
            
        Returns:
            FirmwareUpdate if update available, None otherwise
        """
        logger.info(f"Checking for updates: {device_id} (v{current_version})")
        
        # Create progress entry
        progress = UpdateProgress(
            device_id=device_id,
            status=UpdateStatus.CHECKING,
            message="Checking for updates...",
            started_at=datetime.now(),
        )
        self._progress[device_id] = progress
        
        try:
            # Parse current version
            current = FirmwareVersion.parse(current_version)
            
            # In a real implementation, this would query manufacturer servers
            # For now, we simulate checking for updates
            available = await self._query_update_server(
                device_id=device_id,
                manufacturer=manufacturer,
                model=model,
                current_version=current,
            )
            
            if available and available > current:
                update = FirmwareUpdate(
                    device_id=device_id,
                    device_name=device_name,
                    current_version=current,
                    available_version=available,
                    release_notes="Bug fixes and performance improvements",
                    download_url=f"https://firmware.example.com/{manufacturer}/{model}/{available}.bin",
                    file_size=1024 * 1024,  # 1MB default
                    checksum="abc123...",  # Placeholder
                    release_date=datetime.now(),
                    critical=False,
                )
                self._updates[device_id] = update
                
                progress.status = UpdateStatus.IDLE
                progress.message = f"Update available: v{available}"
                
                logger.info(f"Update available for {device_id}: v{current} -> v{available}")
                return update
            else:
                progress.status = UpdateStatus.IDLE
                progress.message = "No updates available"
                
                logger.info(f"No updates available for {device_id}")
                return None
                
        except Exception as e:
            progress.status = UpdateStatus.FAILED
            progress.error = str(e)
            logger.error(f"Failed to check for updates: {e}")
            return None
    
    async def _query_update_server(
        self,
        device_id: str,
        manufacturer: str,
        model: str,
        current_version: FirmwareVersion,
    ) -> Optional[FirmwareVersion]:
        """Query manufacturer update server for available firmware."""
        # Simulate network delay
        await asyncio.sleep(0.5)
        
        # In production, this would:
        # 1. Make HTTP request to manufacturer's firmware API
        # 2. Parse response for available versions
        # 3. Return latest compatible version
        
        # For simulation, return a newer version occasionally
        # This simulates finding an update 50% of the time
        import random
        if random.random() > 0.5:
            return FirmwareVersion(
                major=current_version.major,
                minor=current_version.minor + 1,
                patch=0,
            )
        
        return None
    
    async def download_update(self, device_id: str) -> bool:
        """
        Download firmware update for a device.
        
        Args:
            device_id: Device to download update for
            
        Returns:
            True if download successful, False otherwise
        """
        update = self._updates.get(device_id)
        if not update:
            logger.error(f"No update available for {device_id}")
            return False
        
        progress = self._progress.get(device_id)
        if not progress:
            progress = UpdateProgress(
                device_id=device_id,
                status=UpdateStatus.DOWNLOADING,
                started_at=datetime.now(),
            )
            self._progress[device_id] = progress
        else:
            progress.status = UpdateStatus.DOWNLOADING
        
        progress.message = "Downloading firmware..."
        self._notify_progress(device_id, progress)
        
        try:
            # Create local file path
            filename = f"{device_id}_{update.available_version}.bin"
            local_path = self.firmware_dir / filename
            
            # Simulate download with progress
            chunk_size = 8192
            total_chunks = update.file_size // chunk_size + 1
            
            # In production, this would actually download from update.download_url
            # For simulation, we create a dummy file
            with open(local_path, "wb") as f:
                for i in range(total_chunks):
                    # Simulate download delay
                    await asyncio.sleep(0.01)
                    
                    # Write dummy data
                    f.write(os.urandom(min(chunk_size, update.file_size - f.tell())))
                    
                    # Update progress
                    progress.progress = (i + 1) / total_chunks * 100
                    update.download_progress = progress.progress
                    self._notify_progress(device_id, progress)
            
            update.downloaded = True
            update.local_path = local_path
            
            progress.status = UpdateStatus.VERIFYING
            progress.message = "Verifying download..."
            self._notify_progress(device_id, progress)
            
            # Verify checksum
            if await self._verify_checksum(local_path, update.checksum):
                progress.status = UpdateStatus.IDLE
                progress.message = "Download complete, ready to install"
                logger.info(f"Download complete for {device_id}")
                return True
            else:
                progress.status = UpdateStatus.FAILED
                progress.error = "Checksum verification failed"
                logger.error(f"Checksum verification failed for {device_id}")
                return False
                
        except Exception as e:
            progress.status = UpdateStatus.FAILED
            progress.error = str(e)
            logger.error(f"Download failed for {device_id}: {e}")
            return False
    
    async def _verify_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Verify file checksum matches expected value."""
        # Simulate verification delay
        await asyncio.sleep(0.5)
        
        # In production, calculate actual checksum
        # For simulation, always pass
        return True
    
    async def install_update(
        self,
        device_id: str,
        matter_controller: Any = None,
        backup_current: bool = True,
    ) -> bool:
        """
        Install firmware update on a device.
        
        Args:
            device_id: Device to update
            matter_controller: Matter controller for device communication
            backup_current: Whether to backup current firmware for rollback
            
        Returns:
            True if installation successful, False otherwise
        """
        update = self._updates.get(device_id)
        if not update or not update.downloaded:
            logger.error(f"No downloaded update for {device_id}")
            return False
        
        progress = self._progress.get(device_id)
        if not progress:
            progress = UpdateProgress(
                device_id=device_id,
                status=UpdateStatus.INSTALLING,
                started_at=datetime.now(),
            )
            self._progress[device_id] = progress
        else:
            progress.status = UpdateStatus.INSTALLING
        
        progress.message = "Installing firmware..."
        progress.progress = 0.0
        self._notify_progress(device_id, progress)
        
        try:
            # Backup current firmware if requested
            if backup_current:
                progress.message = "Backing up current firmware..."
                progress.progress = 10.0
                self._notify_progress(device_id, progress)
                
                # In production, read current firmware from device
                # For simulation, store version info for rollback
                self._rollback_data[device_id] = json.dumps({
                    "version": str(update.current_version),
                    "timestamp": datetime.now().isoformat(),
                }).encode()
                
                progress.rollback_available = True
                progress.previous_version = update.current_version
            
            # Transfer firmware to device
            progress.message = "Transferring firmware to device..."
            progress.progress = 30.0
            self._notify_progress(device_id, progress)
            
            if matter_controller and hasattr(matter_controller, "update_firmware"):
                # Use Matter controller to update device
                await matter_controller.update_firmware(
                    device_id=device_id,
                    firmware_path=str(update.local_path),
                    progress_callback=lambda p: self._update_install_progress(device_id, p),
                )
            else:
                # Simulate installation progress
                for i in range(30, 90, 10):
                    await asyncio.sleep(0.5)
                    progress.progress = i
                    self._notify_progress(device_id, progress)
            
            # Wait for device to reboot
            progress.status = UpdateStatus.REBOOTING
            progress.message = "Waiting for device reboot..."
            progress.progress = 90.0
            self._notify_progress(device_id, progress)
            
            await asyncio.sleep(2)  # Simulate reboot time
            
            # Verify update successful
            progress.message = "Verifying installation..."
            progress.progress = 95.0
            self._notify_progress(device_id, progress)
            
            await asyncio.sleep(0.5)
            
            # Mark complete
            progress.status = UpdateStatus.COMPLETED
            progress.progress = 100.0
            progress.message = f"Updated to v{update.available_version}"
            progress.completed_at = datetime.now()
            self._notify_progress(device_id, progress)
            
            # Publish event
            if self.event_bus:
                self.event_bus.publish({
                    "type": "firmware_updated",
                    "device_id": device_id,
                    "version": str(update.available_version),
                    "timestamp": datetime.now().isoformat(),
                })
            
            logger.info(f"Update complete for {device_id}: v{update.available_version}")
            self._notify_complete(device_id, progress)
            
            return True
            
        except Exception as e:
            progress.status = UpdateStatus.FAILED
            progress.error = str(e)
            logger.error(f"Installation failed for {device_id}: {e}")
            
            # Attempt automatic rollback
            if progress.rollback_available:
                await self.rollback_update(device_id, matter_controller)
            
            self._notify_error(device_id, progress)
            return False
    
    def _update_install_progress(self, device_id: str, progress_value: float):
        """Update installation progress from callback."""
        progress = self._progress.get(device_id)
        if progress:
            progress.progress = 30.0 + (progress_value * 60.0)  # 30-90%
            self._notify_progress(device_id, progress)
    
    async def rollback_update(
        self,
        device_id: str,
        matter_controller: Any = None,
    ) -> bool:
        """
        Rollback firmware to previous version.
        
        Args:
            device_id: Device to rollback
            matter_controller: Matter controller for device communication
            
        Returns:
            True if rollback successful, False otherwise
        """
        progress = self._progress.get(device_id)
        if not progress or not progress.rollback_available:
            logger.error(f"No rollback available for {device_id}")
            return False
        
        progress.status = UpdateStatus.ROLLING_BACK
        progress.message = "Rolling back to previous version..."
        progress.progress = 0.0
        self._notify_progress(device_id, progress)
        
        try:
            # Simulate rollback process
            for i in range(0, 100, 10):
                await asyncio.sleep(0.3)
                progress.progress = i
                self._notify_progress(device_id, progress)
            
            progress.status = UpdateStatus.ROLLED_BACK
            progress.message = f"Rolled back to v{progress.previous_version}"
            progress.completed_at = datetime.now()
            self._notify_progress(device_id, progress)
            
            # Publish event
            if self.event_bus:
                self.event_bus.publish({
                    "type": "firmware_rolled_back",
                    "device_id": device_id,
                    "version": str(progress.previous_version),
                    "timestamp": datetime.now().isoformat(),
                })
            
            logger.info(f"Rollback complete for {device_id}")
            return True
            
        except Exception as e:
            progress.status = UpdateStatus.FAILED
            progress.error = f"Rollback failed: {e}"
            logger.error(f"Rollback failed for {device_id}: {e}")
            return False
    
    def get_update_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get current update status for a device."""
        progress = self._progress.get(device_id)
        update = self._updates.get(device_id)
        
        if not progress:
            return None
        
        result = {
            "device_id": device_id,
            "status": progress.status.value,
            "progress": progress.progress,
            "message": progress.message,
            "error": progress.error,
            "rollback_available": progress.rollback_available,
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
            "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
        }
        
        if update:
            result.update({
                "current_version": str(update.current_version),
                "available_version": str(update.available_version),
                "downloaded": update.downloaded,
                "download_progress": update.download_progress,
            })
        
        if progress.previous_version:
            result["previous_version"] = str(progress.previous_version)
        
        return result
    
    def get_all_updates(self) -> List[Dict[str, Any]]:
        """Get all tracked updates."""
        return [
            self.get_update_status(device_id)
            for device_id in self._updates.keys()
        ]
    
    def cancel_update(self, device_id: str) -> bool:
        """Cancel an in-progress update."""
        task = self._update_tasks.get(device_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled update for {device_id}")
            
            progress = self._progress.get(device_id)
            if progress:
                progress.status = UpdateStatus.FAILED
                progress.error = "Cancelled by user"
            
            return True
        
        return False
    
    def clear_update(self, device_id: str) -> bool:
        """Clear update data for a device."""
        if device_id in self._updates:
            del self._updates[device_id]
        if device_id in self._progress:
            del self._progress[device_id]
        if device_id in self._rollback_data:
            del self._rollback_data[device_id]
        
        # Clean up downloaded file
        update = self._updates.get(device_id)
        if update and update.local_path and update.local_path.exists():
            update.local_path.unlink()
        
        logger.info(f"Cleared update data for {device_id}")
        return True
    
    def _notify_progress(self, device_id: str, progress: UpdateProgress):
        """Notify progress callback."""
        if self._on_progress:
            try:
                self._on_progress(device_id, progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def _notify_complete(self, device_id: str, progress: UpdateProgress):
        """Notify completion callback."""
        if self._on_complete:
            try:
                self._on_complete(device_id, progress)
            except Exception as e:
                logger.error(f"Complete callback error: {e}")
    
    def _notify_error(self, device_id: str, progress: UpdateProgress):
        """Notify error callback."""
        if self._on_error:
            try:
                self._on_error(device_id, progress)
            except Exception as e:
                logger.error(f"Error callback error: {e}")
