from typing import Optional, Any
from pydantic import Field

from .toolcall import ARVISToolAgent
from agent_unified.tools.collection import ToolCollection
from agent_unified.tools.bms import BMSToolkit
# from agent_unified.tools.browser import BrowserUseTool
from agent_unified.tools.base import Terminate
from agent_unified.llm import UnifiedLLM
# from agent_unified.prompts.system import ARVIS_SYSTEM_PROMPT, ARVIS_NEXT_STEP

ARVIS_SYSTEM_PROMPT = """You are ARVIS, an AI building management assistant.
RULES:
1. Always use exact IDs (e.g., "ALM-101", "AHU-01") returned by tools. Never use placeholders like "first_alarm".
2. If you don't know an ID, list available items first."""
ARVIS_NEXT_STEP_PROMPT = "What should we do next?"

class ARVISManus(ARVISToolAgent):
    """Main ARVIS agent combining OpenManus patterns with BMS domain expertise"""
    
    name: str = "ARVIS"
    description: str = "AI-powered building management and automation assistant"
    
    system_prompt: str = ARVIS_SYSTEM_PROMPT
    next_step_prompt: str = ARVIS_NEXT_STEP_PROMPT
    
    max_steps: int = 30
    
    # BMS engines (injected)
    bms_state: Optional[Any] = None
    alarm_engine: Optional[Any] = None
    energy_analyzer: Optional[Any] = None
    skillbook: Optional[Any] = None
    
    available_tools: ToolCollection = Field(default_factory=lambda: ToolCollection(
        Terminate()
    ))
    
    # Injected LLM
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    
    @classmethod
    async def create(
        cls,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        skillbook=None,
        **kwargs
    ) -> "ARVISManus":
        """Factory method to create fully initialized agent"""
        instance = cls(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            skillbook=skillbook,
            **kwargs
        )
        
        # Initialize BMS tools with engines
        bms_toolkit = BMSToolkit(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            skillbook=skillbook
        )
        
        # Build tool collection
        all_tools = [Terminate()] + bms_toolkit.get_tools()
        instance.available_tools = ToolCollection(*all_tools)
        instance.llm = UnifiedLLM()
        
        return instance
    
    async def think(self) -> bool:
        """Enhanced thinking with BMS context"""
        # Inject BMS context into system prompt if available
        if self.bms_state:
            try:
                snapshot = self.bms_state.get_snapshot()
                context = f"\n\nCurrent BMS Status: {snapshot.get('summary', 'Unknown')}"
                # Use a combined prompt
                # self.system_prompt = ARVIS_SYSTEM_PROMPT + context
            except AttributeError:
                pass 
        
        return await super().think()
