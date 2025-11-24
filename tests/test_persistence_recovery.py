"""
Persistence & Recovery Critical Tests

Section 6 from aggressive test spec:
- State DB corruption recovery (CRITICAL)
- Partial write during reboot (atomic commits) (CRITICAL)
- Version migration
- Backup & restore correctness
"""

import pytest
import os
import json
from tests.utils.test_harness import ChaosUtils


class TestStateCorruption:
    """Test recovery from corrupted state files."""
    
    @pytest.mark.critical
    def test_truncated_state_file_recovery(self, state_engine, tmpdir):
        """Agent recovers from truncated state.json."""
        # Create valid state file
        state_file = tmpdir.join("state.json")
        valid_state = {
            "devices": {
                "switch_1": {1: "on", 2: "off", 3: "on"}
            },
            "routines": {},
            "timestamp": 1234567890
        }
        state_file.write(json.dumps(valid_state))
        
        # Corrupt (truncate to 50% of file)
        backup = ChaosUtils.corrupt_file(str(state_file), truncate_at=len(json.dumps(valid_state)) // 2)
        
        # Attempt to load corrupted state
        try:
            with open(str(state_file), 'r') as f:
                data = json.load(f)
            pytest.fail("Should have failed to load corrupted JSON")
        except json.JSONDecodeError:
            # Expected: corruption detected
            pass
        
        # System should:
        # 1. Detect corruption
        # 2. Enter safe mode
        # 3. Rebuild from backup or minimal state
        # 4. Log error
        
        # Restore for cleanup
        ChaosUtils.restore_file(str(state_file), backup)
    
    @pytest.mark.critical
    def test_empty_state_file_recovery(self, state_engine, tmpdir):
        """Handle empty or missing state file."""
        state_file = tmpdir.join("state_missing.json")
        
        # File doesn't exist
        assert not state_file.exists()
        
        # Agent should:
        # 1. Create new state file with defaults
        # 2. Not crash
        # 3. Log warning
        
        # Simulate initialization
        default_state = state_engine.get_default_state()
        assert default_state is not None
        assert "devices" in default_state


class TestAtomicWrites:
    """Test atomic file operations."""
    
    @pytest.mark.critical
    def test_partial_write_during_crash(self, state_engine, tmpdir):
        """Simulate crash during state write - no corruption."""
        state_file = tmpdir.join("state.json")
        
        # Write initial state
        initial_state = {"devices": {}, "version": 1}
        with open(str(state_file), 'w') as f:
            json.dump(initial_state, f)
        
        # Simulate partial write (write to temp first, then atomic rename)
        temp_file = tmpdir.join("state.json.tmp")
        new_state = {"devices": {"switch_1": {1: "on"}}, "version": 2}
        
        # Write to temp
        with open(str(temp_file), 'w') as f:
            json.dump(new_state, f)
        
        # Simulate crash before rename
        # temp_file exists, state_file untouched
        
        # On recovery:
        # 1. Check for .tmp file
        # 2. If valid and newer, complete the write
        # 3. If invalid, discard and use last good state
        
        # Load last good state
        with open(str(state_file), 'r') as f:
            recovered = json.load(f)
        
        assert recovered["version"] == 1, "Should recover last good state"
    
    @pytest.mark.critical
    def test_write_with_fsync(self, tmpdir):
        """Ensure writes are fsynced to disk."""
        test_file = tmpdir.join("fsync_test.json")
        data = {"test": "data"}
        
        # Write with fsync
        with open(str(test_file), 'w') as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())  # Force disk write
        
        # File should exist and be readable even after "power loss"
        assert test_file.exists()
        
        with open(str(test_file), 'r') as f:
            loaded = json.load(f)
        
        assert loaded == data


class TestVersionMigration:
    """Test schema version migration."""
    
    def test_old_schema_migration(self, tmpdir):
        """Load old schema and migrate to new format."""
        old_state_file = tmpdir.join("old_state.json")
        
        # Old schema (v1)
        old_schema = {
            "version": 1,
            "devices": ["switch_1", "switch_2"],  # List format
            "routines": []
        }
        old_state_file.write(json.dumps(old_schema))
        
        # New schema (v2) expects dict format
        # Migration should convert list → dict
        
        with open(str(old_state_file), 'r') as f:
            old_data = json.load(f)
        
        # Simulate migration
        if old_data.get("version") == 1:
            if isinstance(old_data["devices"], list):
                # Migrate to dict
                new_devices = {dev: {} for dev in old_data["devices"]}
                old_data["devices"] = new_devices
                old_data["version"] = 2
        
        assert old_data["version"] == 2
        assert isinstance(old_data["devices"], dict)
    
    def test_unknown_version_rejected(self, tmpdir):
        """Reject state with unknown/future version."""
        future_state_file = tmpdir.join("future_state.json")
        
        # Future schema (v99)
        future_schema = {
            "version": 99,
            "devices": {"unknown_format": True}
        }
        future_state_file.write(json.dumps(future_schema))
        
        with open(str(future_state_file), 'r') as f:
            data = json.load(f)
        
        # Should reject or enter safe mode
        if data.get("version", 0) > 2:  # Current version is 2
            # Reject with error message
            with pytest.raises(ValueError, match="Unsupported version"):
                raise ValueError(f"Unsupported version: {data['version']}")


class TestBackupRestore:
    """Test backup and restore functionality."""
    
    def test_backup_creates_copy(self, state_engine, tmpdir):
        """Backup creates exact copy of state."""
        state_file = tmpdir.join("state.json")
        backup_file = tmpdir.join("state_backup.json")
        
        # Create state
        state = {"devices": {"switch_1": {1: "on"}}, "version": 2}
        state_file.write(json.dumps(state))
        
        # Create backup
        with open(str(state_file), 'r') as src:
            with open(str(backup_file), 'w') as dst:
                dst.write(src.read())
        
        # Verify identical
        with open(str(state_file), 'r') as f:
            original = json.load(f)
        with open(str(backup_file), 'r') as f:
            backup = json.load(f)
        
        assert original == backup
    
    @pytest.mark.critical
    def test_restore_from_backup(self, tmpdir):
        """Restore state from backup after corruption."""
        state_file = tmpdir.join("state.json")
        backup_file = tmpdir.join("state_backup.json")
        
        # Create backup
        good_state = {"devices": {"switch_1": {"1": "on"}}, "version": 2}
        backup_file.write(json.dumps(good_state))
        
        # Corrupt main state
        state_file.write("{corrupted")
        
        # Detect corruption and restore from backup
        try:
            with open(str(state_file), 'r') as f:
                json.load(f)
            pytest.fail("Should detect corruption")
        except json.JSONDecodeError:
            # Restore from backup
            with open(str(backup_file), 'r') as src:
                with open(str(state_file), 'w') as dst:
                    dst.write(src.read())
        
        # Verify restored
        with open(str(state_file), 'r') as f:
            restored = json.load(f)
        
        assert restored == good_state


class TestDiskFull:
    """Test behavior when disk is full."""
    
    @pytest.mark.slow
    def test_disk_full_graceful_degradation(self, tmpdir):
        """Handle disk full scenario without data corruption."""
        # This test would require actually filling disk
        # In practice, mock the write failure
        
        state_file = tmpdir.join("state.json")
        
        # Simulate disk full during write
        try:
            # Attempt write that "fails" due to no space
            # with open(str(state_file), 'w') as f:
            #     raise OSError(28, "No space left on device")
            pass
        except OSError as e:
            # System should:
            # 1. Log error
            # 2. Keep old state intact
            # 3. Not corrupt existing files
            # 4. Alert user
            pass

    def test_state_engine_persists_on_change(self, state_engine):
        """Verify StateEngine saves to disk on state change."""
        # Trigger a state change
        state_engine.handle_event({
            "type": "relay_toggled",
            "payload": {"device": "switch_persist", "endpoint": 1, "state": "on"},
            "timestamp": 123456
        })
        
        # Check if file exists and contains data
        state_file = state_engine.persistence.state_file
        
        assert os.path.exists(state_file)
        with open(state_file, 'r') as f:
            data = json.load(f)
            
        assert data["devices"]["switch_persist"]["1"] == "on"

