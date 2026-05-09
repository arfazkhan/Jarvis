"""
Equipment Tool Handler Tests
============================

Tests for EquipmentHandlerMixin tools:
- get_equipment_status
- list_equipment
- get_equipment_health
- get_point_history
- get_equipment_specs
- hybrid_search_knowledge
- get_dashboard_overview

Hardened for commercial deployment with defensive checks and mock stability.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin, EquipmentType
from tests.mocks import MockBMSStateEngineV2, MockPredictiveEngine

# ============================================================================
# TEST FIXTURES
# ============================================================================

class Handler(EquipmentHandlerMixin):
    """Test handler class."""
    def __init__(self):
        self.bms_state = None
        self.predictive_engine = None
        self.knowledge_base = None
        self.graph_rag = None
        self.hybrid_rag = None

@pytest.fixture
def equipment_handler():
    """Fixture for equipment handler."""
    handler = Handler()
    handler.bms_state = MockBMSStateEngineV2()
    handler.predictive_engine = MockPredictiveEngine()
    
    # Add some default equipment
    handler.bms_state.add_equipment({
        "equipment_id": "CH-01",
        "name": "Chiller 1",
        "equipment_type": EquipmentType.CHILLER,
        "status": "running",
        "location": "Basement"
    })
    handler.bms_state.update_point("CH-01/CHWST", 7.0, "°C", "CH-01")
    
    return handler

# ============================================================================
# TOOL TESTS
# ============================================================================

class TestGetEquipmentStatus:
    """Tests for get_equipment_status tool."""
    
    @pytest.mark.asyncio
    async def test_happy_path(self, equipment_handler):
        """Test happy path for equipment status."""
        result = await equipment_handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert "equipment" in result
        assert "data_points" in result
        assert result["equipment"]["equipment_id"] == "CH-01"
        assert len(result["data_points"]) > 0
        assert result["data_points"][0]["point_id"] == "CH-01/CHWST"

    @pytest.mark.asyncio
    async def test_nonexistent_equipment(self, equipment_handler):
        """Test with nonexistent equipment."""
        result = await equipment_handler._handle_get_equipment_status({"equipment_id": "UNKNOWN"})
        
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_state_engine(self):
        """Test with missing state engine."""
        handler = Handler()
        result = await handler._handle_get_equipment_status({"equipment_id": "CH-01"})
        
        assert "error" in result
        assert "not configured" in result["error"].lower()


class TestListEquipment:
    """Tests for list_equipment tool."""
    
    @pytest.mark.asyncio
    async def test_list_all(self, equipment_handler):
        """Test listing all equipment."""
        result = await equipment_handler._handle_list_equipment({})
        
        assert "count" in result
        assert "equipment" in result
        assert result["count"] >= 1
        assert any(e["equipment_id"] == "CH-01" for e in result["equipment"])

    @pytest.mark.asyncio
    async def test_filter_by_type(self, equipment_handler):
        """Test filtering by equipment type."""
        # Add a different type
        equipment_handler.bms_state.add_equipment({
            "equipment_id": "AHU-01",
            "equipment_type": EquipmentType.AHU
        })
        
        result = await equipment_handler._handle_list_equipment({"equipment_type": "chiller"})
        
        assert result["count"] == 1
        assert result["equipment"][0]["equipment_id"] == "CH-01"

    @pytest.mark.asyncio
    async def test_filter_by_location(self, equipment_handler):
        """Test filtering by location."""
        result = await equipment_handler._handle_list_equipment({"location": "Basement"})
        
        assert result["count"] == 1
        assert result["equipment"][0]["equipment_id"] == "CH-01"


class TestGetEquipmentHealth:
    """Tests for get_equipment_health tool."""
    
    @pytest.mark.asyncio
    async def test_happy_path_with_engine(self, equipment_handler):
        """Test health with predictive engine available."""
        result = await equipment_handler._handle_get_equipment_health({"equipment_id": "CH-01"})
        
        assert "overall_health" in result
        assert "health_score" in result
        assert result["equipment_id"] == "CH-01"

    @pytest.mark.asyncio
    async def test_fallback_without_engine(self, equipment_handler):
        """Test health fallback when engine is missing."""
        equipment_handler.predictive_engine = None
        result = await equipment_handler._handle_get_equipment_health({"equipment_id": "CH-01"})
        
        assert "overall_health" in result
        assert result["health_score"] == 92.5  # Hardcoded fallback


class TestGetPointHistory:
    """Tests for get_point_history tool."""
    
    @pytest.mark.asyncio
    async def test_happy_path(self, equipment_handler):
        """Test getting point history."""
        # Setup mock history
        history_data = [
            (datetime.now(), 7.0),
            (datetime.now(), 7.1)
        ]
        equipment_handler.bms_state.get_point_history = AsyncMock(return_value=history_data)
        
        result = await equipment_handler._handle_get_point_history({
            "point_id": "CH-01/CHWST",
            "minutes": 30
        })
        
        assert result["point_id"] == "CH-01/CHWST"
        assert len(result["data"]) == 2
        assert "timestamp" in result["data"][0]
        assert "value" in result["data"][0]

    @pytest.mark.asyncio
    async def test_fallback_no_history_support(self, equipment_handler):
        """Test fallback when state engine doesn't support history."""
        class SlimState:
            pass
        equipment_handler.bms_state = SlimState()
        
        result = await equipment_handler._handle_get_point_history({"point_id": "CH-01/CHWST"})
        
        assert "data" in result
        assert result["data"] == []
        assert "note" in result


class TestKnowledgeSearch:
    """Tests for knowledge search tools."""
    
    @pytest.mark.asyncio
    async def test_specs_search_fallback(self, equipment_handler):
        """Test specs search fallback to knowledge base."""
        kb = MagicMock()
        kb.query_specs = AsyncMock(return_value=[
            {"content": "Specs for CH-01", "metadata": {"source": "manual.pdf"}}
        ])
        equipment_handler.knowledge_base = kb
        
        result = await equipment_handler._handle_get_equipment_specs({
            "query": "capacity",
            "equipment_id": "CH-01"
        })
        
        assert "findings" in result
        assert "Specs for CH-01" in result["findings"]
        assert result["sources"] == ["manual.pdf"]

    @pytest.mark.asyncio
    async def test_hybrid_search_fallback(self, equipment_handler):
        """Test hybrid search fallback to vector search."""
        kb = MagicMock()
        kb.query_specs = AsyncMock(return_value=[{"content": "Result"}])
        equipment_handler.knowledge_base = kb
        equipment_handler.hybrid_rag = None
        
        result = await equipment_handler._handle_hybrid_search_knowledge({"query": "test"})
        
        assert result["strategy"] == "vector_fallback"
        assert "vector_results" in result


class TestDashboardOverview:
    """Tests for get_dashboard_overview tool."""
    
    @pytest.mark.asyncio
    async def test_happy_path(self, equipment_handler):
        """Test dashboard overview."""
        equipment_handler.bms_state.get_snapshot = AsyncMock(return_value={"status": "all_green"})
        
        result = await equipment_handler._handle_get_dashboard_overview({})
        
        assert result["status"] == "all_green"

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
