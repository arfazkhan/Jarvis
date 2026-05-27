"""
Byzantine Fault-Tolerant (BFT) Consensus Engine for ARVIS Swarm.
Enforces peer review on any operational proposal before surfacing it to the user.
"""
import logging
import re
import asyncio
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent_unified.llm import UnifiedLLM
from arvis_core.swarm.node import SwarmNode

logger = logging.getLogger("arvis.swarm.consensus")


class VoteVerdict(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITION = "APPROVE_WITH_CONDITION"
    VETO = "VETO"
    ABSTAIN = "ABSTAIN"


class VoteResult(BaseModel):
    agent_name: str
    vote: str  # VoteVerdict value
    confidence: float = 0.5
    conditions: List[str] = Field(default_factory=list)
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
    def __init__(self, db=None):
        self.llm = UnifiedLLM()
        self._db = db
        
    async def run_debate(self, round_data: VotingRound, quorum: List[SwarmNode], channel: str = "chat", plan=None) -> Dict[str, Any]:
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
                f"You MUST vet this proposal strictly within your operational domain (e.g. thermal comfort, equipment safety, energy).\n"
                f"Use your tools to simulate or check if this proposal violates any constraints.\n\n"
                f"VOTE OPTIONS:\n"
                f"- APPROVE: Proposal is safe and correct within your domain.\n"
                f"- APPROVE_WITH_CONDITION: Acceptable IF specific conditions are met. List each condition.\n"
                f"- VETO: Proposal violates safety, comfort, or operational constraints.\n\n"
                f"Output your final judgment in strict JSON:\n"
                f"{{\n"
                f"  \"vote\": \"APPROVE\" | \"APPROVE_WITH_CONDITION\" | \"VETO\",\n"
                f"  \"confidence\": 0.0-1.0,\n"
                f"  \"conditions\": [\"condition 1\", ...],\n"
                f"  \"reasoning\": \"Detailed technical reason\"\n"
                f"}}"
            )
            
            try:
                result_map = await node.process(query=prompt, context=round_data.context, channel=channel, plan=plan)
                raw_response = result_map["response"].content
                
                # Find JSON payload
                import json
                content = raw_response
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                content = content.strip()
                # strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
                if not content:
                    raise ValueError("Empty vote response from agent")

                # Fast-fail on Bedrock transient error strings before attempting JSON parse.
                # These are not valid JSON and will always fail; raising here lets the
                # except block handle them cleanly with the VETO-safe default.
                if content.startswith("Bedrock Error") or "Read timeout" in content:
                    raise ValueError(f"Bedrock transient error in vote response: {content[:120]}")

                # First try direct JSON parse, then fall back to greedy brace extraction
                # (matches what ask_json does in llm.py — handles prose-wrapped JSON blobs).
                try:
                    vote_data = json.loads(content)
                except json.JSONDecodeError:
                    match = re.search(r'\{.*\}', content, re.DOTALL)
                    if match:
                        vote_data = json.loads(match.group())
                    else:
                        raise
                vote = vote_data.get("vote", "VETO").upper()
                confidence = float(vote_data.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                conditions = vote_data.get("conditions", [])
                if not isinstance(conditions, list):
                    conditions = [str(conditions)] if conditions else []
                reasoning = vote_data.get("reasoning", "Failed to parse reasoning")

                # Normalize vote to valid verdict
                if vote not in {v.value for v in VoteVerdict}:
                    vote = VoteVerdict.VETO.value

                reviewer_context = {}
                for msg in result_map["history"]:
                    if msg.get("role") == "tool":
                        reviewer_context[msg.get("name")] = msg.get("content")

                return VoteResult(
                    agent_name=node.name,
                    vote=vote,
                    confidence=confidence,
                    conditions=conditions,
                    reasoning=reasoning,
                    tool_observations=reviewer_context
                )
            except Exception as e:
                # Transient failures should not poison quorum with a VETO
                _is_transient = any(s in str(e) for s in (
                    "Empty vote", "Bedrock", "ValidationException",
                    "JSONDecodeError", "Read timeout", "ThrottlingException",
                ))
                _verdict = "ABSTAIN" if _is_transient else "VETO"
                logger.error(
                    f"[Consensus] Failed to parse vote from {node.name}: {e}. "
                    f"Defaulting to {_verdict} ({'transient' if _is_transient else 'safety'})."
                )
                if self._db:
                    try:
                        await self._db.save_bft_abstention(
                            round_id=f"r_{id(round_data):x}",
                            plan_id=plan.id if plan else "",
                            agent_name=node.name,
                            reason=f"parse_error ({_verdict}): {e}",
                        )
                    except Exception:
                        pass
                return VoteResult(
                    agent_name=node.name,
                    vote=_verdict,
                    reasoning=f"Agent exception/Parse error: {e}",
                    tool_observations={}
                )

        BFT_TIMEOUT_S = 15.0
        tasks = {asyncio.ensure_future(run_vote(node)): node for node in quorum}
        done, pending = await asyncio.wait(tasks.keys(), timeout=BFT_TIMEOUT_S)

        for task in done:
            res = task.result()
            if res:
                votes.append(res)

        if pending:
            timed_out_names = [tasks[t].name for t in pending]
            logger.warning(f"[Consensus] BFT timeout ({BFT_TIMEOUT_S}s) — {len(pending)} agent(s) timed out: {timed_out_names}")
            for t in pending:
                t.cancel()
                node = tasks[t]
                votes.append(VoteResult(
                    agent_name=node.name,
                    vote=VoteVerdict.ABSTAIN.value,
                    reasoning=f"Timed out after {BFT_TIMEOUT_S}s",
                    tool_observations={},
                ))

        if self._db and votes:
            round_id = f"r_{id(round_data):x}"
            for v in votes:
                try:
                    await self._db.save_bft_vote(
                        round_id=round_id,
                        plan_id=plan.id if plan else "",
                        agent_name=v.agent_name,
                        vote=v.vote,
                        confidence=v.confidence,
                        conditions=v.conditions,
                        reasoning=v.reasoning,
                        proposal=round_data.proposal[:500],
                        proposer_name=round_data.proposer_name,
                    )
                except Exception as e:
                    logger.debug(f"[Consensus] Failed to persist vote: {e}")

        # Exclude ABSTAIN votes from quorum (transient failures, not reasoned vetoes)
        participating = [v for v in votes if v.vote != VoteVerdict.ABSTAIN.value]
        abstained = [v for v in votes if v.vote == VoteVerdict.ABSTAIN.value]
        if abstained:
            logger.info(f"[Consensus] {len(abstained)} agent(s) abstained (transient failure): {[a.agent_name for a in abstained]}")

        vetoes = [v for v in participating if v.vote == VoteVerdict.VETO.value]
        conditional = [v for v in participating if v.vote == VoteVerdict.APPROVE_WITH_CONDITION.value]
        approvals = [v for v in participating if v.vote == VoteVerdict.APPROVE.value]

        # Collect all conditions that must be satisfied
        all_conditions: List[str] = []
        for v in conditional:
            all_conditions.extend(v.conditions)

        if vetoes:
            logger.warning(f"[Consensus] Proposal VETOED by {len(vetoes)} nodes!")
            status = "REJECTED"
        elif conditional:
            logger.info(
                f"[Consensus] Proposal CONDITIONALLY APPROVED. "
                f"{len(conditional)} node(s) imposed {len(all_conditions)} condition(s)."
            )
            status = "APPROVED_WITH_CONDITIONS"
        elif approvals:
            logger.info(f"[Consensus] Proposal unanimously APPROVED by quorum.")
            status = "APPROVED"
        else:
            # Fix 2: No affirmative votes — all peers abstained/timed out.
            # Refuse to silently APPROVE; downgrade to advisory for Queen post-process.
            logger.warning("[Consensus] No affirmative votes — downgrading to advisory tier")
            status = "DOWNGRADED_TO_ADVISORY"

        # Weighted confidence: average across all votes
        avg_confidence = (
            sum(v.confidence for v in votes) / len(votes) if votes else 0.0
        )

        return {
            "status": status,
            "votes": [v.model_dump() for v in votes],
            "conditions": all_conditions,
            "avg_confidence": round(avg_confidence, 3),
            "original_proposal": round_data.proposal
        }
