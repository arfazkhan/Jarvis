"""
Scene Registry
--------------
Manages loading, storage, and retrieval of Scene Definitions.
Loads from config/scenes/*.json.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

class SceneRegistry:
    def __init__(self, scenes_dir: str = "config/scenes"):
        self.scenes_dir = Path(scenes_dir)
        self.scenes: Dict[str, Dict[str, Any]] = {}
        self._load_scenes()

    def _load_scenes(self):
        """Load all JSON scenes from the directory"""
        if not self.scenes_dir.exists():
            print(f"[SceneRegistry] Warning: Scenes directory {self.scenes_dir} not found.")
            return

        for file_path in self.scenes_dir.glob("*.json"):
            try:
                with open(file_path, "r") as f:
                    scene_def = json.load(f)
                    self._validate_scene(scene_def)
                    self.scenes[scene_def["id"]] = scene_def
                    print(f"[SceneRegistry] Loaded scene: {scene_def['id']}")
            except Exception as e:
                print(f"[SceneRegistry] Error loading {file_path}: {e}")

    def _validate_scene(self, scene_def: Dict[str, Any]):
        """Ensure required fields are present"""
        required = ["id", "name", "targets"]
        for field in required:
            if field not in scene_def:
                raise ValueError(f"Missing required field: {field}")

    def get_scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a scene definition by ID"""
        return self.scenes.get(scene_id)

    def list_scenes(self, category: str = None) -> List[Dict[str, Any]]:
        """List all scenes, optionally filtered by category"""
        if category:
            return [s for s in self.scenes.values() if s.get("category") == category]
        return list(self.scenes.values())

    def create_scene(self, scene_def: Dict[str, Any]):
        """Programmatically add a scene (in-memory for now)"""
        self._validate_scene(scene_def)
        self.scenes[scene_def["id"]] = scene_def
