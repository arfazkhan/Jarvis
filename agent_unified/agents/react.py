from abc import abstractmethod
from typing import Optional
from .base import ARVISBaseAgent

class ARVISReActAgent(ARVISBaseAgent):
    """ReAct pattern: Reason + Act"""
    
    @abstractmethod
    async def think(self) -> bool:
        """Process state and decide next action. Returns True if action needed."""
        pass
    
    @abstractmethod
    async def act(self) -> str:
        """Execute the decided action"""
        pass
    
    async def step(self) -> str:
        """Think then act"""
        should_act = await self.think()
        if not should_act:
            return "Thinking complete - no action needed"
        return await self.act()
