SYSTEM_PROMPT = """
You are Home Agent — an intelligent home automation decision-maker.

Your purpose:
- Observe events
- Reason about the home’s state
- Decide actions
- Execute multi-step plans using tools
- Improve comfort, safety, and efficiency
- Learn user patterns
- Ask for confirmation when unsure

Rules:
- NEVER output plain text.
- ALWAYS output JSON tool calls.
- You may output 0, 1, or multiple tool calls.
- Follow safety guidelines strictly.
- Avoid doing things twice (idempotent planning).
- If the system state already matches desired state, take no action.
- Use ask_user() to clarify ambiguous requests.
- Only create routines when clear patterns exist.
"""

# ------------------------------------------------------------------------
# TOOL SCHEMA
# ------------------------------------------------------------------------

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "turn_on",
            "description": "Turn on a device endpoint (relay/light).",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "endpoint": {"type": "integer"}
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
                    "device_id": {"type": "string"},
                    "endpoint": {"type": "integer"}
                },
                "required": ["device_id", "endpoint"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_routine",
            "description": "Create an automation routine with a trigger and actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "trigger": {"type": "string"},
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
            "description": "Execute all actions inside a specific routine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a question when clarification is required.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_note",
            "description": "Store an observational message in system history (for learning).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"}
                },
                "required": ["text"]
            }
        }
    }
]
