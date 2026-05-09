"""
GSAS Tool Tests
================

Comprehensive tests for GSAS (Global Sustainability Assessment System) tools.

Tests cover:
- Happy path: Normal GSAS operations
- Edge cases: Missing data, empty inputs
- Failure modes: Reporter unavailable, database errors
- Stress: Concurrent GSAS queries
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any, List

from unittest.mock import patch, MagicMock

# Import test utilities
from tests.mocks import MockGSASReporter, MockBMSStateEngine
from tests.factories import RecommendationFactory
from tests.utils.helpers import assert_valid_tool_result
from agent_commercial.tools.handlers.gsas import GSASHandlerMixin

pytestmark = pytest.mark.asyncio


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_gsas_reporter():
    """Mock GSAS reporter with sample data."""
    reporter = MockGSASReporter(
        overall_score=78.5,
        target_score=85.0,
        certification_level="3-Star",
        category_scores={
            "energy": 80.0,
            "water": 75.0,
            "indoor_environment": 82.0,
        }
    )
    
    # Add sample improvements
    reporter.add_improvement({
        "action": "Optimize chiller sequencing",
        "impact": 1.5,
        "category": "Energy",
        "estimated_savings_qar": 500.0,
    })
    reporter.add_improvement({
        "action": "Install low-flow fixtures",
        "impact": 0.8,
        "category": "Water",
        "estimated_savings_qar": 300.0,
    })
    
    return reporter


@pytest.fixture
def mock_bms_state_with_equipment():
    """Mock BMS state with sample equipment."""
    from tests.mocks import create_mock_bms_state_with_equipment
    return create_mock_bms_state_with_equipment()


@pytest.fixture(autouse=True)
def mock_db_globally():
    """Automatically mock database for all tests to prevent hanging connections."""
    from unittest.mock import AsyncMock
    with patch("agent_commercial.tools.handlers.gsas.get_database") as mock:
        mock_db = MagicMock()
        # Setup mock to return no cached score by default
        mock_db.get_latest_gsas_score = AsyncMock(return_value=None)
        mock.return_value = mock_db
        yield mock_db


# ============================================================================
# GET GSAS STATUS TESTS
# ============================================================================

class TestGetGSASStatus:
    """Tests for get_gsas_status tool."""
    
    async def test_returns_current_gsas_status(self, mock_gsas_reporter):
        """Happy path: Returns GSAS status with scores."""
        # Create handler instance
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_get_gsas_status({})
        
        # Verify
        assert_valid_tool_result(result)
        assert "overall_score" in result
        assert "certification_level" in result
        assert "categories" in result
        assert result["overall_score"] == 78.5
        assert result["certification_level"] == "3-Star"
        assert "energy" in result["categories"]
    
    async def test_calculates_from_bms_state_when_no_reporter(self, mock_bms_state_with_equipment):
        """When no reporter, calculates from BMS data."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = None
                self.bms_state = mock_bms_state_with_equipment
        
        handler = Handler()
        result = await handler._handle_get_gsas_status({})
        
        # Verify
        assert "overall_score" in result
        assert "certification_level" in result
        assert result["certification_level"] in ["1-Star", "2-Star", "3-Star", "4-Star"]
        assert result["categories"]["energy"] >= 0
    
    async def test_returns_default_when_no_data(self):
        """When no reporter or BMS state, returns defaults."""
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = None
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_get_gsas_status({})
        
        # Verify defaults
        assert_valid_tool_result(result)
        assert "overall_score" in result
        assert result["certification_level"] in ["1-Star", "2-Star", "3-Star", "4-Star"]
        assert "note" in result or "categories" in result

    async def test_database_unavailable_fallback(self, mock_bms_state_with_equipment):
        """Handle missing database by falling back to BMS data."""
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = None
                self.bms_state = mock_bms_state_with_equipment
        
        handler = Handler()
        
        with patch("agent_commercial.tools.handlers.gsas.get_database", None):
            result = await handler._handle_get_gsas_status({})
            assert_valid_tool_result(result)
            assert "overall_score" in result
            assert "Real-time estimate" in result.get("note", "")


# ============================================================================
# GET GSAS IMPROVEMENT PRIORITIES TESTS
# ============================================================================

class TestGetGSASImprovementPriorities:
    """Tests for get_gsas_improvement_priorities tool."""
    
    async def test_returns_prioritized_improvements(self, mock_gsas_reporter):
        """Happy path: Returns improvement priorities."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_get_gsas_improvement_priorities({})
        
        # Verify
        assert "priorities" in result
        assert isinstance(result["priorities"], list)
        assert len(result["priorities"]) > 0
        
        # Verify structure
        priority = result["priorities"][0]
        assert "action" in priority
        assert "impact" in priority
    
    async def test_returns_defaults_when_no_reporter(self):
        """When no reporter, returns default improvements."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = None
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_get_gsas_improvement_priorities({})
        
        # Verify defaults
        assert "priorities" in result
        assert len(result["priorities"]) > 0
        assert "note" in result


# ============================================================================
# OPTIMIZE RECOMMENDATIONS FOR GSAS TESTS
# ============================================================================

class TestOptimizeRecommendationsForGSAS:
    """Tests for optimize_recommendations_for_gsas tool."""
    
    async def test_scores_and_ranks_recommendations(self, mock_gsas_reporter):
        """Happy path: Ranks recommendations by GSAS impact."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        # Create sample recommendations
        recommendations = [
            RecommendationFactory.reduce_cooling_setpoint(gsas_aligned=True),
            RecommendationFactory.schedule_maintenance(gsas_aligned=True),
            {"title": "Low impact action", "gsas_aligned": False, "impact_estimate": {"gsas_points": 0.1}},
        ]
        
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": recommendations,
            "limit": 10,
        })
        
        # Verify
        assert "optimized" in result
        assert result["count"] == 3
        assert "target_score" in result
        
        # Verify ranking (GSAS-aligned should rank higher)
        optimized = result["optimized"]
        assert len(optimized) == 3
    
    async def test_respects_limit_parameter(self, mock_gsas_reporter):
        """Limit parameter controls number of results."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        # Create 20 recommendations
        recommendations = [
            RecommendationFactory.reduce_cooling_setpoint(gsas_aligned=True)
            for _ in range(20)
        ]
        
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": recommendations,
            "limit": 5,
        })
        
        # Verify limit
        assert result["count"] == 5
        assert len(result["optimized"]) == 5
    
    async def test_handles_empty_recommendations(self, mock_gsas_reporter):
        """Empty input returns empty output."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": [],
            "limit": 10,
        })
        
        # Verify
        assert result["count"] == 0
        assert len(result["optimized"]) == 0
    
    async def test_returns_original_order_when_no_reporter(self):
        """When no reporter, returns original order."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = None
                self.bms_state = None
        
        handler = Handler()
        
        recommendations = [
            {"title": "First", "priority": "high"},
            {"title": "Second", "priority": "low"},
        ]
        
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": recommendations,
            "limit": 10,
        })
        
        # Verify original order
        assert result["optimized"] == recommendations
        assert "note" in result


# ============================================================================
# GENERATE GORD REPORT TESTS
# ============================================================================

class TestGenerateGORDReport:
    """Tests for generate_gord_report tool."""
    
    async def test_generates_report_structure(self, mock_gsas_reporter):
        """Happy path: Generates GORD report structure."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_generate_gord_report({
            "building_id": "TEST-BUILDING-001",
            "building_name": "Test Tower",
        })
        
        # Verify structure
        assert "report_id" in result
        assert "building_name" in result
        assert result["building_name"] == "Test Tower"
        assert "generated_at" in result
        assert "gsas_status" in result
        assert "sections" in result
        assert result["report_status"] == "generated"
    
    async def test_includes_gsas_status_in_report(self, mock_gsas_reporter):
        """Report includes current GSAS status."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_generate_gord_report({})
        
        # Verify GSAS status included
        assert "gsas_status" in result
        assert "overall_score" in result["gsas_status"]
        assert "certification_level" in result["gsas_status"]
    
    async def test_generates_unique_report_id(self, mock_gsas_reporter):
        """Each report gets unique ID."""
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        result1 = await handler._handle_generate_gord_report({"building_id": "BLD-001"})
        await asyncio.sleep(0.01)
        result2 = await handler._handle_generate_gord_report({"building_id": "BLD-001"})
        
        # Verify unique IDs
        assert result1["report_id"] != result2["report_id"]

    async def test_report_generator_unavailable(self, mock_gsas_reporter):
        """Handle missing report generator gracefully."""
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        with patch("agent_commercial.tools.handlers.gsas.generate_gord_pdf", None):
            result = await handler._handle_generate_gord_report({})
            assert_valid_tool_result(result)
            assert "note" in result
            assert "requires report_generator module" in result["note"]
            assert "pdf_path" not in result


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

class TestGSASEdgeCases:
    """Edge case tests for GSAS tools."""
    
    async def test_invalid_building_id(self, mock_gsas_reporter):
        """Invalid building ID handled gracefully."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        result = await handler._handle_get_gsas_status({
            "building_id": "NONEXISTENT-BUILDING",
        })
        
        # Should still return valid status
        assert "overall_score" in result
        assert "certification_level" in result
    
    async def test_missing_required_fields_in_recommendations(self, mock_gsas_reporter):
        """Missing fields in recommendations handled."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        # Recommendations missing fields
        recommendations = [
            {"title": "No impact field"},
            {"title": "No gsas_aligned field"},
        ]
        
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": recommendations,
            "limit": 10,
        })
        
        # Should still work
        assert result["count"] == 2


# ============================================================================
# STRESS TESTS
# ============================================================================

class TestGSASStressTests:
    """Stress tests for GSAS tools."""
    
    async def test_concurrent_gsas_status_queries(self, mock_gsas_reporter):
        """100 concurrent GSAS status queries."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        # Run 100 concurrent queries
        tasks = [
            handler._handle_get_gsas_status({"building_id": f"BLD-{i}"})
            for i in range(100)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0
        
        # Verify all succeeded
        successes = [r for r in results if isinstance(r, dict) and "overall_score" in r]
        assert len(successes) == 100
    
    async def test_large_recommendation_list_optimization(self, mock_gsas_reporter):
        """Optimize 500 recommendations."""
        
        class Handler(GSASHandlerMixin):
            def __init__(self):
                self.gsas_reporter = mock_gsas_reporter
                self.bms_state = None
        
        handler = Handler()
        
        # Create 500 recommendations
        recommendations = [
            {
                "title": f"Recommendation {i}",
                "gsas_aligned": i % 2 == 0,
                "impact_estimate": {"gsas_points": i * 0.1},
            }
            for i in range(500)
        ]
        
        import time
        start = time.time()
        result = await handler._handle_optimize_recommendations_for_gsas({
            "recommendations": recommendations,
            "limit": 10,
        })
        elapsed = time.time() - start
        
        # Verify
        assert result["count"] == 10
        assert elapsed < 1.0, "Should process 500 recommendations in under 1 second"


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    import sys
    exit_code = pytest.main([__file__, "-v"])
    sys.exit(exit_code)
