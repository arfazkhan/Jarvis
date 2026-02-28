import logging
import asyncio
from typing import Optional
from agent_unified.agents.manus import ARVISManus
# Import from existing agent package
from agent_home.voice.realtime_voice import RealtimeVoice
from agent_home.voice.pipeline import VoicePipeline

logger = logging.getLogger(__name__)

class VoiceCoordinator:
    """
    Coordinators Voice I/O with Unified Agent.
    
    Flow:
    Microphone -> RealtimeVoice (STT) -> Coordinator -> ARVISManus -> VoicePipeline (Router -> TTS) -> Speaker
    """
    
    def __init__(self, agent: Optional[ARVISManus] = None):
        self.agent = agent
        
        # Input: STT + VAD + Wake Word
        # Using "jarvis" or "arvis" as wake words
        self.ears = RealtimeVoice(
            on_transcription=self.handle_voice_input,
            wake_words=["jarvis", "arvis"],
        )
        
        # Output: TTS + StreamRouter (Tool detection)
        # Using VibeVoice by default if available, else generic
        self.mouth = VoicePipeline(tts_engine="vibevoice")
        
        self.is_running = False
        self._processing_lock = asyncio.Lock()
        
    async def start(self):
        """Start the full voice loop"""
        if not self.agent:
            logger.info("Initializing default ARVIS Agent...")
            self.agent = await ARVISManus.create()
            
        logger.info("Starting Voice Coordinator...")
        self.mouth.start()
        self.ears.start()
        
        # Start listening in background
        self.ears.listen_loop()
        self.is_running = True
        logger.info("✅ Voice Coordinator is live and listening")
        
    async def stop(self):
        """Stop all components"""
        self.is_running = False
        self.ears.stop()
        self.mouth.stop()
        logger.info("🛑 Voice Coordinator stopped")
        
    def handle_voice_input(self, text: str):
        """Callback from STT when user speaks"""
        if not text.strip():
            return
            
        logger.info(f"🎤 Heard: {text}")
        
        # 1. Processing Logic
        if not self.agent:
            logger.error("Agent not initialized!")
            # Simple fallback response
            self.mouth.speak("I'm broken. Please check my logs.")
            return

        # 2. Agent Execution (Bridge to Async)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        # Run in new task to not block the listener thread
        if loop.is_running():
             asyncio.create_task(self._process_with_agent(text))
        else:
             # Should not happen in normal server execution
             loop.run_until_complete(self._process_with_agent(text))
        
    async def _process_with_agent(self, text: str):
        """Run agent and stream output to TTS"""
        
        # Prevent overlapping processing if desired, or allow parallel
        # For voice, usually we want to process one command at a time per session
        async with self._processing_lock:
            try:
                # Indicate processing (optional sound)
                # self.mouth.play_sound("thinking.wav")
                
                # Use the streaming method we added to ARVISBaseAgent
                stream = self.agent.run_streaming(text)
                
                # Pipe token stream directly to TTS Pipeline
                # This enables low-latency response
                self.mouth.process_llm_stream_async(stream)
                
            except Exception as e:
                logger.error(f"Agent error: {e}")
                self.mouth.speak("I ran into an error processing that request.")
