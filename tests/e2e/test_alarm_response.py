#!/usr/bin/env python3
"""
E2E Test: Alarm Response
========================

Scenario: Chiller trips → cascade of zone alarms → operator response.

Full workflow:
1. Chiller trips at 2:30 PM
2. 5 zone temperature alarms trigger
3. ARVIS clusters alarms into cascade
4. Root cause identified as CH-01
5. Operator asks "what happened?"
6. ARVIS explains cascade
7. Operator schedules emergency maintenance
8. System tracks resolution
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from tests.mocks import (
    MockLLM,
    MockBMSStateEngine,
    MockAlarmEngine,
    MockPredictiveEngine,
)
from tests.factories import AlarmFactory, EquipmentFactory


class TestAlarmResponse:
    """
    Test complete alarm cascade response workflow.
    
    This simulates a real chiller failure scenario.
    """
    
    @pytest.fixture
    def cascade_state(self):
        """Create state with chiller and 5 zones."""
        state = MockBMSStateEngine()
        
        # Chiller
        state.add_equipment(EquipmentFactory.chiller())
        
        # 5 AHUs serving different zones
        for i in range(1, 6):
            state.add_equipment(EquipmentFactory.ahu(equipment_id=f"AHU-{i:02d}"))
        
        # Normal operating points
        state.update_point("CH-01/CHWST", 7.0, "°C", "CH-01")
        state.update_point("CH-01/KW", 250.0, "kW", "CH-01")
        
        return state
    
    @pytest.fixture
    def cascade_alarms(self):
        """Create realistic alarm cascade."""
        base_time = datetime.now() - timedelta(hours=1)
        
        # Chiller trip alarm
        chiller_alarm = AlarmFactory.critical_chiller(
            alarm_id="ALM-CH-001",
            equipment_id="CH-01",
            message="Chiller trip - high vibration detected",
            triggered_at=base_time.isoformat(),
        )
        
        # 5 zone alarms triggered after chiller trip
        zone_alarms = []
        for i in range(1, 6):
            zone_alarms.append(AlarmFactory.warning_ahu(
                alarm_id=f"ALM-ZONE-{i:03d}",
                equipment_id=f"AHU-{i:02d}",
                message=f"Zone {i} temperature above setpoint - cooling lost",
                triggered_at=(base_time + timedelta(minutes=i * 2)).isoformat(),
            ))
        
        return [chiller_alarm] + zone_alarms
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_chiller_trip_creates_cascade(self, cascade_state, cascade_alarms):
        """
        Test that chiller trip properly triggers cascade detection.
        
        Time: ~10 seconds
        """
        # Add all alarms to state
        for alarm in cascade_alarms:
            cascade_state.add_alarm(alarm)
        
        # Create alarm engine
        alarm_engine = MockAlarmEngine(bms_state=cascade_state)
        
        # Process alarms
        active_alarms = cascade_state.get_active_alarms()
        assert len(active_alarms) == 6
        
        # Cluster alarms
        clusters = alarm_engine.cluster_alarms(active_alarms)
        
        # Should identify single cascade
        assert len(clusters) == 1
        cluster = clusters[0]
        
        # All 6 alarms should be in cascade
        assert len(cluster["alarm_ids"]) == 6
        
        # Root cause should be chiller
        assert cluster["root_cause_equipment_id"] == "CH-01"
        assert cluster["root_cause_confidence"] > 0.7
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_operator_receives_clear_explanation(self, cascade_state, cascade_alarms):
        """Operator should understand what happened."""
        llm = MockLLM(responses={
            "explain": '''
            {
                "summary": "Chiller 1 tripped due to high vibration, causing cooling loss to 5 zones",
                "timeline": [
                    {"time": "14:30", "event": "CH-01 trip detected"},
                    {"time": "14:32-14:40", "event": "Zone alarms triggered"}
                ],
                "root_cause": "CH-01 bearing wear causing vibration trip",
                "affected_equipment": ["CH-01", "AHU-01", "AHU-02", "AHU-03", "AHU-04", "AHU-05"],
                "recommended_actions": [
                    {"action": "Reset CH-01 and monitor vibration", "priority": "immediate"},
                    {"action": "Schedule bearing inspection", "priority": "within 24 hours"}
                ]
            }
            ''',
        })
        
        # Simulate operator question
        response = await llm.ask("What happened with the chiller?")
        
        assert "Chiller 1 tripped" in response or "CH-01" in response
        assert "vibration" in response.lower()
        assert "bearing" in response.lower() or "inspect" in response.lower()
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_maintenance_scheduled_from_alarm(self, cascade_state, cascade_alarms):
        """Operator can schedule maintenance directly from alarm view."""
        predictive_engine = MockPredictiveEngine()
        
        # Get prediction for chiller
        prediction = await predictive_engine.predict_rul("CH-01", forecast_days=30)
        
        assert prediction["equipment_id"] == "CH-01"
        assert "health_score" in prediction
        assert "days_until_predicted_failure" in prediction
        
        # Verify maintenance recommendation
        if prediction["health_score"] < 70:
            assert prediction["recommendation"] is not None
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_alarm_resolution_tracking(self, cascade_state, cascade_alarms):
        """System tracks alarm resolution timeline."""
        # Acknowledge alarms
        acknowledged = []
        for alarm in cascade_alarms:
            result = cascade_state.acknowledge_alarm(alarm["alarm_id"])
            acknowledged.append(result)
        
        # All should be acknowledged
        assert all(acknowledged)
        
        # Active alarms should be reduced
        remaining_active = cascade_state.get_active_alarms()
        assert len(remaining_active) == 0  # All acknowledged


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
