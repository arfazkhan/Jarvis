"""
Byzantine Fault-Tolerant (BFT) Consensus Engine for ARVIS Swarm.
Enforces peer review on any operational proposal before surfacing it to the user.
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from arvis_core.swarm.node import SwarmNode

logger = logging.getLogger("arvis.swarm.consensus")

class VoteResult(BaseModel):
    agent_name: str
    vote: str  # "APPROVE" or "VETO"
    reasoning: str
    tool_observations: Dict[str, Any] = Field(default_factory=dict)

class VotingRound(BaseModel):
    proposal: str
    proposer_name: str
    context: Dict[str, Any] = Field(default_factory=dict)
    
class ConsensusEngine:
    """
    Forces safety-critical constraints via peer review. 
    1 Veto from a safety/comfort agent blocks an action.
    """
    def __init__(self):
        self.llm = UnifiedLLM()
        
    async def run_debate(self, round_data: VotingRound, quorum: List[SwarmNode], channel: str = "chat") -> Dict[str, Any]:
        """
        Executes parallel Review phases against the proposed action.
        """
        logger.info(f"[Consensus] Initiating BFT Debate. Proposer: {round_data.proposer_name}. Quorum size: {len(quorum)}")
        
        votes: List[VoteResult] = []
        
        # Run quorum checks in parallel to reduce BFT latency
        async def run_vote(node):
            if node.name == round_data.proposer_name:
                return None
            
            logger.info(f"[Consensus] Seeking peer review from {node.name}...")
            
            prompt = (
                f"You are {node.name}, a specialized Guardian node in the ARVIS Cognitive Swarm.\n"
                f"Another agent ({round_data.proposer_name}) has proposed the following operational action:\n"
                f"PROPOSAL: {round_data.proposal}\n\n"
                f"Your MUST vet this proposal strictly within your operational domain (e.g. thermal comfort, equipment safety, energy).\n"
                f"Use your tools to simulate or check if this proposal violates any constraints.\n"
                f"Output your final judgment in strict JSON: {{\"vote\": \"APPROVE\" or \"VETO\", \"reasoning\": \"Detailed technical reason\"}}"
            )
            
            try:
                result_map = await node.process(query=prompt, context=round_data.context, channel=channel)
                raw_response = result_map["response"].content
                
                # Find JSON payload
                import json
                content = raw_response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                vote_data = json.loads(content)
                vote = vote_data.get("vote", "VETO").upper()
                reasoning = vote_data.get("reasoning", "Failed to parse reasoning")
                
                reviewer_context = {}
                for msg in result_map["history"]:
                    if msg.get("role") == "tool":
                        reviewer_context[msg.get("name")] = msg.get("content")
                        
                return VoteResult(
                    agent_name=node.name,
                    vote=vote,
                    reasoning=reasoning,
                    tool_observations=reviewer_context
                )
            except Exception as e:
                logger.error(f"[Consensus] Failed to parse vote from {node.name}: {e}. Defaulting to VETO for safety.")
                return VoteResult(
                    agent_name=node.name,
                    vote="VETO",
                    reasoning=f"Agent exception/Parse error: {e}",
                    tool_observations={}
                )

        tasks = [run_vote(node) for node in quorum]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res:
                votes.append(res)
            
        vetoes = [v for v in votes if v.vote == "VETO"]
        
        if vetoes:
            logger.warning(f"[Consensus] Proposal VETOED by {len(vetoes)} nodes!")
            status = "REJECTED"
        else:
            logger.info(f"[Consensus] Proposal unanimously APPROVED by quorum.")
            status = "APPROVED"
            
        return {
            "status": status,
            "votes": [v.model_dump() for v in votes],
            "original_proposal": round_data.proposal
        }
