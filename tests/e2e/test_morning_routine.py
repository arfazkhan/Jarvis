#!/usr/bin/env python3
"""
E2E Test: Morning Routine
========================

Scenario: Operator logs in at 7am and checks the building status.

Full workflow:
1. System generates morning briefing at 7:00 AM
2. Operator asks "What should I focus on today?"
3. ARVIS provides prioritized recommendations
4. Operator asks about overnight anomalies
5. ARVIS explains what happened
6. Operator acknowledges critical items
7. System records feedback and updates trust metrics
"""

import pytest
import asyncio
from datetime import datetime, time

from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockBACnetAdapter,
    MockEnergyAnalyzer,
    MockGSASReporter,
    MockBriefingScheduler,
    MockGoalGenerator,
    MockFeedbackLoop,
)
from tests.factories import (
    EquipmentFactory,
    AlarmFactory,
    DataPointFactory,
    EnergyReadingFactory,
)


class TestMorningRoutine:
    """
    Complete morning routine workflow test.
    
    This tests the entire operator experience from login to action.
    """
    
    @pytest.fixture
    def morning_state(self):
        """Create realistic morning building state."""
        state = MockBMSStateEngine()
        
        # Add equipment
        state.add_equipment(EquipmentFactory.chiller())
        state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-01"))
        state.add_equipment(EquipmentFactory.ahu(equipment_id="AHU-02"))
        state.add_equipment(EquipmentFactory.meter())
        
        # Simulate overnight data
        state.update_point("CH-01/CHWST", 7.2, "°C", "CH-01")  # Slightly elevated
        state.update_point("CH-01/KW", 265.0, "kW", "CH-01")    # Higher than normal
        state.update_point("AHU-01/SAT", 14.5, "°C", "AHU-01")
        state.update_point("AHU-02/SAT", 15.1, "°C", "AHU-02")  # Slightly high
        state.update_point("METER-01/KW", 485.0, "kW", "METER-01")  # Elevated overnight
        
        # Add overnight alarm
        state.add_alarm(AlarmFactory.warning_ahu(
            equipment_id="AHU-02",
            message="Supply air temperature slightly elevated",
            triggered_at="2024-01-15T03:22:00",
        ))
        
        return state
    
    @pytest.fixture
    def morning_llm(self):
        """LLM configured for morning routine responses."""
        return MockLLM(responses={
            "briefing": '''
            {
                "headline": "3 items need your attention",
                "critical_items": [
                    {"item": "AHU-02 supply temp elevated overnight", "priority": "medium"},
                    {"item": "Chiller power consumption +6% above baseline", "priority": "high"}
                ],
                "overnight_anomalies": [
                    {"equipment": "AHU-02", "issue": "Elevated supply temp 03:22-05:45"}
                ],
                "recommendations": [
                    {"action": "Inspect AHU-02 coil cleanliness", "confidence": 0.82},
                    {"action": "Review chiller sequencing logic", "confidence": 0.75}
                ]
            }
            ''',
            "focus": '''
            {
                "top_priorities": [
                    {"priority": 1, "item": "AHU-02 coil inspection", "reason": "Overnight temp anomaly"},
                    {"priority": 2, "item": "Chiller power review", "reason": "Energy waste detected"}
                ]
            }
            ''',
            "anomaly": '''
            {
                "explanation": "AHU-02 supply temperature ran 0.6°C above setpoint from 3:22 AM to 5:45 AM. Likely cause: coil fouling reducing heat transfer efficiency.",
                "root_cause": "Probable coil fouling",
                "recommendation": "Schedule coil cleaning within 7 days"
            }
            ''',
        })
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_complete_morning_routine(self, morning_state, morning_llm):
        """
        Test full morning routine from 7am login to action.
        
        Time: ~30 seconds (simulates 15-minute operator session)
        """
        # 1. System generates morning briefing
        briefing_scheduler = MockBriefingScheduler(bms_state=morning_state)
        briefing = await briefing_scheduler.generate_briefing(
            briefing_type="daily_morning"
        )
        
        assert briefing["headline"] is not None
        assert len(briefing["recommendations"]) >= 2
        
        # 2. Operator asks "What should I focus on today?"
        goal_generator = MockGoalGenerator(bms_state=morning_state)
        goals = goal_generator.get_active_goals()
        
        assert len(goals) >= 1
        assert any("AHU-02" in str(g) for g in goals)
        
        # 3. Operator investigates overnight anomaly
        # (Simulated: operator clicks on AHU-02 alert)
        equipment_status = morning_state.get_equipment("AHU-02")
        points = morning_state.get_points_by_equipment("AHU-02")
        
        assert equipment_status is not None
        assert len(points) > 0
        
        # 4. System provides explanation
        response = await morning_llm.ask("What happened with AHU-02 overnight?")
        
        assert "coil" in response.lower()
        assert "fouling" in response.lower() or "cleaning" in response.lower()
        
        # 5. Operator acknowledges and takes action
        feedback_loop = MockFeedbackLoop()
        result = await feedback_loop.submit_feedback(
            feedback_type="acknowledgment",
            target="AHU-02-anomaly",
            content="Will schedule coil cleaning",
        )
        
        assert result["status"] == "recorded"
        
        # 6. Verify trust metrics updated
        trust_metrics = feedback_loop.get_trust_metrics()
        
        assert trust_metrics["interactions_today"] >= 1
        assert trust_metrics["last_interaction_type"] == "acknowledgment"
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_briefing_includes_gsas_context(self, morning_state, morning_llm):
        """Morning briefing should include GSAS compliance status."""
        gsas_reporter = MockGSASReporter(
            current_score=72.5,
            target_rating=4,
        )
        
        briefing_scheduler = MockBriefingScheduler(
            bms_state=morning_state,
            gsas_reporter=gsas_reporter,
        )
        
        briefing = await briefing_scheduler.generate_briefing(
            briefing_type="daily_morning",
            focus_area="compliance",
        )
        
        # Briefing should mention GSAS status
        assert "gsas" in str(briefing).lower() or "compliance" in str(briefing).lower()
        assert briefing.get("gsas_score") == 72.5 or briefing.get("current_gsas_score") == 72.5
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_operator_can_filter_by_priority(self, morning_state):
        """Operator can filter recommendations by priority."""
        goal_generator = MockGoalGenerator(bms_state=morning_state)
        
        # Get high priority only
        high_goals = goal_generator.get_active_goals(category="risk")
        
        # Get all goals
        all_goals = goal_generator.get_active_goals()
        
        # High priority should be subset
        assert len(high_goals) <= len(all_goals)
        assert all(g.get("priority") in ["high", "critical"] for g in high_goals)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
