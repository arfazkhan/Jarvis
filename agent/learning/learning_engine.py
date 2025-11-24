import time
import json
import os
from groq import Groq
from agent.llm_agent.prompt import TOOLS_SCHEMA
from agent.learning.pattern_analyzer import PatternAnalyzer

# Ensure GROQ_API_KEY is set in environment or .env
# client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

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
        
        # Initialize Groq client here - allow tests to run without API key
        api_key = os.environ.get("GROQ_API_KEY")
        
        if api_key:
            self.client = Groq(api_key=api_key)
        else:
            print("[LearningEngine] Warning: GROQ_API_KEY not found in environment - LLM features disabled")
            self.client = None  # Allow tests to run without API key

        self.interval_seconds = interval_minutes * 60
        self.history_limit = history_limit
        self.last_run_ts = 0.0
        
        # Initialize PatternAnalyzer for advanced insights
        self.pattern_analyzer = PatternAnalyzer()

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
        # Skip if no API key available
        if not self.client:
            print("[LearningEngine] Skipping learning cycle - no API key")
            return
            
        # 1. Collect recent history and current routines
        history = self.state_engine.get_history(limit=self.history_limit)
        routines = self.automations.list()

        if not history:
            print("[LearningEngine] No history yet, skipping.")
            return

        # Debug: Show what we're analyzing
        print(f"[LearningEngine] Analyzing {len(history)} events from history")
        print(f"[LearningEngine] Current routines: {len(routines)}")
        
        # 2. Analyze patterns using PatternAnalyzer
        analysis = self.pattern_analyzer.summarize_patterns(history)
        anomalies = analysis.get("anomalies", [])
        clusters = analysis.get("clusters", [])
        wake_drift = analysis.get("wake_drift", {}).get("wake_time")
        bed_drift = analysis.get("bed_drift", {}).get("bedtime")
        
        # Show a sample of the history for debugging
        if wake_drift:
            print(f"[LearningEngine] Wake time drift: {wake_drift}")
        if bed_drift:
            print(f"[LearningEngine] Bedtime drift: {bed_drift}")

        context = {
            "recent_history": history,
            "current_routines": routines,
            "anomalies": anomalies,
            "pattern_clusters": [
                {
                    "event_count": c["event_count"],
                    "time_span_seconds": c["end_time"] - c["start_time"],
                    "sample_events": [e.get("type") for e in c["events"][:5]]
                }
                for c in clusters[:10]  # Limit to top 10 clusters
            ],
            "wake_time_trend": wake_drift,
            "bedtime_trend": bed_drift
        }

        # 3. Ask LLM for pattern-based tool calls
        tool_calls = self._ask_llm_for_patterns(context)

        if not tool_calls:
            print("[LearningEngine] No suggestions from LLM this cycle.")
            return

        # 4. Execute tool calls via ToolExecutor
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
        if not self.client:
            return []
            
        messages = [
            {"role": "system", "content": LEARNING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context)},
        ]

        try:
            response = self.client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto"
            )

            message = response.choices[0].message
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_calls.append({
                        "tool": tc.function.name,
                        "args": json.loads(tc.function.arguments)
                    })
                return tool_calls
            return []
            
        except Exception as e:
            print(f"[LearningEngine] Error calling Groq: {e}")
            return []
