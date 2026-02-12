"""
BMS Battle Tests (Real LLM)
===========================

End-to-end tests for BMS tools using real LLM (k2think/Groq).
Verifies that the agent can correctly select and use the 33 BMS tools
given natural language instructions, utilizing the mock BMS environment.
"""

import pytest
import os
import json
import asyncio

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from agent_unified.schema import AgentState
from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.collection import ToolCollection
from agent_unified.tools.bms import BMSToolkit
from agent_unified.tools.terminate import Terminate

from agent_unified.tests.bms_mocks import (
    MockBMSState, MockAlarmEngine, MockEnergyAnalyzer, 
    MockGSASReporter, MockSkillbook, MockMLEngine, MockBriefingEngine
)

# Skip if no API key configured
pytestmark = pytest.mark.skipif(
    not (os.getenv("K2THINK_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")),
    reason="No LLM API key configured"
)

class TestBMSBattle:
    
    @pytest.fixture
    def agent(self):
        """Create ARVIS agent with full mock BMS toolkit."""
        # Initialize mocks
        bms_state = MockBMSState()
        alarm_engine = MockAlarmEngine()
        energy_analyzer = MockEnergyAnalyzer()
        gsas_reporter = MockGSASReporter()
        skillbook = MockSkillbook()
        ml_engine = MockMLEngine()
        briefing_engine = MockBriefingEngine()
        
        # Create toolkit with mocks
        toolkit = BMSToolkit(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            gsas_reporter=gsas_reporter,
            skillbook=skillbook,
            ml_engine=ml_engine,
            briefing_engine=briefing_engine
        )
        
        # Get all 33 tools + Terminate
        tools = toolkit.get_tools()
        tools.append(Terminate())
        
        # Initialize agent
        agent = ARVISToolAgent(
            name="arvis_ops",
            available_tools=ToolCollection(*tools),
            max_steps=5,
            system_prompt=(
                "You are ARVIS, a precise BMS agent. "
                "You MUST use the provided tools to answer questions. "
                "Do NOT answer from your own knowledge. "
                "If you need information, call the appropriate BMS tool. "
                "When finished, you MUST call the terminate tool."
            )
        )
        return agent

    @pytest.mark.asyncio
    async def test_scen_equipment_status(self, agent):
        """Scenario: Check status of specific equipment."""
        print("\n--- Testing Equipment Status ---")
        result = await agent.run("What is the current status and supply temperature of AHU-01?")
        
        # Verification
        print(f"Agent State: {agent.state}")
        print(f"Traces: {agent.execution_traces}")
        
        trace_tools = []
        for t in agent.execution_traces:
            if t.get("type") == "tool_execution":
                trace_tools.append(t.get("tool"))
        
        print(f"Executed Tools: {trace_tools}")
        
        assert agent.state == AgentState.FINISHED
        assert "get_equipment_status" in trace_tools, f"Expected get_equipment_status, got {trace_tools}"
        print("✅ Equipment status tool called correctly")

    @pytest.mark.asyncio
    async def test_scen_alarm_workflow(self, agent):
        """Scenario: List active alarms clearly."""
        print("\n--- Testing Alarm Listing ---")
        result = await agent.run("List all critical active alarms.")
        
        trace_tools = [t.get("tool") for t in agent.execution_traces if t.get("type") == "tool_execution"]
        print(f"Executed Tools: {trace_tools}")
        
        assert "get_active_alarms" in trace_tools, f"Expected get_active_alarms, got {trace_tools}"
        print("✅ Alarm listing tool called correctly")

    @pytest.mark.asyncio
    async def test_scen_energy_analysis(self, agent):
        """Scenario: Analyze energy consumption."""
        print("\n--- Testing Energy Analysis ---")
        result = await agent.run("Analyze the building's energy consumption breakdown.")
        
        trace_tools = [t.get("tool") for t in agent.execution_traces if t.get("type") == "tool_execution"]
        print(f"Executed Tools: {trace_tools}")
        
        assert "analyze_energy" in trace_tools or "get_burn_rate" in trace_tools, f"Expected energy tool, got {trace_tools}"
        print("✅ Energy analysis tool called correctly")

    @pytest.mark.asyncio
    async def test_scen_operations_briefing(self, agent):
        """Scenario: Generate specific briefing."""
        print("\n--- Testing Briefing Generation ---")
        result = await agent.run("Generate a morning operations briefing.")
        
        trace_tools = [t.get("tool") for t in agent.execution_traces if t.get("type") == "tool_execution"]
        print(f"Executed Tools: {trace_tools}")
        
        assert "generate_briefing" in trace_tools, f"Expected generate_briefing, got {trace_tools}"
        print("✅ Briefing tool called correctly")

    @pytest.mark.asyncio
    async def test_scen_complex_diagnostic(self, agent):
        """Scenario: Complex diagnostic using ML tools."""
        print("\n--- Testing Fault Detection ---")
        result = await agent.run("Detect any faults in the equipment and analyze their root cause.")
        
        trace_tools = [t.get("tool") for t in agent.execution_traces if t.get("type") == "tool_execution"]
        print(f"Executed Tools: {trace_tools}")
        
        assert "detect_equipment_faults" in trace_tools, f"Expected detect_equipment_faults, got {trace_tools}"
        print("✅ ML fault detection tool called correctly")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
