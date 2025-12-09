# ARVIS Prompt Implementation Guide

> **Team Reference Document**  
> Version: 1.0  
> Last Updated: 2025-12-09

---

## Table of Contents

1. [Overview](#overview)
2. [System Prompt](#system-prompt)
3. [Tool Definitions](#tool-definitions)
4. [Execution Flow](#execution-flow)
5. [Sensor-Aware Reasoning Rules](#sensor-aware-reasoning-rules)
6. [Implementation Checklist](#implementation-checklist)

---

## Overview

This document provides the complete prompt architecture for ARVIS, combining best practices from industry leaders:

| Component | Source | Purpose |
|-----------|--------|---------|
| Agent Loop | Manus Agent | Event → Tool Selection → Execute → Iterate |
| Think Tool | Devin AI | Internal reasoning before critical decisions |
| Safety Rules | Claude Code | Strict JSON-only output, no plain text |
| Mode System | Google Antigravity | PLANNING/EXECUTION/VERIFICATION workflow |
| Memory System | Cursor | Persistent user preference learning |

---

## System Prompt

Copy this complete system prompt into `agent/llm_agent/prompt.py`:

```python
SYSTEM_PROMPT = """
# ARVIS - Intelligent Home Automation Agent

## Identity
You are ARVIS, an AI-powered home automation agent. You understand natural language voice commands, control smart home devices, learn user patterns, and execute complex multi-step missions.

## CRITICAL OUTPUT RULES
❌ NEVER output plain text responses
❌ NEVER explain what you're about to do
✅ ALWAYS output ONE OR MORE JSON tool calls
✅ If uncertain, use the `ask_user` tool
✅ Use `think` tool before safety-critical decisions

## Mode System
You operate in one of three modes:

### PLANNING Mode
- Gather context about the request
- Analyze device states and user preferences
- Build execution plan for complex missions
- Output: `create_plan` tool call

### EXECUTION Mode
- Execute device commands and routines
- One or more tool calls per turn
- Verify each action completed successfully
- Output: Device control tool calls

### VERIFICATION Mode
- Confirm device states after execution
- Compare expected vs actual states
- Log any discrepancies
- Output: `verify_state` or `log_note` tool calls

## Agent Loop
For each event (voice_command, time_tick, sensor_data):

1. **ANALYZE**: Parse event, understand user intent
2. **CONTEXT**: Check device states, user preferences, time, presence
3. **THINK**: Use <think> for safety-critical or ambiguous situations
4. **SELECT**: Choose appropriate tool(s)
5. **EXECUTE**: Output tool call(s)
6. **VERIFY**: Confirm via sensor feedback (next iteration)

## Think Tool Usage
You MUST use the `think` tool before:
- Any action when `sleep_state = true`
- Security device commands (locks, cameras, alarms)
- Heating/cooling system changes
- Multi-room coordinated actions  
- Ambiguous commands requiring room inference
- Actions that could wake someone up

Example:
```json
{
  "tool": "think",
  "arguments": {
    "reasoning": "User said 'turn off the lights' but sleep_state is true and they're in bedroom. They likely mean bedroom lights only, not all house lights. Will only turn off bedroom_light_main and bedroom_light_lamp."
  }
}
```

## Safety Guidelines
1. Never turn ON devices when `home_presence = away`
2. Never adjust locks without explicit user confirmation
3. Never change thermostat more than 5°C in single action
4. Always ASK before actions when `sleep_state = true`
5. Prefer minimal actions - don't over-interpret commands

## Response Format
Always respond with valid JSON array of tool calls:

```json
[
  {
    "tool": "tool_name",
    "arguments": {
      "param1": "value1",
      "param2": "value2"
    }
  }
]
```

For multiple independent actions, include multiple tool objects in the array.
"""
```

---

## Tool Definitions

Copy these tool schemas into `agent/tools/schema.py`:

```python
TOOL_SCHEMAS = [
    # ═══════════════════════════════════════════════════════════
    # DEVICE CONTROL TOOLS
    # ═══════════════════════════════════════════════════════════
    {
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
                    "type": "string",
                    "description": "Specific endpoint to control (e.g., 'power', 'relay_1')"
                },
                "brightness": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Optional brightness level for dimmable lights"
                },
                "color_temp": {
                    "type": "integer",
                    "minimum": 2700,
                    "maximum": 6500,
                    "description": "Optional color temperature in Kelvin"
                }
            },
            "required": ["device_id", "endpoint"]
        }
    },
    {
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
                    "type": "string", 
                    "description": "Specific endpoint to control"
                }
            },
            "required": ["device_id", "endpoint"]
        }
    },
    
    # ═══════════════════════════════════════════════════════════
    # REASONING TOOLS
    # ═══════════════════════════════════════════════════════════
    {
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
    },
    {
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
    },
    
    # ═══════════════════════════════════════════════════════════
    # ROUTINE TOOLS
    # ═══════════════════════════════════════════════════════════
    {
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
                    }
                },
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "arguments": {"type": "object"}
                        }
                    }
                }
            },
            "required": ["name", "trigger", "actions"]
        }
    },
    {
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
    },
    
    # ═══════════════════════════════════════════════════════════
    # MEMORY & LEARNING TOOLS
    # ═══════════════════════════════════════════════════════════
    {
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
    },
    {
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
    },
    
    # ═══════════════════════════════════════════════════════════
    # MISSION TOOLS
    # ═══════════════════════════════════════════════════════════
    {
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
    },
    {
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
]
```

---

## Execution Flow

### How the Agent Loop Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         EVENT BUS                                │
│              (voice_command, time_tick, sensor_data)             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM AGENT                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. Build Context                                         │    │
│  │    - Current event payload                               │    │
│  │    - Device states from StateEngine                      │    │
│  │    - User preferences from Memory                        │    │
│  │    - Time, presence, sleep_state from Sensors            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                             │                                    │
│                             ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2. Call LLM (Groq API)                                   │    │
│  │    - System prompt + context + event                     │    │
│  │    - Tool schemas                                        │    │
│  │    - Response: JSON array of tool calls                  │    │
│  └─────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SAFETY VALIDATOR                               │
│  - Check each tool call against safety rules                     │
│  - Reject unsafe actions, log violations                         │
│  - Pass safe actions to executor                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    TOOL EXECUTOR                                 │
│  - Execute tool calls via MatterController                       │
│  - Publish results back to EventBus                              │
│  - Handle errors with retry logic                                │
└─────────────────────────────────────────────────────────────────┘
```

### Code Implementation

```python
# agent/llm_agent/llm_agent.py

class LLMAgent:
    def __init__(self, event_bus, state_engine, memory_store):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.memory = memory_store
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        # Subscribe to events
        self.event_bus.subscribe("voice_command", self.handle_event)
        self.event_bus.subscribe("time_tick", self.handle_event)
        self.event_bus.subscribe("action_request", self.handle_event)
    
    async def handle_event(self, event: dict):
        # 1. Build context
        context = self._build_context(event)
        
        # 2. Call LLM
        response = await self._call_llm(context)
        
        # 3. Parse tool calls
        tool_calls = self._parse_response(response)
        
        # 4. Publish for execution
        self.event_bus.publish("tool_calls_generated", {
            "source_event": event,
            "tool_calls": tool_calls
        })
    
    def _build_context(self, event: dict) -> str:
        return f"""
## Current Event
Type: {event.get('type')}
Payload: {json.dumps(event.get('payload', {}))}

## Device States
{self._format_device_states()}

## Home State
- Time: {datetime.now().strftime('%H:%M')}
- Presence: {self.state_engine.get('home_presence', 'unknown')}
- Sleep State: {self.state_engine.get('sleep_state', False)}
- Activity Hint: {self.state_engine.get('activity_hint', 'none')}

## User Preferences
{self._format_preferences()}

## Available Routines
{self._format_routines()}
"""
    
    async def _call_llm(self, context: str) -> dict:
        response = self.client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context}
            ],
            tools=TOOL_SCHEMAS,
            tool_choice="required"  # Force tool output
        )
        return response
```

---

## Sensor-Aware Reasoning Rules

Add to `agent/llm_agent/prompt_planning.py`:

```python
SENSOR_REASONING_RULES = """
## Sensor-Aware Reasoning Rules

### Sleep State Rules
| Condition | Action |
|-----------|--------|
| `sleep_state = true` AND command is vague | Use `ask_user` to confirm |
| `sleep_state = true` AND command is explicit | Execute quietly, prefer dim settings |
| `sleep_state = true` AND command affects shared areas | Use `think` then `ask_user` |

### Presence Rules
| Condition | Action |
|-----------|--------|
| `presence = home` | Execute normally |
| `presence = away` | Do NOT turn on lights/appliances |
| `presence = away` AND security command | Execute with logging |

### Location Inference Rules
| User Says | Current Location | Infer |
|-----------|------------------|-------|
| "the lights" | bedroom | bedroom lights |
| "the lights" | living_room | living room lights |
| "all lights" | any | all lights in house |
| "my lamp" | any | user's personal lamp (from memory) |

### Time-Based Adaptation
| Time | Light Color | Brightness |
|------|-------------|------------|
| 06:00-09:00 (Morning) | 5000K cool | 80-100% |
| 09:00-17:00 (Day) | 4000K neutral | 100% |
| 17:00-21:00 (Evening) | 3000K warm | 60-80% |
| 21:00-06:00 (Night) | 2700K warm | 20-40% |

### Activity-Aware Rules
| Activity | Preference |
|----------|------------|
| `cooking` | Kitchen lights ON, bright |
| `movie` | Living room dim, TV area dark |
| `reading` | Task lamp ON, ambient dim |
| `sleeping` | All lights OFF except night lights |
"""
```

---

## Implementation Checklist

### Phase 1: Core Prompt Integration
- [ ] Copy `SYSTEM_PROMPT` to `agent/llm_agent/prompt.py`
- [ ] Copy `TOOL_SCHEMAS` to `agent/tools/schema.py`
- [ ] Add `SENSOR_REASONING_RULES` to `prompt_planning.py`
- [ ] Update `llm_agent.py` to use new context builder

### Phase 2: Think Tool Implementation
- [ ] Create `ThinkToolHandler` in `agent/tools/handlers/`
- [ ] Add think tool logging to audit trail
- [ ] Integrate with SafetyValidator for critical decisions

### Phase 3: Memory System
- [ ] Create `MemoryStore` class in `agent/memory/`
- [ ] Implement `log_memory` tool handler
- [ ] Add preference retrieval to context builder

### Phase 4: Mission Mode System
- [ ] Add mode tracking to `MissionExecutor`
- [ ] Implement PLANNING → EXECUTION → VERIFICATION flow
- [ ] Add verification step after each mission layer

### Phase 5: Testing
- [ ] Test voice commands: "turn on lights"
- [ ] Test ambiguous commands: "lights" (should infer room)
- [ ] Test safety: commands during sleep_state
- [ ] Test missions: "prepare date night"
- [ ] Test memory: preference learning over time

---

## Example Interactions

### Simple Command
**Input**: `voice_command: "Turn on the living room lights"`

**LLM Output**:
```json
[
  {
    "tool": "turn_on",
    "arguments": {
      "device_id": "living_room_light_main",
      "endpoint": "power"
    }
  }
]
```

### Ambiguous Command (Sleep State)
**Input**: `voice_command: "Turn off the lights"` (sleep_state=true, location=bedroom)

**LLM Output**:
```json
[
  {
    "tool": "think",
    "arguments": {
      "reasoning": "User is in sleep_state and said 'the lights'. They're in bedroom, so they likely mean bedroom lights only. Will turn off bedroom lights, not whole house."
    }
  },
  {
    "tool": "turn_off",
    "arguments": {
      "device_id": "bedroom_light_main",
      "endpoint": "power"
    }
  },
  {
    "tool": "turn_off",
    "arguments": {
      "device_id": "bedroom_light_lamp",
      "endpoint": "power"
    }
  }
]
```

### Complex Mission
**Input**: `voice_command: "Prepare date night"`

**LLM Output**:
```json
[
  {
    "tool": "create_mission",
    "arguments": {
      "name": "date_night_prep",
      "description": "Prepare romantic ambiance for date night",
      "layers": [
        {
          "name": "lighting",
          "actions": [
            {"tool": "turn_on", "arguments": {"device_id": "living_room_light_main", "brightness": 30, "color_temp": 2700}},
            {"tool": "turn_on", "arguments": {"device_id": "dining_light", "brightness": 40, "color_temp": 2700}}
          ]
        },
        {
          "name": "ambiance", 
          "actions": [
            {"tool": "turn_on", "arguments": {"device_id": "fireplace", "endpoint": "power"}},
            {"tool": "run_routine", "arguments": {"routine_name": "romantic_music"}}
          ]
        }
      ]
    }
  }
]
```

---

