"""
Queen Coordinator for the ARVIS Swarm.
Acts as the central router and orchestrator for the specialized Agent Nodes.
"""

import logging
import asyncio
import json
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
    building_id: str = "default"

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

    async def _route_intent(self, query: str) -> List[Any]:
        """
        Smart intent router that maps query keywords to ARVIS Swarm Node tiers.
        """
        query_lower = query.lower()
        selected = set()
        
        # --- PHASE 4: Load EWC++ weights to skip degraded agents ---
        ewc_weights = {}
        try:
            from agent_cognitive.meta_cognition import MetaCognition
            ewc_weights = MetaCognition(building_id="default").get_active_calibration_rules()
        except Exception:
            pass
        
        hallucination_rule = ewc_weights.get("hallucination_penalty_rule", {})
        if hallucination_rule.get("weight_adjustment", 0) < -0.3:
            logger.warning("[Queen/MoE] Hallucination penalty is high. Restricting responses to factual nodes only.")
        
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
        
        if not selected:
            p0_agents = ['Energy_Agent', 'Alarm_Agent', 'Maintenance_Agent', 'Comfort_Agent', 'Strategic_Agent']
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
        
        # 1.1 CRITICAL GROUNDING OVERRIDE: Ensure Safety agents are active if breaches exist
        thermal_breaches = (context or {}).get("GROUNDING_THERMAL_SAFETY", [])
        if thermal_breaches and "Comfort_Agent" in self.nodes:
            if not any(n.name == "Comfort_Agent" for n in active_nodes):
                logger.info("[Queen] Thermal breaches detected in grounding. FORCE-ADDING Comfort_Agent.")
                active_nodes.append(self.nodes["Comfort_Agent"])

        if not active_nodes:
             return {
                 "advice": "I could not find any specialized agents equipped to handle this request.", 
                 "context": {}
             }

        # 2. Sequential Execution with Rate Limiting
        INTER_NODE_DELAY = 1.0  # seconds between each node call
        
        proposals = {}
        aggregated_context = {}
        
        intent_prompt = (
            "You are a routing supervisor. Read the user's query about a building management system.\n"
            "If the user is asking to change a setting, fix a problem, reduce power, perform any physical optimization, or SIMULATE/assess the impact of a future change, output: {\"is_actionable\": true}\n"
            "If the user is just asking for current status, history, explanations, or data, output: {\"is_actionable\": false}\n"
            "Return ONLY the JSON dictionary."
        )
        
        try:
            intent_result = await self.llm.ask_json(
                messages=[{"role": "user", "content": query}],
                system_msgs=[{"role": "system", "content": intent_prompt}]
            )
            is_actionable = bool(intent_result.get("is_actionable", False))
        except Exception:
            is_actionable = False
            
        if not is_actionable:
            logger.info(f"[Queen] Non-actionable query detected. Bypassing Swarm to use Fast-Path routing.")
            return {
                "advice": "__FAST_PATH_ROUTING__",
                "context": context or {}
            }
        
        if is_actionable and len(active_nodes) > 1:
            from arvis_core.swarm.consensus import ConsensusEngine, VotingRound
            engine = ConsensusEngine()
            proposer = active_nodes[0]
            quorum = active_nodes[1:]
            
            logger.info(f"[Queen] Actionable query detected. Triggering BFT workflow with Proposer: {proposer.name}")
            
            # HARDENED PROPOSER PROMPT: Ensure strict adherence to GROUNDING_DATA
            proposer_prompt = (
                f"The user requested an operational change: '{query}'.\n"
                "Formulate a concrete, high-fidelity proposal to execute this efficiently.\n"
                "CRITICAL: You MUST include your quantitative findings in a 'GROUNDING_DATA' block at the START of your response.\n"
                "Ensure your proposed savings/costs are logically derived from your tool history to avoid BFT vetoes."
            )
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
            
            debate_result = await engine.run_debate(round_obj, quorum)
            
            for v_data in debate_result["votes"]:
                proposals[v_data["agent_name"]] = f"VOTE: {v_data['vote']} - Reasoning: {v_data['reasoning']}"
                for tool_name, tool_val in v_data.get("tool_observations", {}).items():
                    aggregated_context[f"{v_data['agent_name']}_{tool_name}"] = tool_val
                    
            if debate_result["status"] == "REJECTED":
                # Fallback: Instead of just returning a string, return a "Vetoed Advisory" JSON so the runner can see it
                veto_analysis = f"Operational optimization vetoed by cognitive swarm due to safety or data inconsistencies."
                veto_reasons = ""
                for v in debate_result["votes"]:
                    veto_reasons += f"- {v['agent_name']} [{v['vote']}]: {v['reasoning']}\\n"
                
                final_advice_dict = {
                    "analysis": veto_analysis,
                    "advisories": [{
                        "id": "veto-1",
                        "type": "safety_override",
                        "severity": "high",
                        "message": f"I simulated your proposed action, but the swarm VETOED it for the following reasons:\\n\\n{veto_reasons}",
                        "confidence": 1.0,
                        "impact": {"timeframe": "null", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                        "recommended_action": {"type": "abort"},
                        "counterfactual_check": True
                    }]
                }
                final_advice = json.dumps(final_advice_dict)
            else:
                full_grounding_context = {**(context or {}), **aggregated_context}
                final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context)
                
        else:
            # Execute all nodes in parallel to reduce latency
            async def run_node(node):
                try:
                    result = await node.process(query, context)
                    return node.name, result, None
                except Exception as e:
                    logger.error(f"[Queen] Node {node.name} failed: {e}")
                    return node.name, None, e

            tasks = [run_node(node) for node in active_nodes]
            results = await asyncio.gather(*tasks)

            for node_name, result_map, err in results:
                if err:
                    proposals[node_name] = f"Node Failed: {str(err)}"
                else:
                    proposals[node_name] = result_map["response"].content
                    for msg in result_map["history"]:
                        if msg.get("role") == "tool":
                            key = f"{node_name}_{msg.get('name')}"
                            aggregated_context[key] = msg.get("content")
            
            full_grounding_context = {**(context or {}), **aggregated_context}
            final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context)
        
        return {
            "advice": final_advice,
            "context": aggregated_context
        }

    async def _synthesize_consensus(self, original_query: str, proposals: Dict[str, str], context: Optional[Dict[str, Any]]) -> str:
        """
        Synthesizes agent proposals into a high-fidelity consensus advisory.
        Maintains structural robustness for interoperability while preserving 
        probabilistic operational markers.
        """
        system_prompt = (
            "You are the Queen Coordinator of the ARVIS Cognitive Swarm. "
            "Synthesize agent proposals into a unified ARVIS Advisory JSON.\n\n"
            "--- CRITICAL GUIDELINES ---\n"
            "1. CONFLICT RESOLUTION: Resolve domain contradictions by prioritizing Safety > Comfort > Energy.\n"
            "2. DATA INTEGRITY: Copy energy_kwh and cost_qar values EXACTLY from agent 'GROUNDING_DATA' blocks. "
            "If conflicting, use the more conservative (lower savings/higher cost) number.\n"
            "3. MARKER PRESERVATION: Carry forward specific strings like '[VIP_OVERRIDE_DETECTED]' or '[DOWNGRADE_REQUIRED]' into the 'message' field if they appear in any agent proposal.\n"
            "4. TYPE HYGIENE: The 'message' field MUST be a single string (narrative), NOT a list. "
            "The 'evidence' field is for the list of findings.\n\n"
            "--- FORMAT REQUIREMENT ---\n"
            "Return ONLY a valid JSON object. No narrative text.\n\n"
            "SCHEMA:\n"
            "{\n"
            "  \"analysis\": \"str: summary of consensus logic\",\n"
            "  \"advisories\": [{\n"
            "    \"id\": \"auto-1\",\n"
            "    \"type\": \"str (e.g., energy_waste, safety_priority)\",\n"
            "    \"severity\": \"str (low/medium/high/critical)\",\n"
            "    \"message\": \"str: Narrative advisory for FM dashboard. Include operational markers here.\",\n"
            "    \"confidence\": float (0.0-1.0),\n"
            "    \"evidence\": [{\"source\": \"AgentName\", \"finding\": \"str\"}],\n"
            "    \"impact\": {\n"
            "        \"timeframe\": \"str\",\n"
            "        \"energy_kwh\": float,\n"
            "        \"cost_qar\": float,\n"
            "        \"is_savings\": bool\n"
            "    },\n"
            "    \"recommended_action\": {\"type\": \"str\"},\n"
            "    \"counterfactual_check\": bool\n"
            "  }]\n"
            "}"
        )
        
        proposals_text = ""
        for agent_name, proposal in proposals.items():
            proposals_text += f"\n--- {agent_name} Proposal ---\n{proposal}\n"
            
        user_message = (
            f"Original Query: {original_query}\n\n"
            f"Grounding Context (FACTS): {json.dumps(context, default=str)}\n\n"
            f"Agent Proposals:\n{proposals_text}\n\n"
            "Please synthesize these into the final ARVIS Advisory JSON. "
            "CRITICAL: If 'GROUNDING_THERMAL_SAFETY' contains items, you MUST generate a high-priority advisory even if agent proposals are weak."
        )
        
        logger.info(f"[Queen] Synthesizing consensus across {len(proposals)} proposals...")
        logger.debug(f"[Queen] Grounding Context for synthesis: {json.dumps(context)[:1000]}...")
        
        try:
            response = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_message}],
                system_msgs=[{"role": "system", "content": system_prompt}]
            )
            return json.dumps(response) if isinstance(response, dict) else str(response)
        except Exception as e:
            logger.error(f"[Queen] Synthesis failed: {e}")
            return f"Consensus failed: {str(e)}"
