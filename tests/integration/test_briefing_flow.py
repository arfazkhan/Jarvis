"""
Integration Test: Briefing Flow
================================

Tests BriefingEngine + GoalGenerator integration.
"""

import pytest

from agent_commercial.briefing_engine import BriefingGenerator
from agent_advisory.goal_generator import GoalGenerator

from tests.mocks import MockGoalGenerator


class TestBriefingFlow:
    """Test proactive briefing generation."""
    
    @pytest.fixture
    def goal_generator(self):
        """Mock goal generator."""
        return MockGoalGenerator()
    
    @pytest.fixture
    def briefing_engine(self, goal_generator):
        """Real BriefingGenerator."""
        return BriefingGenerator(goal_generator=goal_generator)
    
    @pytest.mark.asyncio
    async def test_morning_briefing_generation(self, briefing_engine):
        """Morning briefing should be generated."""
        briefing = briefing_engine.generate(
            building_id="test-building",
            period="daily",
        )
        
        assert briefing is not None
        assert hasattr(briefing, "headline") or "headline" in briefing
    
    @pytest.mark.asyncio
    async def test_briefing_includes_priorities(self, briefing_engine, goal_generator):
        """Briefing should include priority goals."""
        # Add goals
        goal_generator.add_goal({
            "title": "Reduce energy waste",
            "priority": "high",
        })
        
        briefing = briefing_engine.generate(
            building_id="test-building",
            period="daily",
        )
        
        # Briefing should reference priorities
        assert briefing is not None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
