"""
ARVIS Manus Agent
=================

Main unified agent combining OpenManus architecture with ARVIS BMS expertise.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import Field

from agent_unified.agents.toolcall import ARVISToolAgent
from agent_unified.tools.collection import ToolCollection
from agent_unified.tools.terminate import Terminate
from agent_unified.tools.bms import BMSToolkit
from agent_unified.prompts.system import ARVIS_SYSTEM_PROMPT, ARVIS_NEXT_STEP


logger = logging.getLogger("arvis.unified.manus")


class ARVISManus(ARVISToolAgent):
    """
    Main ARVIS agent combining OpenManus patterns with BMS domain expertise.
    
    This is the primary agent for the unified architecture, featuring:
    - ReAct (think → act) execution pattern
    - Type-safe tool system with BMS tools
    - LLM integration for intelligent tool selection
    - Stuck detection and recovery
    """
    
    name: str = "ARVIS"
    description: str = "AI-powered Building Management System assistant for facility operations"
    
    system_prompt: str = ARVIS_SYSTEM_PROMPT
    next_step_prompt: str = ARVIS_NEXT_STEP
    
    max_steps: int = 30
    
    # BMS engines (injected during creation)
    bms_state: Optional[Any] = None
    alarm_engine: Optional[Any] = None
    energy_analyzer: Optional[Any] = None
    gsas_reporter: Optional[Any] = None
    skillbook: Optional[Any] = None
    ml_engine: Optional[Any] = None
    
    # Initialization flag
    _initialized: bool = False
    
    class Config:
        arbitrary_types_allowed = True
    
    @classmethod
    async def create(
        cls,
        bms_state: Optional[Any] = None,
        alarm_engine: Optional[Any] = None,
        energy_analyzer: Optional[Any] = None,
        gsas_reporter: Optional[Any] = None,
        skillbook: Optional[Any] = None,
        ml_engine: Optional[Any] = None,
        **kwargs
    ) -> "ARVISManus":
        """
        Factory method to create and fully initialize an ARVISManus instance.
        
        Args:
            bms_state: BMS state engine for equipment/point data
            alarm_engine: Alarm management engine
            energy_analyzer: Energy analysis engine
            gsas_reporter: GSAS compliance reporter
            skillbook: Building institutional memory
            ml_engine: ML engines for predictions
            **kwargs: Additional agent configuration
            
        Returns:
            Fully initialized ARVISManus instance
        """
        instance = cls(
            bms_state=bms_state,
            alarm_engine=alarm_engine,
            energy_analyzer=energy_analyzer,
            gsas_reporter=gsas_reporter,
            skillbook=skillbook,
            ml_engine=ml_engine,
            **kwargs
        )
        
        # Build tool collection
        await instance._initialize_tools()
        instance._initialized = True
        
        logger.info(f"[{instance.name}] Initialized with {len(instance.available_tools)} tools")
        
        return instance
    
    async def _initialize_tools(self) -> None:
        """Initialize tool collection with all available tools"""
        
        # Create BMS toolkit with injected engines
        bms_toolkit = BMSToolkit(
            bms_state=self.bms_state,
            alarm_engine=self.alarm_engine,
            energy_analyzer=self.energy_analyzer,
            gsas_reporter=self.gsas_reporter,
            skillbook=self.skillbook,
            ml_engine=self.ml_engine
        )
        
        # Get all BMS tools
        bms_tools = bms_toolkit.get_tools()
        
        # Build collection with BMS tools + terminate
        all_tools = bms_tools + [Terminate()]
        
        self.available_tools = ToolCollection(*all_tools)
        
        logger.info(f"[{self.name}] Loaded {len(bms_tools)} BMS tools")
    
    async def think(self) -> bool:
        """
        Enhanced thinking with BMS context injection.
        
        Before thinking, injects current BMS status into context for better decisions.
        """
        # Inject BMS context if available
        if self.bms_state and not self._initialized:
            await self._initialize_tools()
            self._initialized = True
        
        return await super().think()
    
    async def run(self, request: Optional[str] = None) -> str:
        """
        Run the agent with cleanup when done.
        
        Args:
            request: User request to process
            
        Returns:
            Execution result summary
        """
        if not self._initialized:
            await self._initialize_tools()
            self._initialized = True
        
        try:
            result = await super().run(request)
            return result
        finally:
            await self.cleanup()
    
    async def cleanup(self) -> None:
        """Clean up agent resources"""
        # Cleanup any tool resources
        for tool in self.available_tools:
            if hasattr(tool, 'cleanup'):
                try:
                    await tool.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up tool {tool.name}: {e}")
        
        logger.info(f"[{self.name}] Cleanup complete")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            "name": self.name,
            "state": self.state.value,
            "current_step": self.current_step,
            "max_steps": self.max_steps,
            "tool_count": len(self.available_tools),
            "memory_size": len(self.memory.messages),
            "initialized": self._initialized
        }
