"""
Base Agent Node for the ARVIS Swarm.
Represents a single, specialized agent (e.g., Energy Agent, Safety Agent)
that focuses on a specific domain using specific tools.
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message

logger = logging.getLogger("arvis.swarm.node")

class SwarmNode(BaseModel):
    """
    A single specialized agent within the ARVIS Swarm.
    """
    name: str = Field(..., description="The name of the agent node (e.g., 'Thermal_Comfort_Agent').")
    role: str = Field(..., description="The system prompt describing the agent's specialization and constraints.")
    tools: List[Dict[str, Any]] = Field(default_factory=list, description="The specific tools this agent has access to.")
    
    # Internal references
    llm: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None, history: Optional[List[Dict]] = None) -> Message:
        """
        Processes a query within the agent's specific domain.
        
        Args:
            query: The user's goal or internal swarm request.
            context: Current BMS state and context variables.
            history: Previous messages or trajectory in the current swarm cycle.
            
        Returns:
            The agent's proposed action, analysis, or advice.
        """
        logger.info(f"[Node: {self.name}] Processing query: {query[:50]}...")
        
        # Construct the system message enforcing the agent's role
        system_msgs = [{"role": "system", "content": self.role}]
        if context:
            import json
            system_msgs.append({
                "role": "system", 
                "content": f"Global Context:\n{json.dumps(context, default=str)}"
            })

        # Construct the message history
        messages = history or []
        messages.append({"role": "user", "content": query})

        # Let the LLM decide how to use its specialized tools to answer the query
        try:
            # We use the generic ask() which defaults to reasoning, but pass tools
            response = await self.llm.ask(
                messages=messages,
                system_msgs=system_msgs,
                tools=self.tools if self.tools else None
            )
            return response
        except Exception as e:
            logger.error(f"[Node: {self.name}] Failed to process query: {e}")
            return Message(role="assistant", content=f"[{self.name}] internal error: {str(e)}")
