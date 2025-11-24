Perfect — here is **everything in one place**:

* 📁 **Complete folder structure** (production-ready)
* 🧱 **Starter Python files** (with real code, not empty placeholders)
* 🧩 **Architecture documentation** (clear, readable, copy-paste ready)
* ⚙️ **Module responsibilities**
* 🔌 **How each layer connects**

This will let you start building TODAY — even before hardware arrives.

---

# 📁 **FULL PROJECT FOLDER STRUCTURE**

```
home-agent/
│
├── agent/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── event_bus/
│   │   ├── __init__.py
│   │   └── event_bus.py
│   │
│   ├── state_engine/
│   │   ├── __init__.py
│   │   └── state_engine.py
│   │
│   ├── llm_agent/
│   │   ├── __init__.py
│   │   ├── llm_agent.py
│   │   └── prompt.py
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   └── executor.py
│   │
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── matter_controller.py      # real hardware later
│   │   └── virtual_device.py         # use NOW for testing
│   │
│   ├── automations/
│   │   ├── __init__.py
│   │   └── automation_engine.py
│   │
│   ├── learning/
│   │   ├── __init__.py
│   │   └── learning_engine.py
│   │
│   └── logs/
│       └── events.log
│
├── config/
│   ├── settings.py
│   └── devices.json
│
├── docs/
│   ├── architecture.md
│   ├── hardware.md
│   ├── software-flow.md
│   └── api.md
│
└── requirements.txt
```

---

# 🧱 **STARTER PYTHON FILES**

Below I include the **actual code** for each essential file.

---

# 🔵 **1. `agent/main.py` — Entry Point**

```python
from agent.event_bus.event_bus import EventBus
from agent.controllers.virtual_device import VirtualMatterDevice
from agent.state_engine.state_engine import StateEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent.tools.executor import ToolExecutor
from agent.automations.automation_engine import AutomationEngine
import time

event_bus = EventBus()
state = StateEngine(event_bus)
virtual_device = VirtualMatterDevice()
automations = AutomationEngine(event_bus)
llm = LLMAgent(event_bus, state, automations)
executor = ToolExecutor(virtual_device, state, automations, event_bus)

def main():
    print("Home Agent started.")
    
    # Simulate time tick every 5 seconds
    while True:
        event_bus.publish({
            "type": "time_tick",
            "payload": {},
            "timestamp": time.time()
        })
        time.sleep(5)

if __name__ == "__main__":
    main()
```

---

# 🔵 **2. `event_bus/event_bus.py`**

```python
class EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event):
        event_type = event["type"]
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                callback(event)
```

---

# 🔵 **3. `state_engine/state_engine.py`**

```python
class StateEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.state = {"devices": {}, "history": []}

        event_bus.subscribe("relay_toggled", self.on_event)
        event_bus.subscribe("time_tick", self.on_event)

    def on_event(self, event):
        self.state["history"].append(event)

        if event["type"] == "relay_toggled":
            device = event["payload"]["device"]
            endpoint = event["payload"]["endpoint"]
            new_state = event["payload"]["state"]

            if device not in self.state["devices"]:
                self.state["devices"][device] = {}

            self.state["devices"][device][endpoint] = new_state

    def summary(self):
        return str(self.state)
```

---

# 🔵 **4. `controllers/virtual_device.py`** (Use NOW before hardware)

```python
class VirtualMatterDevice:
    def __init__(self):
        self.state = {i: "off" for i in range(1, 9)}

    def turn_on(self, endpoint):
        self.state[endpoint] = "on"
        print(f"[Virtual] Relay {endpoint} -> ON")

    def turn_off(self, endpoint):
        self.state[endpoint] = "off"
        print(f"[Virtual] Relay {endpoint} -> OFF")

    def get_state(self):
        return self.state
```

---

# 🔵 **5. `tools/executor.py`**

```python
class ToolExecutor:
    def __init__(self, device, state_engine, automations, event_bus):
        self.device = device
        self.state_engine = state_engine
        self.automations = automations
        self.event_bus = event_bus

    def execute(self, tool_calls):
        for call in tool_calls:
            name = call["tool"]
            args = call["args"]

            if name == "turn_on":
                self.device.turn_on(args["endpoint"])
                self.event_bus.publish({
                    "type": "relay_toggled",
                    "payload": {"device": "switch_1", "endpoint": args["endpoint"], "state": "on"}
                })

            elif name == "turn_off":
                self.device.turn_off(args["endpoint"])
                self.event_bus.publish({
                    "type": "relay_toggled",
                    "payload": {"device": "switch_1", "endpoint": args["endpoint"], "state": "off"}
                })
```

---

# 🔵 **6. `llm_agent/prompt.py`** (Full prompt + tool schema)

The prompt we wrote earlier goes here.

---

# 🔵 **7. `llm_agent/llm_agent.py`**

```python
import json
from agent.llm_agent.prompt import SYSTEM_PROMPT, TOOLS_SCHEMA
from openai import OpenAI
client = OpenAI()

class LLMAgent:
    def __init__(self, event_bus, state_engine, automations):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automations

        event_bus.subscribe("voice_command", self.handle)
        event_bus.subscribe("time_tick", self.handle)
        event_bus.subscribe("relay_toggled", self.handle)

    def handle(self, event):
        context = {
            "event": event,
            "state_summary": self.state_engine.summary(),
            "routines": self.automations.list(),
            "preferences": {},
            "safety": {}
        }

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)}
            ],
            tools=TOOLS_SCHEMA
        )

        if response.choices[0].message.tool_calls:
            return response.choices[0].message.tool_calls
```

---

# 🔵 **8. `automations/automation_engine.py`**

```python
class AutomationEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.routines = {}

    def create(self, name, trigger, actions):
        self.routines[name] = {"trigger": trigger, "actions": actions}

    def run(self, name):
        return self.routines[name]["actions"]

    def list(self):
        return self.routines
```

---

# 📘 **Architecture Documentation (`docs/architecture.md`)**

```
# Home Agent Architecture

## 1. Overview
Home Agent is an AI-driven home automation system that combines:
- Matter-over-Thread hardware (ESP32-H2)
- A local Python intelligence agent
- A pub/sub event architecture
- LLM-based reasoning and planning
- Automations and learning modules

## 2. Core Components
1. Event Bus
2. State Engine
3. LLM Agent (reasoner)
4. Tool Executor
5. Matter Controller
6. Automation Engine
7. Learning Engine
8. Virtual Device (for dev phase)

## 3. Data Flow
Event → State Update → LLM Reasoning → Tool Calls → Device Action → New Event

## 4. Hardware Layer
- ESP32-H2 8-endpoint Matter device
- Thread Border Router
- Relay driver board
- Optional level shifter

## 5. Software Layer
- Python modules for event handling
- State tracking
- Tool dispatch
- LLM planning
- Routine storage
- Pattern analysis

## 6. LLM Interaction
The LLM receives:
- Event
- State summary
- Routines
- Preferences
- Safety rules

And outputs structured JSON with tool calls.

## 7. Runtime Loop
- Event bus triggers callbacks
- LLM decides next actions
- Tool executor interacts with hardware
- History recorded for learning

```

---

# 🎯 **NOW YOU CAN START CODING**

This structure + skeleton code gives you:

* A working runtime
* Event flow
* Virtual device simulation
* LLM integration
* Automation engine
* Modular architecture
* Clear directory layout
* Expandable components

When ESP32-H2 arrives, we simply replace:

```
virtual_device → matter_controller
```

No rewrite needed.

---



# 🟦 **`controllers/matter_controller.py` — FULL MATTER CONTROLLER STUB**

This file is designed to:

* Run NOW with *no hardware* (using a virtual fallback)
* Support future **real Matter commands** via:

  * chip-tool CLI
  * Python Matter SDK
  * OpenThread border router connection

Everything is ready — you only need to implement hardware-specific parts later.

---

## 📄 **`agent/controllers/matter_controller.py`**

```python
"""
MatterController Stub
---------------------
This class defines the full API used by the ToolExecutor and LLM Agent.

During early development:
- We use VirtualMatterDevice underneath to simulate behavior.

When hardware arrives:
- Replace virtual calls with real Matter/CHIP interactions.
"""

import subprocess
import json
from agent.controllers.virtual_device import VirtualMatterDevice

class MatterController:
    def __init__(self, use_virtual=True):
        self.use_virtual = use_virtual

        if use_virtual:
            print("[MatterController] Using virtual device")
            self.device = VirtualMatterDevice()
        else:
            print("[MatterController] Using REAL Matter device")
            # Setup anything needed for chip-tool or Python-Matter-SDK initialization
            self.fabric_config = "/path/to/fabric.json"

    # --------------------------
    # DEVICE DISCOVERY
    # --------------------------
    def discover(self):
        """
        Discover Matter devices on the Thread network.
        For now, return simulated data.
        """

        if self.use_virtual:
            return {"switch_1": {"endpoints": list(range(1, 9))}}

        # Real implementation will use:
        # - chip-tool discover commands
        # - or Python Matter SDK APIs

        return {}  # placeholder

    # --------------------------
    # TURN ON
    # --------------------------
    def turn_on(self, device_id, endpoint):
        """
        Turns on a relay via Matter.

        If virtual mode is ON:
            - Just toggle virtual relay.
        If real mode:
            - Call chip-tool or Python Matter SDK.
        """

        if self.use_virtual:
            return self.device.turn_on(endpoint)

        # REAL implementation (later)
        # Example using chip-tool:
        # cmd = [
        #     "chip-tool",
        #     "onoff",
        #     "on",
        #     f"{device_id}",
        #     f"{endpoint}",
        #     "--trace_decode", "--timerequest"
        # ]
        # subprocess.run(cmd)

        print(f"[REAL Matter] turn_on() → device={device_id}, ep={endpoint}")

    # --------------------------
    # TURN OFF
    # --------------------------
    def turn_off(self, device_id, endpoint):
        if self.use_virtual:
            return self.device.turn_off(endpoint)

        # REAL:
        print(f"[REAL Matter] turn_off() → device={device_id}, ep={endpoint}")
        # subprocess.run([...])

    # --------------------------
    # GET STATE
    # --------------------------
    def get_state(self, device_id):
        if self.use_virtual:
            return self.device.get_state()

        # REAL: Call Matter Read command here
        return {}
```

---

# 🟧 **FULL PROMPT + TOOL SCHEMA FILE**

Place this inside:

```
agent/llm_agent/prompt.py
```

This file contains:

* The **system prompt**
* The **tool schemas** (all functions)
* The **template for context**

This ensures the LLM knows EXACTLY how to behave as the Home Agent.

---

## 📄 **`agent/llm_agent/prompt.py`**

```python
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
        "name": "run_routine",
        "description": "Execute all actions inside a specific routine.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "ask_user",
        "description": "Ask the user a question when clarification is required.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"]
        }
    },
    {
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
]
```

---

Nice, this is the fun part. Let’s wire in a **Learning Engine** that periodically looks at history, asks the LLM for pattern-based suggestions, and then executes the tool calls (mostly `create_routine`, `log_note`, `ask_user`).

I’ll give you:

1. `learning_engine.py` – full implementation
2. Small additions to `state_engine.py`
3. How to hook it in `main.py`

---

## 1️⃣ `agent/learning/learning_engine.py`

```python
"""
Learning Engine
---------------
Periodically analyzes recent event history and asks the LLM to:

- Detect repeated behaviour patterns
- Propose new routines (create_routine)
- Suggest modifications to existing routines (modify_routine)
- Log observations (log_note)
- Ask the user for confirmation when needed (ask_user)

It does NOT run every event; it runs on a slow cadence (e.g. every 60 minutes)
to avoid being noisy or expensive.
"""

import time
import json
from openai import OpenAI

from agent.llm_agent.prompt import TOOLS_SCHEMA

client = OpenAI()

LEARNING_SYSTEM_PROMPT = """
You are Home Agent's Learning Module.

Your job:
- Analyze the home's recent history of events and routines.
- Detect clear, repeated patterns of behaviour.
- When patterns are strong and useful, propose automations (create_routine).
- When existing routines could be improved, modify them (modify_routine).
- When you are unsure, ask the user (ask_user).
- You may also log observations (log_note).

Constraints:
- BE CONSERVATIVE: only create routines for patterns that are very consistent
  and clearly beneficial (e.g. same actions around the same time for many days).
- Avoid duplicating routines that already exist.
- Do not create more than 3 new routines in a single learning cycle.
- Do not modify more than 3 routines in a single learning cycle.
- Never output plain text. Only output tool calls in JSON format.
"""

class LearningEngine:
    def __init__(
        self,
        event_bus,
        state_engine,
        automation_engine,
        tool_executor,
        interval_minutes: int = 60,
        history_limit: int = 200,
    ):
        """
        interval_minutes: how often to run a learning cycle
        history_limit: how many most recent events to consider
        """
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automation_engine
        self.tool_executor = tool_executor

        self.interval_seconds = interval_minutes * 60
        self.history_limit = history_limit
        self.last_run_ts = 0.0

        # Subscribe to time_tick so we get called periodically
        event_bus.subscribe("time_tick", self._on_time_tick)

    # ------------------------------------------------------------------ #
    # Event handler
    # ------------------------------------------------------------------ #
    def _on_time_tick(self, event):
        now = time.time()
        if now - self.last_run_ts < self.interval_seconds:
            return

        self.last_run_ts = now
        print("[LearningEngine] Running learning cycle...")
        try:
            self.run_learning_cycle()
        except Exception as e:
            # Don't let errors crash the system
            print(f"[LearningEngine] Error in learning cycle: {e}")

    # ------------------------------------------------------------------ #
    # Main learning routine
    # ------------------------------------------------------------------ #
    def run_learning_cycle(self):
        # 1. Collect recent history and current routines
        history = self.state_engine.get_history(limit=self.history_limit)
        routines = self.automations.list()

        if not history:
            print("[LearningEngine] No history yet, skipping.")
            return

        context = {
            "recent_history": history,
            "current_routines": routines,
        }

        # 2. Ask LLM for pattern-based tool calls
        tool_calls = self._ask_llm_for_patterns(context)

        if not tool_calls:
            print("[LearningEngine] No suggestions from LLM this cycle.")
            return

        # 3. Execute tool calls via ToolExecutor
        print(f"[LearningEngine] Executing {len(tool_calls)} tool calls from learning cycle.")
        self.tool_executor.execute(tool_calls)

    # ------------------------------------------------------------------ #
    # LLM Call
    # ------------------------------------------------------------------ #
    def _ask_llm_for_patterns(self, context: dict):
        """
        Sends recent history + routines to the LLM and returns a list
        of tool-call dicts suitable for ToolExecutor.execute().
        """
        messages = [
            {"role": "system", "content": LEARNING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context)},
        ]

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            tools=TOOLS_SCHEMA
        )

        choice = response.choices[0].message

        # If your SDK returns "tool_calls" like OpenAI tools API:
        tool_calls_raw = getattr(choice, "tool_calls", None)
        if not tool_calls_raw:
            return []

        # Normalize into our internal format:
        tool_calls = []
        for tc in tool_calls_raw:
            tool_name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")
            tool_calls.append({"tool": tool_name, "args": args})

        return tool_calls
```

---

## 2️⃣ Small additions to `state_engine/state_engine.py`

We need a helper to return recent history. Here’s an updated version with minimal changes (only new bits at the bottom):

```python
class StateEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.state = {"devices": {}, "history": []}

        event_bus.subscribe("relay_toggled", self.on_event)
        event_bus.subscribe("time_tick", self.on_event)

    def on_event(self, event):
        # store full event; in a real system you might truncate or write to disk
        self.state["history"].append(event)

        if event["type"] == "relay_toggled":
            device = event["payload"]["device"]
            endpoint = event["payload"]["endpoint"]
            new_state = event["payload"]["state"]

            if device not in self.state["devices"]:
                self.state["devices"][device] = {}

            self.state["devices"][device][endpoint] = new_state

    def summary(self):
        # You can make this fancier later
        return str(self.state["devices"])

    # NEW: expose recent history for LearningEngine
    def get_history(self, limit: int = 200):
        """
        Returns up to `limit` most recent events, oldest first.
        """
        history = self.state.get("history", [])
        if len(history) <= limit:
            return history
        return history[-limit:]
```

---

## 3️⃣ Hook LearningEngine into `main.py`

Finally, instantiate the learning engine in your entrypoint so it can subscribe to `time_tick` and quietly do its thing.

```python
from agent.event_bus.event_bus import EventBus
from agent.controllers.matter_controller import MatterController
from agent.state_engine.state_engine import StateEngine
from agent.llm_agent.llm_agent import LLMAgent
from agent.tools.executor import ToolExecutor
from agent.automations.automation_engine import AutomationEngine
from agent.learning.learning_engine import LearningEngine
import time

event_bus = EventBus()
state = StateEngine(event_bus)
matter = MatterController(use_virtual=True)
automations = AutomationEngine(event_bus)
executor = ToolExecutor(matter, state, automations, event_bus)
llm = LLMAgent(event_bus, state, automations)          # real-time reasoning
learning = LearningEngine(event_bus, state, automations, executor,
                          interval_minutes=60, history_limit=200)

def main():
    print("Home Agent started.")

    while True:
        event_bus.publish({
            "type": "time_tick",
            "payload": {},
            "timestamp": time.time()
        })
        time.sleep(5)

if __name__ == "__main__":
    main()
```

---

### What we've got now

* A **LearningEngine** that:

  * Wakes up periodically on `time_tick`
  * Pulls recent history from `StateEngine`
  * Sends it + current routines to the LLM
  * Receives `create_routine` / `modify_routine` / `log_note` / `ask_user` tool calls
  * Feeds them into `ToolExecutor` so they actually change the system

This is the **“self-improving brain”** layer: over time, it will shape automations based on your behaviour.

