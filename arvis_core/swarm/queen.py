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
    tool_handler: Any = Field(default=None, exclude=True)
    llm: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    def register_node(self, node: SwarmNode):
        """Register a specialized agent into the swarm."""
        if self.tool_handler and not node.tool_handler:
            node.tool_handler = self.tool_handler
            
        self.nodes[node.name] = node
        logger.info(f"[Queen] Registered new node: {node.name} with {len(node.tools)} tools")

    async def _route_intent(self, query: str) -> List[SwarmNode]:
        """
        Tiered Smart Router — Routes queries to the right agents across all 3 tiers.
        
        Routing Strategy:
        - Tier 1 (Perception): Always include relevant perception agents
        - Tier 2 (Cognition): Include Strategic for complex queries, Memory for context
        - Tier 3 (Expression): Include Briefing for summary requests, Voice for dialogue
        - Fallback: P0 agents (Energy, Alarm, Maintenance, Comfort) for general queries
        """
        query_lower = query.lower()
        selected = set()
        
        # --- TIER 1: PERCEPTION ROUTING ---
        energy_keywords = {'energy', 'cost', 'kwh', 'consumption', 'burn rate', 'waste', 'ghost', 'occupancy', 'gsas', 'gord', 'certification', 'green', 'benchmark'}
        alarm_keywords = {'alarm', 'fault', 'broken', 'alert', 'cascade', 'root cause', 'critical', 'emergency', 'trip', 'failure'}
        maintenance_keywords = {'maintenance', 'life', 'rul', 'predict', 'health', 'work order', 'pm', 'lifecycle', 'runtime', 'hours', 'degradation', 'vibration'}
        comfort_keywords = {'hot', 'cold', 'comfort', 'temperature', 'humidity', 'co2', 'zone', 'setpoint', 'occupant', 'thermal'}
        sensor_keywords = {'sensor', 'drift', 'calibration', 'data quality', 'reading', 'stale', 'virtual sensor', 'accuracy'}
        
        if any(kw in query_lower for kw in energy_keywords):
            if 'Energy_Agent' in self.nodes: selected.add('Energy_Agent')
        if any(kw in query_lower for kw in alarm_keywords):
            if 'Alarm_Agent' in self.nodes: selected.add('Alarm_Agent')
        if any(kw in query_lower for kw in comfort_keywords):
            if 'Comfort_Agent' in self.nodes: selected.add('Comfort_Agent')
        if any(kw in query_lower for kw in maintenance_keywords):
            if 'Maintenance_Agent' in self.nodes: selected.add('Maintenance_Agent')
        if any(kw in query_lower for kw in sensor_keywords):
            if 'Sensor_Fusion_Agent' in self.nodes: selected.add('Sensor_Fusion_Agent')
            
        # --- TIER 2: COGNITION ROUTING ---
        strategic_keywords = {'why', 'correlat', 'cause', 'what if', 'simulate', 'trust', 'fleet', 'goal', 'compare', 'trend', 'pattern'}
        planning_keywords = {'plan', 'steps', 'sequence', 'how to', 'schedule', 'rollback', 'procedure'}
        memory_keywords = {'remember', 'history', 'before', 'last time', 'skillbook', 'quirk', 'learned', 'knowledge', 'experience'}
        
        if any(kw in query_lower for kw in strategic_keywords):
            if 'Strategic_Agent' in self.nodes: selected.add('Strategic_Agent')
        if any(kw in query_lower for kw in planning_keywords):
            if 'Planning_Agent' in self.nodes: selected.add('Planning_Agent')
        if any(kw in query_lower for kw in memory_keywords):
            if 'Memory_Agent' in self.nodes: selected.add('Memory_Agent')
            
        # --- TIER 3: EXPRESSION ROUTING ---
        briefing_keywords = {'briefing', 'morning', 'summary', 'handoff', 'shift', 'today', 'overview', 'what should'}
        
        if any(kw in query_lower for kw in briefing_keywords):
            if 'Briefing_Agent' in self.nodes: selected.add('Briefing_Agent')
        
        # --- ALWAYS INCLUDE MEMORY for institutional context ---
        if 'Memory_Agent' in self.nodes and len(selected) > 0:
            selected.add('Memory_Agent')
        
        # --- FALLBACK: P0 perception agents for general/broad queries ---
        if not selected:
            p0_agents = ['Energy_Agent', 'Alarm_Agent', 'Maintenance_Agent', 'Comfort_Agent']
            selected = {name for name in p0_agents if name in self.nodes}
            
        selected_nodes = [self.nodes[name] for name in selected if name in self.nodes]
        logger.info(f"[Queen] Routing query to {len(selected_nodes)} nodes: {[n.name for n in selected_nodes]}")
        return selected_nodes

    async def execute_swarm(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Main entry point for dealing with the swarm.
        Returns a dict: {"advice": str, "context": Dict}
        """
        logger.info(f"[Queen] Initiating swarm execution for query: '{query}'")
        
        # 1. Route Intent
        active_nodes = await self._route_intent(query)
        if not active_nodes:
             return {
                 "advice": "I could not find any specialized agents equipped to handle this request.", 
                 "context": {}
             }

        # 2. Sequential Execution with Rate Limiting
        INTER_NODE_DELAY = 3.0  # seconds between each node call
        
        proposals = {}
        aggregated_context = {}
        
        # Determine if query requires action (config changes, setpoints, physical commands) vs informational synthesis
        intent_prompt = (
            "You are a routing supervisor. Read the user's query about a building management system.\n"
            "If the user is asking to change a setting, fix a problem, reduce power, or perform any physical optimization, output: {\"is_actionable\": true}\n"
            "If the user is just asking for status, history, explanations, or data, output: {\"is_actionable\": false}\n"
            "Return ONLY the JSON dictionary."
        )
        
        try:
            intent_result = await self.llm.ask_json(
                messages=[{"role": "user", "content": query}],
                system_msgs=[{"role": "system", "content": intent_prompt}]
            )
            is_actionable = bool(intent_result.get("is_actionable", False))
        except Exception:
            # Fallback to safe read-only synthesis if classification fails
            is_actionable = False
        
        if is_actionable and len(active_nodes) > 1:
            from arvis_core.swarm.consensus import ConsensusEngine, VotingRound
            engine = ConsensusEngine()
            proposer = active_nodes[0]
            quorum = active_nodes[1:]
            
            logger.info(f"[Queen] Actionable query detected. Triggering BFT workflow with Proposer: {proposer.name}")
            
            # 1. Get the concrete proposal from the Lead Agent
            proposer_prompt = f"The user requested an operational change: '{query}'. Formulate a concrete, step-by-step proposal to execute this efficiently."
            proposer_result = await proposer.process(proposer_prompt, context)
            
            proposal_text = proposer_result["response"].content
            proposals[proposer.name] = proposal_text
            
            for msg in proposer_result["history"]:
                if msg.get("role") == "tool":
                    aggregated_context[f"{proposer.name}_{msg.get('name')}"] = msg.get("content")
                    
            round_obj = VotingRound(
                proposal=proposal_text,
                proposer_name=proposer.name,
                context=context or {}
            )
            
            # 2. Run the Debate on the Quorum
            debate_result = await engine.run_debate(round_obj, quorum)
            
            # 3. Aggregate Quorum tool context
            for v_data in debate_result["votes"]:
                proposals[v_data["agent_name"]] = f"VOTE: {v_data['vote']} - Reasoning: {v_data['reasoning']}"
                for tool_name, tool_val in v_data.get("tool_observations", {}).items():
                    aggregated_context[f"{v_data['agent_name']}_{tool_name}"] = tool_val
                    
            if debate_result["status"] == "REJECTED":
                final_advice = f"The {proposer.name} proposed an optimization, but it was VETOED during the safety peer-review by the swarm.\n\n### Proposal:\n{proposal_text}\n\n### Swarm Debate:\n"
                for v in debate_result["votes"]:
                    final_advice += f"- **{v['agent_name']} [{v['vote']}]**: {v['reasoning']}\n"
                final_advice += "\nAction aborted to preserve operational safety."
            else:
                final_advice = await self._synthesize_consensus(query, proposals, context)
            
        else:
            # Standard Synthesis for informational queries
            for i, node in enumerate(active_nodes):
                try:
                    result_map = await node.process(query, context)
                    proposals[node.name] = result_map["response"].content
                    
                    # Extract any tool calls/observations from this node's history to feed the validator
                    for msg in result_map["history"]:
                        if msg.get("role") == "tool":
                            key = f"{node.name}_{msg.get('name')}"
                            aggregated_context[key] = msg.get("content")
                            
                except Exception as e:
                    logger.error(f"[Queen] Node {node.name} failed: {e}")
                    proposals[node.name] = f"Node Failed: {str(e)}"
                
                # Rate-limit: wait between node calls (skip delay after last node)
                if i < len(active_nodes) - 1:
                    await asyncio.sleep(INTER_NODE_DELAY)
            
            # 3. Simulated Debate (Consensus)
            final_advice = await self._synthesize_consensus(query, proposals, context)
        
        return {
            "advice": final_advice,
            "context": aggregated_context
        }

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
