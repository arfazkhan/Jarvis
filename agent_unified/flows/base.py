"""
ARVIS Base Flow
===============

Base class for execution flows.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM


class BaseFlow(BaseModel, ABC):
    """
    Abstract base class for execution flows.
    
    Flows orchestrate agent execution for complex multi-step tasks.
    """
    
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    agents: Dict[str, Any] = Field(default_factory=dict)
    primary_agent: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """
        Execute the flow with the given input.
        
        Args:
            input_text: Input text/request to process
            
        Returns:
            String result of flow execution
        """
        pass
    
    def get_agent(self, agent_key: Optional[str] = None) -> Optional[Any]:
        """Get an agent by key or the primary agent"""
        key = agent_key or self.primary_agent
        return self.agents.get(key) if key else None
