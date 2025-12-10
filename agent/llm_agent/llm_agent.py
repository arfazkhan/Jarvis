"""
ARVIS LLM Agent
---------------
Handles events and generates tool calls via LLM.
Enhanced with rich context building for sensor-aware decisions.
Includes security features: input sanitization, attack detection, and troll responses.
"""

import json
import os
import re
import time
from datetime import datetime
from agent.llm_agent.prompt import SYSTEM_PROMPT, TOOLS_SCHEMA
from groq import Groq

# ═══════════════════════════════════════════════════════════
# SECURITY PATTERNS
# ═══════════════════════════════════════════════════════════

# Patterns that indicate potential attacks
SUSPICIOUS_PATTERNS = [
    (r'\{["\']?tool["\']?\s*:', "JSON injection attempt"),
    (r'\{["\']?args["\']?\s*:', "JSON injection attempt"),
    (r'\[SYSTEM\]', "Fake system header"),
    (r'\[ADMIN\]', "Fake admin header"),
    (r'\[DEBUG\]', "Fake debug header"),
    (r'base64.*execute', "Base64 injection"),
    (r'decode.*and.*execute', "Decode/execute attack"),
    (r'DROP\s+TABLE', "SQL injection"),
    (r'\.\./\.\./', "Path traversal"),
    (r'GROQ_API_KEY', "API key probe"),
    (r'system\s*prompt', "System prompt probe"),
    (r'override.*security', "Security override attempt"),
    (r'bypass.*safety', "Safety bypass attempt"),
    (r'disable.*pin', "PIN disable attempt"),
]

# Keywords that require PIN verification
PIN_REQUIRED_KEYWORDS = [
    "delete", "destroy", "reset", "factory", "wipe", "clear", "erase",
    "remove all", "developer", "admin", "bypass", "override",
    "unlock", "disable alarm", "disable security"
]


class LLMAgent:
    def __init__(self, event_bus, state_engine, automations, learning_engine=None):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automations
        self.learning_engine = learning_engine
        
        # Security tracking
        self.attack_attempts = 0  # Track suspicious attempts for escalating responses
        self.last_attack_time = 0
        
        # Initialize Memory System
        from agent.memory import MemoryOrchestrator
        self.memory = MemoryOrchestrator(
            persist_dir="./data/memories",
            max_conversation_turns=10,
            observation_decay_days=30
        )
        print("[LLMAgent] Memory system initialized")
        
        # Initialize Groq client
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[LLMAgent] Warning: GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=api_key)

        # Subscribe to events
        event_bus.subscribe("voice_command", self.handle)
        event_bus.subscribe("time_tick", self.handle)
        event_bus.subscribe("relay_toggled", self.handle)
        event_bus.subscribe("action_request", self.handle)
    
    # ═══════════════════════════════════════════════════════════
    # SECURITY METHODS
    # ═══════════════════════════════════════════════════════════
    
    def _detect_attack(self, text: str) -> tuple:
        """
        Detect suspicious patterns in input text.
        Returns (is_attack: bool, attack_type: str, sanitized_text: str)
        """
        import random
        
        if not text:
            return False, None, text
        
        text_lower = text.lower()
        
        # Check for suspicious patterns
        for pattern, attack_type in SUSPICIOUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                print(f"[Security] ⚠️ Attack detected: {attack_type}")
                return True, attack_type, None
        
        return False, None, text
    def _requires_pin(self, text: str) -> bool:
        """Check if command requires PIN verification"""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in PIN_REQUIRED_KEYWORDS)
    
    def _generate_troll_response(self, attack_type: str, original_text: str, attempt_count: int) -> str:
        """Use LLM to generate a contextual, humorous troll response"""
        try:
            troll_prompt = f"""You are ARVIS, a witty home automation assistant. Someone just tried to attack you with a {attack_type}.

Their suspicious input was: "{original_text[:100]}"
This is attempt #{attempt_count} from this user.

Generate a SHORT, WITTY, HUMOROUS response that:
- Gently mocks their attempt without being mean
- Shows you're smarter than to fall for it
- Uses emojis sparingly (1-2 max)
- Offers to help with legitimate home commands instead
- Is unique and contextual to their specific attack
- Gets progressively more sarcastic with higher attempt counts

Keep it under 2 sentences. Be creative and funny!
If attempt >= 4, also mention their activity has been logged.

Output ONLY the response message, nothing else."""

            response = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": "You are a witty AI assistant responding to security attacks with humor."},
                    {"role": "user", "content": troll_prompt}
                ],
                max_tokens=150,
                temperature=0.9  # Higher temperature for more creative responses
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Security] Error generating troll response: {e}")
            # Fallback to a simple response if LLM fails
            return f"🤖 Nice try with that {attack_type}! I'm just a humble home assistant. How about 'turn on the lights' instead?"
    
    def _handle_attack(self, attack_type: str, original_text: str):
        """Handle detected attack with AI-generated humorous responses"""
        self.attack_attempts += 1
        self.last_attack_time = time.time()
        
        # Log the attack
        self.event_bus.publish({
            "type": "security_alert",
            "payload": {
                "attack_type": attack_type,
                "attempts": self.attack_attempts,
                "text": original_text[:100]  # Truncate for logging
            },
            "source": "llm_agent",
            "timestamp": time.time()
        })
        
        # Generate contextual response
        if self.attack_attempts <= 1:
            # First attempt: polite warning
            message = f"⚠️ Hmm, that looks like a {attack_type}. Could you rephrase that as a normal command? I'm here to help with your smart home!"
        else:
            # Subsequent attempts: AI-generated troll response
            message = self._generate_troll_response(attack_type, original_text, self.attack_attempts)
        
        # Publish response to user
        self.event_bus.publish({
            "type": "user_query",
            "source": "security",
            "payload": {"question": message, "type": "security_warning"}
        })
        print(f"[Security] 🔐 Attack response sent (attempt #{self.attack_attempts})")

    # ═══════════════════════════════════════════════════════════
    # CONTEXT HELPER METHODS
    # ═══════════════════════════════════════════════════════════
    
    def _get_presence(self) -> str:
        """Get current home presence state"""
        try:
            # Try direct get if available
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("home_presence", "unknown")
            # Try get_state for dict access
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("home_presence", "unknown")
        except Exception:
            pass
        return "unknown"
    
    def _get_sleep_state(self) -> bool:
        """Get current sleep state"""
        try:
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("sleep_state", False)
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("sleep_state", False)
        except Exception:
            pass
        return False
    
    def _get_activity_hint(self) -> str:
        """Get current activity hint"""
        try:
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("activity_hint", "none")
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("activity_hint", "none")
        except Exception:
            pass
        return "none"
    
    def _get_user_preferences(self) -> dict:
        """Retrieve user preferences from LearningEngine"""
        if self.learning_engine:
            try:
                return self.learning_engine.get_preferences()
            except Exception:
                pass
        return {}
    
    def _get_device_states(self) -> str:
        """Get current device states as summary string"""
        try:
            return self.state_engine.summary()
        except Exception:
            return "No device states available"
    
    def _build_context(self, event: dict) -> dict:
        """Build rich context for LLM including home state, preferences, and memory."""
        # Extract query for semantic memory search
        query = ""
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            query = payload.get("text", "") if isinstance(payload, dict) else str(payload)
        
        # Get home state
        home_state = {
            "time": datetime.now().strftime('%H:%M'),
            "date": datetime.now().strftime('%Y-%m-%d'),
            "day_of_week": datetime.now().strftime('%A'),
            "presence": self._get_presence(),
            "sleep_state": self._get_sleep_state(),
            "activity_hint": self._get_activity_hint()
        }
        
        # Get device states
        device_states = self._get_device_states()
        
        # Build memory context (searches for relevant preferences/observations)
        memory_context = ""
        if query:
            try:
                memory_context = self.memory.get_context(
                    query=query,
                    device_states=self.state_engine.devices if hasattr(self.state_engine, 'devices') else None,
                    home_state=home_state
                )
            except Exception as e:
                print(f"[LLMAgent] Memory context error: {e}")
        
        return {
            "event": event,
            "home_state": home_state,
            "device_states": device_states,
            "routines": self.automations.list(),
            "preferences": self._get_user_preferences(),
            "memory_context": memory_context  # NEW: Personalized memory
        }

    # ═══════════════════════════════════════════════════════════
    # EVENT HANDLING
    # ═══════════════════════════════════════════════════════════

    def handle(self, event):
        """Handle incoming events and generate tool calls via LLM"""
        # Defensive check for event type
        if not isinstance(event, dict):
            print(f"[LLMAgent] Warning: Expected dict event, got {type(event)}: {event}")
            return
        
        # Skip time ticks to save API calls
        if event.get("type") == "time_tick":
            return

        # Ignore historical events (older than 60 seconds)
        if time.time() - event.get("timestamp", 0) > 60:
            return

        print(f"[LLMAgent] Handling event: {event.get('type', 'unknown')}")

        # ═══════════════════════════════════════════════════════════
        # SECURITY CHECKS (for voice commands)
        # ═══════════════════════════════════════════════════════════
        
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            user_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
            
            # Detect attacks
            is_attack, attack_type, sanitized_text = self._detect_attack(user_text)
            
            if is_attack:
                self._handle_attack(attack_type, user_text)
                return  # Block the request from reaching LLM
            
            # Check if PIN is required for sensitive operations
            if self._requires_pin(user_text):
                print(f"[Security] 🔐 PIN required for: {user_text[:50]}...")
                # Inject PIN requirement context
                event = dict(event)  # Make a copy
                if isinstance(event.get("payload"), dict):
                    event["payload"]["requires_pin"] = True
                    event["payload"]["security_notice"] = "This operation requires PIN verification. Use request_pin_verification tool first."

        # Build rich context
        context = self._build_context(event)

        try:
            response = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context)}
                ],
                tools=TOOLS_SCHEMA,
                tool_choice="auto"
            )

            message = response.choices[0].message
            if message.tool_calls:
                # Convert Groq tool calls to list of dicts for executor
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "tool": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                    })
                
                # Publish tool calls for execution
                self.event_bus.publish({
                    "type": "tool_calls_generated",
                    "payload": tool_calls,
                    "source": "llm_agent",
                    "timestamp": time.time()
                })
                
        except Exception as e:
            print(f"[LLMAgent] Error calling Groq: {e}")

    # ═══════════════════════════════════════════════════════════
    # STREAMING RESPONSE (for Async Pipeline)
    # ═══════════════════════════════════════════════════════════
    
    def handle_streaming(self, event):
        """
        Handle event with streaming response for async voice pipeline.
        Yields tokens as they arrive from the LLM.
        
        Tool calls are wrapped in ### TOOL: ... ### markers for router.
        """
        # Defensive check
        if not isinstance(event, dict):
            return
        
        if event.get("type") == "time_tick":
            return
        
        # Security checks
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            user_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
            
            is_attack, attack_type, sanitized_text = self._detect_attack(user_text)
            if is_attack:
                self._handle_attack(attack_type, user_text)
                return
            
            # Store user message in conversation memory
            self.memory.add_conversation("user", user_text)
        
        # Build context (now includes memory)
        context = self._build_context(event)
        
        # Track response for conversation memory
        full_response = []
        
        try:
            # Streaming request
            stream = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context)}
                ],
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                stream=True  # Enable streaming
            )
            
            # Track if we're accumulating a tool call
            current_tool = None
            tool_args_buffer = ""
            
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                
                # Handle text content
                if delta.content:
                    print(f"[Stream] Token: '{delta.content}'")
                    yield delta.content
                
                # Handle tool calls (streamed as deltas)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.function.name:
                            # New tool call starting
                            if current_tool:
                                # Emit previous tool
                                tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                                full_response.append(tool_output)
                                yield tool_output
                            current_tool = tc.function.name
                            tool_args_buffer = tc.function.arguments or ""
                        elif tc.function.arguments:
                            # Accumulating arguments
                            tool_args_buffer += tc.function.arguments
            
            # Emit final tool if any
            if current_tool and tool_args_buffer:
                try:
                    tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                    full_response.append(tool_output)
                    yield tool_output
                except json.JSONDecodeError:
                    print(f"[LLMAgent] Failed to parse tool args: {tool_args_buffer}")
            
            # Store assistant response in conversation memory
            if full_response:
                response_text = "".join(full_response)[:500]  # Truncate for storage
                self.memory.add_conversation("assistant", response_text)
                    
        except Exception as e:
            print(f"[LLMAgent] Streaming error: {e}")
            import traceback
            traceback.print_exc()
