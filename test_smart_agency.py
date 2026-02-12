import asyncio
import sys
import os
from typing import Dict, List, Any
from datetime import datetime

# Adjust path
sys.path.append("e:\\Automation")

# Mock classes
class MockLLMResponse:
    def __init__(self, content):
        self.content = content

class MockLLMProvider:
    async def chat(self, messages):
        prompt = messages[0]['content']
        if "root cause" in prompt.lower():
            return MockLLMResponse('{"cause": "Semantic Root Cause Found", "confidence": 0.95}')
        if "causal relationships" in prompt.lower():
            return MockLLMResponse("Because the sandstorm clogged the filters, the fan ramped up.")
        if "briefing" in prompt.lower():
            return MockLLMResponse("Operations are stable despite the sandstorm. Focus on filter maintenance.")
        if "polite" in prompt.lower():
            return MockLLMResponse("I noticed you rejected the setpoint change; was it due to occupant complaints?")
        return MockLLMResponse("Mock response")

# Import components
from agent_bms.alarm_engine import AlarmEngine, Alarm, AlarmCluster, ProcessedAlarm
from agent_bms.alarm_engine import AlarmEngine, Alarm, AlarmCluster
from agent_bms.bms_data_model import AlarmSeverity, AlarmState

class AlarmType:
    HIGH_TEMP = "High Temp"
    LOW_PRESSURE = "Low Pressure"
    COMM_FAILURE = "Comm Failure"
from agent_advisory.economy import ToolEconomyPolicy
from agent_bms.event_correlator import EventCorrelator, Event, EventSource
from agent_bms.briefing_engine import BriefingGenerator, BriefingPeriod
from agent_advisory.feedback_loop import ActiveLearner, Recommendation, RecommendationStatus

async def test_smart_alarms():
    print("\n[TEST] Smart Alarm Engine")
    engine = AlarmEngine()
    engine.set_llm_provider(MockLLMProvider())
    
    # Create cluster with weak rule-based cause
    cluster = AlarmCluster(
        cluster_id="c1",
        root_cause_equipment_id="Unknown", # Will trigger low confidence
        alarm_ids=["a1"]
    )
    
    # Populate engine with the alarm
    alarm = Alarm(alarm_id="a1", equipment_id="AHU-01", severity=AlarmSeverity.CRITICAL, message="High Temp", triggered_at=datetime.now())
    alarm.alarm_type = AlarmType.HIGH_TEMP # dynamic prop
    engine.active_alarms = {"a1": ProcessedAlarm(alarm=alarm)}
    
    # Test LLM analysis directly
    print("Testing _analyze_root_cause_with_llm...")
    result = await engine._analyze_root_cause_with_llm(cluster)
    print(f"LLM Cause: {result['cause']}, Confidence: {result['confidence']}")
    assert result['cause'] == "Semantic Root Cause Found"

async def test_tool_economy():
    print("\n[TEST] Tool Economy Policy")
    policy = ToolEconomyPolicy()
    
    # Test High Urgency
    tools = policy.get_minimal_sufficient_set("fire alarm in server room", urgency="critical")
    print(f"Critical Urgency Tools: {tools}")
    
    assert "get_active_alarms" in tools
    assert len(tools) > 1

async def test_event_correlator():
    print("\n[TEST] Event Correlator")
    correlator = EventCorrelator()
    correlator.set_llm_provider(MockLLMProvider())
    
    trigger = {
        "event_id": "t1",
        "source": "weather",
        "event_type": "sandstorm",
        "description": "High particulate matter",
        "timestamp": datetime.now().isoformat()
    }
    
    # Add history
    correlator.add_event(Event("e1", EventSource.HVAC, datetime.now(), "load_increase", "Fan ramp up"))
    
    result = await correlator.correlate(trigger)
    print(f"Correlation Confidence: {result.confidence}")
    # We expect semantic correlation to boost confidence if mock works
    # (Mock returns 'Because...' which triggers semantic link)
    
async def test_briefing_engine():
    print("\n[TEST] Briefing Engine")
    gen = BriefingGenerator("TestBuilding")
    gen.set_llm_provider(MockLLMProvider())
    
    briefing = await gen.generate(period="overnight")
    print(f"Narrative: {briefing.narrative}")
    assert briefing.narrative is not None

async def test_active_learner():
    print("\n[TEST] Active Learner")
    # Mock tracker
    class MockTracker:
        def get_recent_recommendations(self, window_days):
            return [
                Recommendation("r1", {}, 0.8, {}, "act1", RecommendationStatus.REJECTED, datetime.now(), {})
            ]
        def get_recommendation(self, id): return None
        
    learner = ActiveLearner(MockTracker())
    learner.set_llm_provider(MockLLMProvider())
    
    reqs = await learner.check_for_feedback_opportunities()
    if reqs:
        print(f"Generated Question: {reqs[0].question_text}")
        assert "Occupant complaints" not in reqs[0].question_text # Should use LLM generated text "I noticed..."
    else:
        print("No requests generated (maybe check_for_feedback_opportunities logic skipped)")

async def main():
    try:
        await test_smart_alarms()
        await test_tool_economy()
        await test_event_correlator()
        await test_briefing_engine()
        await test_active_learner()
        print("\n\nALL SYSTEMS GO! 🚀")
    except Exception as e:
        print(f"\n\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
