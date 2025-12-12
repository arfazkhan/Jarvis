#!/usr/bin/env python3
"""
ARVIS Interactive Test CLI
--------------------------
CLI tool for testing voice commands and new tool schemas.
Simulates voice input and shows LLM responses.

Usage:
    python test_cli.py
    
Commands:
    Type any voice command to test
    Special commands:
        /think - Test the think tool
        /memory - Test log_memory tool
        /mission - Test create_mission tool
        /state - Show current state
        /history - Show recent events
        /logs - Show reasoning audit log
        /help - Show this help
        /quit - Exit
"""

import os
import sys
import time
import json
import threading
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment before imports
load_dotenv()

# ═══════════════════════════════════════════════════════════
# LOGGING SETUP - Save all logs to file
# ═══════════════════════════════════════════════════════════
LOG_DIR = Path(__file__).parent / "agent" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"test_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure root logger to write to file
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        # Also keep console output for errors
        logging.StreamHandler(sys.stdout)
    ]
)

# Check if debug mode is enabled via environment variable
ARVIS_DEBUG = os.environ.get("ARVIS_DEBUG", "false").lower() in ("true", "1", "yes")

# Set console handler level based on debug mode
if ARVIS_DEBUG:
    logging.getLogger().handlers[1].setLevel(logging.DEBUG)
    print(f"🔧 DEBUG MODE ENABLED - Full logging to console")
else:
    logging.getLogger().handlers[1].setLevel(logging.WARNING)

# Create logger for this module
logger = logging.getLogger("test_cli")
logger.info(f"Test CLI started. Logs saved to: {LOG_FILE}")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent.event_bus.event_bus import EventBus
from agent.state_engine.state_engine import StateEngine
from agent.controllers.matter_controller import MatterController
from agent.automations.automation_engine import AutomationEngine
from agent.tools.executor import ToolExecutor
from agent.learning.learning_engine import LearningEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent.voice.transcriber import VoiceTranscriber
from agent.voice.recorder import AudioRecorder
from agent.voice.wake_word import WakeWordEngine
from agent.voice.semantic_vad import SemanticVAD
from agent.voice.speaker import Speaker
from agent.voice.pipeline import VoicePipeline
from agent.voice.realtime_voice import RealtimeVoice

# ANSI colors for pretty output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def strip_colors(text: str) -> str:
    """Remove ANSI color codes from text for clean log files."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)


def log_print(msg: str, level: str = "info"):
    """Print to console AND log to file. Strips colors for log file."""
    print(msg, flush=True)  # Console with colors, flush immediately
    clean_msg = strip_colors(msg)  # Log without colors
    if level == "debug":
        logger.debug(clean_msg)
    elif level == "warning":
        logger.warning(clean_msg)
    elif level == "error":
        logger.error(clean_msg)
    else:
        logger.info(clean_msg)
    
    # Flush all handlers to ensure immediate write to file
    for handler in logger.handlers + logging.getLogger().handlers:
        handler.flush()


class TestCLI:
    """Interactive CLI for testing ARVIS voice commands"""
    
    def __init__(self):
        print(f"{Colors.HEADER}{Colors.BOLD}")
        print("=" * 60)
        print("        ARVIS Interactive Test CLI")
        print("=" * 60)
        print(f"{Colors.RESET}")
        
        # Initialize components
        print(f"{Colors.CYAN}Initializing components...{Colors.RESET}")
        
        self.event_bus = EventBus()
        self.state_engine = StateEngine(self.event_bus)
        
        # Use virtual devices for testing
        self.matter_controller = MatterController(use_virtual=True)
        
        # Use a minimal mock for automations (avoids scheduler noise)
        class MinimalAutomations:
            """Minimal mock to avoid scheduler during testing"""
            def __init__(self):
                self._routines = {}
            def list(self):
                return list(self._routines.keys())
            def create(self, name, trigger, actions):
                self._routines[name] = {"trigger": trigger, "actions": actions}
                print(f"[Mock] Created routine: {name}")
            def run(self, name):
                if name in self._routines:
                    return self._routines[name].get("actions", [])
                return []
        
        self.automation_engine = MinimalAutomations()
        
        self.learning_engine = LearningEngine(
            self.event_bus,
            self.state_engine,
            self.automation_engine,
            tool_executor=None  # Will set after ToolExecutor is created
        )
        
        self.tool_executor = ToolExecutor(
            self.matter_controller,
            self.state_engine,
            self.automation_engine,
            self.event_bus,
            learning_engine=self.learning_engine
        )
        
        # Update learning engine with tool executor
        self.learning_engine.tool_executor = self.tool_executor
        
        # Initialize Voice Components
        self.transcriber = VoiceTranscriber()
        self.recorder = AudioRecorder()
        self.wake_word_engine = WakeWordEngine()
        self.semantic_vad = SemanticVAD()
        self.speaker = Speaker()
        
        # Initialize Voice Pipeline (async streaming with RealtimeTTS)
        self.voice_pipeline = VoicePipeline(tts_engine="kokoro")
        self.voice_pipeline.start()
        
        self.llm_agent = LLMAgent(
            self.event_bus,
            self.state_engine,
            self.automation_engine,
            learning_engine=self.learning_engine
        )
        
        # Track events for display
        self.recent_events = []
        self.event_bus.subscribe("tool_calls_generated", self._on_tool_calls)
        self.event_bus.subscribe("relay_toggled", self._on_device_change)
        self.event_bus.subscribe("user_query", self._on_user_query)
        
        print(f"{Colors.GREEN}✅ All components initialized{Colors.RESET}")
        print()
        self._show_help()
    
    def _on_tool_calls(self, event):
        """Handle tool calls generated by LLM"""
        payload = event.get("payload", [])
        print(f"\n{Colors.BLUE}🔧 Tool Calls Generated:{Colors.RESET}")
        for call in payload:
            tool = call.get("tool", "unknown")
            args = call.get("args", {})
            print(f"   {Colors.CYAN}{tool}{Colors.RESET}({json.dumps(args, indent=6)})")
        self.recent_events.append({"type": "tool_calls", "calls": payload, "ts": time.time()})
    
    def _on_device_change(self, event):
        """Handle device state changes"""
        payload = event.get("payload", {})
        device = payload.get("device", "?")
        state = payload.get("state", "?")
        print(f"\n{Colors.GREEN}💡 Device Changed: {device} -> {state}{Colors.RESET}")
        self.recent_events.append(event)
    
    def _on_user_query(self, event):
        """Handle ask_user requests and speak them via TTS"""
        payload = event.get("payload", {})
        question = payload.get("question", "")
        options = payload.get("options", [])
        print(f"\n{Colors.YELLOW}🤖 ARVIS Asks: {question}{Colors.RESET}")
        if options:
            print(f"   Options: {', '.join(options)}")
        
        # Speak the response via TTS
        if question and hasattr(self, 'speaker'):
            self.speaker.speak(question)
    
    def _show_help(self):
        """Show help message"""
        print(f"{Colors.CYAN}Commands:{Colors.RESET}")
        print("  Type any voice command to test (e.g., 'turn on the lights')")
        print()
        print(f"{Colors.CYAN}Special Commands:{Colors.RESET}")
        print("  /think    - Test the think tool with sample reasoning")
        print("  /memory   - Test log_memory tool")
        print("  /state    - Show current device states")
        print("  /history  - Show recent events")
        print("  /logs     - Show reasoning audit log")
        print("  /prefs    - Show stored preferences")
        print("  /transcribe <file> - Test audio transcription")
        print("  /record   - Record voice command (5s)")
        print("  /chat     - Continuous conversation mode (VAD)")
        print("  /help     - Show this help")
        print("  /quit     - Exit")
        print()
    
    def _test_think_tool(self):
        """Test the think tool directly"""
        print(f"\n{Colors.CYAN}Testing think tool...{Colors.RESET}")
        self.tool_executor.execute([{
            "tool": "think",
            "args": {"reasoning": "User said 'lights'. Sleep state is true. Should I ask for confirmation before turning on lights? Yes, because the safety guidelines say to always ask before actions when sleep_state is true."}
        }])
        print(f"{Colors.GREEN}✅ Think tool executed - check agent/logs/reasoning_audit.log{Colors.RESET}")
    
    def _test_memory_tool(self):
        """Test the log_memory tool"""
        print(f"\n{Colors.CYAN}Testing log_memory tool...{Colors.RESET}")
        self.tool_executor.execute([{
            "tool": "log_memory",
            "args": {
                "title": "test_preference",
                "knowledge": "User prefers warm lighting in the evening",
                "action": "create"
            }
        }])
        print(f"{Colors.GREEN}✅ Memory stored - check with /prefs{Colors.RESET}")
    
    def _show_state(self):
        """Show current device states"""
        print(f"\n{Colors.CYAN}Current State:{Colors.RESET}")
        summary = self.state_engine.summary()
        print(json.dumps(summary, indent=2))
    
    def _show_history(self):
        """Show recent events"""
        print(f"\n{Colors.CYAN}Recent Events ({len(self.recent_events)} total):{Colors.RESET}")
        for event in self.recent_events[-10:]:
            print(f"  {json.dumps(event, default=str)[:100]}...")
    
    def _show_logs(self):
        """Show reasoning audit log"""
        log_path = Path("agent/logs/reasoning_audit.log")
        print(f"\n{Colors.CYAN}Reasoning Audit Log:{Colors.RESET}")
        if log_path.exists():
            with open(log_path, 'r') as f:
                lines = f.readlines()[-20:]  # Last 20 lines
                for line in lines:
                    print(f"  {line.rstrip()}")
        else:
            print(f"  {Colors.YELLOW}No log file yet - run /think to create{Colors.RESET}")
    
    def _show_prefs(self):
        """Show stored preferences"""
        print(f"\n{Colors.CYAN}Stored Preferences:{Colors.RESET}")
        prefs = self.learning_engine.get_preferences()
        if prefs:
            for key, value in prefs.items():
                print(f"  {key}: {value}")
        else:
            print(f"  {Colors.YELLOW}No preferences stored yet{Colors.RESET}")
    
    def send_voice_command(self, text: str):
        """Simulate sending a voice command"""
        print(f"\n{Colors.HEADER}📢 Voice Command: \"{text}\"{Colors.RESET}")
        print(f"{Colors.CYAN}Processing...{Colors.RESET}")
        
        # Publish voice command event
        self.event_bus.publish({
            "type": "voice_command",
            "payload": {"text": text, "source": "test_cli"},
            "timestamp": time.time()
        })
        
        # Give LLM agent time to process
        time.sleep(2)
        
    def test_transcription(self, file_path: str, auto_execute: bool = False):
        """Test audio transcription"""
        print(f"\n{Colors.CYAN}Transcribing {file_path}...{Colors.RESET}")
        
        # Check if file exists relative to current dir or absolute
        path = Path(file_path)
        if not path.exists():
            # Try relative to script dir
            script_dir = Path(__file__).parent
            path = script_dir / file_path
        
        start_time = time.time()
        result = self.transcriber.transcribe(str(path))
        duration = time.time() - start_time
        
        print(f"{Colors.GREEN}Transcription Result ({duration:.2f}s):{Colors.RESET}")
        print(f"{Colors.BOLD}\"{result}\"{Colors.RESET}")
        
        # Executes if auto_execute is True, otherwise asks
        if not result.startswith("Error"):
            if auto_execute:
                self.send_voice_command(result)
            else:
                print(f"\n{Colors.YELLOW}Execute this as a voice command? (y/n){Colors.RESET}")
                choice = input("arvis> ").lower()
                if choice == 'y':
                    self.send_voice_command(result)
                
    def _test_recording(self):
        """Test authentication recording"""
        output_file = "voice_cmd.wav"
        saved_file = self.recorder.record(duration=5, output_file=output_file)
        
        if saved_file:
            self.test_transcription(saved_file, auto_execute=True)
            
            # clean up
            try:
                os.remove(saved_file)
            except:
                pass
                
    def _run_chat_mode(self):
        """Continuous chat loop using RealtimeSTT (wake word + VAD + transcription)"""
        from RealtimeSTT import AudioToTextRecorder
        
        log_print(f"\n{Colors.HEADER}{Colors.BOLD}🦜 Chat Mode (RealtimeSTT){Colors.RESET}")
        log_print("Say 'Jarvis' to wake me up. Ctrl+C to stop.")
        log_print(f"{Colors.YELLOW}Initializing RealtimeSTT...{Colors.RESET}")
        
        def process_text(text: str, is_follow_up: bool = False):
            """Callback when transcription is complete"""
            
            if not text or not text.strip():
                return
            
            # If this is a follow-up response, check if it matches
            if is_follow_up:
                result = self.voice_pipeline.check_follow_up_response(text)
                
                if result["action"] == "ignore":
                    log_print(f"{Colors.YELLOW}[FollowUp] Ignored: '{text}' (no match){Colors.RESET}")
                    return  # Stay in follow-up mode
                    
                elif result["action"] == "exit_politely":
                    exit_msg = self.voice_pipeline.get_follow_up_exit_message()
                    log_print(f"{Colors.YELLOW}[FollowUp] Timeout - {exit_msg}{Colors.RESET}")
                    self.voice_pipeline.speak(exit_msg)
                    in_follow_up = False
                    return
                    
                # result["action"] == "process" - continue processing as normal
                log_print(f"{Colors.GREEN}[FollowUp] Matched: '{result['matched']}'{Colors.RESET}")
                
            log_print(f"\n{Colors.GREEN}You said: \"{text}\"{Colors.RESET}")
            
            # Check for exit phrase
            if "exit" in text.lower() or "stop listening" in text.lower():
                log_print("Exiting chat mode...")
                return
            
            # === STREAMING MODE ===
            log_print(f"{Colors.BLUE}🧠 Sending to LLM ({self.llm_agent.provider})...{Colors.RESET}")
            
            # Create event for streaming LLM
            event = {
                "type": "voice_command",
                "payload": {"text": text, "source": "test_cli"},
                "timestamp": time.time()
            }
            
            # Create a wrapper to log tokens
            full_response = []
            def logged_stream():
                token_stream = self.llm_agent.handle_streaming(event)
                for token in token_stream:
                    full_response.append(token)
                    # Show first part of each token (colored)
                    display = token[:50].replace('\n', '↵')
                    log_print(f"{Colors.YELLOW}▸ {display}{Colors.RESET}", "debug")
                    yield token
            
            # Feed streaming tokens through pipeline
            log_print(f"{Colors.BLUE}📤 Streaming response:{Colors.RESET}")
            self.voice_pipeline.process_llm_stream(logged_stream())
            
            # Show full response summary
            response_text = "".join(full_response)
            log_print(f"\n{Colors.GREEN}━━━ Full LLM Response ━━━{Colors.RESET}")
            log_print(f"{Colors.CYAN}{response_text}{Colors.RESET}")
            log_print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.RESET}")
            
            # Process queued tool calls (execute device commands)
            tools = self.voice_pipeline.get_pending_tools()
            if tools:
                log_print(f"\n{Colors.BLUE}🔧 Executing {len(tools)} tool(s):{Colors.RESET}")
            for tool_data in tools:
                tool_name = tool_data.get('tool', '')
                args = tool_data.get('args', {})
                
                log_print(f"  {Colors.CYAN}→ {tool_name}({args}){Colors.RESET}")
                if tool_name in ('turn_on', 'turn_off', 'create_routine', 'run_routine'):
                    self.event_bus.publish({
                        "type": "tool_calls_generated",
                        "payload": [{"tool": tool_name, "args": args}],
                        "source": "voice_pipeline",
                        "timestamp": time.time()
                    })
            
            # Wait for audio to finish playing
            while self.voice_pipeline.is_speaking():
                time.sleep(0.1)
            
            # Check if we should enter follow-up mode
            log_print(f"[DEBUG] Checking follow_up_mode: {self.voice_pipeline.follow_up_mode}", "debug")
            if self.voice_pipeline.follow_up_mode:
                # FOLLOW-UP MODE: Listen for response WITHOUT wake word
                # Do this HERE inside the callback, before returning
                log_print(f"{Colors.CYAN}🔄 Follow-up mode - listening for response (10s)...{Colors.RESET}")
                
                # RESET the timer NOW - so user has full 10 seconds AFTER TTS finishes
                import time as time_module
                self.voice_pipeline.last_question_time = time_module.time()
                
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                
                try:
                    with sr.Microphone() as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        audio = recognizer.listen(source, timeout=10, phrase_time_limit=5)
                        
                        try:
                            # Use Google's free speech recognition (no model download needed)
                            follow_up_text = recognizer.recognize_google(audio)
                            log_print(f"{Colors.GREEN}[FollowUp] Heard: '{follow_up_text}'{Colors.RESET}")
                            
                            if follow_up_text and follow_up_text.strip():
                                # Check if it matches expected responses
                                result = self.voice_pipeline.check_follow_up_response(follow_up_text)
                                log_print(f"[DEBUG] check_follow_up_response returned: {result}", "debug")
                                
                                if result["action"] == "process":
                                    log_print(f"{Colors.GREEN}[FollowUp] Matched: '{result['matched']}'{Colors.RESET}")
                                    # Recursively process the follow-up (will call LLM again)
                                    process_text(follow_up_text, is_follow_up=False)
                                elif result["action"] == "ignore":
                                    log_print(f"{Colors.YELLOW}[FollowUp] No match, trying again...{Colors.RESET}")
                                elif result["action"] == "exit_politely":
                                    log_print(f"{Colors.YELLOW}[FollowUp] Timeout detected, exiting...{Colors.RESET}")
                                    
                        except sr.UnknownValueError:
                            log_print(f"{Colors.YELLOW}[FollowUp] Couldn't understand audio{Colors.RESET}")
                except sr.WaitTimeoutError:
                    log_print(f"{Colors.YELLOW}[FollowUp] Timeout - no speech detected{Colors.RESET}")
                    exit_msg = self.voice_pipeline.get_follow_up_exit_message()
                    self.voice_pipeline.speak(exit_msg)
                except Exception as e:
                    log_print(f"{Colors.RED}[FollowUp] Error: {e}{Colors.RESET}", "error")
                finally:
                    self.voice_pipeline.exit_follow_up("completed")
                    
                log_print(f"\n{Colors.CYAN}💤 Listening... (say 'Jarvis'){Colors.RESET}")
            else:
                log_print(f"\n{Colors.CYAN}💤 Listening... (say 'Jarvis'){Colors.RESET}")
        
        def on_realtime_update(text: str):
            """Show real-time transcription updates"""
            if text.strip():
                print(f"\r{Colors.YELLOW}[...] {text}{Colors.RESET}", end="", flush=True)
        
        try:
            # Initialize main RealtimeSTT with wake word
            recorder = AudioToTextRecorder(
                model="base",  # Whisper model size
                language="en",
                device="cuda",  # Force CUDA device
                compute_type="int8",  # More compatible than float16
                silero_sensitivity=0.4,
                webrtc_sensitivity=2,
                post_speech_silence_duration=0.6,
                min_length_of_recording=0.5,
                min_gap_between_recordings=0,
                enable_realtime_transcription=True,
                realtime_processing_pause=0.1,
                on_realtime_transcription_update=on_realtime_update,
                wakeword_backend="pvporcupine",  # Use Porcupine engine
                wake_words="jarvis",  # Just "Jarvis" - no "hey" needed!
                wake_word_activation_delay=0.5,
            )
            
            print(f"{Colors.GREEN}✅ RealtimeSTT ready!{Colors.RESET}")
            print(f"{Colors.CYAN}💤 Listening... (say 'Jarvis'){Colors.RESET}")
            
            # Main listening loop - simple wake word mode
            # Follow-up listening is handled inside process_text callback
            while True:
                recorder.text(process_text)
                
        except KeyboardInterrupt:
            print("\nStopping chat mode...")
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                recorder.shutdown()
            except:
                pass
    
    def run(self):
        """Main CLI loop"""
        print(f"\n{Colors.GREEN}Ready! Type a command or /help{Colors.RESET}")
        print()
        
        try:
            while True:
                try:
                    user_input = input(f"{Colors.BOLD}arvis> {Colors.RESET}").strip()
                except EOFError:
                    break
                
                if not user_input:
                    continue
                
                # Handle special commands
                if user_input.startswith("/"):
                    cmd = user_input.lower()
                    
                    if cmd in ("/quit", "/exit", "/q"):
                        print(f"\n{Colors.YELLOW}Goodbye!{Colors.RESET}")
                        break
                    elif cmd == "/help":
                        self._show_help()
                    elif cmd == "/think":
                        self._test_think_tool()
                    elif cmd == "/memory":
                        self._test_memory_tool()
                    elif cmd == "/state":
                        self._show_state()
                    elif cmd == "/history":
                        self._show_history()
                    elif cmd == "/logs":
                        self._show_logs()
                    elif cmd == "/prefs":
                        self._show_prefs()
                    elif cmd.startswith("/transcribe"):
                        parts = user_input.split(maxsplit=1)
                        if len(parts) > 1:
                            self.test_transcription(parts[1])
                        else:
                            print(f"{Colors.RED}Usage: /transcribe <filepath>{Colors.RESET}")
                    elif cmd == "/record":
                        self._test_recording()
                    elif cmd == "/chat":
                        self._run_chat_mode()
                    elif cmd == "/prefs":
                        self._show_prefs()
                    else:
                        print(f"{Colors.RED}Unknown command: {cmd}{Colors.RESET}")
                else:
                    # Treat as voice command
                    self.send_voice_command(user_input)
                
                print()
                
        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}Interrupted. Goodbye!{Colors.RESET}")


def main():
    # Check for API key
    if not os.environ.get("GROQ_API_KEY"):
        print(f"{Colors.RED}⚠️  GROQ_API_KEY not found in environment!{Colors.RESET}")
        print("Set it in .env file or export GROQ_API_KEY=your_key")
        print("Continuing anyway (LLM calls will fail)...")
        print()
    
    cli = TestCLI()
    cli.run()


if __name__ == "__main__":
    main()
