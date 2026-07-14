"""
Verification Toolkit for the Marina Agentic Judge.

Each tool is a read-only query against ARVIS's SQLite databases.
No LLM calls, no side effects. Deterministic and replayable.
"""

from __future__ import annotations

import inspect
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from marina_e2e.schemas import ToolResult

logger = logging.getLogger("marina.judge_tools")

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "agent_commercial" / "data" / "arvis_bms.db"


def _connect_ro(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a read-only SQLite connection."""
    path = db_path or str(DEFAULT_DB_PATH)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_REGISTRY: Dict[str, "callable"] = {}


def _register(fn):
    TOOL_REGISTRY[fn.__name__] = fn
    return fn


# ═══════════════════════════════════════════════════════════════════════════════
# VERIFICATION TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@_register
def query_investigation_plan(plan_id: str, db_path: Optional[str] = None) -> ToolResult:
    """
    Retrieve full investigation plan with tasks and audit spans.
    Answers: what investigation did ARVIS conduct? What tools were called?
    Tables: investigation_plans, plan_tasks, audit_spans
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM investigation_plans WHERE plan_id = ?", (plan_id,)
        )
        plan_row = cur.fetchone()
        if not plan_row:
            conn.close()
            return ToolResult(ok=False, error=f"No plan found with id={plan_id}",
                              tool_name="query_investigation_plan", params={"plan_id": plan_id})

        plan = dict(plan_row)

        cur.execute(
            "SELECT * FROM plan_tasks WHERE plan_id = ? ORDER BY rowid", (plan_id,)
        )
        tasks = _rows_to_dicts(cur.fetchall())

        cur.execute(
            "SELECT * FROM audit_spans WHERE plan_id = ? ORDER BY timestamp", (plan_id,)
        )
        spans = _rows_to_dicts(cur.fetchall())

        conn.close()
        return ToolResult(
            ok=True,
            data={"plan": plan, "tasks": tasks, "spans": spans,
                  "task_count": len(tasks), "span_count": len(spans)},
            tool_name="query_investigation_plan",
            params={"plan_id": plan_id},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_investigation_plan", params={"plan_id": plan_id})


@_register
def query_evidence_ledger(plan_id: str, db_path: Optional[str] = None) -> ToolResult:
    """
    Retrieve evidence records for an investigation plan.
    Answers: what evidence did ARVIS collect? Is it ML-fallback? What's the drift score?
    Tables: plan_evidence
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM plan_evidence WHERE plan_id = ? ORDER BY created_at",
            (plan_id,),
        )
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        ml_fallback_count = sum(1 for r in rows if r.get("is_ml_fallback"))
        return ToolResult(
            ok=True,
            data={"evidence": rows, "count": len(rows),
                  "ml_fallback_count": ml_fallback_count},
            tool_name="query_evidence_ledger",
            params={"plan_id": plan_id},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_evidence_ledger", params={"plan_id": plan_id})


@_register
def query_bft_votes(plan_id: str, db_path: Optional[str] = None) -> ToolResult:
    """
    Retrieve BFT consensus votes for an investigation.
    Answers: did consensus fire? Who vetoed? What conditions were imposed?
    Tables: bft_votes
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM bft_votes WHERE plan_id = ? ORDER BY timestamp",
            (plan_id,),
        )
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        vetoes = [r for r in rows if r.get("vote") == "VETO"]
        approvals = [r for r in rows if r.get("vote") == "APPROVE"]
        conditional = [r for r in rows if r.get("vote") == "APPROVE_WITH_CONDITION"]

        return ToolResult(
            ok=True,
            data={"votes": rows, "total": len(rows),
                  "vetoes": len(vetoes), "approvals": len(approvals),
                  "conditional": len(conditional)},
            tool_name="query_bft_votes",
            params={"plan_id": plan_id},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_bft_votes", params={"plan_id": plan_id})


@_register
def query_bft_abstentions(plan_id: str, db_path: Optional[str] = None) -> ToolResult:
    """
    Retrieve BFT abstention events (nodes that failed to vote).
    Answers: did any agents fail? Why?
    Tables: bft_abstentions
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM bft_abstentions WHERE plan_id = ? ORDER BY timestamp",
            (plan_id,),
        )
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        return ToolResult(
            ok=True,
            data={"abstentions": rows, "count": len(rows)},
            tool_name="query_bft_abstentions",
            params={"plan_id": plan_id},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_bft_abstentions", params={"plan_id": plan_id})


@_register
def query_violation_ledger(
    plan_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Retrieve physics violations from the simulator.
    Answers: did the physics gate fire? What violations were detected?
    Tables: violation_ledger
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        query = "SELECT * FROM violation_ledger WHERE 1=1"
        params: List[Any] = []
        if plan_id:
            query += " AND plan_id = ?"
            params.append(plan_id)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        hard_count = sum(1 for r in rows if r.get("severity") == "hard")
        return ToolResult(
            ok=True,
            data={"violations": rows, "count": len(rows), "hard_count": hard_count},
            tool_name="query_violation_ledger",
            params={"plan_id": plan_id, "severity": severity},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_violation_ledger",
                          params={"plan_id": plan_id, "severity": severity})


@_register
def query_distilled_rules(
    agent_name: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Retrieve distilled rules written during a time window.
    Answers: did procedural memory update? What rules were learned?
    Tables: distilled_rules
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        query = "SELECT * FROM distilled_rules WHERE active = 1"
        params: List[Any] = []
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until)
        query += " ORDER BY created_at DESC"

        cur.execute(query, params)
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        return ToolResult(
            ok=True,
            data={"rules": rows, "count": len(rows)},
            tool_name="query_distilled_rules",
            params={"agent_name": agent_name, "since": since, "until": until},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_distilled_rules",
                          params={"agent_name": agent_name, "since": since, "until": until})


@_register
def query_skillbook_growth(
    building_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Retrieve skills added to the Skillbook during a time window.
    Answers: did institutional memory grow? What was recorded?
    Tables: skills (in same arvis_bms.db)
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        query = "SELECT * FROM skills WHERE building_id = ?"
        params: List[Any] = [building_id]
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until)
        query += " ORDER BY created_at DESC"

        cur.execute(query, params)
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        return ToolResult(
            ok=True,
            data={"skills": rows, "count": len(rows),
                  "skill_types": list(set(r.get("skill_type", "") for r in rows))},
            tool_name="query_skillbook_growth",
            params={"building_id": building_id, "since": since, "until": until},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_skillbook_growth",
                          params={"building_id": building_id, "since": since, "until": until})


@_register
def query_conversation_turns(
    operator_id: str,
    building_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 30,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Retrieve conversation history for an operator.
    Answers: is conversation memory working? Did context carry across turns?
    Tables: conversation_turns
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        query = ("SELECT * FROM conversation_turns "
                 "WHERE operator_id = ? AND building_id = ?")
        params: List[Any] = [operator_id, building_id]
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        if until:
            query += " AND created_at <= ?"
            params.append(until)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        summary_count = sum(1 for r in rows if r.get("is_summary"))
        return ToolResult(
            ok=True,
            data={"turns": list(reversed(rows)), "count": len(rows),
                  "summary_count": summary_count},
            tool_name="query_conversation_turns",
            params={"operator_id": operator_id, "building_id": building_id,
                    "since": since, "until": until},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_conversation_turns",
                          params={"operator_id": operator_id, "building_id": building_id})


@_register
def query_llm_usage(
    plan_id: Optional[str] = None,
    node_name: Optional[str] = None,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Retrieve LLM usage/cost data for an investigation.
    Answers: what models were used? What was the cost? Budget discipline?
    Tables: llm_usage
    """
    try:
        conn = _connect_ro(db_path)
        cur = conn.cursor()

        query = "SELECT * FROM llm_usage WHERE 1=1"
        params: List[Any] = []
        if plan_id:
            query += " AND plan_id = ?"
            params.append(plan_id)
        if node_name:
            query += " AND node_name = ?"
            params.append(node_name)
        query += " ORDER BY timestamp"

        cur.execute(query, params)
        rows = _rows_to_dicts(cur.fetchall())
        conn.close()

        total_cost = sum(r.get("cost_usd", 0) for r in rows)
        total_tokens = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in rows)
        models_used = list(set(r.get("model_id", "") for r in rows))

        return ToolResult(
            ok=True,
            data={"usage": rows, "call_count": len(rows),
                  "total_cost_usd": round(total_cost, 6),
                  "total_tokens": total_tokens,
                  "models_used": models_used},
            tool_name="query_llm_usage",
            params={"plan_id": plan_id, "node_name": node_name},
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="query_llm_usage",
                          params={"plan_id": plan_id, "node_name": node_name})


@_register
def run_physics_crosscheck(
    advisory_text: str,
    conditions: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> ToolResult:
    """
    Re-run the physics simulator on advisory text independently.
    Answers: does the advisory violate thermodynamic constraints?
    Uses: BuildingPhysicsSimulator (deterministic, no LLM)
    """
    try:
        from agent_commercial.verifiers.simulator.engine import BuildingPhysicsSimulator

        sim = BuildingPhysicsSimulator()
        result = sim.predict_advisory(advisory_text, conditions=conditions)

        violations = [
            {"code": v.code, "severity": v.severity, "description": v.description,
             "expected_value": v.expected_value, "cited_value": v.cited_value,
             "component": v.component}
            for v in result.violations
        ]

        return ToolResult(
            ok=True,
            data={"passed": result.passed, "violations": violations,
                  "violation_count": len(violations),
                  "outputs": result.simulation_outputs,
                  "elapsed_ms": result.elapsed_ms},
            tool_name="run_physics_crosscheck",
            params={"advisory_text": advisory_text[:200]},
        )
    except ImportError as e:
        return ToolResult(ok=False, error=f"Simulator not available: {e}",
                          tool_name="run_physics_crosscheck",
                          params={"advisory_text": advisory_text[:200]})
    except Exception as e:
        return ToolResult(ok=False, error=str(e),
                          tool_name="run_physics_crosscheck",
                          params={"advisory_text": advisory_text[:200]})


def get_all_tools() -> Dict[str, "callable"]:
    """Return the full tool registry for judge introspection."""
    return dict(TOOL_REGISTRY)


def call_tool(name: str, **kwargs) -> ToolResult:
    """Call a verification tool by name with kwargs.

    Filters unknown kwargs (using inspect.signature) and checks for missing
    required positional arguments before calling.  A TypeError from missing
    args is returned as a graceful ToolResult rather than a hard crash so the
    judge ReAct loop can continue to the next tool call / dimension.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult(ok=False, error=f"Unknown tool: {name}", tool_name=name)
    fn = TOOL_REGISTRY[name]
    sig = inspect.signature(fn)
    accepted = set(sig.parameters.keys())
    filtered = {k: v for k, v in kwargs.items() if k in accepted}

    # Detect missing required positional arguments before calling so we can
    # surface a clear error instead of letting Python raise a TypeError that
    # crashes the whole scoring phase.
    missing = [
        p_name
        for p_name, p in sig.parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
        and p_name not in filtered
    ]
    if missing:
        return ToolResult(
            ok=False,
            error=f"Missing required args for {name}: {missing}. "
                  f"Provide them in the tool call params.",
            tool_name=name,
            params=dict(filtered),
        )

    try:
        return fn(**filtered)
    except TypeError as e:
        # Catch any remaining signature mismatches (e.g. VAR_KEYWORD surprises)
        return ToolResult(ok=False, error=f"Tool call error: {e}", tool_name=name, params=dict(filtered))
