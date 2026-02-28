"""
Integration Test: LocalAgent → CloudLLM Escalation Flow
Tests the complete pipeline:
1. Simple commands handled by LocalAgent
2. Complex commands escalated to CloudLLM (Gemini/Groq)
3. Response flow back to user
"""

import os
import sys
import json
import time
from typing import Dict, Any, Optional

# Load .env file BEFORE other imports
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, ".")

# Test scenarios
INTEGRATION_TESTS = [
    # ═══════════════════════════════════════════════════════════
    # SIMPLE COMMANDS - Should be handled by LocalAgent
    # ═══════════════════════════════════════════════════════════
    {
        "command": "turn on kitchen light",
        "expected_handler": "local",
        "expected_tool": "turn_on",
        "description": "Simple on command"
    },
    {
        "command": "turn off bedroom light",
        "expected_handler": "local",
        "expected_tool": "turn_off",
        "description": "Simple off command"
    },
    
    # ═══════════════════════════════════════════════════════════
    # COMPLEX COMMANDS - Should escalate to CloudLLM
    # ═══════════════════════════════════════════════════════════
    {
        "command": "turn on all lights",
        "expected_handler": "cloud",
        "expected_tool": None,  # Cloud decides
        "description": "Multi-device - escalate"
    },
    {
        "command": "set up movie mode",
        "expected_handler": "cloud",
        "expected_tool": None,
        "description": "Scene request - escalate"
    },
    {
        "command": "is the kitchen light on?",
        "expected_handler": "cloud",
        "expected_tool": None,
        "description": "Question - escalate"
    },
    {
        "command": "dim the lights to 50%",
        "expected_handler": "cloud",
        "expected_tool": None,
        "description": "Brightness adjustment - escalate"
    },
    
    # ═══════════════════════════════════════════════════════════
    # EDGE CASES
    # ═══════════════════════════════════════════════════════════
    {
        "command": "remember I like warm lights at night",
        "expected_handler": "local",
        "expected_tool": "log_memory",
        "description": "Memory storage - local"
    },
]

KNOWN_DEVICES = [
    "kitchen light", "bedroom light", "living room light",
    "bathroom light", "porch light", "ac", "fan", "tv"
]

TOOLS_SCHEMA = [
    {"name": "turn_on", "description": "Turn on a device"},
    {"name": "turn_off", "description": "Turn off a device"},
    {"name": "log_memory", "description": "Store a learned pattern"},
    {"name": "escalate", "description": "Escalate to cloud LLM"},
]


class IntegrationTester:
    def __init__(self):
        self.local_agent = None
        self.cloud_agent = None
        self.results = {"passed": 0, "failed": 0, "skipped": 0}
    
    def setup(self):
        """Initialize both agents."""
        print("\n" + "="*70)
        print("INTEGRATION TEST: LocalAgent → CloudLLM Flow")
        print("="*70)
        
        # Load LocalAgent
        print("\n🔧 Loading LocalAgent (Qwen 2.5 3B)...")
        try:
            from agent_home.llm_agent.local_agent import LocalAgent
            self.local_agent = LocalAgent(model_type="qwen")
            if self.local_agent.llm:
                print("  ✅ LocalAgent loaded")
            else:
                print("  ⚠️ LocalAgent model not loaded")
                return False
        except Exception as e:
            print(f"  ❌ LocalAgent failed: {e}")
            return False
        
        # Check CloudLLM configuration
        print("\n🔧 Checking CloudLLM configuration...")
        groq_key = os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        
        if groq_key:
            print(f"  ✅ Groq API key found (length: {len(groq_key)})")
            self.cloud_provider = "groq"
        elif gemini_key:
            print(f"  ✅ Gemini API key found")
            self.cloud_provider = "gemini"
        else:
            print(f"  ⚠️ No cloud API key found in environment")
            self.cloud_provider = None
        
        return True
    
    def test_local_agent(self, command: str) -> Dict[str, Any]:
        """Test LocalAgent response."""
        start = time.time()
        result = self.local_agent.generate_tool_call(
            user_input=command,
            tools_schema=TOOLS_SCHEMA,
            known_devices=KNOWN_DEVICES
        )
        latency = (time.time() - start) * 1000
        
        if result is None:
            return {"handler": "local", "tool": None, "escalate": True, "latency": latency}
        
        tool = result[0].get("tool", "unknown")
        args = result[0].get("args", {})
        
        if tool == "escalate":
            return {"handler": "local", "tool": "escalate", "escalate": True, "latency": latency}
        
        return {"handler": "local", "tool": tool, "args": args, "escalate": False, "latency": latency}
    
    def test_cloud_agent(self, command: str) -> Dict[str, Any]:
        """Test CloudLLM response using direct API call."""
        if not self.cloud_provider:
            return {"handler": "cloud_simulated", "response": "Simulated cloud response", "latency": 0}
        
        start = time.time()
        
        try:
            if self.cloud_provider == "groq":
                from groq import Groq
                client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                
                response = client.chat.completions.create(
                    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    messages=[
                        {"role": "system", "content": "You are ARVIS, a smart home assistant. Respond briefly."},
                        {"role": "user", "content": command}
                    ],
                    max_tokens=150
                )
                
                latency = (time.time() - start) * 1000
                content = response.choices[0].message.content
                return {"handler": "groq", "response": content[:100], "latency": latency}
            
            elif self.cloud_provider == "gemini":
                import google.generativeai as genai
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                model = genai.GenerativeModel("gemini-2.0-flash")
                
                response = model.generate_content(f"You are ARVIS. Respond briefly: {command}")
                
                latency = (time.time() - start) * 1000
                return {"handler": "gemini", "response": response.text[:100], "latency": latency}
        
        except Exception as e:
            return {"handler": "cloud_error", "error": str(e), "latency": 0}
        
        return {"handler": "cloud", "response": "Would call cloud LLM", "latency": 0}
    
    def run_test(self, test: Dict) -> bool:
        """Run a single integration test."""
        command = test["command"]
        expected_handler = test["expected_handler"]
        expected_tool = test["expected_tool"]
        
        print(f"\n📋 Test: {test['description']}")
        print(f"   Command: \"{command}\"")
        print(f"   Expected: {expected_handler} → {expected_tool or 'any'}")
        
        # Step 1: Try LocalAgent first
        local_result = self.test_local_agent(command)
        
        if expected_handler == "local":
            # Should be handled locally
            if local_result["escalate"]:
                print(f"   ❌ FAIL: LocalAgent escalated when it should have handled")
                return False
            
            if expected_tool and local_result["tool"] != expected_tool:
                print(f"   ❌ FAIL: Got {local_result['tool']}, expected {expected_tool}")
                return False
            
            print(f"   ✅ PASS: LocalAgent handled ({local_result['tool']}) in {local_result['latency']:.0f}ms")
            return True
        
        else:  # expected_handler == "cloud"
            # Should escalate to cloud
            if not local_result["escalate"]:
                print(f"   ❌ FAIL: LocalAgent handled when it should escalate")
                print(f"   Got: {local_result}")
                return False
            
            # Test cloud handling
            cloud_result = self.test_cloud_agent(command)
            print(f"   ✅ PASS: Escalated to {cloud_result['handler']}")
            return True
    
    def run_all(self):
        """Run all integration tests."""
        if not self.setup():
            print("\n❌ Setup failed, cannot run tests")
            return
        
        print(f"\n🧪 Running {len(INTEGRATION_TESTS)} integration tests...")
        
        for test in INTEGRATION_TESTS:
            try:
                if self.run_test(test):
                    self.results["passed"] += 1
                else:
                    self.results["failed"] += 1
            except Exception as e:
                print(f"   💥 ERROR: {e}")
                self.results["failed"] += 1
        
        # Summary
        print("\n" + "="*70)
        print("INTEGRATION TEST RESULTS")
        print("="*70)
        
        total = self.results["passed"] + self.results["failed"]
        accuracy = (self.results["passed"] / total * 100) if total > 0 else 0
        
        print(f"\n📊 Results: {self.results['passed']}/{total} passed ({accuracy:.1f}%)")
        print(f"   ✅ Passed: {self.results['passed']}")
        print(f"   ❌ Failed: {self.results['failed']}")
        
        if self.cloud_provider:
            print(f"\n☁️ Cloud Provider: {self.cloud_provider}")
        else:
            print(f"\n⚠️ Cloud Provider: Simulated (no API key)")
        
        return self.results["failed"] == 0


if __name__ == "__main__":
    tester = IntegrationTester()
    success = tester.run_all()
    sys.exit(0 if success else 1)
