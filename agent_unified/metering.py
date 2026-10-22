"""
Per-investigation LLM metering.

An investigation fans out across many swarm nodes, verifiers and synthesis
steps, and each of them calls the LLM from a different place. Charging the
investigation's budget at every call site is how spend used to leak (depth
planning, queen synthesis, verifiers and non-Bedrock providers were never
counted). Instead, the investigation is bound to the current async context
once, and the LLM adapters charge whatever investigation is active.

ContextVars are copied into tasks created with asyncio.create_task / gather,
so every node of a swarm run sees the same investigation, while two
investigations running concurrently never see each other's.

    scope = investigation_scope(plan.id, plan.budget)   # in the investigation's own task
    ...
    charge(usage, channel=..., model_id=...)             # called by the LLM adapters
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, NamedTuple, Optional


class InvestigationScope(NamedTuple):
    plan_id: str
    budget: Any          # arvis_core.plan.Budget (duck-typed: record_llm_call(...))


_ACTIVE: ContextVar[Optional[InvestigationScope]] = ContextVar("arvis_investigation", default=None)


def bind_investigation(plan_id: str, budget: Any) -> InvestigationScope:
    """Bind an investigation to the current async context (call inside the investigation's own task)."""
    scope = InvestigationScope(plan_id, budget)
    _ACTIVE.set(scope)
    return scope


def active_investigation() -> Optional[InvestigationScope]:
    return _ACTIVE.get()


def charge(input_tokens: int, output_tokens: int, cost_usd: float) -> Optional[str]:
    """Charge the active investigation's budget. Returns its plan_id, or None outside an investigation."""
    scope = _ACTIVE.get()
    if scope is None:
        return None
    if scope.budget is not None:
        scope.budget.record_llm_call(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd)
    return scope.plan_id
