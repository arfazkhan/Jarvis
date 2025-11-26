"""
Persona Profiles
----------------
Loads and manages persona definitions from configuration.
"""

import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

@dataclass
class Persona:
    id: str
    name: str
    description: str
    style_instructions: List[str]
    allowed_features: Dict[str, Any]

class PersonaProfiles:
    def __init__(self, config_path: str = "config/personality/personas.yaml"):
        self.personas: Dict[str, Persona] = {}
        self._load_config(config_path)

    def _load_config(self, path: str):
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
                for pid, pdata in data.get("personas", {}).items():
                    self.personas[pid] = Persona(
                        id=pid,
                        name=pdata.get("name", pid),
                        description=pdata.get("description", ""),
                        style_instructions=pdata.get("style_instructions", []),
                        allowed_features=pdata.get("allowed_features", {})
                    )
        except FileNotFoundError:
            print(f"Warning: Persona config not found at {path}")
        except Exception as e:
            print(f"Error loading personas: {e}")

    def get_persona(self, persona_id: str) -> Optional[Persona]:
        return self.personas.get(persona_id)

    def get_default_persona(self) -> str:
        return "jarvis_style" # Default as per PRD
