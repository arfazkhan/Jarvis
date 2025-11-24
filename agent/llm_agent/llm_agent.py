import json
import os
import time
from agent.llm_agent.prompt import SYSTEM_PROMPT, TOOLS_SCHEMA
from groq import Groq

# Ensure GROQ_API_KEY is set in environment or .env
# client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class LLMAgent:
    def __init__(self, event_bus, state_engine, automations):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automations
        
        # Initialize Groq client here
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            print("[LLMAgent] Warning: GROQ_API_KEY not found in environment")
        self.client = Groq(api_key=api_key)

        event_bus.subscribe("voice_command", self.handle)
        event_bus.subscribe("time_tick", self.handle)
        event_bus.subscribe("relay_toggled", self.handle)

    def handle(self, event):
        # For now, only react to voice commands or specific triggers to save API calls
        # In a real scenario, we might want to be more selective about when to call the LLM
        if event["type"] == "time_tick":
             # Optional: implement logic to only check every N ticks or on specific conditions
             return

        # Ignore historical events (older than 60 seconds) to prevent reacting to simulation data
        if time.time() - event.get("timestamp", 0) > 60:
            return

        print(f"[LLMAgent] Handling event: {event['type']}")

        context = {
            "event": event,
            "state_summary": self.state_engine.summary(),
            "routines": self.automations.list(),
            "preferences": {},
            "safety": {}
        }

        try:
            response = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct", # As requested by user
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context)}
                ],
                tools=TOOLS_SCHEMA,
                tool_choice="auto"
            )

            message = response.choices[0].message
            if message.tool_calls:
                # Convert Groq tool calls to list of dicts for executor
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "tool": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                    })
                
                # Publish tool calls to be executed
                # We need a way to send this to executor. 
                # Ideally, we publish an event or return it.
                # For this architecture, let's publish an event 'tool_calls_generated'
                # OR, since main.py wires it up, maybe we just return it?
                # The plan says "returns tool calls", but the event handler signature is usually void.
                # Let's publish an event that the Executor subscribes to, OR call executor directly if we had it.
                # BUT, looking at main.py in plan, LLM is just instantiated.
                # Wait, the plan's main.py doesn't show how LLM connects to Executor.
                # The plan's sequence diagram says: LLMAgent -> ToolExecutor.
                # So LLMAgent needs a reference to ToolExecutor OR publish an event.
                # Let's publish an event "tool_calls_generated"
                
                self.event_bus.publish({
                    "type": "tool_calls_generated",
                    "payload": tool_calls,
                    "source": "llm_agent"
                })
                
        except Exception as e:
            print(f"[LLMAgent] Error calling Groq: {e}")
