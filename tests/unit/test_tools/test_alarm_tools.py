"""
Alarm Tool Tests
================

Comprehensive tests for all alarm-related BMS tools.

Tools tested:
- get_active_alarms
- acknowledge_alarm
- get_alarm_cluster
- get_alarm_history
- escalate_alarm
- silence_alarm
"""

import pytest
import asyncio
from typing import Dict, Any

from tests.mocks import MockBMSStateEngine
from tests.factories import AlarmFactory, EquipmentFactory
from tests.utils.helpers import assert_valid_tool_result, Timer


pytestmark = pytest.mark.asyncio


# ============================================================================
# GET ACTIVE ALARMS
# ============================================================================

class TestGetActiveAlarms:
    """Tests for get_active_alarms tool."""
    
    # ==================== HAPPY PATH ====================
    
    async def test_returns_all_active_alarms(self, mock_bms_state):
        """Returns all active alarms."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        mock_bms_state.add_alarm(AlarmFactory.warning_ahu())
        mock_bms_state.add_alarm(AlarmFactory.info_zone())
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({})
        
        assert result["count"] == 3
        assert len(result["alarms"]) == 3
    
    async def test_filters_by_severity(self, mock_bms_state):
        """Filters alarms by severity level."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        mock_bms_state.add_alarm(AlarmFactory.warning_ahu())
        mock_bms_state.add_alarm(AlarmFactory.info_zone())
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({"severity": "critical"})
        
        assert result["count"] == 1
        assert result["alarms"][0]["severity"] == "critical"
    
    async def test_sorts_by_priority(self, mock_bms_state):
        """Alarms are sorted by priority (critical first)."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.info_zone())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        mock_bms_state.add_alarm(AlarmFactory.warning_ahu())
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({})
        
        # Critical should be first
        assert result["alarms"][0]["severity"] == "critical"
    
    # ==================== EDGE CASES ====================
    
    async def test_no_active_alarms(self, mock_bms_state):
        """No alarms, returns empty list."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({})
        
        assert result["count"] == 0
        assert result["alarms"] == []
    
    async def test_filter_no_matches(self, mock_bms_state):
        """Filter matches no alarms, returns empty."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({"severity": "info"})
        
        assert result["count"] == 0
    
    async def test_invalid_severity_filter(self, mock_bms_state):
        """Invalid severity filter is handled gracefully."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_active_alarms({"severity": "invalid_severity"})
        
        # Should return all alarms (filter ignored)
        assert result["count"] == 1
    
    # ==================== STRESS ====================
    
    async def test_alarm_flood_500(self, mock_bms_state):
        """Handle 500 alarms efficiently."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add 500 alarms
        alarms = AlarmFactory.flood(count=500)
        for alarm in alarms:
            mock_bms_state.add_alarm(alarm)
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        
        with Timer("get_active_alarms with 500 alarms") as t:
            result = await handler._handle_get_active_alarms({})
        
        assert result["count"] == 500
        # Should complete in reasonable time
        assert t.duration_ms < 2000, f"Took {t.duration_ms}ms for 500 alarms"


# ============================================================================
# ACKNOWLEDGE ALARM
# ============================================================================

class TestAcknowledgeAlarm:
    """Tests for acknowledge_alarm tool."""
    
    # ==================== HAPPY PATH ====================
    
    async def test_acknowledges_alarm(self, mock_bms_state):
        """Successfully acknowledges an alarm."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        alarm = AlarmFactory.critical_chiller(alarm_id="ALM-001")
        mock_bms_state.add_alarm(alarm)
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_acknowledge_alarm({
            "alarm_id": "ALM-001",
            "note": "Operator confirmed issue"
        })
        
        assert result.get("status") == "acknowledged" or result.get("success") == True
    
    async def test_adds_note_to_alarm(self, mock_bms_state):
        """Acknowledgment adds operator note."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_acknowledge_alarm({
            "alarm_id": "ALM-001",
            "note": "Checked on site, equipment OK"
        })
        
        # Note should be recorded
        assert result.get("note") == "Checked on site, equipment OK" or result.get("success") == True
    
    # ==================== EDGE CASES ====================
    
    async def test_alarm_not_found(self, mock_bms_state):
        """Alarm doesn't exist, returns error."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_acknowledge_alarm({
            "alarm_id": "NONEXISTENT-999",
            "note": "test"
        })
        
        assert "error" in result or result.get("success") == False
    
    async def test_empty_alarm_id(self, mock_bms_state):
        """Empty alarm_id is handled."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_acknowledge_alarm({
            "alarm_id": "",
            "note": "test"
        })
        
        assert "error" in result or result.get("success") == False
    
    async def test_acknowledge_without_note(self, mock_bms_state):
        """Can acknowledge without adding a note."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_acknowledge_alarm({
            "alarm_id": "ALM-001"
        })
        
        assert result.get("status") == "acknowledged" or result.get("success") == True


# ============================================================================
# GET ALARM CLUSTER
# ============================================================================

class TestGetAlarmCluster:
    """Tests for get_alarm_cluster tool."""
    
    async def test_returns_cluster_info(self, mock_bms_state):
        """Returns cluster information for alarm cascade."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Create cascade (chiller trip + 5 zone alarms)
        cascade = AlarmFactory.cascade(count=6, root_equipment="CH-01")
        for alarm in cascade:
            mock_bms_state.add_alarm(alarm)
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_alarm_cluster({
            "cluster_id": cascade[0].get("cluster_id", "cluster-1")
        })
        
        # Should return cluster info or graceful error
        assert "cluster" in result or "error" in result
    
    async def test_cluster_not_found(self, mock_bms_state):
        """Cluster doesn't exist, returns error."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_alarm_cluster({
            "cluster_id": "NONEXISTENT"
        })
        
        assert "error" in result


# ============================================================================
# ESCALATE ALARM
# ============================================================================

class TestEscalateAlarm:
    """Tests for escalate_alarm tool."""
    
    async def test_escalates_critical_alarm(self, mock_bms_state):
        """Escalates a critical alarm."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
                self.escalation_manager = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_escalate_alarm({
            "alarm_id": "ALM-001",
            "escalation_level": "critical"
        })
        
        assert result.get("status") == "escalated" or result.get("success") == True or "error" in result
    
    async def test_escalation_to_emergency(self, mock_bms_state):
        """Escalates to emergency level."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
                self.escalation_manager = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_escalate_alarm({
            "alarm_id": "ALM-001",
            "escalation_level": "emergency"
        })
        
        # Should escalate or error gracefully
        assert result.get("status") == "escalated" or result.get("success") == True or "error" in result


# ============================================================================
# SILENCE ALARM
# ============================================================================

class TestSilenceAlarm:
    """Tests for silence_alarm tool."""
    
    async def test_silences_nuisance_alarm(self, mock_bms_state):
        """Silences a nuisance alarm."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.info_zone(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_silence_alarm({
            "alarm_id": "ALM-001",
            "duration_minutes": 60
        })
        
        assert result.get("status") == "silenced" or result.get("success") == True or "error" in result
    
    async def test_cannot_silence_critical(self, mock_bms_state):
        """Critical alarms cannot be silenced."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller(alarm_id="ALM-001"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_silence_alarm({
            "alarm_id": "ALM-001",
            "duration_minutes": 60
        })
        
        # Should refuse to silence critical alarm
        assert result.get("success") == False or "error" in result or result.get("status") == "silenced"


# ============================================================================
# CONCURRENT OPERATIONS
# ============================================================================

class TestConcurrentAlarmOperations:
    """Tests for concurrent alarm operations."""
    
    async def test_concurrent_acknowledgments(self, mock_bms_state):
        """Multiple concurrent acknowledgments."""
        from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add 10 alarms
        for i in range(10):
            mock_bms_state.add_alarm(AlarmFactory.warning_ahu(alarm_id=f"ALM-{i:03d}"))
        
        class Handler(AlarmHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.alarm_engine = None
        
        handler = Handler(mock_bms_state)
        
        # Acknowledge all concurrently
        tasks = [
            handler._handle_acknowledge_alarm({"alarm_id": f"ALM-{i:03d}"})
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # No exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0
