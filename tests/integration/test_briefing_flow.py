"""
Integration Test: Briefing Flow
================================
Status: Hardened

Tests BriefingEngine + GoalGenerator integration.
"""

import pytest
from datetime import datetime

from agent_advisory.briefing_scheduler import BriefingScheduler
from agent_advisory.goal_generator import ProactiveGoal
from tests.mocks import MockGoalGenerator


class TestBriefingFlow:
    """Test proactive briefing generation."""
    
    @pytest.fixture
    def goal_generator(self):
        """Mock goal generator."""
        return MockGoalGenerator()
    
    @pytest.fixture
    def briefing_scheduler(self, goal_generator):
        """Real BriefingScheduler."""
        return BriefingScheduler(goal_generator=goal_generator)
    
    @pytest.mark.asyncio
    async def test_morning_briefing_generation(self, briefing_scheduler):
        """Morning briefing should be generated."""
        briefing = await briefing_scheduler.generate_briefing(
            building_id="test-building",
            briefing_type="daily_morning",
        )
        
        assert briefing is not None
        assert "headline" in briefing
    
    @pytest.mark.asyncio
    async def test_briefing_includes_priorities(self, briefing_scheduler, goal_generator):
        """Briefing should include priority goals."""
        # Add goals
        goal = ProactiveGoal(
            goal_id="G1",
            title="Reduce energy waste",
            description="High consumption detected",
            goal_type="efficiency",
            priority="high",
            score=0.9,
            source_engine="energy",
            building_id="test-building",
            equipment_ids=["CH-01"],
            potential_savings_qar=5000.0,
            risk_reduction="None"
        )
        goal_generator.add_goal("test-building", goal)
        
        briefing = await briefing_scheduler.generate_briefing(
            building_id="test-building",
            briefing_type="daily_morning",
        )
        
        # Briefing should reference priorities
        assert briefing is not None
        assert "Reduce energy waste" in briefing["content"]
        assert briefing["goals_count"] == 1


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
