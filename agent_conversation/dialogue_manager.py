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
from arvis_core.event_bus.event_bus import EventBus

CONFIG = get_config("conversation")
DIALOGUE_CONFIG = CONFIG.get("dialogue", {})
print(f"DEBUG: Loading DialogueManager. Initial DIALOGUE_CONFIG type: {type(DIALOGUE_CONFIG)}")

# Fallback for testing if config is mocked
if not isinstance(DIALOGUE_CONFIG, dict):
    print("DEBUG: DIALOGUE_CONFIG is not dict, falling back to empty dict")
    DIALOGUE_CONFIG = {}

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
from agent_home.agent_feedback.action_tone_adapter import ActionToneAdapter

from dataclasses import dataclass, field

@dataclass
class DialogueResult:
    """Structured result from DialogueManager"""
    response_text: Optional[str] = None
    action_request: Optional[Dict[str, Any]] = None
    mission_command: Optional[Dict[str, Any]] = None
    should_speak: bool = True

class DialogueManager:
    def __init__(self, personality_manager=None, mission_manager=None):
        self.personality_manager = personality_manager
        self.mission_manager = mission_manager
        self.history: List[Dict[str, str]] = []
        self.last_interaction_time = 0
        self.classifier = IntentClassifier()
        self.tone_adapter = ActionToneAdapter(personality_manager)
        
        # Initialize Groq client
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[DialogueManager] Warning: GROQ_API_KEY not found.")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)

    def process_input(self, text: str) -> DialogueResult:
        """Process natural language input and return structured result"""
        if not text: 
            return DialogueResult(should_speak=False)

        print(f"[DialogueManager] User said: {text}")
        
        # 1. Update session
        self._check_session_timeout()
        self.last_interaction_time = time.time()
        
        # 2. Add to history
        self.history.append({"role": "user", "content": text})
        
        # 3. Check for Intent (NLU)
        intent_res = self.classifier.classify(text)
        result = DialogueResult()
        
        if intent_res["confidence"] > 0.8 and intent_res["intent"] != "unknown":
            # Handle command locally
            print(f"[DialogueManager] Detected intent: {intent_res['intent']}")
            result = self._handle_intent(intent_res)
        else:
            # Fallback to LLM
            response_text = self._generate_response()
            result.response_text = response_text
            
            # Check if response is JSON (Structured Output)
            if response_text and response_text.strip().startswith("{"):
                try:
                    import json
                    data = json.loads(response_text)
                    if "intent" in data:
                        print(f"[DialogueManager] Parsed JSON Action: {data['intent']}")
                        result.action_request = {
                            "intent": data["intent"],
                            "target": "complex_plan",
                            "slots": data.get("slots", {}),
                            "raw_text": text,
                            "confidence": 1.0
                        }
                        # If JSON has explicit response text, use it
                        if "response_text" in data:
                            result.response_text = data["response_text"]
                        else:
                            result.should_speak = False # Don't read raw JSON
                except json.JSONDecodeError:
                    print("[DialogueManager] Failed to parse JSON response")
        
        # 4. Add response to history
        if result.response_text:
            self.history.append({"role": "assistant", "content": result.response_text})
            print(f"[DialogueManager] Jarvis says: {result.response_text}")
            
        return result

    def _handle_intent(self, intent_res: Dict[str, Any]) -> DialogueResult:
        """Execute system action based on intent"""
        intent = intent_res["intent"]
        slots = intent_res["slots"]
        raw_text = intent_res.get("original_text", "")
        confidence = intent_res.get("confidence", 1.0)
        
        result = DialogueResult()
        
        # Generate simple confirmation response
        if intent == "turn_on":
            result.response_text = self.tone_adapter.get_confirmation("turn_on", slots)
            result.action_request = {
                "intent": intent,
                "target": slots.get("device") or slots.get("location") or "unknown",
                "slots": slots,
                "raw_text": raw_text,
                "confidence": confidence
            }
        elif intent == "turn_off":
            result.response_text = self.tone_adapter.get_confirmation("turn_off", slots)
            result.action_request = {
                "intent": intent,
                "target": slots.get("device") or "unknown",
                "slots": slots,
                "raw_text": raw_text,
                "confidence": confidence
            }
        elif intent == "set_routine":
            result.response_text = self.tone_adapter.get_confirmation("set_routine", slots)
            result.action_request = {
                "intent": intent,
                "target": slots.get("routine") or "unknown",
                "slots": slots,
                "raw_text": raw_text,
                "confidence": confidence
            }
        elif intent == "query_status":
            result.response_text = f"Checking status of {slots.get('device', 'device')}."
            # Query status might need an action request too, or just immediate response?
            # For now, let's assume it's an action
            result.action_request = {
                "intent": intent,
                "target": slots.get("device") or "unknown",
                "slots": slots,
                "raw_text": raw_text,
                "confidence": confidence
            }
            
        elif intent == "start_mission":
            mission_type = slots.get("mission_type", "unknown")
            result.response_text = f"Starting mission: {mission_type}."
            result.mission_command = {
                "command": "start",
                "mission_id": mission_type, # Using type as ID for now/template
                "trigger": "voice_command"
            }
        elif intent == "stop_mission":
            result.response_text = "Stopping current mission."
            result.mission_command = {
                "command": "stop",
                "mission_id": "current" # Needs resolution
            }
        elif intent == "mission_status":
            if self.mission_manager:
                status_summary = self._get_mission_status_summary()
                result.response_text = status_summary
            else:
                result.response_text = "I can't check missions right now (Mission Manager not connected)."
            
            result.mission_command = {
                "command": "status"
            }
        else:
            result.response_text = "I understood the command but don't know how to execute it yet."
            
        return result

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
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=messages,
                temperature=0.7,
                max_tokens=150
            )
            
            response = completion.choices[0].message.content.strip()
            
            # Check if response is JSON (Action Request from LLM)
            # NOTE: For now, we return string. If we want LLM actions, we'd parse here 
            # and return DialogueResult with action_request.
            # But the method signature is -> str.
            # Let's keep it simple: LLM returns text. 
            # If we want LLM actions, we should refactor _generate_response to return DialogueResult too.
            # But for this phase, let's assume LLM is mostly chat unless it outputs JSON.
            
            if response.startswith("{") and response.endswith("}"):
                # It's a JSON action?
                # We can't easily return it from here if signature is str.
                # But process_input calls this.
                # Let's just return the text for now, and maybe process_input can parse it?
                # Or better, let's stick to text responses for LLM fallback for now.
                pass
            
            return response
            
        except Exception as e:
            print(f"[DialogueManager] LLM Error: {e}")
            return "I'm having trouble thinking right now."

    def _get_system_prompt(self) -> str:
        """Construct system prompt with personality"""
        if self.personality_manager:
            try:
                context = self.personality_manager.get_personality_context()
                persona = context.get("persona", {})
                emotion = context.get("emotion", {})
                
                prompt = f"You are {persona.get('name', 'Jarvis')}. {persona.get('description', '')}\n"
                prompt += f"Current Emotion: {emotion.get('state', 'neutral')} (Confidence: {emotion.get('confidence', 0.5):.2f})\n"
                prompt += f"Style: {persona.get('style_instructions', '')}\n"
                prompt += "\n" + BASE_SYSTEM_PROMPT
                return prompt
            except Exception as e:
                print(f"[DialogueManager] Error getting personality context: {e}")
        
        # Fallback
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

    def _get_mission_status_summary(self) -> str:
        """Get natural language summary of active missions."""
        try:
            active_missions = self.mission_manager.get_active_missions()
            if not active_missions:
                return "There are no active missions right now."
            
            summary = "Current active missions:\n"
            for mission in active_missions:
                # Assuming mission object has .mission_type and .status
                # We might need to access .value if status is an Enum
                status_str = mission.status.value if hasattr(mission.status, 'value') else str(mission.status)
                summary += f"- {mission.mission_type.replace('_', ' ').title()}: {status_str.upper()}\n"
                
                # Add step info if available
                if mission.runtime_state:
                    # This assumes runtime_state is a dict
                    step_status = mission.runtime_state.get("step_status", {})
                    # Count completed steps
                    completed = sum(1 for s in step_status.values() if s == "success")
                    total = len(step_status)
                    if total > 0:
                        summary += f"  (Progress: {completed}/{total} steps)\n"
            
            return summary
        except Exception as e:
            print(f"[DialogueManager] Error getting mission status: {e}")
            return "I encountered an error while checking mission status."
