import asyncio
import os
import sys
import time
from dotenv import load_dotenv

# Adjust path
sys.path.append("e:\\Automation")

# Load environment
load_dotenv()

async def run_full_benchmark():
    print("🛡️ ZETA GAUNTLET FULL BENCHMARK (Reasoning + Tools) 🛡️")
    print("======================================================")
    
    models = [
        "stepfun-ai/step-3.5-flash",
        "z-ai/glm4.7"
    ]
    
    results = []
    
    # We need to re-import or re-init Copilot for each run to be clean, 
    # but simplest is to modify the global LLM config before OpsCopilot uses it (or patch it).
    
    # Force Tool Provider to NVIDIA for this test
    os.environ["TOOL_PROVIDER"] = "nvidia"
    os.environ["LLM_PROVIDER"] = "nvidia"
    
    from agent_bms.main import OpsCopilot
    from agent_bms.event_correlator import Event, EventSource
    from agent_bms.alarm_engine import Alarm, AlarmSeverity
    from datetime import datetime, timedelta

    # Prepare Data
    timestamp = datetime.now()
    sandstorm_event = Event(
        event_id="weather_sandstorm",
        source=EventSource.WEATHER,
        timestamp=timestamp - timedelta(minutes=10),
        event_type="Weather Alert",
        description="Severe Dust Storm (Shamal)."
    )
    alarm = Alarm(
        alarm_id="chiller_trip",
        equipment_id="CH-01",
        severity=AlarmSeverity.CRITICAL,
        message="High Discharge Pressure Trip",
        triggered_at=timestamp
    )

    for model in models:
        print(f"\n🧪 Testing Model: {model}")
        os.environ["NVIDIA_MODEL"] = model
        
        # Handle Thinking
        if "glm" in model:
             os.environ["NVIDIA_THINKING"] = "true"
        else:
             os.environ["NVIDIA_THINKING"] = "false"
             
        # Initialize System (Re-init to pick up environment changes if valid)
        # Note: UnifiedLLM reads env vars on __init__, so we must re-instantiate LLM.
        # But OpsCopilot instantiates it once.
        # We will manually patch the LLM agent.
        
        print("   Initializing OpsCopilot...")
        copilot = OpsCopilot(mode="api_only")
        
        # Force re-initialization of agents with new Env Vars
        from agent_unified.llm import UnifiedLLM
        # We need to reset the singletons in llm.py if we want true clean slate, 
        # but let's just create a new UnifiedLLM and attach it.
        import agent_unified.llm
        agent_unified.llm._REASONING_AGENT = None
        agent_unified.llm._TOOL_AGENT = None
        
        copilot.llm_agent.llm = UnifiedLLM() 
        copilot.alarm_engine.set_llm_provider(copilot.llm_agent.llm)

        # Inject Data
        if not hasattr(copilot, 'event_correlator') or copilot.event_correlator is None:
            from agent_bms.event_correlator import EventCorrelator
            copilot.event_correlator = EventCorrelator()
            
        copilot.event_correlator.add_event(sandstorm_event)
        await copilot.alarm_engine.ingest_alarm(alarm)
        
        # 1. Tool Call Test: Alarm Root Cause (should trigger tool if needed, 
        # but pure reasoning might be skipped. Let's force a call that NEEDS tools).
        # "Check status of CH-01"
        
        print("   Running Tool Execution Test...")
        start_time = time.time()
        tool_success = False
        try:
            # We ask the tool agent directly to avoid hybrid routing complexity obscuring the test
            tool_msg = [{"role": "user", "content": "What is the status of CH-01? Check active alarms."}]
            # We need the tools definition from bms agent
            tools = copilot.llm_agent.tools 
            
            # Use the UnifiedLLM ask() which routes to Tool Agent (configured as NVIDIA)
            response = await copilot.llm_agent.llm.ask(tool_msg, tools=tools)
            
            if response.tool_calls:
                print(f"   ✓ Tool Call Generated: {response.tool_calls[0].function.name}")
                tool_success = True
            else:
                print(f"   ⚠ No Tool Call: {response.content[:50]}...")
                
            tool_time = time.time() - start_time
            
        except Exception as e:
            print(f"   ❌ Tool Test Failed: {e}")
            tool_time = 0
            
        results.append({
            "model": model,
            "tool_success": tool_success,
            "latency": tool_time
        })

    print("\n🏆 TOOL BENCHMARK RESULTS 🏆")
    print(f"{'Model':<30} | {'Success':<10} | {'Latency (s)':<10}")
    print("-" * 60)
    for r in results:
        status = "✅ YES" if r['tool_success'] else "❌ NO"
        print(f"{r['model']:<30} | {status:<10} | {r['latency']:<10.2f}")

if __name__ == "__main__":
    asyncio.run(run_full_benchmark())
