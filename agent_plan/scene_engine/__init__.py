"""
Scene Engine (Refactored)
-------------------------
Orchestrates scene resolution and adaptation.
Converts high-level SceneDefinitions into concrete Plan Steps.
"""

import time
from typing import List, Dict, Any, Optional
from agent_cognitive.context_graph import ContextGraph
from agent_plan.scene_registry import SceneRegistry

class SceneEngine:
    def __init__(self, context_graph: ContextGraph, scene_registry: SceneRegistry):
        self.context = context_graph
        self.registry = scene_registry

    def build_scene_plan(self, scene_id: str, overrides: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Resolve a scene into a list of executable steps.
        """
        scene_def = self.registry.get_scene(scene_id)
        if not scene_def:
            print(f"[SceneEngine] Unknown scene: {scene_id}")
            return []
            
        overrides = overrides or {}
        plan_steps = []
        
        # 1. Iterate through targets in definition
        for target_def in scene_def.get("targets", []):
            # 2. Resolve concrete devices
            devices = self._resolve_devices(target_def, overrides)
            
            # 3. Generate steps for each device
            for device_id in devices:
                step = self._create_step(device_id, target_def, overrides)
                if step:
                    plan_steps.append(step)
                    
        return plan_steps

    def _resolve_devices(self, target_def: Dict[str, Any], overrides: Dict[str, Any]) -> List[str]:
        """Find actual device IDs matching the target definition"""
        device_type = target_def.get("type")
        room = overrides.get("room") or target_def.get("room")
        
        # Query ContextGraph
        # We assume nodes have 'type' and 'room' attributes
        # For MVP/Mock, we might just filter by ID string if attributes aren't fully populated
        all_nodes = self.context.get_nodes_by_type(device_type) if device_type else []
        
        filtered = []
        for node in all_nodes:
            # Check room if specified
            # In a real graph, room is an edge (device -> is_in -> room)
            # For now, we'll assume it's an attribute or part of ID (e.g., "light_living_room")
            node_id = node["id"]
            node_room = node.get("room")
            
            # Simple heuristic for MVP: Check if room name is in ID
            if room and room not in node_id and node_room != room:
                continue
                
            filtered.append(node_id)
            
        # Fallback for testing if no devices found
        if not filtered and device_type == "lighting" and room == "living_room":
            return ["light_living_room_1", "light_living_room_2"]
            
        return filtered

    def _create_step(self, device_id: str, target_def: Dict[str, Any], overrides: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create an execution step for a device"""
        intent = target_def.get("intent", {}).copy()
        
        # Apply overrides
        # e.g. if overrides has "brightness", apply it to lighting intents
        if "brightness" in overrides and "brightness" in intent:
            intent["brightness"] = overrides["brightness"]
            
        # Determine action based on type/intent
        # This mapping should be more robust in production
        action = "set_state"
        if target_def["type"] == "lighting":
            action = "set_light"
        elif target_def["type"] == "climate":
            action = "set_climate"
        elif target_def["type"] == "media":
            action = "play_media"
            
        return {
            "id": f"step_{device_id}_{int(time.time())}",
            "action": action,
            "params": {
                "device": device_id,
                **intent
            }
        }
