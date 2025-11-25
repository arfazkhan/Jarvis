"""
Scene Definitions
-----------------
Defines the data model for Scenes and provides default templates.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

@dataclass
class SceneRule:
    target: str # device_id or "type:light"
    action: str # "turn_on", "set_color", etc.
    params: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Scene:
    name: str
    description: str
    rules: List[SceneRule]
    overrides: Dict[str, Any] = field(default_factory=dict) # dynamic logic hooks

# Default Scenes
DEFAULT_SCENES = {
    "cozy_mode": Scene(
        name="cozy_mode",
        description="Warm lighting and soft music for relaxation",
        rules=[
            SceneRule(target="type:light", action="set_color", params={"color": "warm_white", "brightness": 30}),
            SceneRule(target="curtains", action="close"),
            SceneRule(target="ac", action="set_temp", params={"temp": 24}),
            SceneRule(target="audio", action="play_playlist", params={"playlist": "lofi-evening"})
        ]
    ),
    "movie_mode": Scene(
        name="movie_mode",
        description="Dark room for movie watching",
        rules=[
            SceneRule(target="type:light", action="turn_off"),
            SceneRule(target="curtains", action="close"),
            SceneRule(target="tv", action="turn_on"),
            SceneRule(target="tv", action="set_app", params={"app": "netflix"})
        ]
    ),
    "work_mode": Scene(
        name="work_mode",
        description="Bright lighting for productivity",
        rules=[
            SceneRule(target="type:light", action="set_color", params={"color": "cool_white", "brightness": 100}),
            SceneRule(target="audio", action="play_playlist", params={"playlist": "deep-focus"})
        ]
    )
}
