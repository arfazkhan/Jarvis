"""
Async Voice Pipeline Workers
---------------------------
Threaded workers for real-time voice streaming.

Uses RealtimeTTS for efficient streaming text-to-speech.
Uses StreamRouter for tool call detection and routing.
"""

import re
import json
import logging
import threading
from queue import Queue, Empty
from typing import Generator, Iterator

logger = logging.getLogger(__name__)


# ==========================================
# Stream Router - Tool Detection & Routing
# ==========================================

class StreamRouter:
    """
    Routes LLM tokens to either TTS (natural language) or Tool Executor.
    
    Uses rolling window to detect tool markers that may be split across tokens.
    Marker format: ### TOOL: {...} ### (easier to detect than XML tags)
    """
    
    TOOL_START = "### TOOL:"
    TOOL_END = "###"
    
    def __init__(self, text_callback=None, tool_callback=None):
        """
        Args:
            text_callback: Called with text chunks for TTS
            tool_callback: Called with tool dicts for execution
        """
        self._text_callback = text_callback
        self._tool_callback = tool_callback
        self.mode = "text"  # "text" or "tool"
        self.tool_buffer = ""
        self.pending_buffer = ""  # For detecting split markers
    
    def process_token(self, token: str):
        """
        Process a single token from LLM stream.
        Routes to text callback or tool callback based on detection.
        
        NOTE: Raw text from LLM is NOT spoken - only ask_user messages
        and tool confirmations are sent to TTS.
        """
        # Accumulate for pattern detection
        self.pending_buffer += token
        
        if self.mode == "tool":
            # Currently in tool mode - accumulate until end marker
            self.tool_buffer += token
            self._check_tool_end()
        
        elif self.TOOL_START in self.pending_buffer:
            # Detected tool start
            # DON'T speak any text before the marker (it's reasoning)
            idx = self.pending_buffer.find(self.TOOL_START)
            # Log but don't speak pre-tool text
            if idx > 0:
                logger.debug(f"Discarding pre-tool text: {self.pending_buffer[:idx][:50]}...")
            
            self.mode = "tool"
            self.tool_buffer = self.pending_buffer[idx:]
            self.pending_buffer = ""
            
            # Check if tool is already complete (single token case)
            self._check_tool_end()
        
        else:
            # Pure text - keep accumulating, don't speak yet
            # We only speak tool-generated text (ask_user messages, confirmations)
            # Keep last 15 chars in case marker is split across tokens
            if len(self.pending_buffer) > 50:
                # Log but don't speak - this is LLM reasoning
                discarded = self.pending_buffer[:-15]
                logger.debug(f"Discarding raw text: {discarded[:50]}...")
                self.pending_buffer = self.pending_buffer[-15:]
    
    def _check_tool_end(self):
        """Check if tool buffer contains end marker and execute if so."""
        # Pattern: ### TOOL: {...} ###
        if self.tool_buffer.count("###") >= 2:
            # We have both start and end markers
            logger.debug(f"Complete tool block detected")
            self._execute_tool(self.tool_buffer)
            self.tool_buffer = ""
            self.pending_buffer = ""
            self.mode = "text"
    
    def flush(self):
        """Flush remaining buffer (end of stream)."""
        # Also flush any pending tool
        if self.tool_buffer and self.mode == "tool":
            logger.debug(f"Flushing tool buffer on stream end")
            self._execute_tool(self.tool_buffer)
            self.tool_buffer = ""
            self.mode = "text"
        
        # DON'T speak remaining text - it's likely LLM reasoning
        if self.pending_buffer and self.mode == "text":
            logger.debug(f"Discarding end-of-stream text: {self.pending_buffer[:50]}...")
        self.pending_buffer = ""
    
    def _send_text(self, text: str):
        """Send sanitized text to TTS callback."""
        text = self._sanitize_markdown(text)
        if text.strip() and self._text_callback:
            self._text_callback(text)
    
    def _execute_tool(self, tool_block: str):
        """Handle tool call - for ask_user, extract message and speak it."""
        try:
            # Extract JSON from tool block
            json_match = re.search(r'\{.*\}', tool_block, re.DOTALL)
            if not json_match:
                logger.warning(f"No JSON found in tool: {tool_block[:50]}")
                return
            
            tool_data = json.loads(json_match.group())
            tool_name = tool_data.get('tool', '')
            args = tool_data.get('args', {})
            
            logger.debug(f"Tool detected: {tool_name}")
            
            # For ask_user, extract message and send to TTS
            if tool_name == 'ask_user':
                message = args.get('message', '')
                if message:
                    logger.info(f"Speaking: '{message[:50]}...'")
                    self._send_text(message)
            elif tool_name == 'think':
                # Think tool is for internal reasoning, don't speak
                reasoning = args.get('reasoning', '')
                logger.debug(f"Thinking: '{reasoning[:50]}...'")
            elif tool_name in ('turn_on', 'turn_off'):
                # Execute device control and speak confirmation
                if self._tool_callback:
                    self._tool_callback(tool_data)
                device = args.get('device_id', 'device')
                action = 'on' if tool_name == 'turn_on' else 'off'
                self._send_text(f"Turning {action} the {device}.")
            elif tool_name == 'get_current_time':
                # Get and speak current time - avoid "12" pause issue
                from datetime import datetime
                now = datetime.now()
                # Use words for hour to avoid TTS pausing on numbers
                hour = now.hour % 12 or 12
                minute = now.minute
                am_pm = "AM" if now.hour < 12 else "PM"
                day_name = now.strftime("%A")
                month_day = now.strftime("%B %d")
                
                if minute == 0:
                    time_str = f"{hour} o'clock {am_pm}"
                else:
                    time_str = f"{hour}:{minute:02d} {am_pm}"
                
                self._send_text(f"It's {time_str} on {day_name}, {month_day}.")
            else:
                # Queue other tools for later execution
                if self._tool_callback:
                    self._tool_callback(tool_data)
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
    
    def _sanitize_markdown(self, text: str) -> str:
        """Strip markdown formatting and emojis for clean TTS."""
        import emoji
        # Remove emojis
        text = emoji.replace_emoji(text, replace='')
        # Remove markdown
        text = re.sub(r'[*#_`~\[\]\(\)]', '', text)
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def reset(self):
        """Reset router state."""
        self.mode = "text"
        self.tool_buffer = ""
        self.pending_buffer = ""


# ==========================================
# Voice Pipeline Manager
# ==========================================

class VoicePipeline:
    """
    Manages the voice pipeline with RealtimeTTS.
    
    Architecture:
    1. LLM tokens -> StreamRouter -> text chunks
    2. Text chunks -> RealtimeTTS.TextToAudioStream
    3. Audio -> Hardware playback
    """
    
    def __init__(self, tts_engine: str = "coqui"):
        """
        Initialize the voice pipeline.
        
        Args:
            tts_engine: TTS engine to use ("coqui", "kokoro", or "piper")
        """
        self._tts_engine_name = tts_engine
        self._tts_engine = None
        self._tts_stream = None
        self._tool_queue = Queue()
        self._running = False
        self._speaking = False
        
        # Router with callbacks
        self.router = StreamRouter(
            text_callback=self._on_text,
            tool_callback=self._on_tool
        )
        
    def start(self):
        """Initialize and start the pipeline."""
        if self._running:
            logger.warning("VoicePipeline already running")
            return
            
        logger.info("Starting VoicePipeline...")
        self._init_tts()
        self._running = True
        logger.info("✅ VoicePipeline started")
        
    def _init_tts(self):
        """Initialize the TTS engine and stream."""
        from RealtimeTTS import TextToAudioStream
        
        if self._tts_engine_name == "coqui":
            from RealtimeTTS import CoquiEngine
            logger.info("Initializing CoquiEngine...")
            self._tts_engine = CoquiEngine()
        elif self._tts_engine_name == "kokoro":
            from RealtimeTTS import KokoroEngine
            logger.info("Initializing KokoroEngine...")
            self._tts_engine = KokoroEngine()
        elif self._tts_engine_name == "piper":
            from RealtimeTTS import PiperEngine
            logger.info("Initializing PiperEngine...")
            self._tts_engine = PiperEngine()
        else:
            raise ValueError(f"Unknown TTS engine: {self._tts_engine_name}")
            
        self._tts_stream = TextToAudioStream(
            self._tts_engine,
            on_audio_stream_start=self._on_tts_start,
            on_audio_stream_stop=self._on_tts_stop,
        )
        
        # Prewarm the engine
        logger.info("Prewarming TTS engine...")
        self._tts_stream.feed(".")
        self._tts_stream.play(muted=True)
        logger.info("⚡ TTS engine ready")
        
    def _on_tts_start(self):
        """Called when TTS playback starts."""
        self._speaking = True
        logger.debug("TTS playback started")
        
    def _on_tts_stop(self):
        """Called when TTS playback stops."""
        self._speaking = False
        logger.debug("TTS playback stopped")
        
    def _on_text(self, text: str):
        """Called by router when text should be spoken."""
        if self._tts_stream and text.strip():
            self._tts_stream.feed(text)
            
    def _on_tool(self, tool_data: dict):
        """Called by router when a tool should be executed."""
        self._tool_queue.put(tool_data)
        
    def process_llm_stream(self, token_generator: Iterator[str]):
        """
        Feed LLM tokens through the pipeline with TRUE STREAMING.
        Audio starts playing as soon as first text chunk is ready.
        
        Args:
            token_generator: Iterator yielding tokens from LLM
        """
        if not self._running:
            raise RuntimeError("VoicePipeline not started")
        
        # Track if we've started playback
        playback_started = False
        
        def _on_text_streaming(text: str):
            """Feed text and start playback on first chunk."""
            nonlocal playback_started
            if self._tts_stream and text.strip():
                self._tts_stream.feed(text)
                
                # Start async playback on first text
                if not playback_started:
                    playback_started = True
                    self._tts_stream.play_async()
        
        # Temporarily replace callback for streaming mode
        original_callback = self.router._text_callback
        self.router._text_callback = _on_text_streaming
        
        try:
            # Process all tokens through the router
            for token in token_generator:
                self.router.process_token(token)
                
            # Flush remaining text
            self.router.flush()
            
            # Wait for playback to complete
            if playback_started:
                import time
                while self._speaking:
                    time.sleep(0.05)
        finally:
            # Restore original callback
            self.router._text_callback = original_callback
            
    def process_llm_stream_async(self, token_generator: Iterator[str]):
        """
        Feed LLM tokens and start playback asynchronously.
        Returns immediately while audio plays in background.
        """
        if not self._running:
            raise RuntimeError("VoicePipeline not started")
            
        # Create a generator that feeds the router
        def _token_feeder():
            for token in token_generator:
                self.router.process_token(token)
                # Yield accumulated text for TTS
                yield ""  # TextToAudioStream expects a generator
            self.router.flush()
            
        # Feed the generator to TTS stream
        self._tts_stream.feed(_token_feeder())
        self._tts_stream.play_async()
        
    def speak(self, text: str, blocking: bool = True):
        """
        Speak the given text directly.
        
        Args:
            text: Text to speak
            blocking: If True, wait for speech to complete
        """
        if not self._tts_stream:
            raise RuntimeError("VoicePipeline not started")
            
        self._tts_stream.feed(text)
        
        if blocking:
            self._tts_stream.play()
        else:
            self._tts_stream.play_async()
            
    def stop_speaking(self):
        """Stop current TTS playback immediately."""
        if self._tts_stream:
            self._tts_stream.stop()
            
    def is_speaking(self) -> bool:
        """Check if TTS is currently playing."""
        return self._speaking
        
    def get_pending_tools(self) -> list:
        """Get all pending tool calls from the queue."""
        tools = []
        while not self._tool_queue.empty():
            try:
                tools.append(self._tool_queue.get_nowait())
            except Empty:
                break
        return tools
        
    def interrupt(self):
        """Handle user interruption."""
        self.stop_speaking()
        self.router.reset()
        # Clear tool queue
        while not self._tool_queue.empty():
            try:
                self._tool_queue.get_nowait()
            except Empty:
                break
    
    def stop(self):
        """Shutdown pipeline."""
        logger.info("Stopping VoicePipeline...")
        self._running = False
        
        if self._tts_stream:
            self._tts_stream.stop()
            
        if self._tts_engine:
            self._tts_engine.shutdown()
            
        logger.info("🛑 VoicePipeline stopped")
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, *args):
        self.stop()
