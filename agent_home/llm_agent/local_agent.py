import os
import json
from llama_cpp import Llama
from huggingface_hub import hf_hub_download
from agent_home.llm_agent.prompt_local import build_local_prompt
from agent_home.llm_agent.local_validator import pre_validate, post_validate, validate_and_correct
from arvis_core.memory.preference_store import PreferenceStore

class LocalAgent:
    def __init__(self, model_path=None, model_type="qwen", persistence_dir="./data/memories"):
        """
        Initialize LocalAgent with a local LLM for fast tool calling.
        
        Args:
            model_path: Path to .gguf model file. If None, uses default.
            model_type: "qwen" (Qwen 2.5 3B) or "functiongemma" (FunctionGemma 270M)
        """
        self.model_type = model_type
        
        if not model_path:
            if model_type == "qwen":
                # Use Qwen 2.5 3B from E: drive
                model_path = "E:/models/qwen2.5-3b-instruct-q4_k_m.gguf"
                if not os.path.exists(model_path):
                    print(f"[LocalAgent] Qwen model not found at {model_path}, falling back to FunctionGemma")
                    model_type = "functiongemma"
                    self.model_type = model_type
            
            if model_type == "functiongemma":
                # Fallback to FunctionGemma from HuggingFace Hub
                try:
                    repo_id = "unsloth/functiongemma-270m-it-GGUF"
                    filename = "functiongemma-270m-it-Q8_0.gguf"
                    print(f"[LocalAgent] Resolving {filename} from {repo_id}...")
                    model_path = hf_hub_download(repo_id=repo_id, filename=filename)
                    print(f"[LocalAgent] Found model at: {model_path}")
                except Exception as e:
                    print(f"[LocalAgent] Failed to resolve model from Hub: {e}")
                    model_path = os.path.join(os.getcwd(), "functiongemma-270m-it-Q8_0.gguf")
            
        self.model_path = model_path
        self.llm = None
        
        try:
            print(f"[LocalAgent] Loading {model_type} model from {model_path}...")
            self.llm = Llama(
                model_path=model_path,
                n_ctx=4096,
                n_gpu_layers=-1,  # GPU acceleration: -1 = offload all layers to RTX 3050
                verbose=False,
                chat_format="chatml" if model_type == "qwen" else None  # Qwen uses ChatML format
            )
            print(f"[LocalAgent] {model_type.upper()} model loaded successfully.")
        except Exception as e:
            print(f"[LocalAgent] Failed to load model: {e}")

        # Initialize Memory Store
        self.memory = PreferenceStore(persist_dir=persistence_dir)

    def generate_tool_call(self, user_input: str, tools_schema: list, 
                           known_devices: list = None, learned_patterns: str = "") -> list:
        """
        Returns a list of tool call dicts or None if no tool selected or model failed.
        
        Args:
            user_input: The user's command text
            tools_schema: List of available tool schemas
            known_devices: List of valid device IDs (e.g., ["kitchen_main", "living_room_light"])
                          If provided, validates that generated device_id exists.
            learned_patterns: Optional pre-formatted few-shot examples from past successes
        """
        if not self.llm:
            return None
        
        # Default to empty list if not provided
        known_devices = known_devices or []

        # ═══════════════════════════════════════════════════════════
        # PRE-VALIDATION: Check if we should skip LLM entirely
        # ═══════════════════════════════════════════════════════════
        should_escalate, reason = pre_validate(user_input)
        if should_escalate:
            print(f"[LocalAgent] Pre-validation escalate: {reason}")
            return [{"tool": "escalate", "args": {}}]

        # ═══════════════════════════════════════════════════════════
        # RETRY LOOP: Retry with correction prompt on hallucination
        # ═══════════════════════════════════════════════════════════
        tools_str = json.dumps(tools_schema, indent=None)
        devices_str = ", ".join(known_devices) if known_devices else "(none specified)"
        
        max_retries = 2
        last_error_reason = None
        
        for attempt in range(max_retries):
            # 0. Pre-validation (fail fast)
            is_valid, reason = pre_validate(user_input)
            if not is_valid:
                return [{"tool": "escalate", "args": {"reason": reason}}]

            # 1. Retrieve relevant memories
            context_str = ""
            try:
                # Search for relevant preferences/patterns
                matches = self.memory.search(user_input, limit=3)
                if matches:
                    memory_lines = ["## RELEVANT MEMORIES:"]
                    for m in matches:
                        memory_lines.append(f"- {m['content']}")
                    context_str = "\n".join(memory_lines)
            except Exception as e:
                print(f"[LocalAgent] Memory retrieval failed: {e}")

            # Build prompt - add correction hint on retry
            correction_hint = ""
            if attempt > 0 and last_error_reason:
                correction_hint = f"\n[CORRECTION: Previous attempt failed: {last_error_reason}. Be more careful.]\n"
            
            # 2. Build Prompt (with injection)
            prompt = build_local_prompt(
                user_input=user_input,
                tools_schema_str=tools_str,
                known_devices_str=devices_str,
                model_type=self.model_type,
                learned_patterns=f"{learned_patterns}\n{context_str}{correction_hint}".strip()
            )
            
            # Extract valid tool names for validation
            valid_tool_names = set()
            for t in tools_schema:
                if "function" in t and "name" in t["function"]:
                    valid_tool_names.add(t["function"]["name"])
                elif "name" in t:
                    valid_tool_names.add(t["name"])

            if attempt == 0:
                print(f"[LocalAgent DEBUG] Prompt:\n{prompt}")
            else:
                print(f"[LocalAgent] Retry {attempt + 1}/{max_retries} with correction hint")

            # Run Inference
            try:
                # Set stop tokens based on model type
                if self.model_type == "qwen":
                    stop_tokens = ["<|im_end|>", "<|im_start|>", "\n\n"]
                else:
                    stop_tokens = ["<end_of_turn>"]
                    
                response = self.llm(
                    prompt,
                    max_tokens=256,
                    stop=stop_tokens,
                    echo=False,
                    temperature=0.0 if attempt == 0 else 0.1  # Slight temperature on retry
                )
                
                text = response['choices'][0]['text'].strip()
                print(f"[LocalAgent DEBUG] Raw Output: '{text}'")
                
                # Parse Output
                if self.model_type == "qwen":
                    try:
                        parsed = json.loads(text)
                        tool_name = parsed.get("tool")
                        args = parsed.get("args", {})
                        
                        # Validate tool name
                        if tool_name not in valid_tool_names:
                            last_error_reason = f"Unknown tool '{tool_name}'"
                            print(f"[LocalAgent] ⚠️ {last_error_reason}. Retrying...")
                            continue  # Retry
                        
                        # POST-VALIDATION
                        result = [{"tool": tool_name, "args": args}]
                        is_valid, corrected, reason = post_validate(result[0], user_input, known_devices)
                        
                        if not is_valid:
                            last_error_reason = reason
                            print(f"[LocalAgent] Post-validation issue: {reason}. Retrying...")
                            continue  # Retry instead of returning
                        
                        # Device existence check
                        if tool_name != "escalate":
                            device_id = args.get("device_id", "")
                            if known_devices and device_id and device_id not in known_devices:
                                normalized = device_id.replace("_", " ")
                                if normalized not in known_devices:
                                    last_error_reason = f"Unknown device '{device_id}'"
                                    print(f"[LocalAgent] ⚠️ {last_error_reason}. Retrying...")
                                    continue  # Retry
                            print(f"[LocalAgent] ✅ Found action tool: {tool_name} -> {device_id}")
                        
                        return result  # Success!
                        
                    except json.JSONDecodeError as e:
                        last_error_reason = f"JSON parse error: {e}"
                        print(f"[LocalAgent] {last_error_reason}. Retrying...")
                        continue  # Retry
                
                else:
                    # FunctionGemma - no retry for now, fallback to original logic
                    break
                    
            except Exception as e:
                last_error_reason = f"Inference error: {e}"
                print(f"[LocalAgent] {last_error_reason}")
                continue  # Retry
        
        # All retries exhausted, escalate
        print(f"[LocalAgent] All {max_retries} attempts failed. Escalating. Last error: {last_error_reason}")
        return [{"tool": "escalate", "args": {}}]

    def process_memory_logs(self, tool_calls: list) -> int:
        """
        Process any log_memory tool calls in the list.
        Returns number of memories logged.
        """
        if not tool_calls:
            return 0
            
        count = 0
        for tc in tool_calls:
            if tc.get("tool") == "log_memory":
                args = tc.get("args", {})
                key = args.get("key")
                value = args.get("value")
                
                if key and value:
                    try:
                        self.memory.add(
                            content=str(value),
                            key=key,
                            context="local_agent",
                            confidence=1.0
                        )
                        count += 1
                        print(f"[LocalAgent] 💾 Persisted memory: {key}={value}")
                    except Exception as e:
                        print(f"[LocalAgent] Failed to persist memory: {e}")
        return count
