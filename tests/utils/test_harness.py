"""
Test Harness Utilities for Aggressive Testing

Provides:
- Time travel (fast-forward simulation)
- Deterministic RNG (reproducible scenarios)
- Network emulation (latency, packet loss)
- Chaos utilities (process kill, disk operations)
"""

import time
import random
import os
import signal
import psutil
from datetime import datetime, timedelta
from typing import Callable, Any
from unittest.mock import Mock


class TimeTravel:
    """
    Fast-forward simulation clock for testing time-based automations.
    
    Usage:
        tt = TimeTravel()
        tt.advance_hours(6)  # Simulate 6 hours passing
    """
    
    def __init__(self, start_time: float = None):
        self.simulated_time = start_time or time.time()
        self.real_start = time.time()
    
    def advance_hours(self, hours: int):
        """Advance simulated time by hours."""
        self.simulated_time += hours * 3600
        return self.simulated_time
    
    def advance_days(self, days: int):
        """Advance simulated time by days."""
        self.simulated_time += days * 86400
        return self.simulated_time
    
    def advance_seconds(self, seconds: int):
        """Advance simulated time by seconds."""
        self.simulated_time += seconds
        return self.simulated_time
    
    def get_current_time(self) -> float:
        """Get current simulated time."""
        return self.simulated_time
    
    def get_current_datetime(self) -> datetime:
        """Get current simulated time as datetime."""
        return datetime.fromtimestamp(self.simulated_time)
    
    def reset(self):
        """Reset to real current time."""
        self.simulated_time = time.time()
        self.real_start = time.time()


class DeterministicScenario:
    """
    Generate reproducible test data with fixed seed.
    
    Usage:
        scenario = DeterministicScenario(seed=42)
        events = scenario.generate_daily_events(count=10)
    """
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
    
    def generate_daily_events(self, count: int, day_offset: int = 0):
        """Generate deterministic daily events."""
        events = []
        base_time = time.time() - (day_offset * 86400)
        
        for i in range(count):
            # Deterministic time within day
            hour = self.rng.randint(6, 23)
            minute = self.rng.randint(0, 59)
            
            timestamp = base_time + (hour * 3600) + (minute * 60)
            
            events.append({
                "type": "relay_toggled",
                "payload": {
                    "device": "switch_1",
                    "endpoint": self.rng.randint(1, 3),
                    "state": self.rng.choice(["on", "off"])
                },
                "timestamp": timestamp
            })
        
        return events
    
    def reset(self):
        """Reset RNG to original seed."""
        self.rng = random.Random(self.seed)


class NetworkEmulator:
    """
    Simulate network conditions for testing.
    
    Usage:
        net = NetworkEmulator()
        with net.slow_network(latency_ms=2000):
            # API calls will be slow
    """
    
    def __init__(self):
        self.active_conditions = []
    
    class slow_network:
        """Context manager for simulated slow network."""
        def __init__(self, latency_ms: int):
            self.latency = latency_ms / 1000.0
        
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            pass
        
        def apply_delay(self):
            """Apply configured latency."""
            time.sleep(self.latency)
    
    class network_partition:
        """Context manager for simulated network partition."""
        def __init__(self):
            self.partitioned = False
        
        def __enter__(self):
            self.partitioned = True
            return self
        
        def __exit__(self, *args):
            self.partitioned = False
        
        def is_partitioned(self) -> bool:
            return self.partitioned


class ChaosUtils:
    """
    Chaos engineering utilities for fault injection.
    
    CAUTION: These functions can cause real system impacts!
    Use only in isolated test environments.
    """
    
    @staticmethod
    def kill_process(pid: int, graceful: bool = False):
        """
        Kill a process (use with extreme caution).
        
        Args:
            pid: Process ID to kill
            graceful: If True, send SIGTERM; if False, SIGKILL
        """
        try:
            process = psutil.Process(pid)
            if graceful:
                process.terminate()  # SIGTERM
            else:
                process.kill()  # SIGKILL
            return True
        except psutil.NoSuchProcess:
            return False
    
    @staticmethod
    def fill_disk(directory: str, size_mb: int = 100):
        """
        Fill disk space (creates temp file).
        
        Args:
            directory: Directory to fill
            size_mb: Size in MB to write
        
        Returns:
            Path to created file
        """
        filepath = os.path.join(directory, "chaos_disk_fill.tmp")
        
        try:
            with open(filepath, 'wb') as f:
                f.write(b'\x00' * (size_mb * 1024 * 1024))
            return filepath
        except Exception as e:
            raise Exception(f"Failed to fill disk: {e}")
    
    @staticmethod
    def cleanup_disk_fill(filepath: str):
        """Clean up disk fill file."""
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
    
    @staticmethod
    def corrupt_file(filepath: str, truncate_at: int = None):
        """
        Corrupt a file (for testing recovery).
        
        Args:
            filepath: File to corrupt
            truncate_at: Byte position to truncate at (None = random)
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        
        # Backup original
        backup_path = f"{filepath}.backup"
        if not os.path.exists(backup_path):
            with open(filepath, 'rb') as f_in:
                with open(backup_path, 'wb') as f_out:
                    f_out.write(f_in.read())
        
        # Corrupt by truncating
        file_size = os.path.getsize(filepath)
        if truncate_at is None:
            truncate_at = file_size // 2  # Middle of file
        
        with open(filepath, 'r+b') as f:
            f.truncate(truncate_at)
        
        return backup_path
    
    @staticmethod
    def restore_file(filepath: str, backup_path: str):
        """Restore file from backup."""
        if os.path.exists(backup_path):
            os.replace(backup_path, filepath)


class MockTimeProvider:
    """
    Mock time provider for testing scheduled automations.
    
    Usage:
        time_provider = MockTimeProvider()
        time_provider.set_time(datetime(2025, 1, 1, 7, 0, 0))
    """
    
    def __init__(self):
        self.current_time = datetime.now()
    
    def set_time(self, dt: datetime):
        """Set the current time."""
        self.current_time = dt
    
    def advance(self, **kwargs):
        """Advance time by timedelta kwargs."""
        self.current_time += timedelta(**kwargs)
    
    def now(self) -> datetime:
        """Get current time."""
        return self.current_time
    
    def timestamp(self) -> float:
        """Get current time as Unix timestamp."""
        return self.current_time.timestamp()


def create_deterministic_llm_mock(scenario: str = "valid"):
    """
    Create a deterministic LLM mock for testing.
    
    Args:
        scenario: Type of response ("valid", "malformed", "hallucination", etc.)
    
    Returns:
        Mock LLM client
    """
    scenarios = {
        "valid": '[{"tool_name": "log_note", "arguments": {"text": "Test"}}]',
        "malformed": '{"incomplete"',
        "hallucination": '[{"tool_name": "invented_tool", "arguments": {}}]',
        "empty": '[]',
        "rate_limit": {"error": "rate_limit_exceeded"},
        "timeout": {"error": "timeout"},
    }
    
    mock = Mock()
    
    if scenario == "rate_limit" or scenario == "timeout":
        mock.chat.completions.create.side_effect = Exception(scenarios[scenario]["error"])
    else:
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = scenarios.get(scenario, scenarios["valid"])
        mock.chat.completions.create.return_value = mock_response
    
    return mock
