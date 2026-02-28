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
    Also detects raw JSON tool format: {"tool": "...", "arguments": {...}}
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
        self.json_mode = False  # Tracking raw JSON accumulation
        self.json_depth = 0  # Brace depth for JSON detection
        self.granite_mode = False  # Tracking Granite <tool_call> format
    
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
            # Detected tool start marker
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
        
        elif '{"tool"' in self.pending_buffer or '{"tool":' in self.pending_buffer:
            # Detected raw JSON tool format - switch to JSON accumulation mode
            idx = self.pending_buffer.find('{"tool"')
            if idx == -1:
                idx = self.pending_buffer.find('{"tool":')
            
            logger.debug(f"Detected raw JSON tool format")
            self.mode = "tool"
            self.json_mode = True
            self.tool_buffer = self.pending_buffer[idx:]
            self.json_depth = self.tool_buffer.count('{') - self.tool_buffer.count('}')
            self.pending_buffer = ""
            
            # Check if JSON is complete
            self._check_json_complete()
        
        elif re.search(r'\{\s*"tool"\s*:', self.pending_buffer):
            # Detected multi-line JSON format with whitespace: { "tool": ... }
            match = re.search(r'\{\s*"tool"\s*:', self.pending_buffer)
            idx = match.start()
            
            logger.debug(f"Detected multi-line JSON tool format")
            self.mode = "tool"
            self.json_mode = True
            self.tool_buffer = self.pending_buffer[idx:]
            self.json_depth = self.tool_buffer.count('{') - self.tool_buffer.count('}')
            self.pending_buffer = ""
            
            # Check if JSON is complete
            self._check_json_complete()
        
        elif '{"type":' in self.pending_buffer or '{"type": "function"' in self.pending_buffer:
            # Detected OpenRouter format: {"type": "function", "name": ...}
            idx = self.pending_buffer.find('{"type":')
            if idx == -1:
                idx = self.pending_buffer.find('{"type": "function"')
            
            logger.debug(f"Detected OpenRouter function format")
            self.mode = "tool"
            self.json_mode = True
            self.tool_buffer = self.pending_buffer[idx:]
            self.json_depth = self.tool_buffer.count('{') - self.tool_buffer.count('}')
            self.pending_buffer = ""
            
            self._check_json_complete()
        
        elif '<tool_call>' in self.pending_buffer:
            # Detected Granite XML format: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
            idx = self.pending_buffer.find('<tool_call>')
            
            logger.debug(f"Detected Granite <tool_call> XML format")
            self.mode = "tool"
            self.json_mode = True
            self.granite_mode = True  # Track Granite format
            self.tool_buffer = self.pending_buffer[idx:]
            self.pending_buffer = ""
            
            self._check_granite_complete()
        
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
        if self.json_mode:
            self._check_json_complete()
            return
            
        # Pattern: ### TOOL: {...} ###
        if self.tool_buffer.count("###") >= 2:
            # We have both start and end markers
            logger.debug(f"Complete tool block detected")
            self._execute_tool(self.tool_buffer)
            self.tool_buffer = ""
            self.pending_buffer = ""
            self.mode = "text"
    
    def _check_json_complete(self):
        """Check if raw JSON tool is complete by tracking brace depth."""
        self.json_depth = self.tool_buffer.count('{') - self.tool_buffer.count('}')
        
        if self.json_depth == 0 and self.tool_buffer.strip():
            # JSON is balanced - execute it
            logger.debug(f"Complete JSON tool detected")
            # Wrap in marker format for _execute_tool
            wrapped = f"### TOOL: {self.tool_buffer.strip()} ###"
            self._execute_tool(wrapped)
            self.tool_buffer = ""
            self.pending_buffer = ""
            self.mode = "text"
            self.json_mode = False
        elif self.json_depth < 0:
            # More closing braces than opening - we have multiple tools concatenated
            # Find the first complete JSON object
            depth = 0
            first_json_end = -1
            for i, c in enumerate(self.tool_buffer):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        first_json_end = i
                        break
            
            if first_json_end > 0:
                first_json = self.tool_buffer[:first_json_end + 1]
                remaining = self.tool_buffer[first_json_end + 1:]
                
                wrapped = f"### TOOL: {first_json.strip()} ###"
                self._execute_tool(wrapped)
                
                # Put remaining back in pending_buffer for next cycle
                self.tool_buffer = ""
                self.pending_buffer = remaining
                self.mode = "text"
                self.json_mode = False
    
    def _check_granite_complete(self):
        """Check if Granite <tool_call> buffer contains complete tool call."""
        if '</tool_call>' in self.tool_buffer:
            # Extract tool call content
            start = self.tool_buffer.find('<tool_call>') + len('<tool_call>')
            end = self.tool_buffer.find('</tool_call>')
            
            if start > 0 and end > start:
                tool_json = self.tool_buffer[start:end].strip()
                remaining = self.tool_buffer[end + len('</tool_call>'):]
                
                # Parse and convert Granite format {"name": "...", "arguments": {...}}
                # to our format {"tool": "...", "args": {...}}
                try:
                    import json
                    granite_tool = json.loads(tool_json)
                    
                    # Convert to our internal format
                    tool_name = granite_tool.get('name', '')
                    tool_args = granite_tool.get('arguments', {})
                    
                    # Create wrapped format for _execute_tool
                    converted = {"tool": tool_name, "args": tool_args}
                    wrapped = f"### TOOL: {json.dumps(converted)} ###"
                    print(f"[StreamRouter] 🔧 Granite tool: {tool_name}")
                    self._execute_tool(wrapped)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Granite tool JSON: {e}")
                
                # Reset and handle remaining
                self.tool_buffer = ""
                self.pending_buffer = remaining
                self.mode = "text"
                self.json_mode = False
                self.granite_mode = False
                
                # Check for more tool calls
                if '<tool_call>' in remaining:
                    self.pending_buffer = remaining
                    # Will be detected on next process_token
    
    def flush(self):
        """Flush remaining buffer (end of stream)."""
        # Also flush any pending tool
        if self.tool_buffer and self.mode == "tool":
            logger.debug(f"Flushing tool buffer on stream end")
            if self.granite_mode:
                # Try to parse as Granite format
                self._check_granite_complete()
            elif self.json_mode:
                wrapped = f"### TOOL: {self.tool_buffer.strip()} ###"
                self._execute_tool(wrapped)
            else:
                self._execute_tool(self.tool_buffer)
            self.tool_buffer = ""
            self.mode = "text"
            self.json_mode = False
            self.granite_mode = False
        
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
            # Find first complete JSON object using brace matching
            start = tool_block.find('{')
            if start == -1:
                logger.warning(f"No JSON found in tool: {tool_block[:50]}")
                return
            
            depth = 0
            end = -1
            for i in range(start, len(tool_block)):
                if tool_block[i] == '{':
                    depth += 1
                elif tool_block[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            
            if end == -1:
                logger.warning(f"Incomplete JSON in tool: {tool_block[:50]}")
                return
            
            json_str = tool_block[start:end+1]
            tool_data = json.loads(json_str)
            
            # Handle both formats:
            # Standard: {"tool": "ask_user", "args": {...}}
            # OpenRouter: {"type": "function", "name": "ask_user", "parameters": {...}}
            tool_name = tool_data.get('tool') or tool_data.get('name', '')
            args = tool_data.get('args', {}) or tool_data.get('arguments', {}) or tool_data.get('parameters', {})
            
            logger.debug(f"Tool detected: {tool_name}")
            print(f"[StreamRouter] 🔧 Tool: {tool_name}, args: {args}")
            
            # For ask_user, extract message and send to TTS
            if tool_name == 'ask_user':
                message = args.get('message', '')
                if message:
                    print(f"[StreamRouter] 🔊 Speaking: {message[:50]}...")
                    logger.info(f"Speaking: '{message[:50]}...'")
                    self._send_text(message)
                # ALWAYS callback for ask_user so follow-up mode can detect options
                if self._tool_callback:
                    self._tool_callback(tool_data)
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
        self.json_mode = False
        self.granite_mode = False


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
        
        # ═══════════════════════════════════════════════════════════
        # FOLLOW-UP MODE - Skip wake word after ask_user with options
        # ═══════════════════════════════════════════════════════════
        self.follow_up_mode = False
        self.follow_up_timeout = 10.0  # seconds - enough time for user to think and respond
        self.expected_responses = []  # Valid responses during follow-up
        self.last_question_time = None
        
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
        
    def stop(self):
        """Stop the pipeline and release resources."""
        self._running = False
        self.stop_speaking()
        if self._tts_stream:
            self._tts_stream.stop()
        logger.info("🛑 VoicePipeline stopped")
        
    def _init_tts(self):
        """Initialize the TTS engine and stream."""
        
        # Edge TTS - Microsoft's cloud-based, free TTS (no API key needed)
        if self._tts_engine_name == "edgetts":
            try:
                from agent_home.voice.edgetts_engine import EdgeTTSEngine, EdgeTTSTTSStream, EDGETTS_AVAILABLE
                
                if not EDGETTS_AVAILABLE:
                    logger.warning("Edge TTS not available, falling back to Kokoro")
                    self._tts_engine_name = "kokoro"
                else:
                    logger.info("Initializing EdgeTTSEngine...")
                    import os
                    voice = os.getenv("EDGETTS_VOICE", "guy")
                    rate = os.getenv("EDGETTS_RATE", "+0%")
                    
                    self._tts_engine = EdgeTTSEngine(
                        voice=voice,
                        rate=rate,
                    )
                    self._tts_stream = EdgeTTSTTSStream(
                        self._tts_engine,
                        on_audio_stream_start=self._on_tts_start,
                        on_audio_stream_stop=self._on_tts_stop,
                    )
                    
                    # Prewarm
                    logger.info("Prewarming Edge TTS engine...")
                    self._tts_stream.feed(".")
                    self._tts_stream.play(muted=True)
                    logger.info("⚡ Edge TTS engine ready")
                    return
                    
            except Exception as e:
                logger.error(f"Edge TTS init failed: {e}, falling back to Kokoro")
                self._tts_engine_name = "kokoro"
        
        # VibeVoice - Microsoft's high-quality, real-time TTS
        if self._tts_engine_name == "vibevoice":
            try:
                from agent_home.voice.vibevoice_engine import VibeVoiceEngine, VibeVoiceTTSStream, VIBEVOICE_AVAILABLE
                
                if not VIBEVOICE_AVAILABLE:
                    logger.warning("VibeVoice not available, falling back to Kokoro")
                    self._tts_engine_name = "kokoro"
                else:
                    logger.info("Initializing VibeVoiceEngine...")
                    import os
                    model = os.getenv("VIBEVOICE_MODEL", "microsoft/VibeVoice-Realtime-0.5B")
                    device = os.getenv("VIBEVOICE_DEVICE", "cuda")
                    speaker = os.getenv("VIBEVOICE_SPEAKER", "carter")
                    
                    self._tts_engine = VibeVoiceEngine(
                        model_path=model,
                        device=device,
                        speaker=speaker,
                    )
                    self._tts_stream = VibeVoiceTTSStream(
                        self._tts_engine,
                        on_audio_stream_start=self._on_tts_start,
                        on_audio_stream_stop=self._on_tts_stop,
                    )
                    
                    # Prewarm
                    logger.info("Prewarming VibeVoice engine...")
                    self._tts_stream.feed(".")
                    self._tts_stream.play(muted=True)
                    logger.info("⚡ VibeVoice engine ready")
                    return
                    
            except Exception as e:
                logger.error(f"VibeVoice init failed: {e}, falling back to Kokoro")
                self._tts_engine_name = "kokoro"
        
        # CosyVoice - High-quality, low-latency alternative
        if self._tts_engine_name == "cosyvoice":
            try:
                from agent_home.voice.cosyvoice_engine import CosyVoiceEngine, CosyVoiceTTSStream, COSYVOICE_AVAILABLE
                
                if not COSYVOICE_AVAILABLE:
                    logger.warning("CosyVoice not available, falling back to Coqui")
                    self._tts_engine_name = "coqui"
                else:
                    logger.info("Initializing CosyVoiceEngine...")
                    import os
                    model = os.getenv("COSYVOICE_MODEL", "Fun-CosyVoice3-0.5B")
                    device = os.getenv("COSYVOICE_DEVICE", "cuda")
                    speaker = os.getenv("COSYVOICE_SPEAKER", "英文女")
                    
                    self._tts_engine = CosyVoiceEngine(
                        model_name=model,
                        device=device,
                        speaker=speaker,
                    )
                    self._tts_stream = CosyVoiceTTSStream(
                        self._tts_engine,
                        on_audio_stream_start=self._on_tts_start,
                        on_audio_stream_stop=self._on_tts_stop,
                    )
                    
                    # Prewarm
                    logger.info("Prewarming CosyVoice engine...")
                    self._tts_stream.feed(".")
                    self._tts_stream.play(muted=True)
                    logger.info("⚡ CosyVoice engine ready")
                    return
                    
            except Exception as e:
                logger.error(f"CosyVoice init failed: {e}, falling back to Coqui")
                self._tts_engine_name = "coqui"
        
        # RealtimeTTS engines (Coqui, Kokoro, Piper)
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
        
        # Check if this ask_user has options -> enter follow-up mode
        tool_name = tool_data.get('tool') or tool_data.get('name', '')
        args = tool_data.get('args', {}) or tool_data.get('arguments', {}) or tool_data.get('parameters', {})
        
        print(f"[DEBUG _on_tool] tool_name={tool_name}, has_options={'options' in args if args else 'no args'}")
        
        if tool_name == 'ask_user':
            options = args.get('options', []) if args else []
            message = args.get('message', '') if args else ''
            
            print(f"[DEBUG _on_tool] ask_user detected. options={options}, has_question_mark={'?' in message}")
            
            if options:
                # Enter follow-up mode with expected responses
                self.enter_follow_up(options)
                print(f"[FollowUp] ✅ Entered follow-up mode. Expected: {options}")
            elif '?' in message:
                # Question without options - short follow-up for free-form answer
                self.enter_follow_up([])  # Empty = accept anything
                print("[FollowUp] ✅ Entered free-form follow-up mode")
    
    # ═══════════════════════════════════════════════════════════
    # FOLLOW-UP MODE METHODS
    # ═══════════════════════════════════════════════════════════
    
    def enter_follow_up(self, expected: list):
        """Enter follow-up mode - skip wake word for next response."""
        import time
        self.follow_up_mode = True
        self.expected_responses = [e.lower().strip() for e in expected]
        self.last_question_time = time.time()
        print(f"[FollowUp] 🎯 Mode set to TRUE. Expected: {self.expected_responses}")
        
    def exit_follow_up(self, reason: str = ""):
        """Exit follow-up mode - require wake word again."""
        self.follow_up_mode = False
        self.expected_responses = []
        self.last_question_time = None
        logger.info(f"[FollowUp] Mode OFF. Reason: {reason}")
        
    def is_follow_up_valid(self) -> bool:
        """Check if follow-up mode is still valid (not timed out)."""
        if not self.follow_up_mode:
            return False
        if self.last_question_time is None:
            return False
            
        import time
        elapsed = time.time() - self.last_question_time
        if elapsed > self.follow_up_timeout:
            self.exit_follow_up("timeout")
            return False
        return True
    
    def check_follow_up_response(self, transcription: str) -> dict:
        """
        Check if transcription matches expected follow-up responses.
        
        Returns:
            {
                "valid": bool,
                "matched": str or None,  # The matched option
                "action": "process" | "ignore" | "exit_politely"
            }
        """
        if not self.is_follow_up_valid():
            return {"valid": False, "matched": None, "action": "exit_politely"}
        
        text = transcription.lower().strip()
        
        # If no expected responses (free-form question), accept anything
        if not self.expected_responses:
            self.exit_follow_up("free_form_response")
            return {"valid": True, "matched": text, "action": "process"}
        
        # Check if response matches any expected option
        for expected in self.expected_responses:
            # Fuzzy matching - check if expected is in the response
            if expected in text or text in expected:
                self.exit_follow_up("matched_response")
                return {"valid": True, "matched": expected, "action": "process"}
        
        # Also check for common variations
        common_yes = ["yes", "yeah", "yep", "sure", "ok", "okay", "yup", "affirmative"]
        common_no = ["no", "nope", "nah", "negative", "cancel", "stop"]
        
        if any(y in text for y in common_yes) and "yes" in self.expected_responses:
            self.exit_follow_up("matched_yes")
            return {"valid": True, "matched": "yes", "action": "process"}
        
        if any(n in text for n in common_no) and "no" in self.expected_responses:
            self.exit_follow_up("matched_no")
            return {"valid": True, "matched": "no", "action": "process"}
        
        # No match - could be background noise, ignore but stay in follow-up
        logger.debug(f"[FollowUp] No match for '{text}'. Expected: {self.expected_responses}")
        return {"valid": False, "matched": None, "action": "ignore"}
    
    def get_follow_up_exit_message(self) -> str:
        """Get a polite message when exiting follow-up mode due to timeout."""
        messages = [
            "I didn't catch that. Say Jarvis if you need me!",
            "Hmm, I missed that. Just say Jarvis when you're ready.",
            "No worries, just say Jarvis to continue.",
        ]
        import random
        return random.choice(messages)
        
    def process_llm_stream(self, token_generator: Iterator[str]):
        """
        Feed LLM tokens through the pipeline with TRUE STREAMING.
        Audio starts playing as soon as first text chunk is ready.
        
        Args:
            token_generator: Iterator yielding tokens from LLM
        """
        if not self._running:
            raise RuntimeError("VoicePipeline not started")
        
        # Create a generator that feeds the router and yields text for TTS
        # This runs INSIDE the TTS thread (via play_async consuming it)
        def _tts_feeder():
            # Temporarily replace callback to capture text
            original_callback = self.router._text_callback
            
            # Queue to pass text from router callback to generator
            text_queue = Queue()
            
            def _on_text_streaming(text: str):
                if text.strip():
                    text_queue.put(text)
            
            self.router._text_callback = _on_text_streaming
            
            try:
                # Process tokens
                for token in token_generator:
                    self.router.process_token(token)
                    
                    # Yield any text produced by this token
                    while not text_queue.empty():
                        yield text_queue.get_nowait()
                
                # Flush router at end
                self.router.flush()
                while not text_queue.empty():
                     yield text_queue.get_nowait()
                     
            finally:
                # Restore callback
                self.router._text_callback = original_callback

        # Start streaming playback
        # VibeVoiceTTSStream.play_async() will wait for the generator
        if self._tts_stream:
             logger.info("Starting async TTS stream...")
             self._tts_stream.feed(_tts_feeder())
             self._tts_stream.play_async()
            
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
    
    def speak(self, text: str, blocking: bool = True):
        """Speak a message through TTS."""
        if not self._running or not self._tts_stream:
            logger.warning("VoicePipeline not running, can't speak")
            return
        
        self._tts_stream.feed(text)
        if blocking:
            self._tts_stream.play()
        else:
            self._tts_stream.play_async()
        
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
    
    def shutdown(self):
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
