import asyncio
from agent_unified.voice.coordinator import VoiceCoordinator

class MockEars:
    def start(self): pass
    def stop(self): pass
    def listen_loop(self): pass

class MockMouth:
    def start(self): pass
    def stop(self): pass
    def speak(self, text): print(f"🔊 SPEAKING: {text}")
    def process_llm_stream_async(self, stream): 
        print("🔊 STREAMING AUDIO...")

class MockAgent:
    async def run(self, text): return f"Echo: {text}"
    async def run_streaming(self, text):
        yield f"Echo: {text}"

async def test_coordinator():
    print("Initializing coordinator...")
    # Instantiate but don't start to avoid real hardware init
    coord = VoiceCoordinator()
    
    # Mock the components to avoid hardware init
    coord.ears = MockEars()
    coord.mouth = MockMouth()
    coord.agent = MockAgent()
    
    print("Simulating voice input: 'Hello Jarvis'")
    await coord._process_with_agent("Hello Jarvis")
    
    print("Test passed!")

if __name__ == "__main__":
    asyncio.run(test_coordinator())
