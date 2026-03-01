"""
Queen Coordinator for the ARVIS Swarm.
Acts as the central router and orchestrator for the specialized Agent Nodes.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message
from arvis_core.swarm.node import SwarmNode

logger = logging.getLogger("arvis.swarm.queen")

class QueenCoordinator(BaseModel):
    """
    The orchestrator of the ARVIS Cognitive Swarm.
    Receives user intents, routes them to specialized agents, and synthesizes 
    the consensus into final advisory actions.
    """
    nodes: Dict[str, SwarmNode] = Field(default_factory=dict)
    llm: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    def register_node(self, node: SwarmNode):
        """Register a specialized agent into the swarm."""
        self.nodes[node.name] = node
        logger.info(f"[Queen] Registered new node: {node.name}")

    async def _route_intent(self, query: str) -> List[SwarmNode]:
        """
        Dynamic Tiered Routing (Smart Router).
        Decides which subclass agents need to be invoked for this specific query.
        For phase 1, we return all relevant nodes for parallel processing, 
        but in the future this will use complexity scoring.
        """
        # A fast LLM pass or heuristic to determine required domains
        # For this skeleton, if it mentions energy, bring in Energy. If it mentions temperatures, Comfort.
        query_lower = query.lower()
        selected_nodes = []
        
        # Extremely basic heuristics for skeleton
        if 'energy' in query_lower or 'cost' in query_lower:
            if 'Energy_Agent' in self.nodes: selected_nodes.append(self.nodes['Energy_Agent'])
        if 'alarm' in query_lower or 'fault' in query_lower or 'broken' in query_lower:
            if 'Alarm_Agent' in self.nodes: selected_nodes.append(self.nodes['Alarm_Agent'])
        if 'hot' in query_lower or 'cold' in query_lower or 'comfort' in query_lower:
            if 'Comfort_Agent' in self.nodes: selected_nodes.append(self.nodes['Comfort_Agent'])
        if 'maintenance' in query_lower or 'life' in query_lower or 'pm' in query_lower:
            if 'Maintenance_Agent' in self.nodes: selected_nodes.append(self.nodes['Maintenance_Agent'])
            
        # If no specific nodes found, return all available nodes for a swarm debate
        if not selected_nodes:
            selected_nodes = list(self.nodes.values())
            
        logger.info(f"[Queen] Routing query to {len(selected_nodes)} nodes: {[n.name for n in selected_nodes]}")
        return selected_nodes

    async def execute_swarm(self, query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Main entry point for dealing with the swarm.
        1. Route to specialized agents
        2. Execute in parallel
        3. Consensus / Debate
        4. Synthesize final answer
        """
        logger.info(f"[Queen] Initiating swarm execution for query: '{query}'")
        
        # 1. Route Intent
        active_nodes = await self._route_intent(query)
        if not active_nodes:
             return "I could not find any specialized agents equipped to handle this request."

        # 2. Sequential Execution with Rate Limiting
        # K2 Think API has ~20 RPM limit. Running nodes in parallel overwhelms the API.
        # Execute each node sequentially with a delay between calls to stay within rate limits.
        INTER_NODE_DELAY = 3.0  # seconds between each node call
        
        proposals = {}
        for i, node in enumerate(active_nodes):
            try:
                result = await node.process(query, context)
                proposals[node.name] = result.content
            except Exception as e:
                logger.error(f"[Queen] Node {node.name} failed: {e}")
                proposals[node.name] = f"Node Failed: {str(e)}"
            
            # Rate-limit: wait between node calls (skip delay after last node)
            if i < len(active_nodes) - 1:
                await asyncio.sleep(INTER_NODE_DELAY)
        
        # 3. Simulated Debate (Consensus)
        # We synthesize the proposals into a final, verified piece of advice.
        # This acts as the consensus mechanism where the Queen resolves conflicts 
        # (e.g., Energy wants X, Comfort wants Y).
        final_advice = await self._synthesize_consensus(query, proposals, context)
        
        return final_advice

    async def _synthesize_consensus(self, original_query: str, proposals: Dict[str, str], context: Optional[Dict[str, Any]]) -> str:
        """
        Takes the parallel proposals from the specialized nodes and synthesizes a final,
        vetted consensus resolving any domain conflicts.
        """
        system_prompt = (
            "You are the Queen Coordinator of the ARVIS Cognitive Swarm. "
            "You just delegated a user query to your specialized sub-agents. "
            "They have provided their independent proposals based on their domain (Energy, Safety, Comfort, etc). "
            "Your job is to read their proposals, resolve any contradictions (prioritizing Safety over Comfort over Energy), "
            "and output a final, unified piece of advice for the Facility Manager.\n"
            "If an agent rejected another agent's idea due to an operational limit, clearly explain this debate to the user so they understand WHY the final advice was chosen."
        )
        
        # Format the proposals
        proposals_text = ""
        for agent_name, proposal in proposals.items():
            proposals_text += f"\n--- {agent_name} Proposal ---\n{proposal}\n"
            
        user_message = (
            f"Original Query: {original_query}\n\n"
            f"Agent Proposals:\n{proposals_text}\n\n"
            "Please synthesize these into the final, verified ARVIS Advisory Statement."
        )
        
        logger.info(f"[Queen] Synthesizing consensus across {len(proposals)} proposals...")
        response = await self.llm.ask(
            messages=[{"role": "user", "content": user_message}],
            system_msgs=[{"role": "system", "content": system_prompt}]
        )
        
        return response.content or "Consensus failed."
