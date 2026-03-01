"""
Simulated Debate Consensus Engine for ARVIS Phase 1.
Implements the BFT-style debate algorithm to validate agent proposals
before presenting them to the user.
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from agent_unified.llm import UnifiedLLM

logger = logging.getLogger("arvis.swarm.consensus")

class ConsensusEngine(BaseModel):
    """
    Evaluates conflicting proposals from different Swarm Nodes
    and enforces a mathematically or logically sound consensus.
    """
    llm: Any = None

    class Config:
        arbitrary_types_allowed = True
        
    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    async def debate(self, original_query: str, proposals: Dict[str, str], context: Optional[Dict[str, Any]] = None) -> str:
        """
        Executes a simulated debate among the provided proposals.
        """
        logger.info(f"[Consensus] Initiating debate among {list(proposals.keys())}")
        
        system_prompt = (
            "You are the ARVIS Consensus Engine. "
            "Your sub-agents have proposed different solutions to the user's query. "
            "You must evaluate all proposals. "
            "CRITICAL RULE 1: Safety and structural integrity ALWAYS overrule Energy savings or Comfort. "
            "CRITICAL RULE 2: If a proposed energy saving risks a thermal breach (as identified by another agent), you MUST reject the energy saving. "
            "Synthesize the debate into a final response. State what was proposed, what was rejected and why, and the final safe recommendation."
        )
        
        proposals_text = ""
        for agent_name, proposal in proposals.items():
            proposals_text += f"\n--- {agent_name} Proposal ---\n{proposal}\n"
            
        user_message = (
            f"Original Query: {original_query}\n\n"
            f"Agent Proposals:\n{proposals_text}\n\n"
            "Evaluate, resolve conflicts, and output the final advisory."
        )
        
        response = await self.llm.ask(
            messages=[{"role": "user", "content": user_message}],
            system_msgs=[{"role": "system", "content": system_prompt}]
        )
        
        return response.content or "Consensus failed due to an LLM error."
