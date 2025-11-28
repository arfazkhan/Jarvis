"""
Plan Generator (Refactored)
---------------------------
Generates structured plans using a Hybrid Strategy:
1. Rule-based Scene Matching (Fast Path)
2. LLM-based Planning (Flexible Path)
"""

import os
import json
import time
from typing import List, Dict, Any, Optional
from groq import Groq

from config.settings import get_config
from agent_plan.scene_registry import SceneRegistry
from agent_plan.scene_engine import SceneEngine

# LLM Tools Schema
PLANNING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "propose_scene_plan",
            "description": "Propose a scene-based plan for a given user request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_id": {"type": "string", "description": "ID of the matched scene"},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "required": ["scene_id", "confidence"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_custom_plan",
            "description": "Return a multi-step plan of actions when no scene fits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "params": {"type": "object"}
                            },
                            "required": ["action", "params"]
                        }
                    },
                    "confidence": {"type": "number"},
                    "requires_confirmation": {"type": "boolean"}
                },
                "required": ["steps", "confidence"]
            }
        }
    }
]

from agent.llm_agent.prompt_planning import SYSTEM_PROMPT

class PlanGenerator:
    def __init__(self, scene_registry: SceneRegistry, scene_engine: SceneEngine):
        self.registry = scene_registry
        self.engine = scene_engine
        
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[PlanGenerator] Warning: GROQ_API_KEY not found.")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)

    def generate_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a plan for the given request.
        Request: {utterance, context, ...}
        Returns: Plan dict
        """
        utterance = request.get("utterance", "").lower()
        context = request.get("context", {})
        
        # 1. Fast Path: Rule-based Matching
        matched_scene = self._match_scene_rule(utterance)
        if matched_scene:
            print(f"[PlanGenerator] Rule matched scene: {matched_scene}")
            return self._build_scene_plan_object(matched_scene, context, origin="rules")
            
        # 2. LLM Path
        return self._generate_llm_plan(utterance, context)

    def _match_scene_rule(self, utterance: str) -> Optional[str]:
        """Simple keyword matching for scenes"""
        # In a real system, this would be more sophisticated or use NLU intent
        scenes = self.registry.list_scenes()
        for scene in scenes:
            # Check ID or tags
            if scene["id"] in utterance or any(tag in utterance for tag in scene.get("tags", [])):
                # Very naive matching: if "cozy" in utterance and "cozy" tag exists
                # Better: exact match on name or strong alias
                if scene["name"].lower() in utterance:
                    return scene["id"]
        return None

    def _generate_llm_plan(self, utterance: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Call LLM to generate plan"""
        if not self.client:
            return {"error": "LLM offline"}
            
        try:
            available_scenes = [s["id"] for s in self.registry.list_scenes()]
            
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Request: {utterance}\nAvailable Scenes: {available_scenes}\nContext: {context}"}
            ]
            
            completion = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=messages,
                tools=PLANNING_TOOLS,
                tool_choice="auto",
                temperature=0.1
            )
            
            tool_calls = completion.choices[0].message.tool_calls
            if tool_calls:
                tool_call = tool_calls[0]
                args = json.loads(tool_call.function.arguments)
                
                if tool_call.function.name == "propose_scene_plan":
                    return self._build_scene_plan_object(args["scene_id"], context, origin="llm", confidence=args.get("confidence", 0.9))
                    
                elif tool_call.function.name == "propose_custom_plan":
                    return {
                        "plan_id": f"plan_{int(time.time())}",
                        "type": "custom",
                        "origin": "llm",
                        "confidence": args.get("confidence", 0.8),
                        "steps": args.get("steps", []),
                        "requires_confirmation": args.get("requires_confirmation", False)
                    }
            
            return {"error": "No plan generated"}
            
        except Exception as e:
            print(f"[PlanGenerator] Error: {e}")
            return {"error": str(e)}

    def _build_scene_plan_object(self, scene_id: str, context: Dict[str, Any], origin: str, confidence: float = 1.0) -> Dict[str, Any]:
        """Helper to build a scene-based plan object"""
        # Resolve steps using SceneEngine
        steps = self.engine.build_scene_plan(scene_id, overrides=context.get("overrides"))
        
        return {
            "plan_id": f"plan_{int(time.time())}",
            "type": "scene",
            "scene_id": scene_id,
            "origin": origin,
            "confidence": confidence,
            "steps": steps,
            "requires_confirmation": False
        }
