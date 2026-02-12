
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime
from agent_advisory.briefing_scheduler import BriefingScheduler, BriefingType, ProactiveGoal
from agent_advisory.goal_generator import GoalGenerator

class TestBriefingScheduler:
    
    @pytest.fixture
    def mock_goal_generator(self):
        generator = MagicMock(spec=GoalGenerator)
        # Setup mock goals
        g1 = ProactiveGoal(
            goal_id="1", title="Critical Issue", description="Danger",
            goal_type="risk_mitigation", priority="critical", score=0.9,
            source_engine="predictive", building_id="b1", equipment_ids=[],
            potential_savings_qar=10000, risk_reduction="high"
        )
        g2 = ProactiveGoal(
            goal_id="2", title="Save Money", description="Efficiency opp",
            goal_type="efficiency", priority="medium", score=0.6,
            source_engine="energy", building_id="b1", equipment_ids=[],
            potential_savings_qar=5000, risk_reduction="low"
        )
        generator.generate_goals.return_value = [g1, g2]
        return generator

    @pytest.mark.asyncio
    async def test_run_daily_briefing(self, mock_goal_generator):
        scheduler = BriefingScheduler(mock_goal_generator)
        
        # Test daily briefing generation
        await scheduler._run_daily_briefing("b1")
        
        assert len(scheduler.generated_briefings) == 1
        briefing = scheduler.generated_briefings[0]
        assert briefing.briefing_type == BriefingType.DAILY_MORNING
        assert "Focus Actions" in briefing.headline # Headline is summary
        assert "Critical Issue" in briefing.content # Content detailed items
        assert "Save Money" in briefing.content
        assert len(briefing.goals) == 2 # Filtering might limit to top 3, we have 2

    @pytest.mark.asyncio
    async def test_run_urgent_check(self, mock_goal_generator):
        scheduler = BriefingScheduler(mock_goal_generator)
        
        # Test urgent check
        await scheduler._run_urgent_check("b1")
        
        assert len(scheduler.generated_briefings) == 1
        briefing = scheduler.generated_briefings[0]
        assert briefing.briefing_type == BriefingType.URGENT_RISK
        assert "URGENT" in briefing.headline
        assert len(briefing.goals) == 1 # Urgent only contains the critical one

if __name__ == "__main__":
    pytest.main([__file__])
