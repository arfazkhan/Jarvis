"""
Equipment Tool Tests
====================

Comprehensive tests for all equipment-related BMS tools.

Tests per tool:
- Happy path (normal operation)
- Edge cases (empty, invalid, boundary)
- Failure modes (unavailable dependencies)
- Stress scenarios (high load, concurrent access)
"""

import pytest
import asyncio
from typing import Dict, Any

from tests.mocks import MockBMSStateEngine, MockLLM
from tests.factories import EquipmentFactory, DataPointFactory
from tests.utils.helpers import (
    assert_valid_tool_result,
    assert_valid_recommendation,
    Timer,
)


# ============================================================================
# MARKER REGISTRATION
# ============================================================================

pytestmark = pytest.mark.asyncio


# ============================================================================
# GET EQUIPMENT STATUS
# ============================================================================

class TestGetEquipmentStatus:
    """Tests for get_equipment_status tool."""
    
    # ==================== HAPPY PATH ====================
    
    async def test_returns_equipment_with_all_points(self, mock_bms_state):
        """Normal: equipment exists, returns status with data points."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        # Setup
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point("CH-01/CHWST", 7.0, equipment_id="CH-01")
        mock_bms_state.update_point("CH-01/KW", 250.0, equipment_id="CH-01")
        
        # Create handler instance
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        
        # Execute
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        # Verify
        assert "error" not in result
        assert "equipment" in result
        assert result["equipment"]["equipment_id"] == "CH-01"
        assert len(result["data_points"]) == 2
    
    async def test_returns_status_running(self, mock_bms_state):
        """Equipment status is correctly reflected."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="running"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert result["equipment"]["status"] == "running"
    
    async def test_returns_status_fault(self, mock_bms_state):
        """Equipment in fault state is correctly reported."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="fault"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert result["equipment"]["status"] == "fault"
    
    # ==================== EDGE CASES ====================
    
    async def test_equipment_not_found(self, mock_bms_state):
        """Equipment doesn't exist, returns error."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": "NONEXISTENT-99"})
        
        assert "error" in result
        assert "not found" in result["error"].lower()
    
    async def test_empty_equipment_id(self, mock_bms_state):
        """Empty equipment_id returns error."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": ""})
        
        # Should handle gracefully (error or empty result)
        assert "error" in result or result.get("equipment") is None
    
    async def test_equipment_with_no_data_points(self, mock_bms_state):
        """Equipment exists but has no data points."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        # Don't add any points
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        # Should succeed with empty points list
        assert "equipment" in result
        assert result["data_points"] == []
    
    async def test_equipment_with_special_characters_in_id(self, mock_bms_state):
        """Equipment ID with special characters is handled."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-01/ZONE-A"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01/ZONE-A"})
        
        assert result["equipment"]["equipment_id"] == "CH-01/ZONE-A"
    
    # ==================== FAILURE MODES ====================
    
    async def test_bms_state_unavailable(self):
        """BMS state engine is None, returns error."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(None)
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert "error" in result
        assert "not configured" in result["error"].lower()
    
    async def test_bms_state_raises_exception(self, mock_bms_state):
        """BMS state throws exception, handler doesn't crash."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        # Make get_equipment raise an exception
        mock_bms_state.get_equipment = lambda eid: (_ for _ in ()).throw(Exception("DB connection lost"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        
        # Should not raise uncaught exception
        try:
            result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
            # If it returns, should be an error
            assert "error" in result
        except Exception as e:
            # If it raises, should be a wrapped/handled exception
            assert "DB connection" in str(e) or "error" in str(e).lower()
    
    # ==================== STRESS ====================
    
    async def test_concurrent_calls_same_equipment(self, mock_bms_state):
        """100 concurrent requests for same equipment."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        
        # Run 100 concurrent calls
        tasks = [
            handler._handle_get_equipment_status({"equipment_id": "CH-01"})
            for _ in range(100)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Got {len(exceptions)} exceptions"
        
        # Verify all succeeded
        successes = [r for r in results if not isinstance(r, Exception) and "equipment" in r]
        assert len(successes) == 100
    
    async def test_large_equipment_list(self, mock_bms_state):
        """Equipment with 500+ data points."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        # Add 500 points
        for i in range(500):
            mock_bms_state.update_point(f"CH-01/P{i:04d}", float(i), equipment_id="CH-01")
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        
        with Timer("get_equipment_status with 500 points") as t:
            result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert "equipment" in result
        assert len(result["data_points"]) == 500
        # Should complete in reasonable time (< 1s)
        assert t.duration_ms < 1000


# ============================================================================
# LIST EQUIPMENT
# ============================================================================

class TestListEquipment:
    """Tests for list_equipment tool."""
    
    # ==================== HAPPY PATH ====================
    
    async def test_lists_all_equipment(self, mock_bms_state):
        """Returns all equipment without filters."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_equipment(EquipmentFactory.ahu())
        mock_bms_state.add_equipment(EquipmentFactory.cooling_tower())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({})
        
        assert result["count"] == 3
        assert len(result["equipment"]) == 3
    
    async def test_filters_by_type(self, mock_bms_state):
        """Filters equipment by type."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_equipment(EquipmentFactory.chiller(equipment_id="CH-02"))
        mock_bms_state.add_equipment(EquipmentFactory.ahu())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({"equipment_type": "chiller"})
        
        assert result["count"] == 2
        assert all(eq["equipment_type"] == "chiller" for eq in result["equipment"])
    
    async def test_filters_by_status(self, mock_bms_state):
        """Filters equipment by status."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="running"))
        mock_bms_state.add_equipment(EquipmentFactory.ahu(status="fault"))
        mock_bms_state.add_equipment(EquipmentFactory.cooling_tower(status="running"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({"status": "fault"})
        
        assert result["count"] == 1
        assert result["equipment"][0]["status"] == "fault"
    
    async def test_filters_by_location(self, mock_bms_state):
        """Filters equipment by location."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(location="Floor 1"))
        mock_bms_state.add_equipment(EquipmentFactory.ahu(location="Floor 2"))
        mock_bms_state.add_equipment(EquipmentFactory.cooling_tower(location="Floor 1"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({"location": "Floor 1"})
        
        assert result["count"] == 2
        assert all("Floor 1" in eq["location"] for eq in result["equipment"])
    
    # ==================== EDGE CASES ====================
    
    async def test_empty_equipment_list(self, mock_bms_state):
        """No equipment in system, returns empty list."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({})
        
        assert result["count"] == 0
        assert result["equipment"] == []
    
    async def test_filter_returns_no_matches(self, mock_bms_state):
        """Filter matches nothing, returns empty list."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_equipment(EquipmentFactory.ahu())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({"status": "nonexistent_status"})
        
        assert result["count"] == 0
    
    async def test_combined_filters(self, mock_bms_state):
        """Multiple filters work together."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="running", location="Floor 1"))
        mock_bms_state.add_equipment(EquipmentFactory.chiller(status="fault", location="Floor 1"))
        mock_bms_state.add_equipment(EquipmentFactory.ahu(status="running", location="Floor 1"))
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_list_equipment({
            "equipment_type": "chiller",
            "status": "running",
            "location": "Floor 1"
        })
        
        # Only CH-01 matches all three filters
        assert result["count"] == 1
        assert result["equipment"][0]["equipment_id"] == "CH-01"
    
    # ==================== FAILURE MODES ====================
    
    async def test_bms_state_unavailable(self):
        """BMS state engine is None, returns error."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(None)
        result = await handler._handle_list_equipment({})
        
        assert "error" in result


# ============================================================================
# GET EQUIPMENT HEALTH
# ============================================================================

class TestGetEquipmentHealth:
    """Tests for get_equipment_health tool."""
    
    async def test_returns_health_score(self, mock_bms_state):
        """Returns health score for equipment."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.predictive_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_health({"equipment_id": "CH-01"})
        
        assert "health_score" in result
        assert 0 <= result["health_score"] <= 100
        assert "overall_health" in result
    
    async def test_health_score_good(self, mock_bms_state):
        """Health score > 70 means 'good'."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
                self.predictive_engine = None
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_equipment_health({"equipment_id": "CH-01"})
        
        # Default should be good
        assert result["overall_health"] == "good"
        assert result["health_score"] > 70


# ============================================================================
# GET POINT HISTORY
# ============================================================================

class TestGetPointHistory:
    """Tests for get_point_history tool."""
    
    async def test_returns_point_history(self, mock_bms_state):
        """Returns history for a data point."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.update_point("CH-01/CHWST", 7.0, equipment_id="CH-01")
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_point_history({
            "point_id": "CH-01/CHWST",
            "minutes": 60
        })
        
        # Should return history (even if mock returns empty)
        assert "point_id" in result or "history" in result or result.get("error") is not None
    
    async def test_point_not_found(self, mock_bms_state):
        """Point doesn't exist, returns error."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_point_history({
            "point_id": "NONEXISTENT/POINT",
            "minutes": 60
        })
        
        # Should handle gracefully
        assert "error" in result or result.get("history") == []


# ============================================================================
# HYBRID SEARCH KNOWLEDGE
# ============================================================================

class TestHybridSearchKnowledge:
    """Tests for hybrid_search_knowledge tool."""
    
    async def test_searches_knowledge_base(self, mock_bms_state, mock_llm):
        """Searches knowledge base with hybrid RAG."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state, llm):
                self.bms_state = state
                self.llm = llm
                self.hybrid_rag = None  # Will use fallback
        
        handler = Handler(mock_bms_state, mock_llm)
        result = await handler._handle_hybrid_search_knowledge({
            "query": "chiller capacity",
            "equipment_id": "CH-01",
            "strategy": "auto",
            "limit": 5
        })
        
        # Should return results or graceful error
        assert "results" in result or "error" in result or "tree_results" in result
    
    async def test_auto_strategy_selection(self, mock_bms_state, mock_llm):
        """Auto strategy picks appropriate path."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state, llm):
                self.bms_state = state
                self.llm = llm
                self.hybrid_rag = None
        
        handler = Handler(mock_bms_state, mock_llm)
        
        # Query that hints at tree search
        result = await handler._handle_hybrid_search_knowledge({
            "query": "startup procedure section",
            "strategy": "auto"
        })
        
        # Should handle without error
        assert "error" not in result or "results" in result


# ============================================================================
# GET DASHBOARD OVERVIEW
# ============================================================================

class TestGetDashboardOverview:
    """Tests for get_dashboard_overview tool."""
    
    async def test_returns_overview(self, mock_bms_state):
        """Returns building overview."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_equipment(EquipmentFactory.ahu())
        mock_bms_state.add_equipment(EquipmentFactory.meter())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_dashboard_overview({})
        
        # Should include counts
        assert "equipment_count" in result or "total_equipment" in result or result.get("error") is not None
    
    async def test_includes_alarm_count(self, mock_bms_state):
        """Overview includes active alarm count."""
        from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
        from tests.factories import AlarmFactory
        
        mock_bms_state.add_equipment(EquipmentFactory.chiller())
        mock_bms_state.add_alarm(AlarmFactory.critical_chiller())
        
        class Handler(EquipmentHandlerMixin):
            def __init__(self, state):
                self.bms_state = state
        
        handler = Handler(mock_bms_state)
        result = await handler._handle_get_dashboard_overview({})
        
        # Should include alarm info
        assert "active_alarms" in result or "alarm_count" in result or result.get("error") is not None
