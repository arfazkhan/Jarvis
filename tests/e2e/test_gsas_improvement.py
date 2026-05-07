#!/usr/bin/env python3
"""
E2E Test: GSAS Improvement Workflow
===================================

Scenario: Target 4 stars → recommendations → actions → score improvement.

Full workflow:
1. Building at 3-star rating (72 points)
2. Operator sets target to 4 stars (85 points)
3. System generates prioritized recommendations
4. Operator implements top 3 actions
5. System validates impact
6. Score improves toward target
"""

import pytest
import asyncio

from tests.mocks import (
    MockGSASReporter,
    MockGSASOptimizer,
)
from tests.factories import RecommendationFactory


class TestGSASImprovement:
    """
    Test complete GSAS improvement workflow.
    """
    
    @pytest.fixture
    def gsas_system(self):
        """GSAS system with 3-star building."""
        reporter = MockGSASReporter(
            current_score=72.5,
            target_rating=4,
            category_scores={
                "energy": 70.0,
                "water": 75.0,
                "indoor_environment": 72.0,
            },
        )
        
        optimizer = MockGSASOptimizer(gsas_reporter=reporter)
        
        return reporter, optimizer
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_gsas_target_gap_analysis(self, gsas_system):
        """System should identify gap to target."""
        reporter, optimizer = gsas_system
        
        status = reporter.get_status()
        
        # Current is 3-star
        assert status["current_rating"] == 3
        
        # Target is 4-star
        assert reporter.target_rating() == 4
        
        # Gap should be identified
        gap = optimizer.analyze_gap()
        
        assert gap["current_score"] == 72.5
        assert gap["target_score"] == 85.0
        assert gap["points_needed"] == 12.5
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_prioritized_recommendations_for_gsas(self, gsas_system):
        """Recommendations should be ranked by GSAS impact."""
        reporter, optimizer = gsas_system
        
        # Generate sample recommendations
        recommendations = [
            RecommendationFactory.energy_optimization(confidence=0.85),
            RecommendationFactory.schedule_maintenance(confidence=0.92),
            RecommendationFactory.energy_optimization(
                equipment_id="AHU-01",
                confidence=0.78,
            ),
        ]
        
        # Optimize for GSAS
        optimized = optimizer.optimize_recommendations_for_targets(
            recommendations=recommendations,
            limit=10,
        )
        
        # Should be prioritized
        assert len(optimized["optimized"]) >= 1
        
        # All should have GSAS alignment score
        for rec in optimized["optimized"]:
            assert "gsas_aligned" in rec
            assert rec["gsas_aligned"] is True
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_action_implementation_improves_score(self, gsas_system):
        """Implementing actions should improve GSAS score."""
        reporter, optimizer = gsas_system
        
        # Initial score
        initial = reporter.get_status()
        initial_score = initial["overall_score"]
        
        # Simulate implementing recommendation
        # (In real system, this would update BMS state)
        reporter.simulate_improvement(
            category="energy",
            points_gained=5.0,
        )
        
        # Check new score
        updated = reporter.get_status()
        updated_score = updated["overall_score"]
        
        assert updated_score > initial_score
        assert updated["category_scores"]["energy"] > initial["category_scores"]["energy"]
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_gsas_report_generation(self, gsas_system):
        """System should generate GORD-compliant report."""
        reporter, optimizer = gsas_system
        
        report = await reporter.generate_gord_report(
            building_id="TEST-001",
            building_name="Test Building",
        )
        
        assert report["status"] == "generated"
        assert "report_id" in report
        assert "gsas_status" in report


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
