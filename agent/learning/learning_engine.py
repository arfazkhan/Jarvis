import time
import json
import os
from groq import Groq
from agent.llm_agent.prompt import TOOLS_SCHEMA
from agent.learning.pattern_analyzer import PatternAnalyzer
from agent.learning.reflector import Reflector

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
- IF a pattern occurs 3+ times in the history: PROPOSE A ROUTINE (create_routine).
- IF a pattern is consistent but you aren't sure of the user's intent: ASK THE USER (ask_user).
- IF the pattern is weak (< 3 times) or vague: JUST LOG IT (log_note).
- Avoid duplicating routines that already exist.
- Do not create more than 3 new routines in a single learning cycle.
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
        llm_client=None
    ):
        """
        interval_minutes: how often to run a learning cycle
        history_limit: how many most recent events to consider
        llm_client: LLMAgent instance for generation
        """
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automation_engine
        self.tool_executor = tool_executor
        
        # LLM Client (injected)
        self.llm_client = llm_client

        self.interval_seconds = interval_minutes * 60
        self.history_limit = history_limit
        self.last_run_ts = 0.0
        
        # Initialize PatternAnalyzer for advanced insights
        self.pattern_analyzer = PatternAnalyzer()
        
        # Initialize Reflector (ACE)
        self.reflector = Reflector(llm_client)

        # Subscribe to time_tick so we get called periodically
        event_bus.subscribe("time_tick", self._on_time_tick)

    def set_llm_client(self, client):
        """Set the LLM client (LLMAgent)"""
        self.llm_client = client
        self.reflector.llm_client = client

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
        # Skip if no LLM client available
        if not self.llm_client:
            print("[LearningEngine] Skipping learning cycle - no LLM client configured")
            return
            
        # 1. Collect recent history
        history = self.state_engine.get_history(limit=self.history_limit)
        routines = self.automations.list()

        if history:
            # --- TITANS LOOP (Pattern Detection) ---
            print(f"[LearningEngine] Analyzing {len(history)} events for patterns...")
            analysis = self.pattern_analyzer.summarize_patterns(history)
            context = {
                "recent_history": history,
                "current_routines": routines,
                "pattern_clusters": [
                     {
                        "event_count": c["event_count"],
                        "time_span_seconds": c["end_time"] - c["start_time"],
                        "sample_events": [e.get("type") for e in c["events"][:5]]
                    }
                    for c in analysis.get("clusters", [])[:5]
                ]
            }
            tool_calls = self._ask_llm_for_patterns(context)
            if tool_calls:
                print(f"[LearningEngine] Titans Loop: Executing {len(tool_calls)} tool calls.")
                self.tool_executor.execute(tool_calls)
            
            # --- ACE REFLECTOR LOOP (Lesson Extraction) ---
            print(f"[LearningEngine] Running Reflector cycle...")
            try:
                reflection_calls = self.reflector.reflect(history)
                if reflection_calls:
                    print(f"[LearningEngine] Reflector: Found {len(reflection_calls)} lessons.")
                    # Process log_lesson calls manually since it's a special internal tool
                    for call in reflection_calls:
                        if call["tool"] == "log_lesson":
                            args = call["args"]
                            self.store_memory(
                                title=f"Lesson: {args.get('lesson')[:30]}...",
                                knowledge=args.get('lesson'),
                                category="lesson" # New category for lessons
                            )
            except Exception as e:
                print(f"[LearningEngine] Reflector failed: {e}")
        else:
             print("[LearningEngine] No history yet, skipping.")

    # ------------------------------------------------------------------ #
    # LLM Call
    # ------------------------------------------------------------------ #
    def _ask_llm_for_patterns(self, context: dict):
        """
        Sends recent history + routines to the LLM and returns a list
        of tool-call dicts suitable for ToolExecutor.execute().
        """
        if not self.llm_client or not hasattr(self.llm_client, 'generate_tool_calls'):
            print("[LearningEngine] LLM client missing generate_tool_calls method")
            return []
            
        try:
            # Use the shared LLM Agent to generate tool calls
            return self.llm_client.generate_tool_calls(
                system_prompt=LEARNING_SYSTEM_PROMPT,
                user_content=json.dumps(context),
                tools=TOOLS_SCHEMA
            )
            
        except Exception as e:
            print(f"[LearningEngine] Error calling LLM: {e}")
            return []

    # ------------------------------------------------------------------ #
    # Memory System - Delegated to MemoryOrchestrator
    # ------------------------------------------------------------------ #
    
    # NOTE: LearningEngine now expects 'llm_client' to be an LLMAgent
    # which has a .memory attribute (MemoryOrchestrator).
    # Alternatively, we can inject memory_system directly.
    
    def _get_memory_system(self):
        """Helper to get memory system from LLM client or simple fallback"""
        if self.llm_client and hasattr(self.llm_client, "memory"):
            return self.llm_client.memory
        return None

    def store_memory(self, title: str, knowledge: str, category: str = "general") -> str:
        """
        Store a new memory via the unified MemoryOrchestrator.
        """
        memory = self._get_memory_system()
        if not memory:
            print("[LearningEngine] ⚠️ No memory system available to store lesson")
            return None
            
        print(f"[LearningEngine] Storing lesson in shared memory: {title}")
        return memory.remember(
            content=knowledge,
            memory_type="preference" if category in ["preference", "lesson"] else "observation",
            key=title, # Use title as key for retrieval
            context=category,
            importance=1.0 # Lessons are high importance
        )
    
    def get_preferences(self) -> dict:
        """Get user preferences from memory system"""
        memory = self._get_memory_system()
        if not memory:
            return {}
            
        # Hack: The current MemoryOrchestrator.preferences.export_all() 
        # might be needed here, or we trust LLMAgent to fetch context.
        # For now, return empty dict as LLMAgent handles injection itself.
        return {}
    
    def search_memories(self, query: str) -> list:
        """
        Search memories by title or content.
        
        Args:
            query: Search string
            
        Returns:
            List of matching memories
        """
        data = self._load_memories()
        query_lower = query.lower()
        
        results = []
        for memory in data["memories"]:
            if (query_lower in memory.get("title", "").lower() or 
                query_lower in memory.get("knowledge", "").lower()):
                results.append(memory)
        
        return results

