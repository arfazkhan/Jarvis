"""
Base Agent Node for the ARVIS Swarm.
Represents a single, specialized agent (e.g., Energy Agent, Safety Agent)
that focuses on a specific domain using specific tools.
"""

import hashlib
import json
import logging
from typing import Dict, Any, List, Optional, Set
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
    llm_channel: str = Field(default="swarm", description="Bedrock channel key for this node's tool-call loop.")

    tool_handler: Any = Field(default=None, exclude=True)
    llm: Any = Field(default=None, exclude=True)
    shared_kb: Any = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.llm:
            self.llm = UnifiedLLM()

    async def process(self, query: str, context: Optional[Dict[str, Any]] = None, history: Optional[List[Dict]] = None, channel: str = "chat", plan=None, tool_choice: str = "auto") -> Dict[str, Any]:
        """
        Processes a query within the agent's specific domain using a ReAct loop.
        Returns a dict with 'response' (Message) and 'history' (evidence list).

        If plan (InvestigationPlan) is provided, the node:
          - Injects plan state into prompt context
          - Records Evidence for each tool result into plan.evidence
          - Writes Span entries to plan.audit_trail
          - Checks plan.budget before each tool call
        """
        logger.info(f"[Node: {self.name}] Processing query: {query[:50]}...")

        system_msgs = [{"role": "system", "content": self.role}]

        # Load distilled rules from DB for this agent (learned constraints).
        # CRITICAL: bounded by 3s timeout to prevent WAL-lock starvation during
        # live emulator runs. The live emulator's background _persist_point_to_db
        # tasks can hold WAL pages long enough that a fresh read blocks past
        # busy_timeout (60s) with retries, hanging the node for 4+ minutes.
        # If we can't get rules in 3s, proceed without them — degraded behavior
        # is "no learned constraints injected", not a crash.
        #
        # System_Capability_Agent has zero tools and only serves capability/
        # boundary responses — skip DB entirely. Saves ~50-200ms on every
        # write_attempt turn and avoids the lock-contention hazard entirely.
        if self.name == "System_Capability_Agent":
            pass  # boundary node has no use for distilled rules
        else:
            try:
                from agent_commercial.database import get_database as _get_db
                import asyncio as _asyncio
                _db = _get_db()
                _rules = await _asyncio.wait_for(
                    _db.get_distilled_rules(self.name),
                    timeout=3.0,
                )
                if _rules:
                    _rule_block = "\n".join(
                        f"  LEARNED CONSTRAINT: {r['rule_text']}"
                        for r in _rules
                    )
                    system_msgs.append({
                        "role": "system",
                        "content": f"DISTILLED RULES (from past experience):\n{_rule_block}",
                    })
            except _asyncio.TimeoutError:
                logger.warning(f"[Node: {self.name}] distilled_rules query timed out (>3s); "
                               f"proceeding without learned constraints")
            except Exception:
                pass  # DB unavailable — degrade gracefully

        # Inject plan state so model sees externalized checklist
        if plan is not None:
            system_msgs.append({
                "role": "system",
                "content": plan.to_prompt_context(),
            })

        # Inject auto-recall context from MemoryOrchestrator (T2+T3+T5+T6)
        _recall_block = (context or {}).get("RECALL_CONTEXT", "") if context else ""
        if _recall_block:
            system_msgs.append({"role": "system", "content": _recall_block})

        if context:
            # Exclude RECALL_CONTEXT from the raw JSON dump to avoid duplication
            _ctx_for_dump = {k: v for k, v in context.items() if k != "RECALL_CONTEXT"}
            # Fix 16: Briefing_Agent isolation — exclude LIVE_BMS_SNAPSHOT, chat history,
            # and cross-agent findings so the briefing reflects only its own tool results.
            if self.name == "Briefing_Agent":
                for _excl in ("LIVE_BMS_SNAPSHOT", "chat_history", "cross_agent_findings"):
                    _ctx_for_dump.pop(_excl, None)
            if _ctx_for_dump:
                system_msgs.append({
                    "role": "system",
                    "content": f"Global Context:\n{json.dumps(_ctx_for_dump, default=str)}"
                })
            if context.get("SYSTEM_CONTRACT"):
                system_msgs.append({
                    "role": "system",
                    "content": (
                        "SYSTEM CONTRACT: ARVIS is read-only advisory software. "
                        "It has no BMS/Desigo write access and no control authority. "
                        "For direct write/control requests, answer this boundary clearly and do not simulate, execute, "
                        "or imply that ARVIS attempted the write."
                    ),
                })

        messages = list(history) if history else []
        messages.append({"role": "user", "content": query})

        # Dynamic ceiling based on query complexity (risk_tier passed via context)
        _rt = (context or {}).get("_risk_tier", 3)
        HARD_CEILING = {1: 2, 2: 6}.get(_rt, 8)
        STAGNATION_LIMIT = 3  # consecutive error/spin turns → force synthesis

        tools_def = []
        if self.tools and self.tool_handler:
            tools_def = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in self.tools
            ]

        # ── LLM plans depth once upfront (cheap single call → Nova Micro) ──────
        if (context or {}).get("SYSTEM_CONTRACT") and not (context or {}).get("REQUIRES_LIVE_DATA"):
            planned_turns = 1
            logger.info(f"[Node: {self.name}] System-contract query: using 1-turn plan")
        else:
            planned_turns = await self._llm_plan_depth(query)

        # Context-driven depth cap (e.g., Memory_Agent capped to 2 for T1/T2)
        _node_max = (context or {}).get(f"_max_turns_{self.name}")
        if _node_max and planned_turns > _node_max:
            logger.info(f"[Node: {self.name}] Depth capped: {planned_turns} → {_node_max} (context override)")
            planned_turns = _node_max
        logger.info(f"[Node: {self.name}] LLM planned depth: {planned_turns} turns (ceiling={HARD_CEILING})")

        # Pre-import plan types (avoid repeated import in hot loop)
        if plan is not None:
            from arvis_core.evidence import Evidence
            from arvis_core.plan import Span, TaskStatus

        seen_call_sigs: Set[str] = set()  # spin detection: (tool:args_hash)
        consecutive_errors: int = 0
        consecutive_empty: int = 0        # early exit when retrieval tools return no data
        nudged: bool = False              # soft-nudge sent at most once
        turn: int = 0

        while turn < HARD_CEILING:
            try:
                if tools_def:
                    response = await self.llm.ask_tool(
                        messages=messages,
                        system_msgs=system_msgs,
                        tools=tools_def,
                        tool_choice=tool_choice,
                        channel=self.llm_channel,
                    )
                else:
                    response = await self.llm.ask(
                        messages=messages,
                        system_msgs=system_msgs,
                        channel=self.llm_channel,
                    )

                if plan is not None and response.usage:
                    plan.budget.record_llm_call(
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        cost_usd=response.usage.cost_usd,
                    )

                # Natural exit — LLM decided it has enough
                if not response.tool_calls:
                    # A7: Adequacy check — if plan coverage is low, allow one extra round
                    if (
                        plan is not None
                        and not (context or {}).get("SKIP_ADEQUACY_RETRY")
                        and plan.coverage < 0.5
                        and plan.check_budget()
                        and turn < HARD_CEILING - 1
                        and not getattr(self, "_adequacy_retry_done", False)
                    ):
                        self._adequacy_retry_done = True
                        uncovered = [t for t in plan.tasks if not t.has_evidence and t.status != TaskStatus.SKIPPED]
                        if uncovered:
                            logger.info(
                                f"[Node: {self.name}] Adequacy check: coverage={plan.coverage:.0%}, "
                                f"{len(uncovered)} tasks lack evidence. Injecting extra round."
                            )
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"ADEQUACY CHECK: {len(uncovered)} investigation tasks still lack evidence: "
                                    + ", ".join(t.goal[:60] for t in uncovered[:3])
                                    + ". Please make ONE more targeted tool call to address the gap, then synthesize."
                                ),
                            })
                            turn += 1
                            continue

                    logger.info(f"[Node: {self.name}] Natural exit after {turn} turns (planned={planned_turns}).")
                    return {"response": response, "history": messages}

                # Filter invalid tool calls (empty name/id from some models)
                valid_tool_calls = [
                    tc for tc in response.tool_calls
                    if getattr(tc.function, "name", "") and getattr(tc, "id", "")
                ]
                if len(valid_tool_calls) < len(response.tool_calls):
                    logger.warning(
                        f"[Node: {self.name}] Filtered {len(response.tool_calls) - len(valid_tool_calls)} "
                        f"invalid tool call(s) with empty name/id"
                    )

                # Store only valid tool_calls in history to avoid Bedrock validation errors
                _raw = response.model_dump().get("tool_calls", [])
                _valid_ids = {tc.id for tc in valid_tool_calls}
                _filtered_tc = [tc for tc in (_raw or []) if tc.get("id") in _valid_ids]

                messages.append({
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": _filtered_tc or None,
                })

                made_progress_this_turn = False

                if not valid_tool_calls:
                    logger.info(f"[Node: {self.name}] No valid tool calls — treating as natural exit after {turn} turns.")
                    return {"response": response, "history": messages}

                for tool_call in valid_tool_calls:
                    tool_name = tool_call.function.name
                    args_str = tool_call.function.arguments
                    logger.info(f"[Node: {self.name}] Turn {turn}/{planned_turns}: calling {tool_name}")

                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                    except Exception:
                        args = {}

                    # ── Spin detection (local + cross-node via plan) ─────────
                    args_hash = hashlib.md5(
                        json.dumps(args, sort_keys=True, default=str).encode()
                    ).hexdigest()[:8]
                    call_sig = f"{tool_name}:{args_hash}"

                    # Cross-node dedup: another node already ran this exact call
                    if plan is not None and plan.is_duplicate_call(call_sig) and call_sig not in seen_call_sigs:
                        logger.info(f"[Node: {self.name}] Cross-node dedup: '{tool_name}' already executed by another node.")
                        cached_evidence = plan.evidence.get_by_call_sig(call_sig)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": (
                                f"CROSS-NODE DEDUP: Another agent already called {tool_name} with same args. "
                                f"Result available in evidence ledger"
                                f"{': ' + str(cached_evidence.raw_payload)[:500] if cached_evidence else '. Use existing findings.'}."
                            ),
                        })
                        seen_call_sigs.add(call_sig)
                        continue

                    if call_sig in seen_call_sigs:
                        logger.warning(f"[Node: {self.name}] Spin on '{tool_name}' — injecting redirect.")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": (
                                "SPIN DETECTED: You already called this tool with identical arguments. "
                                "Do not repeat it. Either synthesize from what you have, "
                                "or use a different tool with different parameters."
                            ),
                        })
                        consecutive_errors += 1
                        continue
                    seen_call_sigs.add(call_sig)
                    if plan is not None:
                        plan.register_call(call_sig)

                    # ── Fix 15: Pre-dispatch shared KB hit check ────────────
                    _shared_kb = getattr(self, "shared_kb", None)
                    if isinstance(_shared_kb, dict):
                        _kb_key = f"{tool_name}:{args_hash}"
                        if _kb_key in _shared_kb:
                            logger.info(f"[Node: {self.name}] Pre-dispatch KB hit on '{tool_name}'")
                            _cached_kb = _shared_kb[_kb_key]
                            _kb_content = json.dumps(_cached_kb, default=str) if isinstance(_cached_kb, dict) else str(_cached_kb)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": f"[SHARED_KB_HIT] {_kb_content}",
                            })
                            made_progress_this_turn = True
                            consecutive_errors = 0
                            continue

                    # ── Budget check (if plan provided) ─────────────────────
                    if plan is not None and not plan.check_budget():
                        logger.warning(f"[Node: {self.name}] Budget exhausted — forcing synthesis.")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": "BUDGET EXHAUSTED: Cannot execute more tools. Synthesize from evidence collected so far.",
                        })
                        break

                    # ── Execute tool ──────────────────────────────────────────
                    import time as _time
                    _t0 = _time.perf_counter()
                    try:
                        # B2 fix: resolve task_id for this node before execute()
                        _task_id = ""
                        if plan is not None:
                            _task = None
                            for _t in plan.tasks:
                                if _t.assigned_node == self.name and _t.status.value == "active":
                                    _task = _t
                                    break
                            if _task is None:
                                _task = plan.current_active_task() or plan.next_pending_task()
                            _task_id = _task.id if _task else ""

                        # T1.3: Cross-node cache check — skip expensive calls already done
                        _cached = plan.get_cached_tool_result(call_sig) if plan is not None else None
                        if _cached is not None:
                            result = _cached
                            tool_content = "[CACHED] " + json.dumps(_cached, default=str)
                            made_progress_this_turn = True
                            consecutive_errors = 0
                        elif self.tool_handler:
                            # T1.1+T1.2: pass plan context so evidence is written at tool boundary
                            result = await self.tool_handler.execute(
                                tool_name, args, plan=plan, task_id=_task_id, node_name=self.name
                            )
                            # T1.3: Cache successful results for cross-node reuse
                            if plan is not None and isinstance(result, dict) and not result.get("error") and not result.get("fallback"):
                                plan.cache_tool_result(call_sig, result)
                        else:
                            result = "Error: Tool handler not configured for this node."

                        # Attach call_sig to already-created evidence entry
                        if plan is not None and isinstance(result, dict) and not result.get("error"):
                            _ev_list = plan.evidence.get_all()
                            if _ev_list and getattr(_ev_list[-1], "source_tool", None) == tool_name:
                                _ev_list[-1].call_sig = call_sig

                        if _cached is None:
                            # Serialize result to LLM message (cache hits already have tool_content set)
                            if isinstance(result, dict) and result.get("fallback"):
                                tool_content = "[ML UNAVAILABLE — DO NOT CITE VALUES FROM THIS RESULT]\n" + json.dumps(result, default=str)
                            elif isinstance(result, dict) and result.get("error"):
                                err = result["error"]
                                if isinstance(err, dict):
                                    err_type = err.get("type", "EXECUTION_ERROR")
                                    err_msg = err.get("message", str(err))
                                    hint = err.get("recovery_hint", "")
                                else:
                                    err_type = "EXECUTION_ERROR"
                                    err_msg = str(err)
                                    hint = ""
                                tool_content = (
                                    f"[TOOL_ERROR:{err_type}] {err_msg}\n"
                                    f"RECOVERY: {hint}\n"
                                    f"FULL: {json.dumps(result, default=str)}"
                                )
                            else:
                                tool_content = json.dumps(result, default=str) if isinstance(result, dict) else str(result)
                        made_progress_this_turn = True
                        consecutive_errors = 0
                    except Exception as e:
                        tool_content = f"Error executing tool {tool_name}: {str(e)}"
                        result = {"error": str(e)}
                        consecutive_errors += 1

                    # ── Empty retrieval detection (prevent Memory_Agent spin) ─────
                    if isinstance(result, dict) and not result.get("error"):
                        _is_retrieval_empty = (
                            result.get("skills") == []
                            or result.get("similar_skills") == []
                            or (result.get("count") == 0 and "alarms" not in result)
                            or result.get("matches") == 0
                            or result.get("results") == []
                        )
                        if _is_retrieval_empty:
                            consecutive_empty += 1
                            if consecutive_empty >= 2:
                                logger.info(f"[Node: {self.name}] Early exit: {consecutive_empty} consecutive empty retrieval results.")
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_name,
                                    "content": tool_content,
                                })
                                break
                        else:
                            consecutive_empty = 0
                    elif isinstance(result, dict) and result.get("error") in (
                        "no_data", "not_available", "insufficient_data"
                    ):
                        # Soft error: tool executed but has no data — treat like empty retrieval
                        consecutive_empty += 1
                        tool_content += (
                            "\n\nNOTE: No data available for this query. "
                            "Do NOT retry with the same arguments — summarize what you know and conclude."
                        )
                        if consecutive_empty >= 2:
                            logger.info(f"[Node: {self.name}] Early exit: {consecutive_empty} consecutive no_data results.")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": tool_content,
                            })
                            break

                    # ── Error hint injection ──────────────────────────────────
                    if tool_content.startswith("Error executing tool"):
                        tool_content += (
                            "\n\nHINT: Check argument types and required fields. "
                            "Try corrected arguments or use an alternative tool."
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": tool_content,
                    })

                # ── Stagnation check ──────────────────────────────────────────
                if consecutive_errors >= STAGNATION_LIMIT:
                    logger.warning(f"[Node: {self.name}] Stagnated after {consecutive_errors} errors. Forcing synthesis.")
                    break

                turn += 1

                # ── Soft nudge at planned depth (fires once, LLM decides) ─────
                if turn >= planned_turns and not nudged:
                    nudged = True
                    logger.info(f"[Node: {self.name}] Reached planned depth ({planned_turns}). Nudging.")
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You have completed your planned {planned_turns}-step analysis. "
                            "Unless you have one critical unanswered question that requires exactly one more tool call, "
                            "please synthesize your final advisory proposal now."
                        ),
                    })

            except Exception as e:
                logger.error(f"[Node: {self.name}] Turn {turn} failed: {e}")
                return {
                    "response": Message(role="assistant", content=f"[{self.name}] internal error: {str(e)}"),
                    "history": messages,
                }

        # Hard ceiling or stagnation — force synthesis from accumulated evidence
        logger.warning(
            f"[Node: {self.name}] Forcing synthesis (turn={turn}, planned={planned_turns}, "
            f"ceiling={HARD_CEILING}, errors={consecutive_errors})."
        )
        messages.append({"role": "user", "content": "Please synthesize a final proposal based on your observations so far."})
        # Pass tools_def so Bedrock includes toolConfig (required when history has tool blocks)
        final_response = await self.llm.ask(
            messages=messages, system_msgs=system_msgs, channel=self.llm_channel,
            tools=tools_def or None,
        )
        if plan is not None and final_response.usage:
            plan.budget.record_llm_call(
                input_tokens=final_response.usage.input_tokens,
                output_tokens=final_response.usage.output_tokens,
                cost_usd=final_response.usage.cost_usd,
            )
        return {"response": final_response, "history": messages}

    async def _llm_plan_depth(self, query: str) -> int:
        """
        Ask LLM to estimate how many tool-call turns this query needs.
        Returns 1-8. Falls back to 3 on any failure.
        Single cheap call — runs before the main ReAct loop.
        """
        planner_prompt = (
            "You are a reasoning planner for a BMS (Building Management System) advisory agent. "
            "Read the query and return how many tool-call turns the agent needs to answer it well.\n\n"
            "Return ONLY valid JSON: {\"turns\": N, \"reason\": \"one line\"}\n\n"
            "Calibration:\n"
            "  1-2: single value lookup, current status, simple yes/no\n"
            "  3-4: multi-equipment analysis, trend check, basic fault diagnosis\n"
            "  5-6: root cause investigation, cross-system correlation, energy audit\n"
            "  7-8: full building compliance assessment, multi-system optimization, complex simulation\n"
        )
        try:
            result = await self.llm.ask_json(
                messages=[{"role": "user", "content": query}],
                system_msgs=[{"role": "system", "content": planner_prompt}],
                channel="depth_plan",
            )
            turns = int(result.get("turns", 3))
            reason = result.get("reason", "")
            planned = max(1, min(8, turns))
            logger.info(f"[Node: {self.name}] Depth planner → {planned} turns. Reason: {reason}")
            return planned
        except Exception as _e:
            logger.debug(f"[Node: {self.name}] Depth planner fallback (3): {_e}")
            return 3
