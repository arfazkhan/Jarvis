import time
import logging
from dotenv import load_dotenv
import os

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CloudVerify")

load_dotenv()

from arvis_core.event_bus.event_bus import EventBus
from agent_home.llm_agent.llm_agent import LLMAgent

# Minimal Mocks
class MockStateEngine:
    def __init__(self): self.devices = {}
    def get_device_state(self, device_id): return "unknown"
    def summary(self): return {}

class MockAutomationEngine:
    def list(self): return []

def run_cloud_check():
    bus = EventBus()
    
    # Capture responses
    responses = []
    def on_response(event):
        responses.append(event)
        logger.info(f"📩 RECEIVED RESPONSE: {event}")
        
    bus.subscribe("agent_response", on_response)
    bus.subscribe("tool_calls_generated", on_response)
    
    logger.info("☁️ Initializing Cloud Agent...")
    try:
        agent = LLMAgent(
            bus, 
            state_engine=MockStateEngine(), 
            automations=MockAutomationEngine(), 
            subscribe_to_voice=False
        )
        logger.info(f"✅ Agent Init. Provider: {os.getenv('LLM_PROVIDER', 'unknown')}")
        
        # Test 1: Simple Chat
        logger.info("\n🧪 TEST 1: Simple Chat ('Tell me a joke')")
        bus.publish({
            "type": "voice_command", 
            "payload": {"text": "Tell me a short joke about AI", "source": "verify_script"}
        })
        # agent.handle() is sync
        agent.handle({
             "type": "voice_command", 
             "payload": {"text": "Tell me a short joke about AI", "source": "verify_script"}
        })
        
        # Test 2: Tool Call
        logger.info("\n🧪 TEST 2: Tool Plan ('Create a mission to save the world')")
        agent.handle({
             "type": "voice_command", 
             "payload": {"text": "Create a mission to save the world", "source": "verify_script"}
        })
        
        logger.info("\n📝 SUMMARY OF RESPONSES:")
        for r in responses:
            print(r)
            
    except Exception as e:
        logger.error(f"❌ CRITICAL FAILURE: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_cloud_check()
