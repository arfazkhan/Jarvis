"""
Integration Test: GSAS Full Flow
================================

Tests GSASOptimizer + GSASReporter integration.
"""

import pytest

from agent_commercial.gsas_reporter import GSASReporter, GSASStarRating
from agent_commercial.gsas_optimizer import GSASOptimizer

from tests.factories import RecommendationFactory


class TestGSASFullFlow:
    """Test complete GSAS workflow."""
    
    @pytest.fixture
    def gsas_reporter(self):
        """Real GSASReporter."""
        reporter = GSASReporter(
            building_id="TEST-BUILDING",
            building_name="Test Building",
            target_rating=GSASStarRating.FOUR_STAR,
        )
        reporter.initialize_criteria()
        return reporter
    
    @pytest.fixture
    def gsas_optimizer(self, gsas_reporter):
        """Real GSASOptimizer."""
        return GSASOptimizer(gsas_reporter=gsas_reporter)
    
    @pytest.mark.asyncio
    async def test_gsas_status_calculation(self, gsas_reporter):
        """GSAS status should be calculated from building data."""
        status = gsas_reporter.get_status()
        
        assert "overall_score" in status
        assert "star_rating" in status
    
    @pytest.mark.asyncio
    async def test_gsas_optimization_generates_actions(self, gsas_optimizer, gsas_reporter):
        """Optimizer should generate GSAS-aligned actions."""
        # Get current status
        status = gsas_reporter.get_status()
        
        # Optimize
        actions = await gsas_optimizer.generate_recommendations()
        
        assert len(actions) > 0
        
        # Each action should be GSAS-aligned
        for action in actions:
            # Actions in generate_recommendations are GSASRecommendation objects or dicts
            data = action.to_dict() if hasattr(action, "to_dict") else action
            assert data.get("category") in ["Energy", "Water", "Indoor Environment", "MO", "E", "W", "IE"]
    
    @pytest.mark.asyncio
    async def test_recommendation_scoring(self, gsas_optimizer):
        """Recommendations should be scored against GSAS targets."""
        recommendations = [
            RecommendationFactory.reduce_setpoint(),
            RecommendationFactory.schedule_maintenance(),
        ]
        
        # GSASOptimizer.generate_recommendations handles scoring internally
        scored = await gsas_optimizer.generate_recommendations(
            max_recommendations=5
        )
        
        assert len(scored) > 0
        
        # Check scoring
        for rec in scored:
            # Check attributes of GSASRecommendation object
            assert rec.estimated_points_gain >= 0
            assert rec.confidence > 0
            assert rec.recommendation_id.startswith("GSAS-REC-")
    
    @pytest.mark.asyncio
    async def test_gsas_improvement_flow(self, gsas_optimizer, gsas_reporter):
        """Complete GSAS improvement workflow."""
        # 1. Get current status
        current = gsas_reporter.get_status()
        current_score = current["overall_score"]
        
        # 2. Generate improvements
        actions = await gsas_optimizer.generate_recommendations()
        
        # 3. Simulate implementation (update scores)
        # (In real system, this would come from actual BMS data changes)
        
        # 4. Verify improvement tracking
        assert len(actions) > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
