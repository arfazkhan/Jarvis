"""
Queen Coordinator for the ARVIS Swarm.
Acts as the central router and orchestrator for the specialized Agent Nodes.
"""

import logging
import asyncio
import json
import re
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from agent_unified.schema import Message
from arvis_core.swarm.node import SwarmNode
from arvis_core.swarm.intent_router import EmbeddingIntentRouter, build_intent_router

logger = logging.getLogger("arvis.swarm.queen")

# Module-level constants (avoid Pydantic wrapping as PrivateAttr)
_SAFETY_KEYWORDS_RE = re.compile(
    r"\b(fail|failure|breakdown|trip|emergency|critical|alarm|safety|"
    r"leak|fire|smoke|fault|diagnos|root\s*cause|why\s+is|investigate)\b",
    re.IGNORECASE,
)

_ACTION_VERBS_RE = re.compile(
    r"\b(submitted|corrected|updated|changed|adjusted|turned\s+off|"
    r"restarted|applied|executed|implemented|activated|deactivated|"
    r"shut\s+down|powered\s+off|overrode|modified)\b",
    re.IGNORECASE,
)

_VERB_REPLACEMENTS = {
    "submitted": "recommend submitting",
    "corrected": "recommend correcting",
    "updated": "recommend updating",
    "changed": "recommend changing",
    "adjusted": "recommend adjusting",
    "turned off": "recommend turning off",
    "restarted": "recommend restarting",
    "applied": "recommend applying",
    "executed": "recommend executing",
    "implemented": "recommend implementing",
    "activated": "recommend activating",
    "deactivated": "recommend deactivating",
    "shut down": "recommend shutting down",
    "powered off": "recommend powering off",
    "overrode": "recommend overriding",
    "modified": "recommend modifying",
}


class QueenCoordinator(BaseModel):
    """
    The orchestrator of the ARVIS Cognitive Swarm.
    Receives user intents, routes them to specialized agents, and synthesizes
    the consensus into final advisory actions.
    """
    nodes: Dict[str, SwarmNode] = Field(default_factory=dict)
    tool_handler: Any = Field(default=None, exclude=True)
    llm: Any = Field(default=None, exclude=True)
    intent_router: Any = Field(default=None, exclude=True)
    building_id: str = "default"

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()
        if not self.intent_router:
            self.intent_router = build_intent_router()

    def register_node(self, node: SwarmNode):
        """Register a specialized agent into the swarm."""
        if self.tool_handler and not node.tool_handler:
            node.tool_handler = self.tool_handler
            
        if self.llm and not getattr(node, 'llm', None):
            node.llm = self.llm
            
        self.nodes[node.name] = node
        logger.info(f"[Queen] Registered new node: {node.name} with {len(node.tools)} tools")

    async def _route_intent(self, query: str) -> List[Any]:
        """
        Embedding-based intent router with keyword fallback.
        Routes queries to the most semantically relevant swarm nodes.
        """
        # Use semantic routing via intent_router
        route_results = self.intent_router.route(query, top_k=3, threshold=0.35)

        selected = set()
        for node_name, score in route_results:
            if node_name in self.nodes:
                selected.add(node_name)

        # Always include Memory_Agent for institutional context
        if selected and "Memory_Agent" in self.nodes:
            selected.add("Memory_Agent")

        # Fallback: if nothing matched, activate core agents
        if not selected:
            p0_agents = ["Energy_Agent", "Alarm_Agent", "Maintenance_Agent", "Comfort_Agent", "Strategic_Agent"]
            selected = {name for name in p0_agents if name in self.nodes}

        selected_nodes = [self.nodes[name] for name in selected if name in self.nodes]
        logger.info(f"[Queen] Routing query to {len(selected_nodes)} nodes: {[n.name for n in selected_nodes]}")
        return selected_nodes

    async def execute_swarm(self, query: str, context: Optional[Dict[str, Any]] = None, channel: str = "chat") -> Dict[str, Any]:
        """
        Main entry point for dealing with the swarm.
        Returns a dict: {"advice": str, "context": Dict, "plan": InvestigationPlan}
        """
        from arvis_core.plan import InvestigationPlan, Budget
        plan = InvestigationPlan(query=query, budget=Budget())
        logger.info(f"[Queen] Initiating swarm execution for query: '{query}' (plan={plan.id})")
        
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
                 "context": {},
                 "plan": plan,
             }

        # 2. Sequential Execution with Rate Limiting
        INTER_NODE_DELAY = 1.0  # seconds between each node call

        proposals = {}
        aggregated_context = {}

        # Risk-tiered routing: T1 (lookup) / T2 (diagnostic) / T3 (actionable)
        risk_tier = await self._classify_risk_tier(query)
        logger.info(f"[Queen] Risk tier: T{risk_tier}")

        # C1 fix: Populate plan with one task per active node
        for node in active_nodes:
            plan.add_task(
                goal=f"{node.name}: investigate '{query[:60]}'",
                tool_hint=node.name,
                expected_outcome=f"Evidence from {node.name} domain",
            )
            plan.tasks[-1].assigned_node = node.name

        # ── Auto-recall: T2+T3+T5+T6 memory injected before any node runs ─
        _recall_context_block = ""
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                recall_bundle = await _mo.recall_for_investigation(plan)
                if not recall_bundle.is_empty:
                    _recall_context_block = recall_bundle.to_context_block()
                    logger.info(f"[Queen] Auto-recall: {len(recall_bundle.similar_investigations)} past investigations, "
                                f"{len(recall_bundle.applicable_skills)} skills, "
                                f"{len(recall_bundle.matching_patterns)} patterns injected")
                    # Inject recall hits as Evidence so plan coverage counts them
                    from arvis_core.evidence import Evidence, FreshnessStatus
                    from arvis_core.memory.types import MemoryTier
                    for hit in (recall_bundle.similar_investigations + recall_bundle.applicable_skills
                                + recall_bundle.matching_patterns)[:10]:
                        ev = Evidence(
                            source_tool=f"memory_recall:{hit.tier.value}",
                            raw_payload={"content": hit.content, "source": hit.source, **hit.metadata},
                            node_name="MemoryOrchestrator",
                            freshness=FreshnessStatus.RECENT,
                            summary=hit.content[:200],
                        )
                        plan.evidence.add(ev)
            except Exception as _rc_err:
                logger.debug(f"[Queen] Auto-recall failed (non-fatal): {_rc_err}")

        # Attach recall context to context dict so nodes receive it
        if _recall_context_block:
            context = {**(context or {}), "RECALL_CONTEXT": _recall_context_block}

        if risk_tier == 1:
            # T0.4: T1 lookup queries MUST call at least one tool.
            # Route through the best-fit node with tool_choice="required" so the
            # LLM is forced to fetch live data rather than hallucinating from memory.
            lookup_node = self._pick_lookup_node(query, active_nodes)
            logger.info(f"[Queen] T1 Lookup — forced-tool via {lookup_node.name}")
            for t in plan.tasks:
                if t.assigned_node == lookup_node.name:
                    t.mark_active()
                    break
            try:
                t1_result = await lookup_node.process(
                    query, context, channel=channel, plan=plan, tool_choice="required"
                )
                for t in plan.tasks:
                    if t.assigned_node == lookup_node.name and t.status.value == "active":
                        t.mark_complete()
                        break
                t1_response = t1_result.get("response") if isinstance(t1_result, dict) else t1_result
                t1_advice = t1_response.content if hasattr(t1_response, "content") else str(t1_response)
            except Exception as _e:
                logger.error(f"[Queen] T1 lookup node failed: {_e}")
                t1_advice = f"Lookup failed: {_e}"
            return {
                "advice": t1_advice,
                "context": context or {},
                "plan": plan,
            }

        # A3: Solo-node T3 proposals must face independent review
        if risk_tier == 3 and len(active_nodes) == 1:
            logger.info("[Queen] T3 solo-node: spawning Guardian for independent review.")
            _proposer_tools = active_nodes[0].tools
            guardian = SwarmNode(
                name="Guardian_Reviewer",
                role=(
                    "You are an independent safety reviewer for ARVIS. "
                    "Your job is to critically evaluate whether a proposed action is safe, "
                    "well-supported by evidence, and does not risk equipment damage or comfort violations. "
                    "Challenge assumptions. Check for missing data. Vote VETO if uncertain."
                ),
                tools=_proposer_tools,
                tool_handler=active_nodes[0].tool_handler,
                llm=self.llm,
            )
            active_nodes.append(guardian)
            # NM4 fix: Guardian gets its own plan task
            plan.add_task(
                goal=f"Guardian_Reviewer: independent safety review of '{query[:60]}'",
                tool_hint="Guardian_Reviewer",
                expected_outcome="Independent safety verification of proposal",
            )
            plan.tasks[-1].assigned_node = "Guardian_Reviewer"

        if risk_tier == 3 and len(active_nodes) > 1:
            from arvis_core.swarm.consensus import ConsensusEngine, VotingRound
            engine = ConsensusEngine()
            proposer = active_nodes[0]
            quorum = active_nodes[1:]

            logger.info(f"[Queen] Actionable query detected. Triggering BFT workflow with Proposer: {proposer.name}")

            # ── Conversation history prefix ──────────────────────────────────
            _conv_history = (context or {}).get("chat_history", [])
            _history_prefix = ""
            if _conv_history:
                _recent = _conv_history[-6:]  # last 3 turns (user+assistant pairs)
                _history_prefix = "CONVERSATION HISTORY (last turns):\n" + "\n".join(
                    f"  {m['role'].upper()}: {str(m.get('content',''))[:200]}"
                    for m in _recent
                ) + "\n\n"

            # HARDENED PROPOSER PROMPT: Ensure strict adherence to GROUNDING_DATA
            proposer_prompt = (
                _history_prefix
                + f"The user requested an operational change: '{query}'.\n"
                "Formulate a concrete, high-fidelity proposal to execute this efficiently.\n"
                "CRITICAL: You MUST include your quantitative findings in a 'GROUNDING_DATA' block at the START of your response.\n"
                "Ensure your proposed savings/costs are logically derived from your tool history to avoid BFT vetoes."
            )
            # NM2 fix: Mark proposer task active → process → complete/failed
            proposer_result = await self._run_with_task_lifecycle(
                proposer, plan, proposer_prompt, context, channel
            )

            proposal_text = proposer_result["response"].content

            # H8: Self-consistency check on ALL T3 proposals (not just safety keywords)
            proposal_text = await self._self_consistency_check(
                proposer, proposer_prompt, proposal_text, context, channel, plan
            )

            proposals[proposer.name] = proposal_text

            # Build proposer's shared KB from tool results
            proposer_kb: Dict[str, Any] = {}
            for msg in proposer_result["history"]:
                if msg.get("role") == "tool":
                    aggregated_context[f"{proposer.name}_{msg.get('name')}"] = msg.get("content")
                    _key = f"{proposer.name}:{msg.get('name', 'tool')}"
                    try:
                        _fact = json.loads(msg["content"])
                        proposer_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                    except Exception:
                        proposer_kb[_key] = {"raw": str(msg.get("content", ""))[:300]}

            # M2-C: OutcomePredictor soft annotation before BFT voting
            _outcome_annotation = {}
            try:
                from agent_advisory.ml_models.outcome_predictor import OutcomePredictor
                _op = OutcomePredictor()
                _action = {"action_type": "advisory", "description": proposal_text[:500]}
                _prediction = _op.predict(context or {}, _action)
                if _prediction.confidence > 0.6 and _prediction.predicted_quality == "poor":
                    _outcome_annotation = {
                        "PREDICTED_NEGATIVE_OUTCOME": _prediction.to_dict(),
                    }
                    logger.info(
                        f"[Queen] OutcomePredictor: poor outcome predicted "
                        f"(utility={_prediction.predicted_utility:.2f}, conf={_prediction.confidence:.2f})"
                    )
            except Exception as _op_err:
                logger.debug(f"[Queen] OutcomePredictor skipped (non-fatal): {_op_err}")

            # Inject proposer findings into quorum context — quorum votes knowing what proposer observed
            round_obj = VotingRound(
                proposal=proposal_text,
                proposer_name=proposer.name,
                context={**(context or {}), "cross_agent_findings": proposer_kb, **_outcome_annotation}
            )

            # NM2 fix: Mark quorum tasks active before debate
            for q_node in quorum:
                for t in plan.tasks:
                    if t.assigned_node == q_node.name and t.status.value == "pending":
                        t.mark_active()
                        break
            # B3 fix: broadcast quorum activation
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass

            # B4 fix: wrap run_debate in try/except
            try:
                debate_result = await engine.run_debate(round_obj, quorum, channel=channel, plan=plan)
            except Exception as _debate_err:
                logger.error(f"[Queen] run_debate raised: {_debate_err}. Marking quorum tasks FAILED.")
                for q_node in quorum:
                    for t in plan.tasks:
                        if t.assigned_node == q_node.name and t.status.value == "active":
                            t.mark_failed()
                            break
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
                # Fall through to hard-veto path
                debate_result = {"status": "REJECTED", "votes": [], "conditions": [], "avg_confidence": 0.0, "original_proposal": proposal_text}

            # B5 fix: per-vote task marking (not blanket complete)
            vote_outcomes = {v["agent_name"]: v["vote"] for v in debate_result.get("votes", [])}
            for q_node in quorum:
                for t in plan.tasks:
                    if t.assigned_node == q_node.name and t.status.value == "active":
                        node_vote = vote_outcomes.get(q_node.name, "")
                        if node_vote in ("APPROVE", "APPROVE_WITH_CONDITION"):
                            t.mark_complete()
                        else:
                            t.mark_failed()  # VETO and parse_error both count as failed
                        break
            # B3 fix: broadcast quorum completion
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass
            
            for v_data in debate_result["votes"]:
                proposals[v_data["agent_name"]] = f"VOTE: {v_data['vote']} - Reasoning: {v_data['reasoning']}"
                for tool_name, tool_val in v_data.get("tool_observations", {}).items():
                    aggregated_context[f"{v_data['agent_name']}_{tool_name}"] = tool_val
                    
            if debate_result["status"] == "REJECTED":
                veto_reasons = ""
                for v in debate_result["votes"]:
                    veto_reasons += f"- {v['agent_name']} [{v['vote']}]: {v['reasoning']}\n"

                # 4C: Attempt re-route to alternate nodes before hard veto
                original_node_names = {n.name for n in active_nodes}
                alternate_nodes = [
                    n for n in self.nodes.values()
                    if n.name not in original_node_names
                ][:2]

                if alternate_nodes:
                    logger.warning(f"[Queen] BFT vetoed. Re-routing to {len(alternate_nodes)} alternate nodes with veto constraints.")
                    # NM3 fix: Add tasks for alternate nodes
                    for alt_node in alternate_nodes:
                        plan.add_task(
                            goal=f"{alt_node.name}: veto re-route for '{query[:40]}'",
                            tool_hint=alt_node.name,
                            expected_outcome="Alternative proposal addressing veto constraints",
                        )
                        plan.tasks[-1].assigned_node = alt_node.name
                    # A5: Pass veto reasons as explicit constraints — alternates must address each
                    constrained_query = (
                        f"{query}\n\n"
                        f"--- VETO CONSTRAINTS (from prior peer review — you MUST address each) ---\n"
                        f"{veto_reasons}\n"
                        f"Your proposal must explicitly resolve each concern above. "
                        f"If you cannot address a constraint, state why clearly.\n"
                        f"--- END VETO CONSTRAINTS ---"
                    )
                    # NM3 fix: Run alternates with task lifecycle
                    alt_tasks = [
                        self._run_with_task_lifecycle(node, plan, constrained_query, context, channel)
                        for node in alternate_nodes
                    ]
                    alt_results = await asyncio.gather(*alt_tasks, return_exceptions=True)
                    alt_proposals = {}
                    for node, res in zip(alternate_nodes, alt_results):
                        if isinstance(res, dict):
                            alt_proposals[node.name] = res.get("response", {}).content if hasattr(res.get("response", {}), "content") else str(res.get("response", ""))
                        else:
                            alt_proposals[node.name] = f"Alternate node error: {res}"

                    if any(not v.startswith("Alternate node error") for v in alt_proposals.values()):
                        logger.info("[Queen] Alternate nodes produced valid proposals. Synthesizing.")
                        full_grounding_context = {**(context or {}), **aggregated_context}
                        final_advice = await self._synthesize_consensus(query, alt_proposals, full_grounding_context, plan=plan)
                    else:
                        # All alternates failed — fall through to hard veto
                        alternate_nodes = []

                if not alternate_nodes:
                    veto_analysis = "Operational optimization vetoed by cognitive swarm due to safety or data inconsistencies."
                    final_advice_dict = {
                        "analysis": veto_analysis,
                        "advisories": [{
                            "id": "veto-1",
                            "type": "safety_override",
                            "severity": "high",
                            "message": f"I simulated your proposed action, but the swarm VETOED it for the following reasons:\n\n{veto_reasons}",
                            "confidence": 1.0,
                            "impact": {"timeframe": "null", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                            "recommended_action": {"type": "abort"},
                            "counterfactual_check": True
                        }]
                    }
                    final_advice = json.dumps(final_advice_dict)
            else:
                # Merge proposer KB + quorum vote tool observations into shared KB for synthesis
                bft_kb: Dict[str, Any] = {**proposer_kb}
                for v_data in debate_result["votes"]:
                    for t_name, t_val in v_data.get("tool_observations", {}).items():
                        _key = f"{v_data['agent_name']}:{t_name}"
                        try:
                            _fact = json.loads(t_val) if isinstance(t_val, str) else t_val
                            bft_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                        except Exception:
                            bft_kb[_key] = {"raw": str(t_val)[:300]}
                full_grounding_context = {**(context or {}), **aggregated_context, "cross_agent_findings": bft_kb}

                # Inject conditions from APPROVE_WITH_CONDITION votes into synthesis
                bft_conditions = debate_result.get("conditions", [])
                if bft_conditions:
                    full_grounding_context["BFT_CONDITIONS"] = bft_conditions
                    logger.info(f"[Queen] Synthesis must satisfy {len(bft_conditions)} condition(s) from BFT.")

                final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context, plan=plan)
                
        else:
            # Execute all nodes in parallel to reduce latency
            async def run_node(node):
                # Mark task active + broadcast
                for t in plan.tasks:
                    if t.assigned_node == node.name:
                        t.mark_active()
                        break
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
                try:
                    result = await node.process(query, context, channel=channel, plan=plan)
                    # Mark task complete + broadcast
                    for t in plan.tasks:
                        if t.assigned_node == node.name and t.status.value == "active":
                            t.mark_complete()
                            break
                    try:
                        from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                        await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                    except Exception:
                        pass
                    return node.name, result, None
                except Exception as e:
                    logger.error(f"[Queen] Node {node.name} failed: {e}")
                    for t in plan.tasks:
                        if t.assigned_node == node.name and t.status.value == "active":
                            t.mark_failed()
                            break
                    # NM1 fix: broadcast after mark_failed
                    try:
                        from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                        await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                    except Exception:
                        pass
                    return node.name, None, e

            tasks = [run_node(node) for node in active_nodes]
            results = await asyncio.gather(*tasks)

            shared_kb: Dict[str, Any] = {}

            for node_name, result_map, err in results:
                if err:
                    proposals[node_name] = f"Node Failed: {str(err)}"
                else:
                    proposals[node_name] = result_map["response"].content
                    for msg in result_map["history"]:
                        if msg.get("role") == "tool":
                            _tool_name = msg.get("name", "tool")
                            aggregated_context[f"{node_name}_{_tool_name}"] = msg.get("content")
                            # 5A: extract structured facts into shared KB
                            _key = f"{node_name}:{_tool_name}"
                            try:
                                _fact = json.loads(msg["content"])
                                shared_kb[_key] = _fact if isinstance(_fact, dict) else {"raw": str(_fact)[:300]}
                            except Exception:
                                shared_kb[_key] = {"raw": str(msg.get("content", ""))[:300]}

            if shared_kb:
                logger.info(f"[Queen] SharedKB populated with {len(shared_kb)} cross-agent findings.")

            full_grounding_context = {**(context or {}), **aggregated_context, "cross_agent_findings": shared_kb}
            final_advice = await self._synthesize_consensus(query, proposals, full_grounding_context, plan=plan)
        
        # ── P4: Broadcast live plan state to operator ──
        try:
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
        except Exception as _sse_err:
            logger.debug(f"[Queen] Plan update broadcast failed (non-fatal): {_sse_err}")

        # ── H4: Faithfulness check — answer must not contradict evidence ──
        if plan and len(plan.evidence) > 0:
            final_advice = await self._faithfulness_check(final_advice, plan)

        # ── H2: Claim decomposition — mark unsupported claims ──
        if plan and len(plan.evidence) > 0:
            final_advice = await self._verify_claims(final_advice, plan)

        # ── H6: Deterministic physics verifier — blocks on violation ──
        try:
            from agent_commercial.verifiers.physics import PhysicsVerifier
            pv = PhysicsVerifier()
            pv_result = pv.verify_advisory_text(final_advice)
            if not pv_result.passed:
                logger.warning(f"[Queen] Physics verifier FAILED: {pv_result.violations}")
                # Attempt regeneration with violations as constraints
                violations_text = "\n".join(f"- {v}" for v in pv_result.violations)
                regen_prompt = (
                    f"Your previous advisory contained physics violations:\n{violations_text}\n\n"
                    f"Original advisory:\n{final_advice}\n\n"
                    "Regenerate the advisory removing or correcting the implausible claims. "
                    "Do NOT include numbers that violate physics bounds. Output valid JSON only."
                )
                try:
                    regen_result = await self.llm.ask_json(
                        messages=[{"role": "user", "content": regen_prompt}],
                        system_msgs=[{"role": "system", "content": "You are ARVIS Queen. Fix physics violations. Output JSON advisory only."}],
                        channel="physics_regen",
                    )
                    regen_str = json.dumps(regen_result) if isinstance(regen_result, dict) else str(regen_result)
                    # Verify regeneration passes
                    regen_check = pv.verify_advisory_text(regen_str)
                    if regen_check.passed:
                        final_advice = self._enforce_read_only(regen_str)
                        logger.info("[Queen] Physics regeneration succeeded.")
                    else:
                        # Second fail → abstain
                        logger.error(f"[Queen] Physics regeneration still failed: {regen_check.violations}. Abstaining.")
                        final_advice = json.dumps({
                            "analysis": "Advisory contained physically implausible claims that could not be corrected.",
                            "advisories": [{
                                "id": "physics-block-1",
                                "type": "system_notice",
                                "severity": "medium",
                                "message": "ARVIS detected implausible physics in its analysis and cannot deliver a verified advisory. Please re-query or consult your FM engineer.",
                                "confidence": 0.2,
                                "evidence_ids": [],
                                "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                                "recommended_action": {"type": "retry"},
                                "counterfactual_check": False
                            }]
                        })
                except Exception as _regen_err:
                    logger.error(f"[Queen] Physics regeneration error: {_regen_err}. Abstaining.")
                    final_advice = json.dumps({
                        "analysis": "Physics verification failed and regeneration unavailable.",
                        "advisories": [{
                            "id": "physics-block-1",
                            "type": "system_notice",
                            "severity": "medium",
                            "message": "ARVIS cannot verify the physical plausibility of its analysis. Please retry or consult FM engineer.",
                            "confidence": 0.2,
                            "evidence_ids": [],
                            "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                            "recommended_action": {"type": "retry"},
                            "counterfactual_check": False
                        }]
                    })
        except Exception as _pv_err:
            logger.debug(f"[Queen] Physics verifier unavailable: {_pv_err}")

        # Surface structured tool calls for ChatResponse auditability
        _tool_calls = []
        _tool_results = []
        for key, content in aggregated_context.items():
            if key.startswith("_"):
                continue
            parts = key.split("_", 1)
            if len(parts) == 2:
                node_name, tool_name = parts
                _tool_calls.append({"tool": tool_name, "node": node_name})
                _tool_results.append({"tool": tool_name, "node": node_name, "content": str(content)[:500]})
        aggregated_context["_tool_calls"] = _tool_calls
        aggregated_context["_tool_results"] = _tool_results

        # Mark plan status based on task satisfaction
        from arvis_core.plan import PlanStatus
        if plan.budget.exhausted:
            plan.status = PlanStatus.BUDGET_EXHAUSTED
        elif plan.all_done:
            plan.status = PlanStatus.COMPLETE
        else:
            plan.status = PlanStatus.ABANDONED

        # ── T2: Archive completed investigation to episodic memory ────────
        _mo = getattr(self, "memory_orchestrator", None)
        if _mo is not None:
            try:
                await _mo.archive_investigation(plan)
                logger.debug(f"[Queen] Investigation {plan.id} archived to T2 episodic store")
            except Exception as _arc_err:
                logger.debug(f"[Queen] archive_investigation failed (non-fatal): {_arc_err}")

        return {
            "advice": final_advice,
            "context": aggregated_context,
            "plan": plan,
        }

    async def _synthesize_consensus(self, original_query: str, proposals: Dict[str, str], context: Optional[Dict[str, Any]], plan=None) -> str:
        """
        Synthesizes agent proposals into a high-fidelity consensus advisory.
        If plan with evidence ledger is available, uses it as sole factual source.
        """
        # M4.4: Run ML evidence through LLMInterpreter before synthesis
        # This converts raw ML numbers into grounded prose, preventing LLM from paraphrasing them incorrectly
        ml_interpretations_block = ""
        if plan and len(plan.evidence) > 0:
            _ml_ev = [e for e in plan.evidence.get_all() if not getattr(e, "is_ml_fallback", False) and getattr(e, "model_id", None)]
            if _ml_ev:
                _interp_lines = []
                try:
                    from agent_commercial.ml.llm_interpreter import MLInterpreter, InterpretationType
                    _interp = MLInterpreter()
                    _type_map = {
                        "fdd_autoencoder": InterpretationType.FAULT_DETECTION,
                        "energy_forecaster": InterpretationType.ENERGY_FORECAST,
                        "bayesian_network": InterpretationType.ROOT_CAUSE,
                        "building_embeddings": InterpretationType.FLEET_BENCHMARK,
                    }
                    for _ev in _ml_ev[:4]:  # cap at 4 to avoid prompt bloat
                        _itype = _type_map.get(_ev.model_id, InterpretationType.FAULT_DETECTION)
                        try:
                            _result = await _interp.interpret(_itype, _ev.raw_payload, use_llm=False)
                            if _result.explanation:
                                _interp_lines.append(f"  [{_ev.id}] {_ev.model_id}: {_result.explanation[:300]}")
                        except Exception:
                            pass
                except Exception as _ie:
                    logger.debug(f"[Queen] MLInterpreter skipped: {_ie}")
                if _interp_lines:
                    ml_interpretations_block = (
                        "\n\n--- ML INTERPRETATIONS (deterministic, cite verbatim) ---\n"
                        + "\n".join(_interp_lines)
                        + "\n--- END ML INTERPRETATIONS ---\n"
                    )

        # Build evidence ledger block if plan has evidence
        evidence_ledger_block = ""
        if plan and len(plan.evidence) > 0:
            evidence_ledger_block = (
                "\n\n--- EVIDENCE LEDGER (authoritative, from tool results) ---\n"
                + plan.evidence.to_synthesis_context()
                + "\n--- END EVIDENCE LEDGER ---\n"
            )

        system_prompt = (
            "You are the Queen Coordinator of the ARVIS Cognitive Swarm. "
            "Synthesize agent proposals into a unified ARVIS Advisory JSON.\n\n"
            "--- CRITICAL GUIDELINES ---\n"
            "1. CONFLICT RESOLUTION: Resolve domain contradictions by prioritizing Safety > Comfort > Energy.\n"
            "2. DATA INTEGRITY: ALL numbers (energy_kwh, cost_qar, percentages, scores) MUST be copied EXACTLY "
            "from the EVIDENCE LEDGER below. You may NOT perform arithmetic or invent numbers. "
            "If a number is not in the ledger, do NOT include it. "
            "If conflicting, use the more conservative (lower savings/higher cost) number.\n"
            "3. MARKER PRESERVATION: Carry forward specific strings like '[VIP_OVERRIDE_DETECTED]' or '[DOWNGRADE_REQUIRED]' into the 'message' field if they appear in any agent proposal.\n"
            "4. TYPE HYGIENE: The 'message' field MUST be a single string (narrative), NOT a list. "
            "The 'evidence_ids' field references evidence ledger entries by ID.\n"
            "5. CROSS-AGENT CORRELATION: If CROSS-AGENT TOOL FINDINGS are provided, use them to surface correlations "
            "that individual agents may have missed.\n"
            "6. READ-ONLY ENFORCEMENT (STRICT): ARVIS is an advisory-only system. Every 'message' and 'recommended_action' "
            "field MUST use advisory language only. FORBIDDEN verbs: 'submitted', 'corrected', 'updated', 'changed', "
            "'adjusted', 'turned off', 'restarted', 'applied', 'executed'. "
            "REQUIRED language: 'recommend', 'suggest', 'advise', 'please have the operator', 'the operator should'. "
            "ARVIS never claims to have performed any physical or BMS action.\n\n"
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
            "    \"evidence_ids\": [\"str: IDs from EVIDENCE LEDGER above\"],\n"
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

        # 5A: Surface cross-agent tool findings for synthesis
        cross_findings_text = ""
        cross_kb = (context or {}).get("cross_agent_findings", {})
        if cross_kb:
            lines = []
            for k, v in list(cross_kb.items())[:8]:  # cap at 8 to avoid prompt bloat
                lines.append(f"  [{k}]: {json.dumps(v, default=str)[:250]}")
            cross_findings_text = "\n\nCROSS-AGENT TOOL FINDINGS (raw observations from all agents):\n" + "\n".join(lines)

        # BFT conditions block: synthesis must address each condition
        bft_conditions_block = ""
        bft_conditions = (context or {}).get("BFT_CONDITIONS", [])
        if bft_conditions:
            conditions_list = "\n".join(f"  - {c}" for c in bft_conditions)
            bft_conditions_block = (
                f"\n\n--- BFT CONDITIONS (MANDATORY) ---\n"
                f"The following conditions were imposed by reviewing agents. "
                f"Your synthesis MUST address each one explicitly in the advisory message:\n"
                f"{conditions_list}\n"
                f"--- END BFT CONDITIONS ---\n"
            )

        user_message = (
            f"Original Query: {original_query}\n\n"
            f"Grounding Context (FACTS): {json.dumps(context, default=str)}\n\n"
            f"Agent Proposals:\n{proposals_text}"
            f"{cross_findings_text}"
            f"{evidence_ledger_block}"
            f"{ml_interpretations_block}"
            f"{bft_conditions_block}\n\n"
            "Please synthesize these into the final ARVIS Advisory JSON. "
            "CRITICAL: If 'GROUNDING_THERMAL_SAFETY' contains items, you MUST generate a high-priority advisory even if agent proposals are weak. "
            "IMPORTANT: ALL numbers in your output must come from the EVIDENCE LEDGER. Do NOT invent or compute numbers."
        )
        
        logger.info(f"[Queen] Synthesizing consensus across {len(proposals)} proposals...")
        logger.debug(f"[Queen] Grounding Context for synthesis: {json.dumps(context)[:1000]}...")
        
        try:
            response = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_message}],
                system_msgs=[{"role": "system", "content": system_prompt}],
                channel="synthesis",
            )
            result_str = json.dumps(response) if isinstance(response, dict) else str(response)

            # Deterministic read-only enforcement — code check, not prompt rule
            result_str = self._enforce_read_only(result_str)

            return result_str
        except Exception as e:
            logger.error(f"[Queen] Synthesis failed: {e}")
            fallback = {
                "analysis": "Advisory synthesis temporarily unavailable. Individual agent assessments were gathered but could not be consolidated.",
                "advisories": [{
                    "id": "fallback-1",
                    "type": "system_notice",
                    "severity": "low",
                    "message": (
                        "ARVIS has gathered observations from the swarm agents but the synthesis service is temporarily unavailable. "
                        "Please re-submit your query for a consolidated advisory, or consult your FM engineer for immediate guidance."
                    ),
                    "confidence": 0.5,
                    "evidence": [{"source": "Queen", "finding": f"Synthesis unavailable ({type(e).__name__})"}],
                    "impact": {"timeframe": "N/A", "energy_kwh": 0.0, "cost_qar": 0.0, "is_savings": False},
                    "recommended_action": {"type": "retry"},
                    "counterfactual_check": False
                }]
            }
            return json.dumps(fallback)

    # ── T1 lookup node picker ───────────────────────────────────────────────

    def _pick_lookup_node(self, query: str, active_nodes) -> "SwarmNode":
        """Return best-fit node for a T1 lookup query based on keyword heuristics."""
        q = query.lower()
        priority = [
            (["alarm", "alert", "fault", "trip"], "Alarm_Agent"),
            (["energy", "power", "kwh", "consumption", "demand"], "Energy_Agent"),
            (["maintenance", "service", "pm", "schedule", "work order"], "Maintenance_Agent"),
            (["temperature", "comfort", "humidity", "co2", "zone", "ahu", "vav"], "Comfort_Agent"),
        ]
        for keywords, preferred_name in priority:
            if any(kw in q for kw in keywords):
                for node in active_nodes:
                    if node.name == preferred_name:
                        return node
        return active_nodes[0]

    # ── Risk-tier classification ────────────────────────────────────────────

    async def _classify_risk_tier(self, query: str) -> int:
        """
        Classify query into risk tiers:
          T1 = lookup (status, value, list)
          T2 = diagnostic (fault analysis, trend, root cause, why)
          T3 = actionable (change, optimize, simulate, fix)
        Safety keywords force ≥T2 regardless of classifier output.
        """
        # Keyword floor: safety terms → at least T2
        has_safety = bool(_SAFETY_KEYWORDS_RE.search(query))

        tier_prompt = (
            "You are a risk-tier classifier for a BMS copilot.\n"
            "Classify the query into exactly one tier:\n"
            "  T1: Simple lookup — current value, status check, list items, history recall\n"
            "  T2: Diagnostic — fault analysis, trend investigation, root cause, causal reasoning, 'why' questions\n"
            "  T3: Actionable — change settings, optimize, simulate impact, fix a problem, recommend physical action\n"
            "Return ONLY: {\"tier\": 1} or {\"tier\": 2} or {\"tier\": 3}"
        )
        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": query}],
                system_msgs=[{"role": "system", "content": tier_prompt}],
                channel="classify",
            )
            tier = int(result.get("tier", 2))
            tier = max(1, min(3, tier))
        except Exception:
            tier = 2  # safe default: full validation

        # Safety floor: never let safety-related queries go T1
        if has_safety and tier < 2:
            logger.info(f"[Queen] Safety keyword floor: T{tier} → T2")
            tier = 2

        return tier

    # ── Task lifecycle helper (NM2/NM3/NM4) ────────────────────────────────

    async def _run_with_task_lifecycle(
        self, node: SwarmNode, plan, query: str, context: Optional[Dict[str, Any]], channel: str
    ) -> Dict[str, Any]:
        """Mark task active → run node.process → mark complete/failed. Broadcasts on transitions."""
        task = None
        for t in plan.tasks:
            if t.assigned_node == node.name and t.status.value == "pending":
                task = t
                break

        if task:
            task.mark_active()
            try:
                from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
            except Exception:
                pass

        try:
            result = await node.process(query, context, channel=channel, plan=plan)
            if task:
                task.mark_complete()
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error(f"[Queen] Node {node.name} failed in lifecycle wrapper: {e}")
            if task:
                task.mark_failed()
                try:
                    from agent_commercial.api.sse_broadcaster import SSEBroadcaster
                    await SSEBroadcaster().broadcast_plan_update(plan, channel=channel)
                except Exception:
                    pass
            raise

    # ── Read-only enforcement (deterministic, not prompt-based) ───────────

    def _enforce_read_only(self, synthesis_text: str) -> str:
        """Scan synthesis output for action-claiming language. Replace violations."""
        violations = _ACTION_VERBS_RE.findall(synthesis_text)
        if not violations:
            return synthesis_text
        logger.warning(
            f"[Queen] READ-ONLY VIOLATION: found action verbs {violations} in synthesis. Sanitizing."
        )
        sanitized = synthesis_text
        for verb in violations:
            verb_lower = verb.lower().strip()
            replacement = _VERB_REPLACEMENTS.get(verb_lower, f"recommend {verb_lower}")
            sanitized = re.sub(
                r"\b" + re.escape(verb) + r"\b",
                replacement,
                sanitized,
                count=1,
                flags=re.IGNORECASE,
            )
        return sanitized

    async def _faithfulness_check(self, advice: str, plan) -> str:
        """
        Post-synthesis faithfulness verification.
        Checks if the answer contradicts any observation in the evidence ledger.
        If contradiction found → regenerate with explicit correction.
        """
        if not plan or len(plan.evidence) == 0:
            return advice

        evidence_summary = plan.evidence.to_synthesis_context()

        prompt = (
            "You are a strict Faithfulness Verifier for a BMS advisory system.\n"
            "Compare the ADVISORY against the EVIDENCE LEDGER below.\n"
            "A contradiction means the advisory asserts something opposite to what the evidence shows "
            "(e.g., 'equipment is healthy' when evidence shows degradation, or 'temperature is normal' "
            "when evidence shows a breach).\n\n"
            "IMPORTANT: Output ONLY a valid JSON object:\n"
            "{\n"
            "  \"faithful\": true/false,\n"
            "  \"contradictions\": [\"description of contradiction 1\", ...]\n"
            "}\n"
            "If no contradictions found, set faithful=true and contradictions=[]."
        )

        user_msg = (
            f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
            f"ADVISORY:\n{advice}\n\n"
            "Check faithfulness."
        )

        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": prompt}],
                channel="faithfulness",
            )

            if isinstance(result, list) and len(result) > 0:
                result = result[0]

            is_faithful = result.get("faithful", True) if isinstance(result, dict) else True
            contradictions = result.get("contradictions", []) if isinstance(result, dict) else []

            if is_faithful or not contradictions:
                logger.info("[Queen] Faithfulness check PASSED.")
                return advice

            logger.warning(f"[Queen] Faithfulness check FAILED: {len(contradictions)} contradiction(s): {contradictions}")

            # Attempt one regeneration with explicit correction instructions
            correction_prompt = (
                "The following advisory was found to CONTRADICT live observations:\n\n"
                f"CONTRADICTIONS:\n" + "\n".join(f"  - {c}" for c in contradictions) + "\n\n"
                f"ORIGINAL ADVISORY:\n{advice}\n\n"
                f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
                "Rewrite the advisory to be FAITHFUL to the evidence. "
                "Remove or correct contradicted claims. Output ONLY the corrected JSON advisory."
            )

            corrected = await self.llm.ask_json(
                messages=[{"role": "user", "content": correction_prompt}],
                system_msgs=[{"role": "system", "content": "You are ARVIS Queen Coordinator. Fix contradictions in the advisory to match evidence. Output valid JSON only."}],
                channel="faithfulness_correction",
            )

            corrected_str = json.dumps(corrected) if isinstance(corrected, dict) else str(corrected)
            corrected_str = self._enforce_read_only(corrected_str)
            logger.info("[Queen] Faithfulness correction applied.")
            return corrected_str

        except Exception as e:
            logger.error(f"[Queen] Faithfulness check failed with error: {e}. Passing original.")
            return advice

    async def _verify_claims(self, advice: str, plan) -> str:
        """
        H2: Decompose advisory into atomic claims, verify each against evidence ledger.
        Unsupported claims get marked [unverified]. Contradicted claims get stripped.
        M3.4: Numbers outside ML confidence_bounds are flagged before LLM pass.
        """
        if not plan or len(plan.evidence) == 0:
            return advice

        # M3.4: Deterministic CI bounds pre-check — faster than LLM, no cost
        import re as _re
        ci_violations = []
        for _ev in plan.evidence.get_all():
            bounds = getattr(_ev, "confidence_bounds", None)
            if not bounds:
                continue
            lo = bounds.get("lower")
            hi = bounds.get("upper")
            if lo is None or hi is None:
                continue
            # Extract all numbers from advice and check if any fall outside bounds for this model
            for _m in _re.findall(r'\b(\d+(?:\.\d+)?)\b', advice):
                try:
                    num = float(_m)
                    # Only check numbers in the plausible ML output range (avoid flagging years, counts, etc.)
                    if 0.0 < num < 1000.0 and (num < lo or num > hi):
                        model_id = getattr(_ev, "model_id", _ev.source_tool)
                        ci_violations.append(
                            f"Value {num} from advisory is outside {model_id} confidence bounds [{lo:.2f}, {hi:.2f}]"
                        )
                except ValueError:
                    pass
        if ci_violations:
            logger.warning(f"[Queen] M3.4 CI bounds violations: {ci_violations}")

        evidence_summary = plan.evidence.to_synthesis_context()

        prompt = (
            "You are a Claim Verifier. Decompose the ADVISORY into atomic factual claims "
            "(numbers, equipment states, predictions, severities).\n"
            "For each claim, check if it is SUPPORTED, UNSUPPORTED, or CONTRADICTED by the evidence.\n\n"
            "Output ONLY valid JSON:\n"
            "{\n"
            "  \"claims\": [\n"
            "    {\"claim\": \"text of claim\", \"status\": \"supported|unsupported|contradicted\", \"evidence_id\": \"id or null\"}\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- SUPPORTED: claim's number/state appears in evidence\n"
            "- UNSUPPORTED: claim makes a factual assertion not present in evidence\n"
            "- CONTRADICTED: evidence shows opposite of claim\n"
            "- Ignore meta-statements, recommendations, and advisory language — only verify factual assertions"
        )

        ci_block = ""
        if ci_violations:
            ci_block = "\n\nCI BOUNDS VIOLATIONS (deterministic pre-check):\n" + "\n".join(f"  - {v}" for v in ci_violations) + "\nTreat these numbers as UNSUPPORTED.\n"

        user_msg = (
            f"EVIDENCE LEDGER:\n{evidence_summary}{ci_block}\n\n"
            f"ADVISORY:\n{advice}\n\n"
            "Decompose and verify."
        )

        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": prompt}],
                channel="claim_verify",
            )

            if isinstance(result, list) and len(result) > 0:
                result = result[0]
            if not isinstance(result, dict):
                return advice

            claims = result.get("claims", [])
            if not claims:
                return advice

            unsupported = [c for c in claims if c.get("status") == "unsupported"]
            contradicted = [c for c in claims if c.get("status") == "contradicted"]

            if not unsupported and not contradicted:
                logger.info(f"[Queen] Claim verification PASSED: all {len(claims)} claims supported.")
                return advice

            logger.warning(
                f"[Queen] Claim verification: {len(unsupported)} unsupported, "
                f"{len(contradicted)} contradicted out of {len(claims)} claims."
            )

            # Regenerate with explicit instructions to remove bad claims
            contradicted_list = "\n".join(f"  - CONTRADICTED: {c.get('claim', '')}" for c in contradicted)
            unsupported_list = "\n".join(f"  - UNSUPPORTED: {c.get('claim', '')}" for c in unsupported)

            correction_prompt = (
                f"The following claims in your advisory have verification issues:\n"
                f"{contradicted_list}\n{unsupported_list}\n\n"
                f"ORIGINAL ADVISORY:\n{advice}\n\n"
                f"EVIDENCE LEDGER:\n{evidence_summary}\n\n"
                "Rules:\n"
                "- REMOVE all CONTRADICTED claims entirely.\n"
                "- Mark UNSUPPORTED claims with '[unverified]' prefix in the message text.\n"
                "- Keep all SUPPORTED claims unchanged.\n"
                "- Output ONLY the corrected JSON advisory."
            )

            corrected = await self.llm.ask_json(
                messages=[{"role": "user", "content": correction_prompt}],
                system_msgs=[{"role": "system", "content": "You are ARVIS Queen. Remove contradicted claims, mark unsupported. Output valid JSON only."}],
                channel="claim_correction",
            )

            corrected_str = json.dumps(corrected) if isinstance(corrected, dict) else str(corrected)
            corrected_str = self._enforce_read_only(corrected_str)
            logger.info("[Queen] Claim verification correction applied.")
            return corrected_str

        except Exception as e:
            logger.error(f"[Queen] Claim verification failed: {e}. Passing original.")
            return advice

    async def _self_consistency_check(
        self, proposer, prompt: str, first_draft: str, context, channel: str, plan
    ) -> str:
        """
        H8: Sample a second independent draft from the same proposer.
        If the two drafts diverge significantly, escalate to BFT (caller handles).
        Returns the first draft if consistent, or flags divergence.
        """
        _N_SAMPLES = 1  # one additional sample (total 2 drafts compared)

        try:
            second_result = await proposer.process(prompt, context, channel=channel, plan=plan)
            second_draft = second_result["response"].content

            # Use LLM to assess consistency between the two drafts
            consistency_prompt = (
                "Compare these two advisory proposals for the SAME query.\n"
                "Do they agree on: (1) the diagnosis/root cause, (2) the recommended action, "
                "(3) the severity assessment?\n\n"
                "Output ONLY JSON: {\"consistent\": true/false, \"divergence\": \"description if inconsistent\"}"
            )
            user_msg = (
                f"DRAFT 1:\n{first_draft[:1500]}\n\n"
                f"DRAFT 2:\n{second_draft[:1500]}\n\n"
                "Are these consistent?"
            )

            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": user_msg}],
                system_msgs=[{"role": "system", "content": consistency_prompt}],
                channel="self_consistency",
            )

            if isinstance(result, list) and result:
                result = result[0]

            is_consistent = result.get("consistent", True) if isinstance(result, dict) else True

            if is_consistent:
                logger.info("[Queen] H8 Self-consistency check PASSED.")
                return first_draft
            else:
                divergence = result.get("divergence", "unknown") if isinstance(result, dict) else "unknown"
                logger.warning(f"[Queen] H8 Self-consistency DIVERGED: {divergence}")
                # Flag the divergence — BFT will still run and provide additional review
                return (
                    first_draft + "\n\n"
                    "[SELF-CONSISTENCY WARNING] Independent re-analysis produced divergent conclusions. "
                    f"Divergence: {divergence}. BFT peer review is mandatory for this advisory."
                )

        except Exception as e:
            logger.error(f"[Queen] Self-consistency check error: {e}. Using first draft.")
            return first_draft
