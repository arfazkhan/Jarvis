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

    # ------------------------------------------------------------------ #
    # Memory System - CRUD operations for log_memory tool
    # ------------------------------------------------------------------ #
    
    def _get_memory_file_path(self) -> str:
        """Get path to memory persistence file"""
        return os.path.join(os.path.dirname(__file__), "memories.json")
    
    def _load_memories(self) -> dict:
        """Load memories from persistence file"""
        try:
            path = self._get_memory_file_path()
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[LearningEngine] Error loading memories: {e}")
        return {"memories": [], "preferences": {}}
    
    def _save_memories(self, data: dict) -> None:
        """Save memories to persistence file"""
        try:
            path = self._get_memory_file_path()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[LearningEngine] Error saving memories: {e}")
    
    def store_memory(self, title: str, knowledge: str, category: str = "general") -> str:
        """
        Store a new memory/observation.
        
        Args:
            title: Short title for the memory
            knowledge: The content/observation to store
            category: Category (preference, observation, pattern, etc.)
            
        Returns:
            Generated memory ID
        """
        import uuid
        
        data = self._load_memories()
        memory_id = str(uuid.uuid4())[:8]
        
        memory = {
            "id": memory_id,
            "title": title,
            "knowledge": knowledge,
            "category": category,
            "created_at": time.time(),
            "updated_at": time.time()
        }
        
        data["memories"].append(memory)
        
        # If it's a preference, also add to quick-access preferences dict
        if category == "preference":
            data["preferences"][title] = knowledge
        
        self._save_memories(data)
        print(f"[LearningEngine] Stored memory: {title} (ID: {memory_id})")
        return memory_id
    
    def update_memory(self, memory_id: str, knowledge: str) -> bool:
        """
        Update an existing memory.
        
        Args:
            memory_id: ID of memory to update
            knowledge: New content
            
        Returns:
            True if updated, False if not found
        """
        data = self._load_memories()
        
        for memory in data["memories"]:
            if memory["id"] == memory_id:
                old_title = memory["title"]
                memory["knowledge"] = knowledge
                memory["updated_at"] = time.time()
                
                # Update preferences if applicable
                if memory.get("category") == "preference":
                    data["preferences"][old_title] = knowledge
                
                self._save_memories(data)
                print(f"[LearningEngine] Updated memory: {memory_id}")
                return True
        
        print(f"[LearningEngine] Memory not found: {memory_id}")
        return False
    
    def delete_memory(self, memory_id: str) -> bool:
        """
        Delete a memory.
        
        Args:
            memory_id: ID of memory to delete
            
        Returns:
            True if deleted, False if not found
        """
        data = self._load_memories()
        
        for i, memory in enumerate(data["memories"]):
            if memory["id"] == memory_id:
                title = memory["title"]
                
                # Remove from preferences if applicable
                if memory.get("category") == "preference" and title in data["preferences"]:
                    del data["preferences"][title]
                
                data["memories"].pop(i)
                self._save_memories(data)
                print(f"[LearningEngine] Deleted memory: {memory_id}")
                return True
        
        print(f"[LearningEngine] Memory not found: {memory_id}")
        return False
    
    def get_memory(self, memory_id: str) -> dict:
        """Get a specific memory by ID"""
        data = self._load_memories()
        for memory in data["memories"]:
            if memory["id"] == memory_id:
                return memory
        return None
    
    def get_all_memories(self, category: str = None, limit: int = 50) -> list:
        """
        Get all memories, optionally filtered by category.
        
        Args:
            category: Optional category filter
            limit: Max number to return
            
        Returns:
            List of memory dicts
        """
        data = self._load_memories()
        memories = data["memories"]
        
        if category:
            memories = [m for m in memories if m.get("category") == category]
        
        # Sort by most recent first
        memories.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return memories[:limit]
    
    def get_preferences(self) -> dict:
        """
        Get user preferences for LLM context.
        
        Returns:
            Dict of preference title -> value
        """
        data = self._load_memories()
        return data.get("preferences", {})
    
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

