"""
ARVIS WebSocket Server Test
============================
Standalone script to test the WebSocket API with virtual devices.

Run: python test_websocket.py
Then open: http://localhost:5000/voice
"""

import sys
import time
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arvis_core.event_bus.event_bus import EventBus
from agent_home.llm_agent.local_agent import LocalAgent
from agent_home.llm_agent.hybrid_orchestrator import HybridOrchestrator
from arvis_core.memory.orchestrator import MemoryOrchestrator
from agent_home.web.app import start_server


class SimpleStateEngine:
    """Minimal state engine for testing."""
    def __init__(self):
        self.state = {"devices": {}}
    
    def get_all_states(self):
        return self.state["devices"]
    
    def get_history(self, limit=20):
        return []


class MockToolExecutor:
    """Mock executor that logs tool calls."""
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.call_log = []
    
    def execute(self, tool_calls):
        """Execute tool calls (mock implementation)."""
        for call in tool_calls:
            tool = call.get('tool')
            args = call.get('args', {})
            print(f"[MockExecutor] {tool}({args})")
            self.call_log.append(call)
            
            # Publish device state change for virtual devices
            if tool in ['turn_on', 'turn_off']:
                device_id = args.get('device_id', 'unknown')
                state = 'on' if tool == 'turn_on' else 'off'
                self.event_bus.publish({
                    "type": "device_state_changed",
                    "payload": {"device_id": device_id, "state": state}
                })


def main():
    print("=" * 60)
    print("ARVIS WebSocket Server Test")
    print("=" * 60)
    
    # Initialize components
    print("\n[1/5] Initializing Event Bus...")
    event_bus = EventBus()
    
    print("[2/5] Initializing Memory Orchestrator...")
    memory = MemoryOrchestrator(persist_dir="./data/test_memories")
    
    print("[3/5] Initializing Local Agent...")
    local_agent = LocalAgent()
    
    print("[4/5] Initializing Mock Executor...")
    executor = MockToolExecutor(event_bus)
    
    print("[5/5] Initializing Hybrid Orchestrator...")
    
    # Create a mock cloud agent that just prints
    class MockCloudAgent:
        def handle(self, event):
            print(f"[MockCloud] Would handle: {event}")
    
    orchestrator = HybridOrchestrator(
        event_bus=event_bus,
        local_agent=local_agent,
        cloud_agent=MockCloudAgent(),
        tool_executor=executor,
        memory=memory
    )
    
    # Start web server with WebSocket
    print("\n" + "=" * 60)
    print("Starting WebSocket Server...")
    print("=" * 60)
    
    state_engine = SimpleStateEngine()
    
    socketio = start_server(
        state_engine=state_engine,
        event_bus=event_bus,
        orchestrator=orchestrator,
        memory=memory,
        port=5000,
        enable_websocket=True
    )
    
    print("\n" + "=" * 60)
    print("✅ ARVIS WebSocket Server Running!")
    print("=" * 60)
    print("\n📍 Dashboard:  http://localhost:5000/")
    print("📍 Voice UI:   http://localhost:5000/voice")
    print("📍 Ping:       http://localhost:5000/ping")
    print("\n[Press Ctrl+C to stop]")
    
    # Keep running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[Shutting down...]")


if __name__ == "__main__":
    main()
