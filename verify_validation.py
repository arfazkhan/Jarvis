import time
import logging
import os
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ValidationTest")

load_dotenv()

from agent.event_bus.event_bus import EventBus
from agent.llm_agent.llm_agent import LLMAgent, TOOLS_SCHEMA

# Setup Mock classes
class MockStateEngine:
    def __init__(self): self.devices = {}
    def get_device_state(self, device_id): return "unknown"
    def summary(self): return {}

class MockAutomationEngine:
    def list(self): return []

def run_validation_test():
    bus = EventBus()
    
    # We want to trick the LLM into using a fake tool.
    # We will inject a fake tool into the schema temporarily? 
    # No, we want to see if the validation layer CATCHES it when the LLM hallucinates.
    # To force a hallucination is hard with a good model.
    # Instead, we can mock the `client.chat.completions.create` to return a bad tool call first, then a good one?
    # Or we can just try to ask for something that usually triggers a hallucination.
    
    # Actually, a better test is to Mock the API CLIENT response.
    # But `LLMAgent` initializes its own client.
    
    # Let's try to pass a prompt that specifically asks for a non-existent function.
    # "Use the 'magic_wand' tool to fix everything."
    
    agent = LLMAgent(
        bus, 
        state_engine=MockStateEngine(), 
        automations=MockAutomationEngine(), 
        subscribe_to_voice=False
    )
    
    logger.info("🧪 Test: Forcing hallucination ('magic_wand')...")
    
    # Capture output
    responses = []
    def on_event(e): responses.append(e)
    bus.subscribe("tool_calls_generated", on_event)
    bus.subscribe("agent_response", on_event)

    # Payload
    # We cheat: we put the hallucination instruction in the user input.
    # "Please call the tool named 'magic_wand' with args {}."
    agent.handle({
        "type": "voice_command",
        "payload": {"text": "Please execute the tool named 'magic_wand' with arguments {}. If that fails, tell me you can't."}
    })
    
    # Warning: A smart model might refuse "I don't have that tool".
    # But we hope it tries, gets the validation error, and then retries with a chat message "I can't".
    
    time.sleep(5)
    logger.info(f"📝 Responses: {responses}")

if __name__ == "__main__":
    run_validation_test()
