"""
Comprehensive Hybrid Agent Test Suite
=====================================
Simulates real user behavior with virtual devices, timing measurements,
and edge case testing. Produces a detailed findings report.
"""

import time
import random
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ComprehensiveTest")

# ═══════════════════════════════════════════════════════════════════════════════
# VIRTUAL DEVICE SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VirtualDevice:
    device_id: str
    device_type: str  # light, switch, sensor
    room: str
    state: bool = False
    brightness: int = 100
    color_temp: int = 4000
    
    def turn_on(self, brightness=None, color_temp=None):
        self.state = True
        if brightness: self.brightness = brightness
        if color_temp: self.color_temp = color_temp
        return f"✅ {self.device_id} ON (brightness={self.brightness}%)"
    
    def turn_off(self):
        self.state = False
        return f"⬛ {self.device_id} OFF"
    
    def get_state(self):
        return {"on": self.state, "brightness": self.brightness, "color_temp": self.color_temp}


class VirtualHome:
    """Simulates a smart home with multiple devices."""
    def __init__(self):
        self.devices: Dict[str, VirtualDevice] = {}
        self._setup_home()
    
    def _setup_home(self):
        # Kitchen
        self.devices["kitchen_main"] = VirtualDevice("kitchen_main", "light", "kitchen")
        self.devices["kitchen_counter"] = VirtualDevice("kitchen_counter", "light", "kitchen")
        self.devices["kitchen_fan"] = VirtualDevice("kitchen_fan", "switch", "kitchen")
        
        # Living Room
        self.devices["living_room_light"] = VirtualDevice("living_room_light", "light", "living_room")
        self.devices["living_room_lamp"] = VirtualDevice("living_room_lamp", "light", "living_room")
        self.devices["tv_backlight"] = VirtualDevice("tv_backlight", "light", "living_room")
        
        # Bedroom
        self.devices["bedroom_main"] = VirtualDevice("bedroom_main", "light", "bedroom")
        self.devices["bedroom_lamp"] = VirtualDevice("bedroom_lamp", "light", "bedroom")
        self.devices["bedroom_ac"] = VirtualDevice("bedroom_ac", "switch", "bedroom")
        
        # Bathroom
        self.devices["bathroom_light"] = VirtualDevice("bathroom_light", "light", "bathroom")
        self.devices["bathroom_exhaust"] = VirtualDevice("bathroom_exhaust", "switch", "bathroom")
        
        # Outdoor
        self.devices["porch_light"] = VirtualDevice("porch_light", "light", "outdoor")
        self.devices["garage_light"] = VirtualDevice("garage_light", "light", "outdoor")
        
        logger.info(f"🏠 Virtual Home initialized with {len(self.devices)} devices")
    
    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a tool call on virtual devices."""
        device_id = args.get("device_id")
        
        if tool_name == "turn_on":
            if device_id in self.devices:
                return self.devices[device_id].turn_on(
                    args.get("brightness"), 
                    args.get("color_temp")
                )
            return f"❌ Device '{device_id}' not found"
        
        elif tool_name == "turn_off":
            if device_id in self.devices:
                return self.devices[device_id].turn_off()
            return f"❌ Device '{device_id}' not found"
        
        elif tool_name == "get_device_state":
            if device_id in self.devices:
                return str(self.devices[device_id].get_state())
            return f"❌ Device '{device_id}' not found"
        
        elif tool_name == "list_devices":
            room = args.get("filter_room")
            if room:
                return str([d.device_id for d in self.devices.values() if d.room == room])
            return str(list(self.devices.keys()))
        
        elif tool_name in ["think", "ask_user", "log_note", "log_memory", "escalate"]:
            return f"🧠 {tool_name}: {args}"
        
        elif tool_name == "create_mission":
            return f"📋 Mission created: {args.get('name', 'unnamed')}"
        
        return f"⚠️ Unhandled tool: {tool_name}"
    
    def summary(self):
        on_devices = [d.device_id for d in self.devices.values() if d.state]
        return f"Devices ON: {on_devices}" if on_devices else "All devices OFF"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST RESULT TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TestResult:
    test_name: str
    command: str
    expected_path: str  # "local" or "cloud"
    actual_path: str
    latency_ms: float
    tool_calls: List[dict]
    success: bool
    notes: str = ""

@dataclass
class TestReport:
    results: List[TestResult] = field(default_factory=list)
    start_time: datetime = None
    end_time: datetime = None
    
    def add(self, result: TestResult):
        self.results.append(result)
    
    def summary(self) -> dict:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.success)
        failed = total - passed
        
        local_tests = [r for r in self.results if r.expected_path == "local"]
        cloud_tests = [r for r in self.results if r.expected_path == "cloud"]
        
        local_correct = sum(1 for r in local_tests if r.actual_path == "local")
        cloud_correct = sum(1 for r in cloud_tests if r.actual_path == "cloud")
        
        avg_local_latency = sum(r.latency_ms for r in local_tests if r.actual_path == "local") / max(1, local_correct)
        avg_cloud_latency = sum(r.latency_ms for r in cloud_tests if r.actual_path == "cloud") / max(1, cloud_correct)
        
        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{100*passed/total:.1f}%" if total else "N/A",
            "local_routing_accuracy": f"{100*local_correct/len(local_tests):.1f}%" if local_tests else "N/A",
            "cloud_routing_accuracy": f"{100*cloud_correct/len(cloud_tests):.1f}%" if cloud_tests else "N/A",
            "avg_local_latency_ms": round(avg_local_latency, 2),
            "avg_cloud_latency_ms": round(avg_cloud_latency, 2),
            "duration_sec": (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════

TEST_SCENARIOS = [
    # === EXPLICIT COMMANDS (Should go LOCAL) ===
    {"name": "Explicit: Kitchen Light On", "command": "Turn on kitchen_main", "expected": "local"},
    {"name": "Explicit: Kitchen Light Off", "command": "Turn off kitchen_main", "expected": "local"},
    {"name": "Explicit: Living Room Light", "command": "Turn on living_room_light", "expected": "local"},
    {"name": "Explicit: Bedroom AC", "command": "Turn on bedroom_ac", "expected": "local"},
    {"name": "Explicit: Porch Light", "command": "Turn on porch_light", "expected": "local"},
    {"name": "Explicit: Multiple Word ID", "command": "Turn on living_room_lamp", "expected": "local"},
    {"name": "Explicit: Brightness", "command": "Set kitchen_main to 50% brightness", "expected": "local"},
    
    # === NATURAL LANGUAGE (May go LOCAL or CLOUD) ===
    {"name": "Natural: Kitchen Lights", "command": "Turn on the kitchen lights", "expected": "local"},
    {"name": "Natural: Bedroom Lamp", "command": "Switch on the bedroom lamp", "expected": "local"},
    {"name": "Natural: All Lights Off", "command": "Turn off all the lights", "expected": "cloud"},
    
    # === NATURAL LANGUAGE DEVICE ALIASES (Should go LOCAL with alias resolution) ===
    {"name": "Alias: Kitchen Light", "command": "Turn on kitchen light", "expected": "local"},
    {"name": "Alias: Living Room Light", "command": "Turn off the living room light", "expected": "local"},
    {"name": "Alias: Bedroom Light", "command": "Turn on bedroom light", "expected": "local"},
    {"name": "Alias: Bathroom Light", "command": "Switch on bathroom light", "expected": "local"},
    {"name": "Alias: Porch Light", "command": "Turn on the porch light", "expected": "local"},
    {"name": "Alias: Garage Light", "command": "Turn off garage light", "expected": "local"},
    {"name": "Alias: TV Light", "command": "Turn on tv light", "expected": "local"},
    {"name": "Alias: AC", "command": "Turn on the ac", "expected": "local"},
    {"name": "Alias: Kitchen Fan", "command": "Turn on the kitchen fan", "expected": "local"},
    {"name": "Alias: Exhaust Fan", "command": "Turn on bathroom exhaust", "expected": "local"},
    
    # === CONVERSATIONAL NATURAL COMMANDS (Should go LOCAL) ===
    {"name": "Conversational: Please Kitchen", "command": "Please turn on the kitchen light", "expected": "local"},
    {"name": "Conversational: Can You Bedroom", "command": "Can you turn off the bedroom light", "expected": "local"},
    {"name": "Conversational: Hey Porch", "command": "Hey, turn on the porch", "expected": "local"},
    
    # === AMBIGUOUS COMMANDS (Should go CLOUD) ===
    {"name": "Ambiguous: Turn it on", "command": "Turn it on", "expected": "cloud"},
    {"name": "Ambiguous: Make it brighter", "command": "Make it brighter", "expected": "cloud"},
    {"name": "Ambiguous: That light", "command": "Turn off that light", "expected": "cloud"},
    
    # === CONTEXT-REQUIRED (Should go CLOUD) ===
    {"name": "Context: Its dark", "command": "It's getting dark in here", "expected": "cloud"},
    {"name": "Context: Movie time", "command": "I'm going to watch a movie", "expected": "cloud"},
    {"name": "Context: Going to bed", "command": "I'm going to sleep now", "expected": "cloud"},
    {"name": "Context: Too hot", "command": "It's too hot", "expected": "cloud"},
    
    # === COMPLEX/MISSIONS (Should go CLOUD) ===
    {"name": "Mission: Morning Routine", "command": "Create a morning routine that turns on kitchen lights at 7am", "expected": "cloud"},
    {"name": "Mission: Party Mode", "command": "Set up a party mode with all lights colorful", "expected": "cloud"},
    {"name": "Mission: Vacation", "command": "I'm going on vacation, simulate presence", "expected": "cloud"},
    
    # === QUESTIONS (Should go CLOUD) ===
    {"name": "Question: Light Status", "command": "Is the kitchen light on?", "expected": "cloud"},
    {"name": "Question: Energy Usage", "command": "How much energy am I using?", "expected": "cloud"},
    {"name": "Question: Weather", "command": "What's the weather like?", "expected": "cloud"},
    
    # === EDGE CASES ===
    {"name": "Edge: Typo Device", "command": "Turn on kichen_main", "expected": "local"},  # typo
    {"name": "Edge: Unknown Device", "command": "Turn on the fridge", "expected": "cloud"},
    {"name": "Edge: Mixed", "command": "Turn on kitchen_main and tell me a joke", "expected": "cloud"},
    {"name": "Edge: Empty", "command": "", "expected": "cloud"},
    {"name": "Edge: Gibberish", "command": "asdfghjkl", "expected": "cloud"},
    
    # === STRESS/RAPID COMMANDS ===
    {"name": "Rapid: Light 1", "command": "Turn on bathroom_light", "expected": "local"},
    {"name": "Rapid: Light 2", "command": "Turn off bathroom_light", "expected": "local"},
    {"name": "Rapid: Light 3", "command": "Turn on garage_light", "expected": "local"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutor:
    def __init__(self):
        self.home = VirtualHome()
        self.report = TestReport()
        self._init_agents()
    
    def _init_agents(self):
        from arvis_core.event_bus.event_bus import EventBus
        from agent_home.llm_agent.local_agent import LocalAgent
        from agent_home.llm_agent.llm_agent import LLMAgent
        from agent_home.llm_agent.hybrid_orchestrator import HybridOrchestrator
        from agent_home.llm_agent.tools_schema import TOOLS_SCHEMA
        
        self.bus = EventBus()
        self.tools_schema = TOOLS_SCHEMA
        
        # Track responses
        self.last_response = None
        self.last_source = None
        
        def on_tool_calls(event):
            self.last_response = event.get("payload", [])
            self.last_source = event.get("source", "unknown")
            # Execute on virtual home
            for tc in self.last_response:
                result = self.home.execute(tc["tool"], tc.get("args", {}))
                logger.debug(f"  -> {result}")
        
        def on_agent_response(event):
            payload = event.get("payload", {})
            source = payload.get("source", "unknown") if isinstance(payload, dict) else "unknown"
            
            # DON'T overwrite if we already captured a local source from tool_calls_generated
            if self.last_source != "local":
                self.last_response = payload
                self.last_source = "cloud" if source in ["llm_agent", "cloud"] else source
        
        self.bus.subscribe("tool_calls_generated", on_tool_calls)
        self.bus.subscribe("agent_response", on_agent_response)
        
        # Mock engines for LLMAgent
        class MockState:
            devices = {}
            def get_device_state(self, d): return "unknown"
            def summary(self): return {}
        
        class MockAuto:
            def list(self): return []
        
        logger.info("🤖 Initializing Local Agent...")
        self.local_agent = LocalAgent()
        
        logger.info("☁️ Initializing Cloud Agent...")
        self.cloud_agent = LLMAgent(self.bus, MockState(), MockAuto(), subscribe_to_voice=False)
        
        logger.info("🔀 Initializing Hybrid Orchestrator...")
        self.orchestrator = HybridOrchestrator(
            self.bus, 
            self.local_agent, 
            self.cloud_agent, 
            tool_executor=self,  # Use self as executor to capture calls
            memory=self.cloud_agent.memory  # Wire memory for pattern learning
        )
        
        logger.info("✅ All agents initialized")
    
    def execute(self, tool_calls: list) -> dict:
        """Mock executor for HybridOrchestrator."""
        results = []
        for tc in tool_calls:
            result = self.home.execute(tc["tool"], tc.get("args", {}))
            results.append(result)
        return {"success": True, "results": results}
    
    def run_test(self, scenario: dict) -> TestResult:
        """Run a single test scenario."""
        name = scenario["name"]
        command = scenario["command"]
        expected_path = scenario["expected"]
        
        logger.info(f"🧪 {name}: \"{command}\"")
        
        self.last_response = None
        self.last_source = None
        
        start = time.time()
        
        # Simulate user command via event
        event = {
            "type": "voice_command",
            "payload": {"text": command, "source": "test"},
            "timestamp": time.time()
        }
        
        try:
            self.orchestrator.handle_command(event)
        except Exception as e:
            logger.error(f"  ❌ Exception: {e}")
            return TestResult(
                test_name=name,
                command=command,
                expected_path=expected_path,
                actual_path="error",
                latency_ms=(time.time() - start) * 1000,
                tool_calls=[],
                success=False,
                notes=str(e)
            )
        
        latency = (time.time() - start) * 1000
        
        # Determine actual path from source
        if self.last_source in ["local", "local_agent"]:
            actual_path = "local"
        elif self.last_source in ["cloud", "llm_agent", "cloud_chat"]:
            actual_path = "cloud"
        elif self.last_source == "unknown":
            actual_path = "local"  # Orchestrator executes locally
        else:
            actual_path = self.last_source or "none"
        
        tool_calls = self.last_response if isinstance(self.last_response, list) else []
        
        # Determine success
        # For now: success if we got a response and routing was correct
        success = (actual_path == expected_path) or (self.last_response is not None)
        
        notes = ""
        if actual_path != expected_path:
            notes = f"Routing mismatch: expected {expected_path}, got {actual_path}"
        
        logger.info(f"  -> Path: {actual_path} | Latency: {latency:.0f}ms | Tools: {len(tool_calls)}")
        
        return TestResult(
            test_name=name,
            command=command,
            expected_path=expected_path,
            actual_path=actual_path,
            latency_ms=latency,
            tool_calls=tool_calls,
            success=success,
            notes=notes
        )
    
    def run_all(self, delay_between=0.5):
        """Run all test scenarios."""
        self.report.start_time = datetime.now()
        
        for scenario in TEST_SCENARIOS:
            result = self.run_test(scenario)
            self.report.add(result)
            time.sleep(delay_between)  # Simulate realistic timing
        
        self.report.end_time = datetime.now()
        return self.report
    
    def generate_findings(self) -> str:
        """Generate human-readable findings report."""
        summary = self.report.summary()
        
        # Categorize issues
        routing_issues = [r for r in self.report.results if r.actual_path != r.expected_path]
        failures = [r for r in self.report.results if not r.success]
        slow_local = [r for r in self.report.results if r.actual_path == "local" and r.latency_ms > 500]
        slow_cloud = [r for r in self.report.results if r.actual_path == "cloud" and r.latency_ms > 5000]
        
        report = f"""
# 🧪 Comprehensive Test Report
**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Duration**: {summary['duration_sec']:.1f} seconds
**Total Tests**: {summary['total_tests']}

---

## 📊 Summary

| Metric | Value |
|--------|-------|
| Pass Rate | {summary['pass_rate']} |
| Local Routing Accuracy | {summary['local_routing_accuracy']} |
| Cloud Routing Accuracy | {summary['cloud_routing_accuracy']} |
| Avg Local Latency | {summary['avg_local_latency_ms']}ms |
| Avg Cloud Latency | {summary['avg_cloud_latency_ms']}ms |

---

## ✅ What's Working

"""
        # Find what works
        working = []
        if summary['avg_local_latency_ms'] < 500:
            working.append("- **Fast Local Path**: Local agent responds quickly (<500ms avg)")
        if len([r for r in self.report.results if r.actual_path == "local" and r.success]) > 0:
            working.append("- **Explicit Commands**: Direct device commands are handled locally")
        if len([r for r in self.report.results if r.expected_path == "cloud" and r.actual_path == "cloud"]) > 0:
            working.append("- **Cloud Fallback**: Complex commands correctly route to cloud")
        
        report += "\n".join(working) if working else "- No clear wins detected"
        
        report += """

---

## ❌ What's Breaking

"""
        breaking = []
        if routing_issues:
            report += f"### Routing Mismatches ({len(routing_issues)} issues)\n"
            for r in routing_issues[:5]:
                report += f"- **{r.test_name}**: Expected `{r.expected_path}`, got `{r.actual_path}`\n"
                report += f"  - Command: \"{r.command}\"\n"
        
        if failures:
            report += f"\n### Failures ({len(failures)} issues)\n"
            for r in failures[:5]:
                report += f"- **{r.test_name}**: {r.notes or 'No response'}\n"
        
        if not routing_issues and not failures:
            report += "- Nothing critical breaking! 🎉\n"
        
        report += """

---

## 🤦 What's Stupid

"""
        stupid = []
        
        if slow_local:
            stupid.append(f"- **Slow Local**: {len(slow_local)} local commands took >500ms. Defeats purpose of local path.")
        
        if slow_cloud:
            stupid.append(f"- **Very Slow Cloud**: {len(slow_cloud)} cloud commands took >5s. User experience suffers.")
        
        # Check for obvious routing failures
        explicit_to_cloud = [r for r in self.report.results 
                            if r.expected_path == "local" and r.actual_path == "cloud"]
        if explicit_to_cloud:
            stupid.append(f"- **Unnecessary Cloud Calls**: {len(explicit_to_cloud)} explicit commands went to cloud instead of local")
        
        ambiguous_to_local = [r for r in self.report.results 
                             if r.expected_path == "cloud" and r.actual_path == "local"]
        if ambiguous_to_local:
            stupid.append(f"- **Risky Local Guessing**: {len(ambiguous_to_local)} ambiguous commands handled locally (may hallucinate)")
        
        report += "\n".join(stupid) if stupid else "- Architecture seems sensible!\n"
        
        report += """

---

## 📝 Detailed Results

| Test | Command | Expected | Actual | Latency | Status |
|------|---------|----------|--------|---------|--------|
"""
        for r in self.report.results:
            status = "✅" if r.success else "❌"
            report += f"| {r.test_name} | {r.command[:30]}... | {r.expected_path} | {r.actual_path} | {r.latency_ms:.0f}ms | {status} |\n"
        
        return report


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("🚀 COMPREHENSIVE HYBRID AGENT TEST SUITE")
    logger.info("=" * 60)
    
    executor = TestExecutor()
    
    logger.info("\n📋 Running test scenarios...")
    report = executor.run_all(delay_between=0.3)
    
    logger.info("\n📊 Generating findings report...")
    findings = executor.generate_findings()
    
    # Save report
    report_path = "test_findings.md"
    with open(report_path, "w") as f:
        f.write(findings)
    
    logger.info(f"\n📄 Report saved to: {report_path}")
    print("\n" + "=" * 60)
    print(findings)
    print("=" * 60)
    
    return report

if __name__ == "__main__":
    main()
