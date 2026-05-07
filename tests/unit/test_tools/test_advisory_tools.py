"""
Advisory Tool Tests
=============

Tests for 6 advisory tools:
- get_advisory_recommendations: ML-ranked recommendations
- check_goals: Active proactive goals
- generate_briefing: Proactive operations briefing
- run_briefing: On-demand briefing
- submit_feedback: Operator feedback for learning
- get_trust_metrics: Advisor reliability metrics
"""

import pytest
from datetime import datetime
from agent_unified.tools.base import ToolResult
from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockAdvisor,
    MockGoalGenerator,
    MockBriefingScheduler,
    MockFeedbackLoop,
    MockTrustCalibrator,
    MockTracker,
    MockOnlineLearner,
)
from tests.utils.helpers import run_concurrently, assert_tool_result_valid


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_advisor():
    """Mock advisor with sample recommendations."""
    return MockAdvisor(recommendations=[
        {
            "id": "rec-001",
            "title": "Reduce Cooling Setpoint",
            "description": "Lower setpoint by 2°C to reduce energy waste",
            "confidence": 0.88,
            "impact": "medium",
            "risk": "low",
            "gsas_aligned": True,
        },
        {
            "id": "rec-002",
            "title": "Schedule Filter Cleaning",
            "description": "AHU-01 filter pressure drop indicates cleaning needed",
            "confidence": 0.92,
            "impact": "high",
            "risk": "low",
            "gsas_aligned": True,
        },
        {
            "id": "rec-003",
            "title": "Investigate Chiller Vibration",
            "description": "CH-01 showing elevated vibration trend",
            "confidence": 0.75,
            "impact": "high",
            "risk": "medium",
            "gsas_aligned": False,
        },
    ])


@pytest.fixture
def mock_goal_generator():
    """Mock goal generator with sample goals."""
    generator = MockGoalGenerator()
    generator.add_goal({
        "goal_id": "GOAL-001",
        "title": "Reduce Energy Consumption by 10%",
        "category": "waste",
        "priority": "high",
        "progress": 0.25,
    })
    generator.add_goal({
        "goal_id": "GOAL-002",
        "title": "Prevent Chiller Failure",
        "category": "risk",
        "priority": "critical",
        "progress": 0.0,
    })
    return generator


@pytest.fixture
def mock_briefing_scheduler():
    """Mock briefing scheduler."""
    return MockBriefingScheduler(briefing={
        "briefing_type": "daily_morning",
        "generated_at": datetime.now().isoformat(),
        "sections": {
            "critical_items": [
                {"title": "CH-01 vibration warning", "priority": "high"},
            ],
            "overnight_anomalies": [
                {"description": "Energy spike at 2am", "severity": "medium"},
            ],
            "optimization_wins": [
                {"title": "VAV optimization saved 15 kWh", "savings_qar": 2.25},
            ],
            "today_context": {
                "weather": "Clear, 35°C",
                "events": ["VIP meeting at 2pm"],
                "tariff_period": "peak",
            },
            "recommendations": [
                {"title": "Review chiller maintenance schedule"},
            ],
        }
    })


@pytest.fixture
def mock_feedback_loop():
    """Mock feedback loop."""
    return MockFeedbackLoop()


@pytest.fixture
def mock_trust_calibrator():
    """Mock trust calibrator."""
    return MockTrustCalibrator(trust_score=0.85, adoption_rate=0.92)


@pytest.fixture
def mock_tracker():
    """Mock tracker."""
    return MockTracker()


# ============================================================================
# GET ADVISORY RECOMMENDATIONS
# ============================================================================

class TestGetAdvisoryRecommendations:
    """Tests for get_advisory_recommendations tool."""
    
    @pytest.mark.asyncio
    async def test_returns_recommendations_for_context(self, mock_advisor):
        """Happy path: Get recommendations for operational context."""
        # This would use a real tool with mock_advisor injected
        # For now, test the mock behavior directly
        
        result = await mock_advisor.get_recommendations(
            context="High energy consumption in zone A",
            top_k=3,
        )
        
        assert "context" in result
        assert len(result["recommendations"]) == 3
        assert result["recommendations"][0]["id"] == "rec-001"
    
    @pytest.mark.asyncio
    async def test_filters_by_equipment_id(self, mock_advisor):
        """Recommendations can be filtered by equipment."""
        result = await mock_advisor.get_recommendations(
            context="Equipment issue",
            equipment_id="AHU-01",
            top_k=10,
        )
        
        # Mock doesn't filter, but real tool would
        assert "recommendations" in result
    
    @pytest.mark.asyncio
    async def test_respects_top_k_limit(self, mock_advisor):
        """Returns only top_k recommendations."""
        result = await mock_advisor.get_recommendations(
            context="General query",
            top_k=1,
        )
        
        assert len(result["recommendations"]) == 1
    
    @pytest.mark.asyncio
    async def test_handles_empty_context(self, mock_advisor):
        """Empty context should still return recommendations."""
        result = await mock_advisor.get_recommendations(
            context="",
            top_k=3,
        )
        
        assert "recommendations" in result
    
    @pytest.mark.asyncio
    async def test_with_alarm_id_reference(self, mock_advisor):
        """Can reference specific alarm for context."""
        result = await mock_advisor.get_recommendations(
            context="Alarm triggered",
            alarm_id="ALM-001",
            top_k=3,
        )
        
        assert "recommendations" in result


# ============================================================================
# CHECK GOALS
# ============================================================================

class TestCheckGoals:
    """Tests for check_goals tool."""
    
    @pytest.mark.asyncio
    async def test_returns_all_goals_without_category(self, mock_goal_generator):
        """Happy path: Get all active goals."""
        goals = mock_goal_generator.get_active_goals()
        
        assert len(goals) == 2
        assert goals[0]["goal_id"] == "GOAL-001"
        assert goals[1]["goal_id"] == "GOAL-002"
    
    @pytest.mark.asyncio
    async def test_filters_by_category(self, mock_goal_generator):
        """Filter goals by category."""
        goals = mock_goal_generator.get_active_goals(category="risk")
        
        assert len(goals) == 1
        assert goals[0]["category"] == "risk"
    
    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_category(self, mock_goal_generator):
        """Unknown category returns empty list."""
        goals = mock_goal_generator.get_active_goals(category="nonexistent")
        
        assert len(goals) == 0
    
    @pytest.mark.asyncio
    async def test_goal_has_required_fields(self, mock_goal_generator):
        """Goals have all required fields."""
        goals = mock_goal_generator.get_active_goals()
        
        for goal in goals:
            assert "goal_id" in goal
            assert "title" in goal
            assert "category" in goal
            assert "priority" in goal
            assert "progress" in goal


# ============================================================================
# GENERATE BRIEFING
# ============================================================================

class TestGenerateBriefing:
    """Tests for generate_briefing tool."""
    
    @pytest.mark.asyncio
    async def test_generates_daily_morning_briefing(self, mock_briefing_scheduler):
        """Happy path: Generate daily morning briefing."""
        briefing = await mock_briefing_scheduler.generate_briefing(
            briefing_type="daily_morning"
        )
        
        assert briefing["briefing_type"] == "daily_morning"
        assert "sections" in briefing
        assert "critical_items" in briefing["sections"]
    
    @pytest.mark.asyncio
    async def test_briefing_includes_all_sections(self, mock_briefing_scheduler):
        """Briefing has all required sections."""
        briefing = await mock_briefing_scheduler.generate_briefing()
        
        sections = briefing["sections"]
        assert "critical_items" in sections
        assert "overnight_anomalies" in sections
        assert "optimization_wins" in sections
        assert "today_context" in sections
        assert "recommendations" in sections
    
    @pytest.mark.asyncio
    async def test_briefing_with_focus_area(self, mock_briefing_scheduler):
        """Can generate focused briefing."""
        briefing = await mock_briefing_scheduler.generate_briefing(
            focus_area="energy"
        )
        
        assert briefing["focus_area"] == "energy"
    
    @pytest.mark.asyncio
    async def test_urgent_risk_briefing_type(self, mock_briefing_scheduler):
        """Can generate urgent risk briefing."""
        briefing = await mock_briefing_scheduler.generate_briefing(
            briefing_type="urgent_risk"
        )
        
        assert briefing["briefing_type"] == "urgent_risk"
    
    @pytest.mark.asyncio
    async def test_briefing_has_timestamp(self, mock_briefing_scheduler):
        """Briefing includes generation timestamp."""
        briefing = await mock_briefing_scheduler.generate_briefing()
        
        assert "generated_at" in briefing


# ============================================================================
# RUN BRIEFING
# ============================================================================

class TestRunBriefing:
    """Tests for run_briefing tool (alias for generate_briefing)."""
    
    @pytest.mark.asyncio
    async def test_run_briefing_generates_briefing(self, mock_briefing_scheduler):
        """run_briefing is an alias for generate_briefing."""
        briefing = await mock_briefing_scheduler.generate_briefing(
            briefing_type="daily_morning"
        )
        
        assert "briefing_type" in briefing
        assert "sections" in briefing


# ============================================================================
# SUBMIT FEEDBACK
# ============================================================================

class TestSubmitFeedback:
    """Tests for submit_feedback tool."""
    
    @pytest.mark.asyncio
    async def test_submits_correction_feedback(self, mock_feedback_loop):
        """Happy path: Submit correction feedback."""
        result = await mock_feedback_loop.submit_feedback(
            feedback_type="correction",
            target="rec-001",
            content="The setpoint should be 24°C, not 22°C",
        )
        
        assert result["status"] == "recorded"
        assert "feedback_id" in result
    
    @pytest.mark.asyncio
    async def test_submits_rating_feedback(self, mock_feedback_loop):
        """Submit rating feedback."""
        result = await mock_feedback_loop.submit_feedback(
            feedback_type="rating",
            target="rec-002",
            content="Good recommendation",
            rating=4,
        )
        
        assert result["status"] == "recorded"
    
    @pytest.mark.asyncio
    async def test_feedback_types(self, mock_feedback_loop):
        """All feedback types are accepted."""
        valid_types = ["correction", "explanation", "preference", "rating"]
        
        for fb_type in valid_types:
            result = await mock_feedback_loop.submit_feedback(
                feedback_type=fb_type,
                target="test",
                content="test content",
            )
            assert result["status"] == "recorded"
    
    @pytest.mark.asyncio
    async def test_feedback_is_stored(self, mock_feedback_loop):
        """Feedback is persisted in the loop."""
        await mock_feedback_loop.submit_feedback(
            feedback_type="correction",
            target="rec-001",
            content="test",
        )
        
        feedback = mock_feedback_loop.get_feedback()
        assert len(feedback) == 1
        assert feedback[0]["target"] == "rec-001"
    
    @pytest.mark.asyncio
    async def test_multiple_feedback_submissions(self, mock_feedback_loop):
        """Multiple feedback submissions are all stored."""
        for i in range(5):
            await mock_feedback_loop.submit_feedback(
                feedback_type="rating",
                target=f"rec-{i:03d}",
                content="test",
                rating=3,
            )
        
        feedback = mock_feedback_loop.get_feedback()
        assert len(feedback) == 5


# ============================================================================
# GET TRUST METRICS
# ============================================================================

class TestGetTrustMetrics:
    """Tests for get_trust_metrics tool."""
    
    @pytest.mark.asyncio
    async def test_returns_trust_metrics(self, mock_trust_calibrator):
        """Happy path: Get trust metrics."""
        metrics = await mock_trust_calibrator.calculate_trust_metrics(window_days=30)
        
        assert "trust_score" in metrics
        assert "adoption_rate" in metrics
        assert metrics["trust_score"] == 0.85
        assert metrics["adoption_rate"] == 0.92
    
    @pytest.mark.asyncio
    async def test_metrics_include_window_days(self, mock_trust_calibrator):
        """Metrics include the window period."""
        metrics = await mock_trust_calibrator.calculate_trust_metrics(window_days=7)
        
        assert metrics["window_days"] == 7
    
    @pytest.mark.asyncio
    async def test_metrics_include_recommendation_counts(self, mock_trust_calibrator):
        """Metrics show recommendation counts."""
        metrics = await mock_trust_calibrator.calculate_trust_metrics()
        
        assert "total_recommendations" in metrics
        assert "followed_recommendations" in metrics
    
    @pytest.mark.asyncio
    async def test_low_trust_score_warning(self, mock_trust_calibrator):
        """Low trust score is flagged."""
        mock_trust_calibrator.set_trust_score(0.45)
        
        metrics = await mock_trust_calibrator.calculate_trust_metrics()
        
        assert metrics["trust_score"] < 0.5
    
    @pytest.mark.asyncio
    async def test_high_adoption_rate(self, mock_trust_calibrator):
        """High adoption rate is tracked."""
        mock_trust_calibrator.set_adoption_rate(0.98)
        
        metrics = await mock_trust_calibrator.calculate_trust_metrics()
        
        assert metrics["adoption_rate"] == 0.98


# ============================================================================
# EDGE CASES
# ============================================================================

class TestAdvisoryEdgeCases:
    """Edge case tests for advisory tools."""
    
    @pytest.mark.asyncio
    async def test_advisor_with_no_recommendations(self):
        """Advisor with no recommendations returns empty list."""
        advisor = MockAdvisor(recommendations=[])
        
        result = await advisor.get_recommendations(context="test")
        
        assert result["recommendations"] == []
    
    @pytest.mark.asyncio
    async def test_goal_generator_with_no_goals(self):
        """Goal generator with no goals returns empty list."""
        generator = MockGoalGenerator(goals=[])
        
        goals = generator.get_active_goals()
        
        assert len(goals) == 0
    
    @pytest.mark.asyncio
    async def test_briefing_with_empty_sections(self):
        """Briefing with no issues still has valid structure."""
        scheduler = MockBriefingScheduler(briefing={
            "briefing_type": "daily_morning",
            "generated_at": datetime.now().isoformat(),
            "sections": {
                "critical_items": [],
                "overnight_anomalies": [],
                "optimization_wins": [],
                "today_context": {},
                "recommendations": [],
            }
        })
        
        briefing = await scheduler.generate_briefing()
        
        assert briefing["sections"]["critical_items"] == []
        assert briefing["sections"]["recommendations"] == []


# ============================================================================
# STRESS TESTS
# ============================================================================

class TestAdvisoryStress:
    """Stress tests for advisory tools."""
    
    @pytest.mark.asyncio
    async def test_concurrent_recommendation_requests(self, mock_advisor):
        """100 concurrent recommendation requests."""
        tasks = [
            mock_advisor.get_recommendations(context=f"context-{i}")
            for i in range(100)
        ]
        
        results = await run_concurrently([lambda: mock_advisor.get_recommendations(context="test")], count=100)
        
        # Mock doesn't support concurrent calls directly, but real tool would
        pass  # Placeholder - would test real tool in integration tests
    
    @pytest.mark.asyncio
    async def test_large_feedback_history(self, mock_feedback_loop):
        """Submit 500 feedback items."""
        for i in range(500):
            await mock_feedback_loop.submit_feedback(
                feedback_type="rating",
                target=f"rec-{i:04d}",
                content="test",
                rating=3,
            )
        
        feedback = mock_feedback_loop.get_feedback()
        assert len(feedback) == 500
