"""
ARVIS ReAct Agent
=================

ReAct (Reasoning + Acting) pattern implementation.

Provides think → act cycle for structured agent behavior.
"""

from abc import abstractmethod

from .base import ARVISBaseAgent


class ARVISReActAgent(ARVISBaseAgent):
    """
    ReAct pattern agent: Reason then Act.
    
    Implements the think → act cycle:
    1. think(): Analyze state and decide action
    2. act(): Execute the decided action
    """
    
    @abstractmethod
    async def think(self) -> bool:
        """
        Process current state and decide next action.
        
        Returns:
            True if an action should be taken, False otherwise
        """
        pass
    
    @abstractmethod
    async def act(self) -> str:
        """
        Execute decided actions.
        
        Returns:
            String describing action result
        """
        pass
    
    async def step(self) -> str:
        """
        Execute a single step: think then act.
        
        Returns:
            String describing step result
        """
        should_act = await self.think()
        
        if not should_act:
            return "Thinking complete - no action needed"
        
        return await self.act()
