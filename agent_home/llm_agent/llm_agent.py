"""
ARVIS LLM Agent
---------------
Handles events and generates tool calls via LLM.
Enhanced with rich context building for sensor-aware decisions.
Includes security features: input sanitization, attack detection, and troll responses.
Supports: Gemini (primary) and Groq (fallback)
"""

import json
import os
import re
import time
from datetime import datetime
from agent_home.llm_agent.tools_schema import TOOLS_SCHEMA
from agent_home.llm_agent.prompt_builder import PromptBuilder, get_prompt_builder
from agent_home.llm_agent.prompt import SYSTEM_PROMPT

# ═══════════════════════════════════════════════════════════
# SECURITY PATTERNS
# ═══════════════════════════════════════════════════════════

# Patterns that indicate potential attacks
SUSPICIOUS_PATTERNS = [
    (r'\{["\']?tool["\']?\s*:', "JSON injection attempt"),
    (r'\{["\']?args["\']?\s*:', "JSON injection attempt"),
    (r'\[SYSTEM\]', "Fake system header"),
    (r'\[ADMIN\]', "Fake admin header"),
    (r'\[DEBUG\]', "Fake debug header"),
    (r'base64.*execute', "Base64 injection"),
    (r'decode.*and.*execute', "Decode/execute attack"),
    (r'DROP\s+TABLE', "SQL injection"),
    (r'\.\./\.\./', "Path traversal"),
    (r'GROQ_API_KEY', "API key probe"),
    (r'GEMINI_API_KEY', "API key probe"),
    (r'system\s*prompt', "System prompt probe"),
    (r'override.*security', "Security override attempt"),
    (r'bypass.*safety', "Safety bypass attempt"),
    (r'disable.*pin', "PIN disable attempt"),
]

# Keywords that require PIN verification
PIN_REQUIRED_KEYWORDS = [
    "delete", "destroy", "reset", "factory", "wipe", "clear", "erase",
    "remove all", "developer", "admin", "bypass", "override",
    "unlock", "disable alarm", "disable security"
]


def convert_tools_for_gemini(openai_tools):
    """
    Convert OpenAI/Groq tool schema to Gemini protos format.
    Gemini SDK requires FunctionDeclaration objects, not raw dicts.
    Properly handles arrays with 'items' field.
    """
    from google.generativeai import protos
    
    function_declarations = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool["function"]
            params = func.get("parameters", {"type": "object", "properties": {}})
            
            # Convert parameters to Gemini Schema format
            properties = {}
            for name, prop in params.get("properties", {}).items():
                properties[name] = _convert_property_to_schema(prop)
            
            schema = protos.Schema(
                type=protos.Type.OBJECT,
                properties=properties,
                required=params.get("required", [])
            )
            
            fd = protos.FunctionDeclaration(
                name=func["name"],
                description=func.get("description", ""),
                parameters=schema
            )
            function_declarations.append(fd)
    
    # Return as a Tool containing all function declarations
    return [protos.Tool(function_declarations=function_declarations)]


def _convert_property_to_schema(prop: dict):
    """Convert a single property to Gemini Schema, handling arrays recursively."""
    from google.generativeai import protos
    
    prop_type = prop.get("type", "string")
    
    if prop_type == "array":
        # Arrays MUST have an 'items' field in Gemini
        items = prop.get("items", {"type": "string"})
        items_schema = _convert_property_to_schema(items)
        return protos.Schema(
            type=protos.Type.ARRAY,
            items=items_schema,
            description=prop.get("description", "")
        )
    elif prop_type == "object":
        # Nested objects
        nested_props = {}
        for name, nested_prop in prop.get("properties", {}).items():
            nested_props[name] = _convert_property_to_schema(nested_prop)
        return protos.Schema(
            type=protos.Type.OBJECT,
            properties=nested_props,
            required=prop.get("required", []),
            description=prop.get("description", "")
        )
    else:
        # Simple types (string, integer, number, boolean)
        return protos.Schema(
            type=_get_gemini_type(prop_type),
            description=prop.get("description", "")
        )


def _get_gemini_type(openai_type: str):
    """Map OpenAI types to Gemini protos.Type"""
    from google.generativeai import protos
    type_map = {
        "string": protos.Type.STRING,
        "integer": protos.Type.INTEGER,
        "number": protos.Type.NUMBER,
        "boolean": protos.Type.BOOLEAN,
        "array": protos.Type.ARRAY,
        "object": protos.Type.OBJECT,
    }
    return type_map.get(openai_type, protos.Type.STRING)



# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITING AND CACHING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
GEMINI_DAILY_LIMIT = 1000  # Free tier: 1000 requests/day
SEMANTIC_CACHE_SIZE = 100  # Max cached responses
CACHE_SIMILARITY_THRESHOLD = 0.85  # 85% similarity to use cache


class SemanticCache:
    """
    Semantic caching for LLM responses.
    Caches responses based on query similarity to avoid redundant API calls.
    """
    
    def __init__(self, max_size: int = 100):
        self.cache = {}  # {query_hash: {"query": str, "response": str, "timestamp": float}}
        self.max_size = max_size
        
    def _normalize_query(self, query: str) -> str:
        """Normalize query for comparison."""
        # Lowercase, remove extra whitespace, strip punctuation
        import re
        normalized = query.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = re.sub(r'[^\w\s]', '', normalized)
        return normalized
    
    def _simple_hash(self, text: str) -> str:
        """Simple hash for quick lookup."""
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()[:16]
    
    def _similarity(self, a: str, b: str) -> float:
        """Simple word-based Jaccard similarity."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = len(words_a & words_b)
        union = len(words_a | words_b)
        return intersection / union if union > 0 else 0.0
    
    def get(self, query: str) -> str | None:
        """Get cached response if similar query exists."""
        normalized = self._normalize_query(query)
        query_hash = self._simple_hash(normalized)
        
        # Exact match
        if query_hash in self.cache:
            print(f"[Cache] ✅ Exact hit")
            return self.cache[query_hash]["response"]
        
        # Semantic similarity search
        for cached_hash, cached_data in self.cache.items():
            similarity = self._similarity(normalized, cached_data["query"])
            if similarity >= CACHE_SIMILARITY_THRESHOLD:
                print(f"[Cache] ✅ Semantic hit ({similarity:.0%} similar)")
                return cached_data["response"]
        
        return None
    
    def put(self, query: str, response: str):
        """Cache a response."""
        normalized = self._normalize_query(query)
        query_hash = self._simple_hash(normalized)
        
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k]["timestamp"])
            del self.cache[oldest_key]
        
        self.cache[query_hash] = {
            "query": normalized,
            "response": response,
            "timestamp": time.time()
        }
        print(f"[Cache] 💾 Stored response (cache size: {len(self.cache)})")


class RateLimiter:
    """
    Rate limiter for Gemini API calls.
    Persists count to disk for tracking across restarts.
    """
    
    def __init__(self, daily_limit: int = GEMINI_DAILY_LIMIT, persist_path: str = "./data/rate_limit.json"):
        self.daily_limit = daily_limit
        self.persist_path = persist_path
        self._load()
    
    def _load(self):
        """Load rate limit state from disk."""
        try:
            with open(self.persist_path, 'r') as f:
                data = json.load(f)
                # Reset if it's a new day
                stored_date = data.get("date", "")
                today = datetime.now().strftime("%Y-%m-%d")
                if stored_date == today:
                    self.count = data.get("count", 0)
                else:
                    self.count = 0  # New day, reset counter
                self.date = today
        except (FileNotFoundError, json.JSONDecodeError):
            self.count = 0
            self.date = datetime.now().strftime("%Y-%m-%d")
    
    def _save(self):
        """Save rate limit state to disk."""
        import os
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        with open(self.persist_path, 'w') as f:
            json.dump({"date": self.date, "count": self.count}, f)
    
    def check(self) -> bool:
        """Check if we're within rate limit."""
        # Reset if new day
        today = datetime.now().strftime("%Y-%m-%d")
        if self.date != today:
            self.count = 0
            self.date = today
            self._save()
        return self.count < self.daily_limit
    
    def increment(self):
        """Increment request count."""
        self.count += 1
        self._save()
        remaining = self.daily_limit - self.count
        print(f"[RateLimit] 📊 {self.count}/{self.daily_limit} requests today ({remaining} remaining)")
    
    def get_remaining(self) -> int:
        """Get remaining requests for today."""
        return max(0, self.daily_limit - self.count)



class LLMAgent:
    def __init__(self, event_bus, state_engine, automations, learning_engine=None, subscribe_to_voice=True, 
                 override_provider=None, override_model=None):
        self.event_bus = event_bus
        self.state_engine = state_engine
        self.automations = automations
        self.learning_engine = learning_engine
        self.subscribe_to_voice = subscribe_to_voice
        
        # Security tracking
        self.attack_attempts = 0
        self.last_attack_time = 0
        
        # Initialize Memory System
        from arvis_core.memory import MemoryOrchestrator
        # Only init memory if not in "dummy" mode (event_bus is not None)
        if event_bus and hasattr(event_bus, 'subscribe'):
            self.memory = MemoryOrchestrator(
                persist_dir="./data/memories",
                max_conversation_turns=10,
                observation_decay_days=30
            ) 
            print("[LLMAgent] Memory system initialized")
        else:
            self.memory = None
        
        # ═══════════════════════════════════════════════════════════
        # CACHING AND RATE LIMITING
        # ═══════════════════════════════════════════════════════════
        self.semantic_cache = SemanticCache(max_size=SEMANTIC_CACHE_SIZE)
        self.rate_limiter = RateLimiter(daily_limit=GEMINI_DAILY_LIMIT)
        # print(f"[LLMAgent] Rate limit: {self.rate_limiter.get_remaining()}/{GEMINI_DAILY_LIMIT} remaining today")
        
        # ═══════════════════════════════════════════════════════════
        # LLM PROVIDER SELECTION: Gemini (primary) or Groq (fallback)
        # ═══════════════════════════════════════════════════════════
        self.provider = None
        self.client = None
        self.gemini_model = None
        
        # LLM_PROVIDER env: "gemini", "groq", "lmstudio", or "auto" (default)
        if override_provider:
             preferred_provider = override_provider.lower()
             print(f"[LLMAgent] Using OVERRIDE provider: {preferred_provider}")
        else:
             preferred_provider = os.environ.get("LLM_PROVIDER", "auto").lower()
             print(f"[LLMAgent] LLM_PROVIDER={preferred_provider}")
        
        # Initialize based on preference
        if preferred_provider in ("gemini", "auto"):
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if gemini_key:
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=gemini_key)
                    # Use layered prompt from PromptBuilder
                    self.prompt_builder = get_prompt_builder()
                    self.gemini_model = genai.GenerativeModel(
                        model_name="gemini-2.0-flash",
                        system_instruction=self.prompt_builder.build_system_prompt("gemini"),
                        tools=convert_tools_for_gemini(TOOLS_SCHEMA)
                    )
                    self.provider = "gemini"
                    print("[LLMAgent] ✅ Using Gemini 2.0 Flash")
                except Exception as e:
                    print(f"[LLMAgent] Gemini init failed: {e}")
        
        if preferred_provider in ("groq", "auto") and not self.provider:
            groq_key = os.environ.get("GROQ_API_KEY")
            if groq_key:
                from groq import Groq
                self.client = Groq(api_key=groq_key)
                self.provider = "groq"
                print("[LLMAgent] ✅ Using Groq")
        
        # OpenAI (GPT-4o, GPT-4, GPT-3.5-turbo)
        if preferred_provider in ("openai", "auto") and not self.provider:
            openai_key = os.environ.get("OPENAI_API_KEY")
            if openai_key:
                try:
                    from openai import OpenAI
                    self.client = OpenAI(api_key=openai_key)
                    self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
                    self.provider = "openai"
                    print(f"[LLMAgent] ✅ Using OpenAI ({self.openai_model})")
                except Exception as e:
                    print(f"[LLMAgent] OpenAI init failed: {e}")
        
        # Synthetic API (OpenAI-compatible)
        if preferred_provider in ("synthetic", "auto") and not self.provider:
            synthetic_key = os.environ.get("SYNTHETIC_API_KEY")
            if synthetic_key:
                try:
                    from openai import OpenAI
                    self.client = OpenAI(
                        api_key=synthetic_key,
                        base_url="https://api.synthetic.new/openai/v1"
                    )
                    self.synthetic_model = os.environ.get("SYNTHETIC_MODEL", "hf:meta-llama/Llama-3.3-70B-Instruct")
                    self.provider = "synthetic"
                    print(f"[LLMAgent] ✅ Using Synthetic API ({self.synthetic_model})")
                except Exception as e:
                    print(f"[LLMAgent] Synthetic API init failed: {e}")
        
        # OpenRouter (OpenAI-compatible, multi-model gateway)
        if preferred_provider in ("openrouter", "auto") and not self.provider:
            openrouter_key = os.environ.get("OPENROUTER_API_KEY")
            if openrouter_key:
                try:
                    from openai import OpenAI
                    self.client = OpenAI(
                        api_key=openrouter_key,
                        base_url="https://openrouter.ai/api/v1"
                    )
                    self.openrouter_model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
                    self.provider = "openrouter"
                    print(f"[LLMAgent] ✅ Using OpenRouter ({self.openrouter_model})")
                except Exception as e:
                    print(f"[LLMAgent] OpenRouter init failed: {e}")
        
        # K2 Think (OpenAI-compatible reasoning model)
        if preferred_provider in ("k2think", "k2", "auto") and not self.provider:
            k2think_key = os.environ.get("K2THINK_API_KEY")
            if k2think_key:
                try:
                    from openai import OpenAI
                    self.client = OpenAI(
                        api_key=k2think_key,
                        base_url="https://api.k2think.ai/v1"
                    )
                    self.k2think_model = os.environ.get("K2THINK_MODEL", "MBZUAI-IFM/K2-Think-v2")
                    self.provider = "k2think"
                    print(f"[LLMAgent] ✅ Using K2 Think ({self.k2think_model})")
                except Exception as e:
                    print(f"[LLMAgent] K2 Think init failed: {e}")
        
        # LM Studio local LLM (OpenAI-compatible API)
        if preferred_provider in ("lmstudio", "local", "auto") and not self.provider:
            lmstudio_url = os.environ.get("LMSTUDIO_URL", "http://localhost:1234/v1")
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=lmstudio_url, api_key="lm-studio")
                self.lmstudio_model = os.environ.get("LMSTUDIO_MODEL", "local-model")
                self.provider = "lmstudio"
                print(f"[LLMAgent] ✅ Using LM Studio ({lmstudio_url})")
            except Exception as e:
                print(f"[LLMAgent] LM Studio init failed: {e}")
        
        # Custom Colab API (direct requests to ngrok endpoint)
        if preferred_provider in ("colab", "custom") and not self.provider:
            self.colab_url = os.environ.get("COLAB_API_URL", "https://f4d5170fa4ea.ngrok-free.app/chat")
            import requests
            try:
                # Quick health check
                requests.get(self.colab_url.replace("/chat", "/"), timeout=5)
                self.provider = "colab"
                print(f"[LLMAgent] ✅ Using Colab API ({self.colab_url})")
            except Exception as e:
                print(f"[LLMAgent] Colab API init failed: {e}")
        
        if not self.provider:
            print("[LLMAgent] ⚠️ No LLM configured! Set LLM_PROVIDER and API keys")
        
        # Ensure prompt_builder is initialized for non-Gemini providers
        if not hasattr(self, 'prompt_builder') or self.prompt_builder is None:
            self.prompt_builder = get_prompt_builder()
        
        # Subscribe to events
        if self.subscribe_to_voice:
            event_bus.subscribe("voice_command", self.handle)
        
        event_bus.subscribe("time_tick", self.handle)

        event_bus.subscribe("relay_toggled", self.handle)
        event_bus.subscribe("action_request", self.handle)
    
    # ═══════════════════════════════════════════════════════════
    # REUSABLE GENERATION METHODS
    # ═══════════════════════════════════════════════════════════
    
    def generate_tool_calls(self, system_prompt: str, user_content: str, tools=None) -> list:
        """
        Generate tool calls from any configured provider.
        Returns a list of tool call dicts: [{"tool": "name", "args": {...}}]
        """
        # Default to standard tools if not provided
        if tools is None:
            tools = TOOLS_SCHEMA

        # 1. GEMINI
        if self.provider == "gemini":
            try:
                # Gemini requires specific tool formatting
                gemini_tools = convert_tools_for_gemini(tools)
                
                # We need to temporarily override system instruction or use chat
                # Since system instruction is fixed in model init, we'll prepend it to user msg 
                # or use a new chat session.
                chat = self.gemini_model.start_chat(history=[
                    {"role": "user", "parts": [system_prompt]}
                ])
                
                response = chat.send_message(user_content)
                
                # Parse Gemini function calls
                tool_calls = []
                for part in response.parts:
                    if fn := part.function_call:
                        # Convert arguments to dict
                        args = {}
                        for key, value in fn.args.items():
                            args[key] = value
                        
                        tool_calls.append({
                            "tool": fn.name,
                            "args": args
                        })
                return tool_calls
                
            except Exception as e:
                print(f"[LLMAgent] Gemini generation failed: {e}")
                return []

        # 2. OPENAI-COMPATIBLE (Groq, OpenAI, LM Studio, etc.)
        elif self.client:
            try:
                # Determine model name
                model = "gpt-3.5-turbo" # Default fallback
                if self.provider == "groq":
                    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
                elif self.provider == "openai":
                    model = override_model or getattr(self, "openai_model", "gpt-4o-mini")
                elif self.provider == "synthetic":
                    model = override_model or getattr(self, "synthetic_model", "hf:meta-llama/Llama-3.3-70B-Instruct")
                elif self.provider == "openrouter":
                    model = override_model or getattr(self, "openrouter_model", "meta-llama/llama-3.3-70b-instruct")
                elif self.provider == "lmstudio":
                    model = override_model or getattr(self, "lmstudio_model", "local-model")
                elif self.provider == "k2think":
                    model = override_model or getattr(self, "k2think_model", "MBZUAI-IFM/K2-Think")

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
                
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto"
                )
                
                if not response.choices:
                    return []
                    
                message = response.choices[0].message
                if message.tool_calls:
                    tool_calls = []
                    for tc in message.tool_calls:
                        try:
                            tool_calls.append({
                                "tool": tc.function.name,
                                "args": json.loads(tc.function.arguments)
                            })
                        except json.JSONDecodeError:
                            pass
                    return tool_calls
            
            except Exception as e:
                print(f"[LLMAgent] Provider {self.provider} generation failed: {e}")
                return []
        
        return []

    # ═══════════════════════════════════════════════════════════
    # K2 THINK RESPONSE PARSING
    # ═══════════════════════════════════════════════════════════
    
    def _parse_k2think_response(self, content: str) -> tuple[str, str]:
        """
        Parse K2 Think response which uses <think>...</think> and <answer>...</answer> tags.
        Returns (answer, thinking) - answer is the user-facing response, thinking is for logs.
        """
        answer = content
        thinking = ""
        
        # Extract thinking trace (for debugging/logging)
        think_match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
        
        # Extract final answer (user-facing)
        answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL)
        if answer_match:
            answer = answer_match.group(1).strip()
        else:
            # If no <answer> tags, strip <think> tags and use remainder
            answer = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
        return answer, thinking

    # ═══════════════════════════════════════════════════════════
    # SECURITY METHODS
    # ═══════════════════════════════════════════════════════════
    
    def _detect_attack(self, text: str) -> tuple:
        """
        Detect suspicious patterns in input text.
        Returns (is_attack: bool, attack_type: str, sanitized_text: str)
        """
        import random
        
        if not text:
            return False, None, text
        
        text_lower = text.lower()
        
        # Check for suspicious patterns
        for pattern, attack_type in SUSPICIOUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                print(f"[Security] ⚠️ Attack detected: {attack_type}")
                return True, attack_type, None
        
        return False, None, text
    def _requires_pin(self, text: str) -> bool:
        """Check if command requires PIN verification"""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in PIN_REQUIRED_KEYWORDS)
    
    def _generate_troll_response(self, attack_type: str, original_text: str, attempt_count: int) -> str:
        """Use LLM to generate a contextual, humorous troll response"""
        try:
            troll_prompt = f"""You are ARVIS, a witty home automation assistant. Someone just tried to attack you with a {attack_type}.

Their suspicious input was: "{original_text[:100]}"
This is attempt #{attempt_count} from this user.

Generate a SHORT, WITTY, HUMOROUS response that:
- Gently mocks their attempt without being mean
- Shows you're smarter than to fall for it
- Uses emojis sparingly (1-2 max)
- Offers to help with legitimate home commands instead
- Is unique and contextual to their specific attack
- Gets progressively more sarcastic with higher attempt counts

Keep it under 2 sentences. Be creative and funny!
If attempt >= 4, also mention their activity has been logged.

Output ONLY the response message, nothing else."""

            groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            response = self.client.chat.completions.create(
                model=groq_model,
                messages=[
                    {"role": "system", "content": "You are a witty AI assistant responding to security attacks with humor."},
                    {"role": "user", "content": troll_prompt}
                ],
                max_tokens=150,
                temperature=0.9  # Higher temperature for more creative responses
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Security] Error generating troll response: {e}")
            # Fallback to a simple response if LLM fails
            return f"🤖 Nice try with that {attack_type}! I'm just a humble home assistant. How about 'turn on the lights' instead?"
    
    def _handle_attack(self, attack_type: str, original_text: str):
        """Handle detected attack with AI-generated humorous responses"""
        self.attack_attempts += 1
        self.last_attack_time = time.time()
        
        # Log the attack
        self.event_bus.publish({
            "type": "security_alert",
            "payload": {
                "attack_type": attack_type,
                "attempts": self.attack_attempts,
                "text": original_text[:100]  # Truncate for logging
            },
            "source": "llm_agent",
            "timestamp": time.time()
        })
        
        # Generate contextual response
        if self.attack_attempts <= 1:
            # First attempt: polite warning
            message = f"⚠️ Hmm, that looks like a {attack_type}. Could you rephrase that as a normal command? I'm here to help with your smart home!"
        else:
            # Subsequent attempts: AI-generated troll response
            message = self._generate_troll_response(attack_type, original_text, self.attack_attempts)
        
        # Publish response to user
        self.event_bus.publish({
            "type": "user_query",
            "source": "security",
            "payload": {"question": message, "type": "security_warning"}
        })
        print(f"[Security] 🔐 Attack response sent (attempt #{self.attack_attempts})")

    # ═══════════════════════════════════════════════════════════
    # CONTEXT HELPER METHODS
    # ═══════════════════════════════════════════════════════════
    
    def _get_presence(self) -> str:
        """Get current home presence state"""
        try:
            # Try direct get if available
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("home_presence", "unknown")
            # Try get_state for dict access
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("home_presence", "unknown")
        except Exception:
            pass
        return "unknown"
    
    def _get_sleep_state(self) -> bool:
        """Get current sleep state"""
        try:
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("sleep_state", False)
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("sleep_state", False)
        except Exception:
            pass
        return False
    
    def _get_activity_hint(self) -> str:
        """Get current activity hint"""
        try:
            if hasattr(self.state_engine, 'get'):
                return self.state_engine.get("activity_hint", "none")
            if hasattr(self.state_engine, 'get_state'):
                state = self.state_engine.get_state()
                if isinstance(state, dict):
                    return state.get("activity_hint", "none")
        except Exception:
            pass
        return "none"
    
    def _get_user_preferences(self) -> dict:
        """Retrieve user preferences from LearningEngine"""
        if self.learning_engine:
            try:
                return self.learning_engine.get_preferences()
            except Exception:
                pass
        return {}
    
    def _get_device_states(self) -> str:
        """Get current device states as summary string"""
        try:
            return self.state_engine.summary()
        except Exception:
            return "No device states available"
    
    def _build_context(self, event: dict) -> dict:
        """Build rich context for LLM including home state, preferences, and memory."""
        # Extract query for semantic memory search
        query = ""
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            query = payload.get("text", "") if isinstance(payload, dict) else str(payload)
        
        # Get home state
        home_state = {
            "time": datetime.now().strftime('%H:%M'),
            "date": datetime.now().strftime('%Y-%m-%d'),
            "day_of_week": datetime.now().strftime('%A'),
            "presence": self._get_presence(),
            "sleep_state": self._get_sleep_state(),
            "activity_hint": self._get_activity_hint()
        }
        
        # Get device states
        device_states = self._get_device_states()
        
        # Build memory context (searches for relevant preferences/observations)
        memory_context = ""
        if query:
            try:
                memory_context = self.memory.get_context(
                    query=query,
                    device_states=self.state_engine.devices if hasattr(self.state_engine, 'devices') else None,
                    home_state=home_state
                )
            except Exception as e:
                print(f"[LLMAgent] Memory context error: {e}")
        
        return {
            "event": event,
            "home_state": home_state,
            "device_states": device_states,
            "routines": self.automations.list(),
            "preferences": self._get_user_preferences(),
            "memory_context": memory_context  # NEW: Personalized memory
        }

    # ═══════════════════════════════════════════════════════════
    # EVENT HANDLING
    # ═══════════════════════════════════════════════════════════

    def handle(self, event):
        """Handle incoming events and generate tool calls via LLM"""
        # Defensive check for event type
        if not isinstance(event, dict):
            print(f"[LLMAgent] Warning: Expected dict event, got {type(event)}: {event}")
            return
        
        # Skip time ticks to save API calls
        print(f"[LLMAgent] Handling event: {event.get('type', 'unknown')}")

        # Ignore historical events (older than 60 seconds)
        if time.time() - event.get("timestamp", 0) > 60:
             return

        # ═══════════════════════════════════════════════════════════
        # SECURITY CHECKS (for voice commands)
        # ═══════════════════════════════════════════════════════════
        
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            user_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
            
            # Detect attacks
            is_attack, attack_type, sanitized_text = self._detect_attack(user_text)
            
            if is_attack:
                self._handle_attack(attack_type, user_text)
                return  # Block the request from reaching LLM
            
            # Check if PIN is required for sensitive operations
            if self._requires_pin(user_text):
                print(f"[Security] 🔐 PIN required for: {user_text[:50]}...")
                # Inject PIN requirement context
                event = dict(event)  # Make a copy
                if isinstance(event.get("payload"), dict):
                    event["payload"]["requires_pin"] = True
                    event["payload"]["security_notice"] = "This operation requires PIN verification. Use request_pin_verification tool first."

        # Build rich context
        context = self._build_context(event)

        # Helper to extract valid tool names
        valid_tool_names = {t["function"]["name"] for t in TOOLS_SCHEMA}

        # ═══════════════════════════════════════════════════════════
        # GENERATION LOOP (with Retry for Validation)
        # ═══════════════════════════════════════════════════════════
        max_retries = 2
        messages = [
            {"role": "system", "content": self.prompt_builder.build_system_prompt(self.provider)},
            {"role": "user", "content": json.dumps(context)}
        ]

        for attempt in range(max_retries + 1):
            try:
                groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
                response = self.client.chat.completions.create(
                    model=groq_model,
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto"
                )

                if not response or not response.choices:
                    print(f"[LLMAgent] Error: Empty response from provider: {response}")
                    return

                message = response.choices[0].message
                
                # Handle non-tool response (Chat)
                if not message.tool_calls:
                    content = message.content
                    
                    # Parse K2 Think response to extract answer from tags
                    if self.provider == "k2think" and content:
                        answer, thinking = self._parse_k2think_response(content)
                        if thinking:
                            print(f"[LLMAgent] 🧠 K2 Think reasoning: {thinking[:200]}...")
                        content = answer
                    
                    print(f"[LLMAgent] 🗣️ Chat Response: {content}")
                    self.event_bus.publish({
                        "type": "agent_response",
                        "payload": {"text": content, "source": "llm_agent"}
                    })
                    return # Success (Chat)

                elif message.tool_calls:
                    # VALIDATION PHASE
                    validation_errors = []
                    tool_calls = []
                    
                    for tc in message.tool_calls:
                        t_name = tc.function.name
                        t_args_str = tc.function.arguments
                        
                        # 1. Check if tool exists
                        if t_name not in valid_tool_names:
                            validation_errors.append(f"Tool '{t_name}' does not exist. Available tools include: turn_on, turn_off, etc.")
                            continue
                            
                        # 2. Check JSON validity
                        try:
                            t_args = json.loads(t_args_str)
                        except json.JSONDecodeError:
                            validation_errors.append(f"Arguments for '{t_name}' are not valid JSON.")
                            continue

                        # 3. Basic Check (e.g. required args - deeper check could use JSON Schema lib)
                        # For now, we trust the model mostly on structure if name is correct, 
                        # but we capture the valid call.
                        
                        tool_calls.append({
                            "tool": t_name,
                            "args": t_args
                        })
                    
                    # If we have validation errors, feed them back
                    if validation_errors:
                        print(f"[LLMAgent] ⚠️ Validation Failed (Attempt {attempt+1}): {validation_errors}")
                        error_msg = "Error: " + " ".join(validation_errors) + " Please correct your response."
                        
                        # Append assistant's bad response and our error message to history
                        # We need to reconstruct the assistant message for the history
                        # OpenAI API requires tool_calls to be in the message if we continue conversation
                        messages.append(message) 
                        messages.append({"role": "user", "content": error_msg})
                        continue # Retry loop
                    
                    # Success! Publish valid calls
                    self.event_bus.publish({
                        "type": "tool_calls_generated",
                        "payload": tool_calls,
                        "source": "llm_agent",
                        "timestamp": time.time()
                    })
                    return # Success (Tools)

            except Exception as e:
                print(f"[LLMAgent] Error calling Groq: {e}")
                return # Stop on fatal API error

    # ═══════════════════════════════════════════════════════════
    # STREAMING RESPONSE (for Async Pipeline)
    # ═══════════════════════════════════════════════════════════
    
    def handle_streaming(self, event):
        """
        Handle event with streaming response for async voice pipeline.
        Yields tokens as they arrive from the LLM.
        
        Tool calls are wrapped in ### TOOL: ... ### markers for router.
        Supports both Gemini and Groq providers.
        """
        # Defensive check
        if not isinstance(event, dict):
            return
        
        if event.get("type") == "time_tick":
            return
        
        # Security checks
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            user_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
            
            is_attack, attack_type, sanitized_text = self._detect_attack(user_text)
            if is_attack:
                self._handle_attack(attack_type, user_text)
                return
            
            # Store user message in conversation memory
            self.memory.add_conversation("user", user_text)
            
            # ═══════════════════════════════════════════════════════════
            # SEMANTIC CACHE CHECK - Return cached response if similar query
            # ═══════════════════════════════════════════════════════════
            cached_response = self.semantic_cache.get(user_text)
            if cached_response:
                print(f"[LLMAgent] 🚀 Using cached response")
                yield cached_response
                return
        
        # ═══════════════════════════════════════════════════════════
        # RATE LIMIT CHECK
        # ═══════════════════════════════════════════════════════════
        if self.provider == "gemini" and not self.rate_limiter.check():
            print("[LLMAgent] ⚠️ Rate limit exceeded!")
            yield "### TOOL: {\"tool\": \"ask_user\", \"args\": {\"message\": \"I've reached my daily limit. Please try again tomorrow or switch to Groq.\"}} ###"
            return
        
        # Build context (now includes memory)
        context = self._build_context(event)
        
        # Extract query text for caching
        query_text = ""
        if event.get("type") == "voice_command":
            payload = event.get("payload", {})
            query_text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
        
        # Track response for conversation memory
        full_response = []
        
        try:
            if self.provider == "gemini":
                # ═══════════════════════════════════════════════════════════
                # GEMINI SDK STREAMING  
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                
                response = self.gemini_model.generate_content(
                    json.dumps(context),
                    stream=True
                )
                
                for chunk in response:
                    # Check candidates and parts directly
                    if hasattr(chunk, 'candidates') and chunk.candidates:
                        for candidate in chunk.candidates:
                            if hasattr(candidate, 'content') and candidate.content:
                                for part in candidate.content.parts:
                                    # Handle function calls
                                    if hasattr(part, 'function_call') and part.function_call:
                                        fc = part.function_call
                                        tool_output = f"### TOOL: {json.dumps({'tool': fc.name, 'args': dict(fc.args)})} ###"
                                        full_response.append(tool_output)
                                        yield tool_output
                                    # Handle text
                                    elif hasattr(part, 'text') and part.text:
                                        yield part.text
                                        full_response.append(part.text)
            
            elif self.provider == "vertex":
                # ═══════════════════════════════════════════════════════════
                # VERTEX AI REST API STREAMING
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                import requests
                
                url = f"https://aiplatform.googleapis.com/v1/publishers/google/models/{self.vertex_model}:streamGenerateContent?key={self.vertex_api_key}"
                
                # Build request body with system instruction and tools
                request_body = {
                    "contents": [
                        {"role": "user", "parts": [{"text": json.dumps(context)}]}
                    ],
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "tools": [{"functionDeclarations": self._get_vertex_tools()}]
                }
                
                response = requests.post(url, json=request_body, stream=True)
                
                if response.status_code != 200:
                    error_msg = response.text[:500]
                    print(f"[LLMAgent] Vertex API error: {error_msg}")
                    yield f"### TOOL: {{\"tool\": \"ask_user\", \"args\": {{\"message\": \"API error: {response.status_code}\"}}}} ###"
                    return
                
                # Parse streaming JSON response
                buffer = ""
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        buffer += line
                        try:
                            # Try to parse accumulated buffer
                            data = json.loads(buffer.strip().lstrip('[').rstrip(',]'))
                            buffer = ""
                            
                            # Extract text or function calls
                            for candidate in data.get("candidates", []):
                                content = candidate.get("content", {})
                                for part in content.get("parts", []):
                                    if "text" in part:
                                        yield part["text"]
                                        full_response.append(part["text"])
                                    if "functionCall" in part:
                                        fc = part["functionCall"]
                                        tool_output = f"### TOOL: {json.dumps({'tool': fc['name'], 'args': fc.get('args', {})})} ###"
                                        full_response.append(tool_output)
                                        yield tool_output
                        except json.JSONDecodeError:
                            # Keep accumulating
                            pass
            
            elif self.provider == "groq":
                # ═══════════════════════════════════════════════════════════
                # GROQ STREAMING
                # ═══════════════════════════════════════════════════════════
                groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
                stream = self.client.chat.completions.create(
                    model=groq_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(context)}
                    ],
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    stream=True
                )
                
                # Track if we're accumulating a tool call
                current_tool = None
                tool_args_buffer = ""
                
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    
                    # Handle text content
                    if delta.content:
                        yield delta.content
                        full_response.append(delta.content)
                    
                    # Handle tool calls (streamed as deltas)
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc.function.name:
                                # New tool call starting
                                if current_tool:
                                    # Emit previous tool
                                    tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                                    full_response.append(tool_output)
                                    yield tool_output
                                current_tool = tc.function.name
                                tool_args_buffer = tc.function.arguments or ""
                            elif tc.function.arguments:
                                # Accumulating arguments
                                tool_args_buffer += tc.function.arguments
                
                # Emit final tool if any
                if current_tool and tool_args_buffer:
                    try:
                        tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                        full_response.append(tool_output)
                        yield tool_output
                    except json.JSONDecodeError:
                        print(f"[LLMAgent] Failed to parse tool args: {tool_args_buffer}")
            
            elif self.provider in ("openai", "k2think"):
                # ═══════════════════════════════════════════════════════════
                # OPENAI & K2 THINK STREAMING
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                
                # Model selection
                model = "gpt-4o" # Default fallback
                if self.provider == "openai":
                    model = getattr(self, "openai_model", "gpt-4o")
                elif self.provider == "k2think":
                    model = getattr(self, "k2think_model", "MBZUAI-IFM/K2-Think")
                
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(context)}
                    ],
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    stream=True
                )
                
                current_tool = None
                tool_args_buffer = ""
                
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue
                    
                    if delta.content:
                        yield delta.content
                        full_response.append(delta.content)
                    
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            if tc.function.name:
                                if current_tool:
                                    tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                                    full_response.append(tool_output)
                                    yield tool_output
                                current_tool = tc.function.name
                                tool_args_buffer = tc.function.arguments or ""
                            elif tc.function.arguments:
                                tool_args_buffer += tc.function.arguments
                
                if current_tool and tool_args_buffer:
                    try:
                        tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                        full_response.append(tool_output)
                        yield tool_output
                    except json.JSONDecodeError:
                        print(f"[LLMAgent] Failed to parse tool args: {tool_args_buffer}")
            
            elif self.provider == "synthetic":
                # ═══════════════════════════════════════════════════════════
                # SYNTHETIC API STREAMING
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                
                stream = self.client.chat.completions.create(
                    model=self.synthetic_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(context)}
                    ],
                    stream=True
                )
                
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        yield chunk.choices[0].delta.content
                        full_response.append(chunk.choices[0].delta.content)
            
            elif self.provider == "openrouter":
                # ═══════════════════════════════════════════════════════════
                # OPENROUTER STREAMING (text-based, some models don't support tools)
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                
                stream = self.client.chat.completions.create(
                    model=self.openrouter_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(context)}
                    ],
                    stream=True
                )
                
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        yield chunk.choices[0].delta.content
                        full_response.append(chunk.choices[0].delta.content)
            
            elif self.provider == "lmstudio":
                # ═══════════════════════════════════════════════════════════
                # LM STUDIO STREAMING (OpenAI-compatible local LLM)
                # Identity is in Jinja template, use reduced prompt
                # ═══════════════════════════════════════════════════════════
                self.rate_limiter.increment()
                
                # Use reduced prompt (identity is baked into Jinja template)
                lmstudio_prompt = get_system_prompt("lmstudio")
                combined_message = f"{lmstudio_prompt}\n\n---\nUser Request:\n{json.dumps(context)}"
                
                stream = self.client.chat.completions.create(
                    model=self.lmstudio_model,
                    messages=[
                        {"role": "user", "content": combined_message}
                    ],
                    temperature=0.3,
                    stream=True
                )
                
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        yield delta.content
                        full_response.append(delta.content)
            
            elif self.provider == "colab":
                # ═══════════════════════════════════════════════════════════
                # COLAB API STREAMING (Custom ngrok endpoint)
                # ═══════════════════════════════════════════════════════════
                import requests
                self.rate_limiter.increment()
                
                # Build the request payload
                system_prompt = get_system_prompt("lmstudio")  # Use reduced prompt
                
                payload = {
                    "system_prompt": system_prompt,
                    "messages": [
                        {"role": "user", "content": json.dumps(context)}
                    ],
                    "stream": True
                }
                
                try:
                    response = requests.post(
                        self.colab_url,
                        json=payload,
                        timeout=60,
                        stream=True,
                        headers={"ngrok-skip-browser-warning": "true"}
                    )
                    response.raise_for_status()
                    
                    # Stream the response
                    for line in response.iter_lines():
                        if line:
                            line_str = line.decode('utf-8')
                            # Handle SSE format (data: {...})
                            if line_str.startswith("data: "):
                                line_str = line_str[6:]  # Remove "data: " prefix
                            
                            if line_str.strip() == "[DONE]":
                                break
                            
                            try:
                                data = json.loads(line_str)
                                # Handle different response formats
                                if "content" in data:
                                    token = data["content"]
                                elif "response" in data:
                                    token = data["response"]
                                elif "text" in data:
                                    token = data["text"]
                                elif "delta" in data:
                                    token = data.get("delta", {}).get("content", "")
                                else:
                                    token = line_str
                                
                                if token:
                                    yield token
                                    full_response.append(token)
                            except json.JSONDecodeError:
                                # Not JSON, yield as raw text
                                if line_str.strip():
                                    yield line_str
                                    full_response.append(line_str)
                                    
                except requests.exceptions.RequestException as e:
                    print(f"[LLMAgent] Colab API error: {e}")
                    yield f"### TOOL: {{\"tool\": \"ask_user\", \"args\": {{\"message\": \"Colab API error: {str(e)[:50]}\"}}}} ###"
            
            else:
                print("[LLMAgent] No LLM provider configured!")
                yield "### TOOL: {\"tool\": \"ask_user\", \"args\": {\"message\": \"LLM not configured. Please set GEMINI_API_KEY or GROQ_API_KEY.\"}} ###"
            
            # Store assistant response in conversation memory
            if full_response:
                response_text = "".join(full_response)[:500]
                self.memory.add_conversation("assistant", response_text)
                
                # ═══════════════════════════════════════════════════════════
                # CACHE THE RESPONSE for future similar queries
                # ═══════════════════════════════════════════════════════════
                if query_text and response_text:
                    self.semantic_cache.put(query_text, "".join(full_response))
                    
        except Exception as e:
            print(f"[LLMAgent] Streaming error: {e}")
            import traceback
            traceback.print_exc()

    def _get_tool_descriptions_for_local(self):
        """Generate text-based tool descriptions for local LLMs without native function calling."""
        lines = ["AVAILABLE TOOLS (output as ### TOOL: {\"tool\": \"name\", \"args\": {...}} ###):"]
        for tool in TOOLS_SCHEMA:
            if tool.get("type") == "function":
                func = tool["function"]
                name = func["name"]
                desc = func.get("description", "")
                params = func.get("parameters", {}).get("properties", {})
                param_strs = []
                for pname, pdef in params.items():
                    ptype = pdef.get("type", "string")
                    pdesc = pdef.get("description", "")
                    param_strs.append(f"  - {pname} ({ptype}): {pdesc}")
                lines.append(f"\n• {name}: {desc}")
                if param_strs:
                    lines.extend(param_strs)
        return "\n".join(lines)

    def _call_groq_streaming(self, context: dict, full_response: list):
        """Helper method to call Groq streaming API. Used for fallback."""
        groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        stream = self.client.chat.completions.create(
            model=groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)}
            ],
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            stream=True
        )
        
        current_tool = None
        tool_args_buffer = ""
        
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            
            # Text content
            if delta.content:
                yield delta.content
                full_response.append(delta.content)
            
            # Tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    if tc.function.name:
                        if current_tool:
                            # Emit previous tool
                            tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                            full_response.append(tool_output)
                            yield tool_output
                        current_tool = tc.function.name
                        tool_args_buffer = tc.function.arguments or ""
                    elif tc.function.arguments:
                        tool_args_buffer += tc.function.arguments
        
        # Emit final tool
        if current_tool and tool_args_buffer:
            try:
                tool_output = f"### TOOL: {json.dumps({'tool': current_tool, 'args': json.loads(tool_args_buffer)})} ###"
                full_response.append(tool_output)
                yield tool_output
            except json.JSONDecodeError:
                print(f"[LLMAgent] Failed to parse tool args: {tool_args_buffer}")
