import asyncio
import os
import sys
from pathlib import Path

# Add root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_home.llm_agent.llm_agent import LLMAgent
from arvis_core.event_bus.event_bus import EventBus

class MockStateEngine:
    def get(self, key, default=None): return default
    def get_state(self): return {}
    def summary(self): return "System Nominal"

class MockAutomations:
    def list(self): return []

async def test_k2_streaming():
    print("⚡ TESTING K2 STREAMING ⚡")
    
    # Ensure env vars are set (or rely on .env loading)
    # The agent loads .env itself usually via main or verify script, so we assume environment is ready
    # But for safety, let's load it here if needed
    from dotenv import load_dotenv
    load_dotenv()
    
    # Check if keys exist
    if not os.getenv("K2THINK_API_KEY"):
        print("❌ K2THINK_API_KEY not found in env")
        return

    # Initialize Agent
    bus = EventBus()
    agent = LLMAgent(
        event_bus=bus,
        state_engine=MockStateEngine(),
        automations=MockAutomations(),
        subscribe_to_voice=False,
        override_provider="k2think"
    )
    
    # Verify provider
    print(f"→ Agent Provider: {agent.provider}")
    print(f"→ Agent Model: {getattr(agent, 'k2think_model', 'unknown')}")
    
    if agent.provider != "k2think":
        print("❌ Agent did not initialize with k2think provider")
        return

    # Create dummy event
    event = {
        "type": "voice_command",
        "payload": {
            "text": "Hello, explain quantum physics in one sentence.",
            "source": "test_script"
        },
        "timestamp": 0 # bypass age check hack? No, handle_streaming checks time.time()
    }
    # Hack: handle_streaming checks timestamp age.
    import time
    event["timestamp"] = time.time()

    print("\n→ Starting Stream...")
    try:
        # handle_streaming is a generator, not async generator?
        # Let's check implementation. Yes, "yield" makes it a generator.
        # But wait, it calls `self.gemini_model.generate_content(..., stream=True)` which is blocking sync?
        # Or `self.client.chat.completions.create(..., stream=True)` which is sync stream in standard OpenAI?
        # The code uses `self.client.chat.completions.create` which is SYNC by default in OpenAI lib unless AsyncOpenAI is used.
        # LLMAgent imports `from openai import OpenAI` (sync client).
        # So `handle_streaming` is a synchronous generator.
        
        generator = agent.handle_streaming(event)
        
        token_count = 0
        for token in generator:
            sys.stdout.write(token)
            sys.stdout.flush()
            token_count += 1
            
        print(f"\n\n✅ Stream Complete. Tokens: {token_count}")
        
    except Exception as e:
        print(f"\n❌ Streaming Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_k2_streaming())
