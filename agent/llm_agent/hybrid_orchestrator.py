import asyncio
import json
import time

class HybridOrchestrator:
    def __init__(self, event_bus, local_agent, cloud_agent, tool_executor, 
                 memory=None, alias_resolver=None):
        self.event_bus = event_bus
        self.local = local_agent
        self.cloud = cloud_agent
        self.executor = tool_executor
        self.memory = memory  # For pattern learning (Titans Update loop)
        self.alias_resolver = alias_resolver  # Smart device name resolution
        self._resolver_initialized = False
        
        # Subscribe to user intents/commands
        # Assuming 'voice_decoded' or similar is the event carrying text
        self.event_bus.subscribe("voice_command", self.handle_command)
        
    def handle_command(self, event):
        user_input = event.get("payload", {}).get("text")
        if not user_input:
            return

        print(f"[HybridOrchestrator] Processing: '{user_input}'")
        
        # 1. Fast Path (Local)
        # We need to pass the schemas to the local agent. 
        # Assuming cloud agent has the master list of tools? 
        # For now, we'll give local agent a restricted list (lights, switches).
        
        # TODO: Load this dynamically from state_engine
        local_tools = [
            {
                "name": "turn_on",
                "description": "Turn on a device (light, switch, fan)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string"},
                        "endpoint": {"type": "string"} # Optional
                    },
                    "required": ["device_id"]
                }
            },
            {
                "name": "turn_off",
                "description": "Turn off a device",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string"},
                        "endpoint": {"type": "string"}
                    },
                    "required": ["device_id"]
                }
            },
             {
                "name": "escalate",
                "description": "Use this if the user request is ambiguous, complex, requires reasoning, or mentions a routine/mission.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }
        ]
        
        # Known devices for validation (TODO: get from state_engine dynamically)
        # This prevents the local agent from "guessing" non-existent devices
        known_devices = [
            "kitchen_main", "kitchen_counter", "kitchen_fan",
            "living_room_light", "living_room_lamp", "tv_backlight",
            "bedroom_main", "bedroom_lamp", "bedroom_ac",
            "bathroom_light", "bathroom_exhaust",
            "porch_light", "garage_light"
        ]
        
        # Initialize alias resolver lazily if not provided
        if self.alias_resolver is None and not self._resolver_initialized:
            self._init_alias_resolver(known_devices)
        
        # The local agent receives both device IDs and natural variations
        # The resolver will handle matching later
        known_with_aliases = list(known_devices)
        
        # Add some natural language variations for the prompt
        # (these don't need to be exhaustive - the resolver handles matching)
        natural_variations = [
            "kitchen light", "living room light", "bedroom light", 
            "bathroom light", "porch light", "garage light",
            "tv light", "ac", "kitchen fan", "exhaust fan"
        ]
        known_with_aliases.extend(natural_variations)
        
        # Retrieve similar patterns for few-shot injection (Titans Retrieval loop)
        learned_patterns = ""
        if self.memory:
            learned_patterns = self.memory.format_patterns_for_prompt(user_input, k=3)
            if learned_patterns:
                print(f"[HybridOrchestrator] 🔍 Found {learned_patterns.count('User:')} similar patterns")
        
        print("[HybridOrchestrator] Trying Local Agent...")
        local_calls = self.local.generate_tool_call(
            user_input, local_tools, known_with_aliases, learned_patterns
        )
        
        if local_calls:
            # Check for escalation
            if any(c['tool'] == 'escalate' for c in local_calls):
                print("[HybridOrchestrator] Local Agent requested ESCALATION.")
                self._fallback_to_cloud(event)
            else:
                # Resolve device names using smart resolver
                original_phrase = None
                for call in local_calls:
                    if 'args' in call and 'device_id' in call['args']:
                        device_id = call['args']['device_id']
                        original_phrase = device_id
                        
                        # Skip if already a known device ID
                        if device_id in known_devices:
                            continue
                        
                        # Use smart resolver for alias matching
                        if self.alias_resolver:
                            result = self.alias_resolver.resolve(device_id)
                            if result:
                                actual_id, confidence, source = result
                                print(f"[HybridOrchestrator] 🎯 Resolved: '{device_id}' → '{actual_id}' ({confidence:.0%}, {source})")
                                call['args']['device_id'] = actual_id
                            else:
                                print(f"[HybridOrchestrator] ⚠️ Could not resolve device: '{device_id}'")
                
                print(f"[HybridOrchestrator] Local Agent Success! Calls: {local_calls}")
                
                # Publish tool calls event (same format as cloud agent)
                self.event_bus.publish({
                    "type": "tool_calls_generated",
                    "payload": local_calls,
                    "source": "local",
                    "timestamp": time.time()
                })
                
                # Execute locally!
                self.executor.execute(local_calls)
                
                # Process explicit memory logs (User: "remember X")
                if hasattr(self.local, "process_memory_logs"):
                    self.local.process_memory_logs(local_calls)
                
                # Log successful pattern for few-shot learning (Titans Update loop)
                resolved_device = local_calls[0].get('args', {}).get('device_id') if local_calls else None
                
                if self.memory:
                    self.memory.log_successful_pattern(user_input, local_calls, resolved_device)
                    print(f"[HybridOrchestrator] 📝 Pattern logged for learning")
                
                # Learn the alias for future use
                if self.alias_resolver and original_phrase and resolved_device:
                    self.alias_resolver.learn_alias(original_phrase, resolved_device)
                
                # Notify completion
                self.event_bus.publish({"type": "agent_response", "payload": {"text": "Done.", "source": "local"}})
        else:
            print("[HybridOrchestrator] Local Agent unsure (None). Falling back.")
            self._fallback_to_cloud(event)

    def _fallback_to_cloud(self, event):
        print("[HybridOrchestrator] Engaging Cloud Agent (Slow Path)...")
        # Current logic likely resides in LLMAgent.handle_event
        # We can just delegate to it.
        # Assuming cloud_agent has a handle_event method or similar
        self.cloud.handle(event)
    
    def _init_alias_resolver(self, known_devices: list):
        """Lazily initialize the DeviceAliasResolver with semantic embeddings."""
        try:
            from agent.memory.device_alias_resolver import DeviceAliasResolver
            
            persist_dir = "./data/memories"
            if self.memory:
                persist_dir = str(self.memory.persist_dir)
            
            self.alias_resolver = DeviceAliasResolver(
                known_devices=known_devices,
                persist_dir=persist_dir
            )
            self._resolver_initialized = True
            print(f"[HybridOrchestrator] 🧠 Smart alias resolver initialized with {len(known_devices)} devices")
        except ImportError as e:
            print(f"[HybridOrchestrator] ⚠️ DeviceAliasResolver not available: {e}")
            self._resolver_initialized = True  # Don't retry
        except Exception as e:
            print(f"[HybridOrchestrator] ⚠️ Failed to init resolver: {e}")
            self._resolver_initialized = True
    
    def teach_alias(self, phrase: str, device_id: str) -> bool:
        """
        Teach a new alias to the resolver.
        Called by voice: "ARVIS, call the bedroom light 'reading lamp'"
        
        Args:
            phrase: The alias phrase (e.g., "reading lamp")
            device_id: The target device (e.g., "bedroom_main")
            
        Returns:
            Success boolean
        """
        if self.alias_resolver:
            success = self.alias_resolver.add_user_alias(phrase, device_id)
            if success:
                print(f"[HybridOrchestrator] ✅ Learned alias: '{phrase}' → {device_id}")
            return success
        return False
    
    def get_alias_stats(self) -> dict:
        """Get statistics about the alias resolver."""
        if self.alias_resolver:
            return self.alias_resolver.get_stats()
        return {"status": "not initialized"}
