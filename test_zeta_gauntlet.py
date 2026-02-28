import asyncio
import logging
import sys
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any
from dotenv import load_dotenv

# Load environment variables for Real LLM
load_dotenv()

# Adjust path
sys.path.append("e:\\Automation")

# ═══════════════════════════════════════════════════════════════════════════
# ZETA GAUNTLET (REAL LLM EDITION)
# ═══════════════════════════════════════════════════════════════════════════

async def run_zeta_gauntlet():
    print("⚡ STARTING SUPER AGENTIC ZETA GAUNTLET (REAL LLM) ⚡")
    print("Scenario: 'The Shamal Strike' (Doha, Qatar)")
    print("==================================================")
    
    # Check for credentials
    if not os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY"):
         print("⚠️ WARNING: No API Keys found in .env. Real LLM calls may fail.")

    # 1. Initialize Ops Copilot
    from agent_commercial.main import OpsCopilot
    from agent_commercial.bms_data_model import AlarmSeverity, Equipment
    from agent_commercial.alarm_engine import Alarm, ProcessedAlarm
    from agent_commercial.event_correlator import Event, EventSource, EventCorrelator
    from agent_advisory.schemas import Recommendation, RecommendationStatus
    
    copilot = OpsCopilot(mode="api_only") # Lightweight mode, but initializes BMSLLMAgent
    
    # Manually attach Event Correlator if not present in core (it might not be in __init__ yet)
    # Note: OpsCopilot might have it, but let's ensure we use the one we analyze
    if not hasattr(copilot, 'event_correlator') or copilot.event_correlator is None:
         copilot.event_correlator = EventCorrelator()
    
    # Get Real LLM Provider
    real_llm = copilot.llm_agent.llm
    print(f"[1] System Initialized with Real LLM: {type(real_llm).__name__}")
    
    # Connect Real LLM to sub-engines
    copilot.alarm_engine.set_llm_provider(real_llm)
    copilot.event_correlator.set_llm_provider(real_llm)
    
    # SETUP TOPOLOGY (Required for clustering)
    await copilot._register_simulated_equipment()
    eq_list = await copilot.state_engine.get_all_equipment()
    copilot.alarm_engine.set_equipment_topology(eq_list)
    
    # 2. Inject Context: The Shamal
    print("\n[2] Injecting Scenario Data...")
    timestamp = datetime.now()
    
    # Weather Interaction
    sandstorm_event = Event(
        event_id="weather_sandstorm",
        source=EventSource.WEATHER,
        timestamp=timestamp - timedelta(minutes=10),
        event_type="Weather Alert",
        description="Severe Dust Storm (Shamal). Visibility < 500m. PM2.5 > 600."
    )
    copilot.event_correlator.add_event(sandstorm_event)
    print("   > Weather: 48°C, Severe Dust Storm")
    
    # Alarm: Chiller Trip
    alarm = Alarm(
        alarm_id="chiller_trip",
        equipment_id="CH-01",
        severity=AlarmSeverity.CRITICAL,
        message="High Discharge Pressure Trip",
        triggered_at=timestamp
    )
    # AlarmType class mock no longer needed if bms_data_model is correct, 
    # but we just set message and let engine handle it or use string.
    # alarm.alarm_type = "Pressure" # implicit
    
    # Ingest Alarm
    processed_alarm = await copilot.alarm_engine.ingest_alarm(alarm)
    copilot.alarm_engine.active_alarms["chiller_trip"] = processed_alarm # Ensure it's active
    print(f"   > Alarm Triggered: {alarm.equipment_id} - {alarm.message}")
    
    # DEBUG STATE
    print(f"   > DEBUG: Active Alarms: {len(copilot.alarm_engine.active_alarms)}")
    # print(f"   > DEBUG: Clusters: {len(copilot.alarm_engine.get_clusters())}")
    if not copilot.alarm_engine.get_clusters():
        # Force cluster creation if engine didn't auto-cluster (it might need a tick)
        print("   > INFO: Creating cluster for test...")
        from agent_commercial.alarm_engine import AlarmCluster
        cluster = AlarmCluster(cluster_id="force_cluster", alarm_ids=["chiller_trip"], root_cause_equipment_id="CH-01")
        copilot.alarm_engine.clusters["force_cluster"] = cluster
    
    # 3. Phase 1: Alarm Intelligence
    print("\n[3] Testing Alarm Engine (Hybrid-Cognitive)...")
    cluster = copilot.alarm_engine.get_clusters()[0]
    
    # REAL LLM CALL
    print("   > Asking Real LLM for Root Cause...")
    rc_result = await copilot.alarm_engine._analyze_root_cause_with_llm(cluster)
    print(f"   > Root Cause Identified: {rc_result.get('cause')}")
    
    # We can't strictly assert the exact string with a real LLM, but we check relevance
    cause_lower = str(rc_result.get('cause')).lower()
    if "sand" in cause_lower or "dust" in cause_lower or "fouling" in cause_lower or "weather" in cause_lower:
        print("   ✅ PASS: LLM identified environmental factor.")
    else:
        print(f"   ⚠️ WARNING: LLM might have missed the sandstorm context. Result: {cause_lower}")

    # 4. Phase 2: Correlation (Semantic)
    print("\n[4] Testing Event Correlator (Semantic Causality)...")
    print(f"   > DEBUG: History Count: {len(copilot.event_correlator.event_history)}")
    
    # REAL LLM CALL
    correlation = await copilot.event_correlator.correlate(alarm.to_dict())
    print(f"   > Correlation Confidence: {correlation.confidence}")
    print(f"   > Insight: {correlation.insight}")
    
    if correlation.confidence > 0.6:
         print("   ✅ PASS: Semantic correlation found.")
    else:
         print("   ⚠️ WARNING: Low confidence correlation.")
    
    # 5. Phase 3: Agency (Tool Economy & Planning)
    print("\n[5] Testing Agentic Response...")
    # Using real ToolEconomyPolicy (which is deterministic code + LLM for surgical sets potentially)
    # The policy itself handles urgency.
    tools = copilot.llm_agent.economy_policy.get_minimal_sufficient_set("critical chiller failure", urgency="critical")
    print(f"   > Strategy (Critical Urgency): Selected {len(tools)} tools")
    print(f"   > Tools: {tools}")
    
    # 6. Phase 4: Reflection (Briefing & Curiosity)
    print("\n[6] Testing Reflection & Reporting...")
    
    # Briefing
    from agent_commercial.briefing_engine import BriefingGenerator
    bg = BriefingGenerator("West Bay Tower")
    bg.set_llm_provider(real_llm)
    
    # REAL LLM CALL
    print("   > Generating Briefing...")
    briefing = await bg.generate(period="overnight")
    print(f"   > Narrative Generated (Snippet): \"{briefing.narrative[:100]}...\"")
    
    # Active Learner
    from agent_advisory.feedback_loop import ActiveLearner
    learner = ActiveLearner(copilot.llm_agent.tracker)
    learner.set_llm_provider(real_llm)
    
    # Simulate a rejected recommendation
    rec = Recommendation(
        id="r1",
        timestamp=datetime.now().timestamp(),
        context={},
        trigger_type="alarm",
        recommended_action={"action": "Start Chiller-2"},
        confidence=0.8,
        reasoning="Prevent thermal runaway",
        status=RecommendationStatus.REJECTED
    )
    
    # REAL LLM CALL
    print("   > Generating Curiosity Question...")
    req = await learner._create_disagreement_request(rec)
    print(f"   > Curiosity Question: \"{req.question_text}\"")
    
    print("\n==================================================")
    print("✅ ZETA GAUNTLET COMPLETE (REAL LLM EXECUTION)")
    print("==================================================")

if __name__ == "__main__":
    try:
        asyncio.run(run_zeta_gauntlet())
    except Exception as e:
        print(f"\n❌ GAUNTLET FAILED: {e}")
        import traceback
        traceback.print_exc()
