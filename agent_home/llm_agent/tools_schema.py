"""
ARVIS Tool Schema
-----------------
Defines all 36 tools available to the LLM agent.
Separated from prompt.py for maintainability.
"""

TOOLS_SCHEMA = [
    # === Device Control ===
    {
        "type": "function",
        "function": {
            "name": "turn_on",
            "description": "Turn on a device endpoint with optional brightness and color temperature.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device identifier"},
                    "endpoint": {"type": "integer", "description": "Endpoint number"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Brightness percentage (0-100)"},
                    "color_temp": {"type": "integer", "minimum": 2700, "maximum": 6500, "description": "Color temperature in Kelvin"}
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
                    "device_id": {"type": "string", "description": "Device identifier"},
                    "endpoint": {"type": "integer", "description": "Endpoint number"}
                },
                "required": ["device_id", "endpoint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_state",
            "description": "Get the current state of a specific device. Use to answer 'Is the light on?' queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device identifier to check"}
                },
                "required": ["device_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "List all available devices and their current states. Use for device discovery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_room": {"type": "string", "description": "Optional room filter"},
                    "filter_type": {"type": "string", "description": "Optional device type filter (light, switch, sensor)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_brightness",
            "description": "Set brightness level for a light. Use for 'Dim to 50%' commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Light device identifier"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Brightness percentage"},
                    "transition_ms": {"type": "integer", "description": "Transition time in milliseconds"}
                },
                "required": ["device_id", "brightness"]
            }
        }
    },
    
    # === Timers ===
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a timer to execute an action after a delay. Use for 'Turn off in 10 minutes'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Timer name for reference"},
                    "delay_minutes": {"type": "integer", "minimum": 1, "description": "Minutes until action executes"},
                    "action": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"}
                        },
                        "description": "Action to execute when timer fires"
                    }
                },
                "required": ["name", "delay_minutes", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_timer",
            "description": "Cancel an active timer by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Timer name to cancel"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_timers",
            "description": "List all active timers with their remaining time.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    
    # === Routines ===
    {
        "type": "function",
        "function": {
            "name": "create_routine",
            "description": "Create an automation routine with a trigger and actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Routine name"},
                    "trigger": {"type": "string", "description": "Trigger condition (e.g., 'time:07:00', 'sunset', 'presence:home')"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "args": {"type": "object"}
                            },
                            "required": ["tool", "args"]
                        }
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
                    "delta": {
                        "type": "object",
                        "properties": {
                            "add_actions": {"type": "array", "items": {"type": "object"}},
                            "remove_actions": {"type": "array", "items": {"type": "string"}},
                            "new_trigger": {"type": "string"}
                        }
                    }
                },
                "required": ["name", "delta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_routine",
            "description": "Execute all actions inside a specific routine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Routine name to execute"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_routine",
            "description": "Delete an existing routine. Requires PIN verification for safety.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Routine name to delete"}
                },
                "required": ["name"]
            }
        }
    },
    
    # === User Interaction ===
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a question or provide a response. Use for clarification, confirmation, or conversational replies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The message to speak to the user"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional suggested responses (2-4 options)"
                    }
                },
                "required": ["message"]
            }
        }
    },
    
    # === Logging & Memory ===
    {
        "type": "function",
        "function": {
            "name": "log_note",
            "description": "Store an observational message in system history (for learning and audit).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The note to log"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_memory",
            "description": "Store a user preference or learned pattern for future reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Preference key (e.g., 'preferred_brightness', 'wake_time')"},
                    "value": {"type": "string", "description": "Preference value"},
                    "context": {"type": "string", "description": "When this preference applies"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search for relevant memories using natural language. Returns preferences and observations matching the query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to remember (e.g., 'brightness preferences', 'morning routine')"},
                    "memory_type": {"type": "string", "enum": ["preferences", "observations", "all"], "description": "Type of memory to search"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Max results (default 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "Delete a specific memory. Use for privacy requests like 'forget my preferences'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "ID of memory to delete"},
                    "memory_type": {"type": "string", "enum": ["preference", "observation"]},
                    "confirm": {"type": "boolean", "description": "Must be true to confirm deletion"}
                },
                "required": ["memory_id", "memory_type", "confirm"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_my_data",
            "description": "Export all user data (GDPR compliance). Returns all preferences, observations, and conversations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    
    # === Reasoning ===
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Internal reasoning step before taking action. Use for safety-critical decisions, ambiguous commands, or multi-step plans.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string", "description": "Your internal reasoning about what to do"}
                },
                "required": ["reasoning"]
            }
        }
    },
    
    # === Time & Utilities ===
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current date and time. Use when user asks about time, date, or scheduling.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    
    # === Security & PIN ===
    {
        "type": "function",
        "function": {
            "name": "request_pin_verification",
            "description": "Request PIN verification for critical operations like unlocking doors, factory reset, or security changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "description": "What operation requires PIN"},
                    "reason": {"type": "string", "description": "Why PIN is needed"}
                },
                "required": ["operation", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_pin",
            "description": "Verify user-provided PIN for critical operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pin": {"type": "string", "description": "The PIN provided by user"}
                },
                "required": ["pin"]
            }
        }
    },
    
    # === Missions (Multi-Step Tasks) ===
    {
        "type": "function",
        "function": {
            "name": "create_mission",
            "description": "Create a multi-step mission with goals and checkpoints.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Mission name"},
                    "goal": {"type": "string", "description": "What the mission accomplishes"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "condition": {"type": "string"}
                            }
                        }
                    }
                },
                "required": ["name", "goal", "steps"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_mission_status",
            "description": "Update the status of an ongoing mission.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_name": {"type": "string"},
                    "status": {"type": "string", "enum": ["in_progress", "completed", "failed", "paused"]},
                    "current_step": {"type": "integer"},
                    "notes": {"type": "string"}
                },
                "required": ["mission_name", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_mission",
            "description": "Cancel an ongoing mission. Use for 'Stop that' or 'Cancel' commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_name": {"type": "string", "description": "Mission to cancel"},
                    "reason": {"type": "string", "description": "Why cancelled"}
                },
                "required": ["mission_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "undo_last",
            "description": "Undo the last action. Use for 'Undo' or 'Go back' commands.",
            "parameters": {
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "description": "Confirm undo action"}
                },
                "required": []
            }
        }
    },
    
    # === Scenes ===
    {
        "type": "function",
        "function": {
            "name": "create_scene",
            "description": "Save current device states as a named scene. Use for 'Save this as movie mode'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Scene name"},
                    "device_ids": {"type": "array", "items": {"type": "string"}, "description": "Devices to include (empty = all)"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "activate_scene",
            "description": "Restore a saved scene. Use for 'Activate movie mode'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Scene name to activate"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_scenes",
            "description": "List all saved scenes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    
    # === External Services ===
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather. Use for context-aware decisions like 'Should I turn on AC?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "Location (default: home)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_notification",
            "description": "Send push notification to user's phone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Notification title"},
                    "message": {"type": "string", "description": "Notification body"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"], "description": "Priority level"}
                },
                "required": ["title", "message"]
            }
        }
    },
    
    # === Media & Announcements ===
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Control media playback (Spotify, TV, etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "pause", "stop", "next", "previous", "volume"]},
                    "target": {"type": "string", "description": "Device or service name"},
                    "value": {"type": "string", "description": "Song name, playlist, or volume level"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "announce",
            "description": "Broadcast voice announcement to speakers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Message to announce"},
                    "rooms": {"type": "array", "items": {"type": "string"}, "description": "Rooms to announce in (empty = all)"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_device",
            "description": "Blink or beep a device to locate it. Use for 'Where is my lamp?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device to find"}
                },
                "required": ["device_id"]
            }
        }
    },
    
    # === Energy & Modes ===
    {
        "type": "function",
        "function": {
            "name": "get_energy_usage",
            "description": "Get energy consumption data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": ["today", "week", "month"], "description": "Time period"},
                    "device_id": {"type": "string", "description": "Specific device (empty = whole home)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_away_mode",
            "description": "Enable/disable away mode for vacation or extended absence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean", "description": "Enable or disable away mode"},
                    "simulate_presence": {"type": "boolean", "description": "Randomly toggle lights to simulate presence"},
                    "return_date": {"type": "string", "description": "Expected return date (ISO format)"}
                },
                "required": ["enabled"]
            }
        }
    }
]
