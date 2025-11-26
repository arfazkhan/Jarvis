"""
Scene Resolver
--------------
Resolves abstract scene definitions into concrete action lists.
Handles:
1. Target expansion (e.g., "type:light" -> ["light_1", "light_2"])
2. Dynamic overrides (Time of day, etc.)
"""

import time
from typing import List, Dict, Any
from agent_cognitive.context_graph import ContextGraph
from agent_plan.scene_engine.scene_definitions import DEFAULT_SCENES, Scene, SceneRule

class SceneResolver:
    def __init__(self, context_graph: ContextGraph):
        self.context = context_graph

    def resolve_scene(self, scene_name: str) -> List[Dict[str, Any]]:
        """
        Convert a scene name into a list of executable actions.
        """
        scene = DEFAULT_SCENES.get(scene_name)
        if not scene:
            print(f"[SceneResolver] Unknown scene: {scene_name}")
            return []
            
        actions = []
        
        for rule in scene.rules:
            concrete_actions = self._resolve_rule(rule)
            actions.extend(concrete_actions)
            
        return actions

    def _resolve_rule(self, rule: SceneRule) -> List[Dict[str, Any]]:
        """Resolve a single rule into one or more actions"""
        targets = []
        
        if rule.target.startswith("type:"):
            # Expand type selector
            device_type = rule.target.split(":")[1]
            # Query ContextGraph for devices of this type
            # Assuming context graph has nodes with type="device" and attribute "device_type"
            # Or just type="light"
            # My ContextGraph implementation: add_node(id, type, attrs)
            # So I should query nodes where type == device_type
            nodes = self.context.get_nodes_by_type(device_type)
            targets = [n["id"] for n in nodes]
            
            # Fallback if no devices found in graph (for testing/MVP)
            if not targets:
                # Mock expansion
                if device_type == "light":
                    targets = ["light_living_room", "light_kitchen"]
        else:
            # Direct target
            targets = [rule.target]
            
        actions = []
        for target in targets:
            action = {
                "action": rule.action,
                "params": rule.params.copy()
            }
            action["params"]["device"] = target # Standardize target as 'device' param
            # Or keep it separate? PlanExecutor expects 'params' to contain target info usually.
            # My SafetyValidator checks params.get("device") or params.get("target").
            
            actions.append(action)
            
        return actions
