"""
Test Memory Persistence in LocalAgent
Verifies that log_memory tools are persisted to disk and retrieved for context.
"""

import sys
import shutil
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, ".")

from agent.llm_agent.local_agent import LocalAgent
from agent.memory.preference_store import PreferenceStore

TEST_DIR = "./data/test_memories"
TOOLS_SCHEMA = [
    {"name": "turn_on", "description": "Turn on a device"},
    {"name": "turn_off", "description": "Turn off a device"},
    {"name": "log_memory", "description": "Store a learned pattern"},
]
KNOWN_DEVICES = ["kitchen light", "bedroom light"]

def clean_test_dir():
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    os.makedirs(TEST_DIR)

def run_test():
    print("\n" + "="*70)
    print("TEST: Memory Persistence")
    print("="*70)
    
    clean_test_dir()
    
    # Initialize Agent with test dir
    print("\n1. Initializing LocalAgent...")
    agent = LocalAgent(model_type="qwen", persistence_dir=TEST_DIR)
    
    if not agent.llm:
        print("❌ Failed to load model")
        return False
        
    # Test 1: Store a memory
    print("\n2. Storing memory via 'log_memory'...")
    store_cmd = "remember I like the kitchen light bright"
    
    # We simulate what the LLM would return for this command
    tool_calls = [{"tool": "log_memory", "args": {"key": "kitchen_pref", "value": "bright"}}]
    
    # Process the memory log
    count = agent.process_memory_logs(tool_calls)
    
    if count == 1:
        print("✅ Correctly processed 1 memory log")
    else:
        print(f"❌ Failed to process memory log (count={count})")
        return False
        
    # Verify persistence on disk (check if file exists or store has it)
    print("\n3. Verifying storage...")
    memory_store = PreferenceStore(persist_dir=TEST_DIR)
    stored = memory_store.get_by_key("kitchen_pref")
    
    if stored and stored["content"] == "bright":
        print(f"✅ Found in store: {stored}")
    else:
        print(f"❌ Not found in store: {stored}")
        return False
        
    # Test 2: Retrieval in Context
    print("\n4. Testing Retrieval in Context...")
    # This calls generate_tool_call which should search memory
    # We look for the "RELEVANT MEMORIES" log in the output
    
    # We can't easily capture the print output of the agent, 
    # but we can verify the search works directly on the agent's memory instance
    matches = agent.memory.search("kitchen light preference", limit=1)
    
    if matches and "bright" in matches[0]["content"]:
        print(f"✅ Agent memory retrieval works: {matches[0]['content']}")
    else:
        print(f"❌ Agent memory retrieval failed: {matches}")
        return False
        
    print("\n🎉 PERSISTENCE TEST PASSED!")
    return True

if __name__ == "__main__":
    success = run_test()
    # Cleanup
    # clean_test_dir() 
    sys.exit(0 if success else 1)
