import asyncio
import os
import sys
import time
import json
from dotenv import load_dotenv

# Adjust path
sys.path.append("e:\\Automation")

# Load environment
load_dotenv()

async def run_benchmark():
    print("📊 COMPREHENSIVE MULTI-MODEL BENCHMARK 📊")
    print("=========================================")
    
    # Configurations to test
    # (Provider, Model Name, Tool Provider Override for this test)
    # We set TOOL_PROVIDER to the same as LLM_PROVIDER to test NATIVE capability.
    configs = [
        ("groq", "llama-3.3-70b-versatile", "groq"),
        ("nvidia", "stepfun-ai/step-3.5-flash", "groq"),
        ("nvidia", "z-ai/glm4.7", "groq"),
        ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5", "nvidia"),
        ("k2think", "MBZUAI-IFM/K2-Think-v2", "groq")
    ]
    
    results = []
    output_log = "e:\\Automation\\benchmark_outputs.txt"
    with open(output_log, "w", encoding="utf-8") as f:
        f.write("BENCHMARK OUTPUT LOG\n====================\n")

    from agent_bms.main import OpsCopilot
    from agent_bms.event_correlator import Event, EventSource
    from agent_bms.alarm_engine import Alarm, AlarmSeverity, AlarmCluster
    from datetime import datetime, timedelta
    
    # Setup Data
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
    cluster = AlarmCluster(cluster_id="bench_cluster", alarm_ids=["chiller_trip"], root_cause_equipment_id="CH-01")

    for provider, model, tool_prov in configs:
        print(f"\n🧪 Testing Config: Provider={provider}, Model={model}")
        
        # 1. Configure Environment
        os.environ["LLM_PROVIDER"] = provider
        if provider == "nvidia":
            os.environ["NVIDIA_MODEL"] = model
            if "glm" in model:
                os.environ["NVIDIA_THINKING"] = "true"
            else:
                os.environ["NVIDIA_THINKING"] = "false"
        elif provider == "k2think":
             os.environ["K2THINK_MODEL"] = model
        elif provider == "groq":
             os.environ["GROQ_MODEL"] = model
             
        # Force Tool Provider to test native capability
        os.environ["TOOL_PROVIDER"] = tool_prov
        if tool_prov == "nvidia":
             os.environ["TOOL_MODEL"] = model # Use same model for tools
        
        # 2. Re-Initialize Agent
        # We manually rebuild the UnifiedLLM to pick up new env vars
        from agent_unified.llm import UnifiedLLM, _REASONING_AGENT, _TOOL_AGENT
        import agent_unified.llm
        agent_unified.llm._REASONING_AGENT = None
        agent_unified.llm._TOOL_AGENT = None
        
        llm = UnifiedLLM() # Re-init
        
        # Log Logic
        def log_output(task, content, latency):
            header = f"\n--- [{provider}/{model}] {task} ({latency:.2f}s) ---\n"
            with open(output_log, "a", encoding="utf-8") as f:
                f.write(header + str(content) + "\n")

        # TEST A: REASONING (RCA)
        # -----------------------
        print("   Running Reasoning (RCA)...")
        start = time.time()
        try:
            # Manually construct prompt to avoid complex engine dependencies, focusing on LLM
            prompt = f"""
            Analyze the following BMS situation.
            Event: {sandstorm_event.description}
            Alarm: {alarm.message} on {alarm.equipment_id}
            
            Determine the root cause.
            """
            msgs = [{"role": "system", "content": "You are a BMS Expert."}, {"role": "user", "content": prompt}]
            resp = await llm.ask(msgs)
            rca_time = time.time() - start
            rca_content = resp.content
            log_output("Reasoning", rca_content, rca_time)
            print(f"   ✓ Done ({rca_time:.2f}s)")
        except Exception as e:
            print(f"   ❌ Reasoning Failed: {e}")
            rca_time = 0
            rca_content = f"ERROR: {e}"
            log_output("Reasoning", rca_content, 0)
            
        # TEST B: GENERATION (Briefing)
        # -----------------------------
        print("   Running Generation (Briefing)...")
        start = time.time()
        try:
            prompt = f"Write a professional executive briefing about the {sandstorm_event.event_type} impacting {alarm.equipment_id}. Keep it under 100 words."
            msgs = [{"role": "user", "content": prompt}]
            resp = await llm.ask(msgs)
            gen_time = time.time() - start
            gen_content = resp.content
            log_output("Generation", gen_content, gen_time)
            print(f"   ✓ Done ({gen_time:.2f}s)")
        except Exception as e:
            print(f"   ❌ Generation Failed: {e}")
            gen_time = 0
            gen_content = f"ERROR: {e}"
            log_output("Generation", gen_content, 0)

        # TEST C: TOOL USE (Weather)
        # --------------------------
        print("   Running Tool Use (Native)...")
        start = time.time()
        tool_success = False
        try:
            # We use the Tool Agent directly (which is now set to this provider)
            # Define a simple tool
            tools = [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"}
                        },
                        "required": ["location"]
                    }
                }
            }]
            tool_msg = [{"role": "user", "content": "What is the weather in Doha?"}]
            
            # Use UnifiedLLM's ask_tool which correctly uses the configured _TOOL_AGENT
            resp = await llm.ask_tool(tool_msg, system_msgs=None, tools=tools, tool_choice="auto")
            
            tool_time = time.time() - start
            if resp.tool_calls:
                tool_success = True
                tool_content = f"Tool Called: {resp.tool_calls[0].function.name}"
            else:
                tool_content = f"No Tool Call. Content: {resp.content}"
                
            log_output("Tool Use", tool_content, tool_time)
            msg = "✓ Success" if tool_success else "❌ Failed"
            print(f"   {msg} ({tool_time:.2f}s)")
            
        except Exception as e:
            print(f"   ❌ Tool Failed: {e}")
            tool_time = 0
            tool_success = False
            log_output("Tool Use", f"ERROR: {e}", 0)

        results.append({
            "model": model,
            "rca_time": rca_time,
            "gen_time": gen_time,
            "tool_time": tool_time,
            "tool_success": tool_success
        })

    # Summary Table
    print("\n🏆 FINAL BENCHMARK COMPARISON 🏆")
    print(f"{'Model':<30} | {'RCA(s)':<8} | {'Gen(s)':<8} | {'Tool?':<6} | {'Tool(s)':<8}")
    print("-" * 75)
    for r in results:
        ts = "✅" if r['tool_success'] else "❌"
        print(f"{r['model'][:30]:<30} | {r['rca_time']:<8.2f} | {r['gen_time']:<8.2f} | {ts:<6} | {r['tool_time']:<8.2f}")
        
    print(f"\nFull outputs saved to: {output_log}")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
