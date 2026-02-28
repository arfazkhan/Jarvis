"""
ARVIS Tool Schemas
------------------
Centralized tool definitions for LLM function calling.
Enhanced with new tools: think, log_memory, create_mission, update_mission_status
"""

# Groq API format for tool schemas
TOOL_SCHEMAS = [
    # ═══════════════════════════════════════════════════════════
    # DEVICE CONTROL TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "turn_on",
            "description": "Turn on a device endpoint. Use for lights, appliances, switches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Unique identifier for the device (e.g., 'living_room_light_main')"
                    },
                    "endpoint": {
                        "type": "integer",
                        "description": "Endpoint number to control (default: 1)"
                    },
                    "brightness": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "Optional brightness level for dimmable lights (0-100%)"
                    },
                    "color_temp": {
                        "type": "integer",
                        "minimum": 2700,
                        "maximum": 6500,
                        "description": "Optional color temperature in Kelvin (2700=warm, 6500=cool)"
                    }
                },
                "required": ["device_id", "endpoint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "turn_off",
            "description": "Turn off a device endpoint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Unique identifier for the device"
                    },
                    "endpoint": {
                        "type": "integer",
                        "description": "Endpoint number to control"
                    }
                },
                "required": ["device_id", "endpoint"]
            }
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # REASONING TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Internal reasoning scratchpad. Use before safety-critical decisions, ambiguous commands, or multi-step planning. The user does NOT see this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your internal thoughts about context, safety, user intent, and planned actions"
                    }
                },
                "required": ["reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Request clarification when uncertain. Use sparingly - only when truly ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Clear, concise question to ask the user"
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional suggested responses (2-4 options)"
                    }
                },
                "required": ["question"]
            }
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # ROUTINE TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "create_routine",
            "description": "Create a new automation routine with trigger and actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Human-readable routine name"
                    },
                    "trigger": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["time", "event", "state"]},
                            "condition": {"type": "string"}
                        },
                        "description": "What activates this routine"
                    },
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "args": {"type": "object"}
                            },
                            "required": ["tool", "args"]
                        },
                        "description": "List of actions to execute"
                    }
                },
                "required": ["name", "trigger", "actions"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "modify_routine",
            "description": "Modify an existing routine by adding/removing steps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "delta": {"type": "object"}
                },
                "required": ["name", "delta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_routine",
            "description": "Execute an existing routine by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "routine_name": {
                        "type": "string",
                        "description": "Name of the routine to execute"
                    }
                },
                "required": ["routine_name"]
            }
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # MEMORY & LEARNING TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "log_memory",
            "description": "Store an observation or preference for future reference. Use to learn user patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the memory (e.g., 'morning_light_preference')"
                    },
                    "knowledge": {
                        "type": "string",
                        "description": "The observation or preference to store"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["create", "update", "delete"],
                        "description": "Whether to create new, update existing, or delete memory"
                    },
                    "existing_id": {
                        "type": "string",
                        "description": "ID of existing memory if updating or deleting"
                    }
                },
                "required": ["title", "knowledge", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_note",
            "description": "Log a general observation for audit trail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Observation to log"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["safety", "user_behavior", "device_state", "error"],
                        "description": "Category for the note"
                    }
                },
                "required": ["note"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "teach_alias",
            "description": "Teach the system a custom name for a device. Use when user says things like 'call the bedroom light reading lamp' or 'remember that X means Y'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "alias": {
                        "type": "string",
                        "description": "The custom name/alias the user wants to use (e.g., 'reading lamp', 'movie lights')"
                    },
                    "device_id": {
                        "type": "string",
                        "description": "The actual device ID to map to (e.g., 'bedroom_lamp', 'living_room_light')"
                    }
                },
                "required": ["alias", "device_id"]
            }
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # MISSION TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "create_mission",
            "description": "Create a multi-step mission with sequential layers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Mission name (e.g., 'date_night_prep')"
                    },
                    "description": {
                        "type": "string",
                        "description": "What this mission accomplishes"
                    },
                    "layers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "actions": {"type": "array"}
                            }
                        },
                        "description": "Ordered layers of actions to execute"
                    }
                },
                "required": ["name", "layers"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_mission_status",
            "description": "Update the status of a mission step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "string"},
                    "step_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "failed", "cancelled"]
                    }
                },
                "required": ["mission_id", "step_id", "status"]
            }
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # SECURITY TOOLS
    # ═══════════════════════════════════════════════════════════
    {
        "type": "function",
        "function": {
            "name": "request_pin_verification",
            "description": "Request PIN verification for critical operations. Use before destructive actions (delete, reset, destroy), developer mode access, or security bypass attempts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "description": "Description of the critical operation requiring verification"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this operation requires security verification"
                    }
                },
                "required": ["operation", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_pin",
            "description": "Verify a user-provided PIN for security authentication.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pin": {
                        "type": "string",
                        "description": "The PIN entered by the user (4-8 digits)"
                    }
                },
                "required": ["pin"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "setup_security_pin",
            "description": "Set up or change the security PIN. Only use when user explicitly asks to set up or change their PIN.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_pin": {
                        "type": "string",
                        "description": "New security PIN (4-8 digits only)"
                    }
                },
                "required": ["new_pin"]
            }
        }
    }
]
