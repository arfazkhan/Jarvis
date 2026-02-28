import asyncio
import os
import sys
import time
from dotenv import load_dotenv

# Adjust path
sys.path.append("e:\\Automation")

# Load environment
load_dotenv()

async def run_benchmark():
    print("📊 NVIDIA MODEL PERFORMANCE BENCHMARK")
    print("====================================")
    
    models = [
        "stepfun-ai/step-3.5-flash",
        "z-ai/glm4.7"
    ]
    
    results = []

    # Initialize Copilot ONCE to get the framework, 
    # but we will patch the LLM provider for each run if needed, 
    # or rely on UnifiedLLM reading env var dynamically.
    
    # UnifiedLLM._ask_nvidia reads os.getenv("NVIDIA_MODEL") on every call, 
    # so we just need to change the env var.
    
    from agent_commercial.main import OpsCopilot
    from agent_commercial.event_correlator import Event, EventSource
    from agent_commercial.alarm_engine import Alarm, AlarmSeverity
    from datetime import datetime, timedelta

    # Setup Scenario Data (Same for all)
    timestamp = datetime.now()
    sandstorm_event = Event(
        event_id="weather_sandstorm",
        source=EventSource.WEATHER,
        timestamp=timestamp - timedelta(minutes=10),
        event_type="Weather Alert",
        description="Severe Dust Storm (Shamal). Visibility < 500m. PM2.5 > 600."
    )
    alarm = Alarm(
        alarm_id="chiller_trip",
        equipment_id="CH-01",
        severity=AlarmSeverity.CRITICAL,
        message="High Discharge Pressure Trip",
        triggered_at=timestamp
    )
    
    # Initialize System
    print("→ Initializing ARVIS Core...")
    copilot = OpsCopilot(mode="api_only")
    if not hasattr(copilot, 'event_correlator') or copilot.event_correlator is None:
        from agent_commercial.event_correlator import EventCorrelator
        copilot.event_correlator = EventCorrelator()
        
    # Pre-inject data
    copilot.event_correlator.add_event(sandstorm_event)
    await copilot.alarm_engine.ingest_alarm(alarm)
    
    # Force cluster
    from agent_commercial.alarm_engine import AlarmCluster
    cluster = AlarmCluster(cluster_id="bench_cluster", alarm_ids=["chiller_trip"], root_cause_equipment_id="CH-01")
    copilot.alarm_engine.clusters["bench_cluster"] = cluster
    
    # Ensure provider is nvidia
    os.environ["LLM_PROVIDER"] = "nvidia" 
    
    for model in models:
        print(f"\n🧪 Testing Model: {model}")
        os.environ["NVIDIA_MODEL"] = model
        
        # Handle Thinking Mode (GLM needs specific dict, StepFun doesn't)
        if "glm" in model:
             os.environ["NVIDIA_THINKING"] = "true"
        else:
             os.environ["NVIDIA_THINKING"] = "false"
             
        # Metric: Root Cause Analysis
        print("   Running Root Cause Analysis...")
        start_time = time.time()
        try:
            # We call the internal method that uses LLM
            # Mocking the cluster analysis call
            prompt = copilot.alarm_engine._construct_root_cause_prompt(cluster, [alarm], [sandstorm_event])
            analyze_msg = [{"role": "system", "content": "You are a BMS Expert."}, {"role": "user", "content": prompt}]
            
            response_rca = await copilot.llm_agent.llm.ask(analyze_msg)
            rca_time = time.time() - start_time
            rca_len = len(response_rca.content)
            print(f"   ✓ RCA Done in {rca_time:.2f}s (Len: {rca_len})")
        except Exception as e:
            print(f"   ❌ RCA Failed: {e}")
            rca_time = 0
            rca_len = 0
            
        # Metric: Briefing Generation
        print("   Running Briefing Generation...")
        start_time = time.time()
        try:
            # Mock briefing call
            briefing_prompt = f"Write a daily briefing for the facility manager about: {sandstorm_event.description} and {alarm.message}."
            briefing_msg = [{"role": "system", "content": "You are an Executive Assistant."}, {"role": "user", "content": briefing_prompt}]
            
            response_briefing = await copilot.llm_agent.llm.ask(briefing_msg)
            briefing_time = time.time() - start_time
            briefing_len = len(response_briefing.content)
            print(f"   ✓ Briefing Done in {briefing_time:.2f}s (Len: {briefing_len})")
        except Exception as e:
            print(f"   ❌ Briefing Failed: {e}")
            briefing_time = 0
            briefing_len = 0
            
        results.append({
            "model": model,
            "rca_time": rca_time,
            "briefing_time": briefing_time,
            "total_time": rca_time + briefing_time,
            "total_chars": rca_len + briefing_len
        })
        
    print("\n🏆 BENCHMARK RESULTS 🏆")
    print(f"{'Model':<30} | {'RCA (s)':<10} | {'Brief (s)':<10} | {'Total (s)':<10} | {'Chars':<10}")
    print("-" * 85)
    for r in results:
        print(f"{r['model']:<30} | {r['rca_time']:<10.2f} | {r['briefing_time']:<10.2f} | {r['total_time']:<10.2f} | {r['total_chars']:<10}")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
