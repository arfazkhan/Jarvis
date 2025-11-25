"""
Dialogue Manager
----------------
Manages conversation state, history, and LLM interaction for natural dialogue.
Integrates with STT (input) and TTS (output).
"""

import os
import time
import json
from typing import List, Dict, Any, Optional
from groq import Groq

from config.settings import get_config
from agent.event_bus.event_bus import EventBus

CONFIG = get_config("conversation")
DIALOGUE_CONFIG = CONFIG.get("dialogue", {})
PERSONALITY_CONFIG = get_config("personality")

# Basic system prompt for conversation
BASE_SYSTEM_PROMPT = """You are Jarvis, an intelligent home automation assistant.
Your goal is to be helpful, concise, and friendly.
You have access to the home state and can control devices.
Keep responses short (1-2 sentences) unless asked for details.

If the user asks to perform an action that you cannot do directly but understand, output a JSON object with the intent and parameters.
Example: {"intent": "prepare_date_night", "steps": ["dim lights", "play music"]}
"""

from agent_conversation.intent_classifier import IntentClassifier

class DialogueManager:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.history: List[Dict[str, str]] = []
        self.last_interaction_time = 0
        self.classifier = IntentClassifier()
        
        # Initialize Groq client
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[DialogueManager] Warning: GROQ_API_KEY not found.")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)

        # Subscribe to voice input
        self.event_bus.subscribe("voice_input", self.handle_voice_input)

    def handle_voice_input(self, event: Dict[str, Any]):
        """Handle incoming voice text from STT"""
        text = event.get("payload", {}).get("text")
        if not text: return

        print(f"[DialogueManager] User said: {text}")
        
        # 1. Update session
        self._check_session_timeout()
        self.last_interaction_time = time.time()
        
        # 2. Add to history
        self.history.append({"role": "user", "content": text})
        
        # 3. Check for Intent (NLU)
        intent_res = self.classifier.classify(text)
        response_text = ""
        
        if intent_res["confidence"] > 0.8 and intent_res["intent"] != "unknown":
            # Handle command locally
            print(f"[DialogueManager] Detected intent: {intent_res['intent']}")
            response_text = self._handle_intent(intent_res)
        else:
            # Fallback to LLM
            response_text = self._generate_response()
        
        # 4. Add response to history
        if response_text:
            self.history.append({"role": "assistant", "content": response_text})
            print(f"[DialogueManager] Jarvis says: {response_text}")
            
            # 5. Publish for TTS
            self.event_bus.publish({
                "type": "voice_response",
                "source": "dialogue_manager",
                "payload": {"text": response_text}
            })

    def _handle_intent(self, intent_res: Dict[str, Any]) -> str:
        """Execute system action based on intent"""
        intent = intent_res["intent"]
        slots = intent_res["slots"]
        raw_text = intent_res.get("original_text", "")
        confidence = intent_res.get("confidence", 1.0)
        
        # Publish standardized action event for Executor (Phase 3)
        self.event_bus.publish({
            "type": "action_request",
            "source": "dialogue_manager",
            "payload": {
                "intent": intent,
                "target": slots.get("device") or slots.get("routine") or "unknown",
                "slots": slots,
                "raw_text": raw_text,
                "confidence": confidence
            }
        })
        
        # Generate simple confirmation response
        if intent == "turn_on":
            return f"Turning on {slots.get('device', 'device')} in {slots.get('location', 'here')}."
        elif intent == "turn_off":
            return f"Turning off {slots.get('device', 'device')}."
        elif intent == "set_routine":
            return f"Activating {slots.get('routine', 'routine')} mode."
        elif intent == "query_status":
            return f"Checking status of {slots.get('device', 'device')}."
            
        return "I understood the command but don't know how to execute it yet."

    def _generate_response(self) -> str:
        """Call LLM to generate response"""
        if not self.client:
            return "I'm sorry, my brain is offline (No API Key)."
            
        try:
            # Prepare messages
            messages = [
                {"role": "system", "content": self._get_system_prompt()},
            ] + self.history[-5:] # Keep last 5 turns
            
            completion = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                max_tokens=150
            )
            
            response = completion.choices[0].message.content.strip()
            
            # Check if response is JSON (Action Request from LLM)
            if response.startswith("{") and response.endswith("}"):
                try:
                    action_data = json.loads(response)
                    self.event_bus.publish({
                        "type": "action_request",
                        "source": "dialogue_manager",
                        "payload": {
                            "intent": action_data.get("intent", "unknown"),
                            "target": "complex_plan",
                            "slots": action_data,
                            "raw_text": self.history[-1]["content"],
                            "confidence": 0.9
                        }
                    })
                    return "I'm working on that plan."
                except json.JSONDecodeError:
                    pass
            
            return response
            
        except Exception as e:
            print(f"[DialogueManager] LLM Error: {e}")
            return "I'm having trouble thinking right now."

    def _get_system_prompt(self) -> str:
        """Construct system prompt with personality"""
        profile = PERSONALITY_CONFIG.get("profiles", {}).get("default_user", {})
        
        prompt = BASE_SYSTEM_PROMPT
        if profile.get("humor") == "high":
            prompt += " You have a witty sense of humor."
        if profile.get("formality") == "casual":
            prompt += " Speak casually."
            
        return prompt

    def _check_session_timeout(self):
        """Clear history if session timed out"""
        timeout = DIALOGUE_CONFIG.get("session_timeout_minutes", 30) * 60
        if time.time() - self.last_interaction_time > timeout:
            if self.history:
                print("[DialogueManager] Session timed out. Clearing history.")
                self.history = []
