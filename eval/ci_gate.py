"""
CI Gate for ARVIS
=================

Deterministic checks that run in CI. Build fails on any regression.
No LLM calls — all checks are regex/structural.

Usage:
    python -m eval.ci_gate
    Exit code 0 = pass, 1 = failure
"""

from __future__ import annotations

import importlib
import sys
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("arvis.eval.ci_gate")

# Resolve repo root relative to this file (eval/ci_gate.py → repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent


def check_no_hardcoded_confidence() -> Tuple[bool, str]:
    """No path ships LLM output with hardcoded confidence."""
    import ast

    target_files = [
        _REPO_ROOT / "agent_commercial" / "bms_llm_agent.py",
        _REPO_ROOT / "arvis_core" / "swarm" / "queen.py",
    ]

    violations = []
    for path in target_files:
        try:
            with open(path, "r") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "confidence":
                    if isinstance(node.value, ast.Constant) and node.value.value == 0.99:
                        violations.append(f"{path}:line ~{node.lineno}: confidence=0.99 hardcoded")
        except Exception as e:
            violations.append(f"{path}: parse error: {e}")

    if violations:
        return False, f"Hardcoded confidence found: {violations}"
    return True, "No hardcoded confidence values"


def check_no_auto_pass_validator() -> Tuple[bool, str]:
    """No keyword/string auto-passes the validator."""
    import ast

    validator_path = _REPO_ROOT / "arvis_core" / "swarm" / "validator.py"
    with open(validator_path, "r") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"validator.py parse error: {e}"

    violations = []
    for node in ast.walk(tree):
        # Detect: return {"score": 1.0, ...} — direct auto-pass dict return
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key, val in zip(node.value.keys, node.value.values):
                if (
                    isinstance(key, ast.Constant) and key.value == "score"
                    and isinstance(val, ast.Constant) and val.value == 1.0
                ):
                    violations.append(f"line {node.lineno}: return dict with score=1.0")

        # Detect: score = 1.0 (direct assignment, unbounded)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "score":
                    if isinstance(node.value, ast.Constant) and node.value.value == 1.0:
                        violations.append(f"line {node.lineno}: score = 1.0 direct assignment")

    if violations:
        return False, f"validator.py auto-pass patterns: {violations}"

    return True, "No auto-pass in validator (AST verified)"


def check_read_only_enforcement() -> Tuple[bool, str]:
    """Read-only enforcement exists as code, not just prompt."""
    with open(_REPO_ROOT / "arvis_core" / "swarm" / "queen.py", "r") as f:
        content = f.read()

    if "_enforce_read_only" not in content:
        return False, "queen.py missing _enforce_read_only method"

    if "_ACTION_VERBS_RE" not in content:
        return False, "queen.py missing _ACTION_VERBS_RE pattern"

    return True, "Read-only enforcement present as code"


def check_grounding_guard_isolation() -> Tuple[bool, str]:
    """GroundingGuard uses per-request isolation."""
    with open(_REPO_ROOT / "agent_commercial" / "grounding_guard.py", "r") as f:
        content = f.read()

    if "contextvars" not in content:
        return False, "grounding_guard.py missing contextvars import"

    if "_active_guard" not in content:
        return False, "grounding_guard.py missing _active_guard ContextVar"

    return True, "GroundingGuard uses per-request contextvars isolation"


def check_evidence_ledger_exists() -> Tuple[bool, str]:
    """Evidence Ledger is the factual source for synthesis."""
    try:
        from arvis_core.evidence import Evidence, EvidenceLedger
        ledger = EvidenceLedger()
        assert hasattr(ledger, "add")
        assert hasattr(ledger, "to_synthesis_context")
        return True, "EvidenceLedger importable and has required methods"
    except Exception as e:
        return False, f"EvidenceLedger check failed: {e}"


def check_investigation_plan_exists() -> Tuple[bool, str]:
    """InvestigationPlan is runtime spine."""
    try:
        from arvis_core.plan import InvestigationPlan, Budget, Task, TaskStatus
        plan = InvestigationPlan(query="test")
        assert hasattr(plan, "check_budget")
        assert hasattr(plan, "to_prompt_context")
        assert hasattr(plan, "coverage")
        assert hasattr(plan, "is_duplicate_call")
        return True, "InvestigationPlan importable with required interface"
    except Exception as e:
        return False, f"InvestigationPlan check failed: {e}"


def check_physics_verifier_exists() -> Tuple[bool, str]:
    """Physics verifier is wired in."""
    try:
        from agent_commercial.verifiers.physics import PhysicsVerifier, VerificationResult
        pv = PhysicsVerifier()
        # Test with a known-bad COP
        result = pv.verify_cop_claim(cop=9.0, plr=0.8)
        assert not result.passed, "COP=9.0 should fail physics check"
        return True, "PhysicsVerifier works and catches implausible COP"
    except Exception as e:
        return False, f"PhysicsVerifier check failed: {e}"


def check_truth_validator_blocking() -> Tuple[bool, str]:
    """TruthValidator is blocking (not advisory-only)."""
    with open(_REPO_ROOT / "agent_commercial" / "bms_llm_agent.py", "r") as f:
        content = f.read()

    if "val_score < 0.7" not in content:
        return False, "bms_llm_agent.py missing val_score < 0.7 blocking gate"

    if "[Low Confidence]" not in content:
        return False, "bms_llm_agent.py missing [Low Confidence] downgrade"

    # Check there's no "During Pilot" bypass
    if "During Pilot" in content:
        return False, "bms_llm_agent.py still has 'During Pilot' bypass"

    return True, "TruthValidator is blocking with <0.7 abstain and 0.7-0.95 downgrade"


def check_no_tolerance_in_grounding() -> Tuple[bool, str]:
    """Numeric grounding is exact-match only."""
    import re

    with open(_REPO_ROOT / "agent_commercial" / "grounding_guard.py", "r") as f:
        content = f.read()

    # P2c: Regex-based check — catches abs(x)*0.05, abs(val)*0.03, etc.
    tolerance_pattern = re.compile(r'abs\s*\(.*?\)\s*\*\s*0\.\d+')
    match = tolerance_pattern.search(content)
    if match:
        return False, f"grounding_guard.py has tolerance pattern: '{match.group()}'"

    # Also catch explicit tol/tolerance variable assignment with float multiplier
    tol_assign = re.compile(r'\btol(?:erance)?\s*=\s*.*(?:abs|0\.\d)')
    match2 = tol_assign.search(content)
    if match2:
        return False, f"grounding_guard.py has tolerance assignment: '{match2.group()}'"

    return True, "Grounding uses exact-match (no amnesty)"


def check_grounding_guard_blocks_ungrounded() -> Tuple[bool, str]:
    """GroundingGuard flags numbers without tool provenance."""
    from agent_commercial.grounding_guard import GroundingGuard

    guard = GroundingGuard()
    # Register a tool result with specific numbers
    guard.register_tool_result("get_equipment_status", {"cop": 4.2, "load_pct": 75})

    # Test: grounded number passes
    audit = guard.audit("The COP is 4.2 kW/kW")
    if not audit.passed:
        return False, f"Grounded COP=4.2 incorrectly flagged: {audit.ungrounded_claims}"

    # Test: fabricated number gets flagged (use format that matches evidence patterns)
    audit2 = guard.audit("There is an 87% probability of failure within the next month.")
    if audit2.passed:
        return False, "Fabricated 87% failure probability was NOT flagged"

    # B9 fix: verify the flagged claim contains the specific fabricated number
    claims_str = str(audit2.ungrounded_claims).lower()
    if "87" not in claims_str:
        return False, f"Ungrounded claims don't reference '87': {audit2.ungrounded_claims}"

    # B9 fix: plain count (not measurement) should pass — avoid over-broad matching
    audit3 = guard.audit("The system has 3 compressors in the plant room.")
    if not audit3.passed:
        return False, f"Plain count '3 compressors' incorrectly flagged: {audit3.ungrounded_claims}"

    return True, "GroundingGuard correctly flags ungrounded numbers and passes counts"


def check_read_only_enforcement_runtime() -> Tuple[bool, str]:
    """Read-only enforcement produces valid English, not gibberish."""
    from unittest.mock import MagicMock
    from arvis_core.swarm.queen import QueenCoordinator

    # B8 fix: proper Pydantic init (no __new__ bypass)
    queen = QueenCoordinator(
        llm=MagicMock(),
        intent_router=MagicMock(),
        tool_handler=MagicMock(),
    )

    # Main case: action verbs replaced with advisory language
    test_input = 'I have submitted the new setpoint and restarted the chiller.'
    sanitized = queen._enforce_read_only(test_input)

    if "submitteding" in sanitized.lower() or "restarteding" in sanitized.lower():
        return False, f"Read-only sub produced gibberish: {sanitized}"

    if "recommend" not in sanitized.lower():
        return False, f"Result lacks advisory language: {sanitized}"

    if "recommend submitting" not in sanitized:
        return False, f"'submitted' not mapped to 'recommend submitting'. Got: {sanitized}"

    if "recommend restarting" not in sanitized:
        return False, f"'restarted' not mapped to 'recommend restarting'. Got: {sanitized}"

    # P2a: Edge case — empty string
    empty_result = queen._enforce_read_only("")
    if empty_result != "":
        return False, f"Empty input should return empty, got: '{empty_result}'"

    # P2a: Edge case — no violations (passthrough unchanged)
    clean_input = "The chiller COP is 4.2 and operating normally."
    clean_result = queen._enforce_read_only(clean_input)
    if clean_result != clean_input:
        return False, f"Clean input mutated: '{clean_result}'"

    # P2a: Edge case — present-tense verb forms should NOT match (word boundary protection)
    gerund_input = "The system is currently restarting after the scheduled cycle."
    gerund_result = queen._enforce_read_only(gerund_input)
    if "recommend restartinging" in gerund_result.lower():
        return False, f"Mid-word false positive on gerund: '{gerund_result}'"

    return True, f"Read-only sub valid: '{sanitized[:80]}...'"


def check_plan_tasks_populated() -> Tuple[bool, str]:
    """InvestigationPlan.add_task is called in queen.execute_swarm."""
    with open(_REPO_ROOT / "arvis_core" / "swarm" / "queen.py", "r") as f:
        content = f.read()

    if "plan.add_task(" not in content:
        return False, "queen.py never calls plan.add_task() — plan stays empty"

    return True, "Plan tasks are populated in execute_swarm"


def check_task_lifecycle_in_bft_path() -> Tuple[bool, str]:
    """BFT path marks tasks active/complete (not left PENDING → ABANDONED)."""
    from unittest.mock import MagicMock, AsyncMock
    import asyncio

    from arvis_core.plan import InvestigationPlan, Budget, TaskStatus, PlanStatus
    from arvis_core.swarm.queen import QueenCoordinator
    from arvis_core.swarm.node import SwarmNode

    # Build a plan simulating BFT path task creation
    plan = InvestigationPlan(query="test optimize chiller", budget=Budget())
    plan.add_task(goal="Energy_Agent: investigate", tool_hint="Energy_Agent", expected_outcome="evidence")
    plan.tasks[-1].assigned_node = "Energy_Agent"

    # Create mock node
    mock_node = MagicMock(spec=SwarmNode)
    mock_node.name = "Energy_Agent"
    mock_response = MagicMock()
    mock_response.content = "test proposal"
    mock_response.tool_calls = []
    mock_node.process = AsyncMock(return_value={"response": mock_response, "history": []})

    # B8 fix: proper Pydantic init (no __new__ bypass)
    queen = QueenCoordinator(
        llm=MagicMock(),
        intent_router=MagicMock(),
        tool_handler=MagicMock(),
    )

    # Run the lifecycle wrapper (B7 fix: handle existing event loop)
    async def _test():
        result = await queen._run_with_task_lifecycle(mock_node, plan, "test query", {}, "test")
        return result

    try:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _test()).result(timeout=10)
        except RuntimeError:
            asyncio.run(_test())
    except Exception as e:
        return False, f"_run_with_task_lifecycle raised: {e}"

    task = plan.tasks[0]
    if task.status != TaskStatus.COMPLETE:
        return False, f"Task status after lifecycle = {task.status.value}, expected COMPLETE"

    return True, "BFT task lifecycle wrapper marks tasks COMPLETE"


def check_no_numeric_confidence_in_fallback() -> Tuple[bool, str]:
    """ML fallback returns never carry numeric confidence values."""
    import ast

    ml_handler_path = _REPO_ROOT / "agent_commercial" / "tools" / "handlers" / "ml.py"
    with open(ml_handler_path, "r") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, f"ml.py parse error: {e}"

    violations = []
    # Walk all Return nodes containing a dict — find those with "fallback": True
    # and check if they also have a numeric "confidence" value
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        keys = [k.value if isinstance(k, ast.Constant) else None for k in node.value.keys]
        vals = node.value.values
        kv = dict(zip(keys, vals))

        # Must be a fallback dict
        fallback_val = kv.get("fallback")
        if not (isinstance(fallback_val, ast.Constant) and fallback_val.value is True):
            continue

        # Check confidence is not numeric
        conf_val = kv.get("confidence")
        if conf_val is None:
            continue
        if isinstance(conf_val, ast.Constant) and isinstance(conf_val.value, (int, float)):
            violations.append(f"line {node.lineno}: fallback dict has numeric confidence={conf_val.value}")

    if violations:
        return False, f"Numeric confidence in fallback: {violations}"
    return True, "No numeric confidence values in ML fallback returns"


def check_tool_contracts_have_response_schema() -> Tuple[bool, str]:
    """All tool definitions have response_schema declared."""
    try:
        from agent_commercial.tools.definitions import get_all_tools
        tools = get_all_tools()
        missing = [t["name"] for t in tools if "response_schema" not in t]
        if missing:
            return False, f"Tools missing response_schema ({len(missing)}): {missing}"
        return True, f"All {len(tools)} tools have response_schema"
    except Exception as e:
        return False, f"Tool definitions import failed: {e}"


def check_tool_registry_built() -> Tuple[bool, str]:
    """BMSToolHandler builds handler + tool-def registries on init."""
    try:
        from agent_commercial.tools.handlers.base import BMSToolHandler
        h = BMSToolHandler()
        if not h._handler_registry:
            return False, "BMSToolHandler._handler_registry is empty"
        if not h._tool_def_registry:
            return False, "BMSToolHandler._tool_def_registry is empty"
        # Spot-check a known tool exists in both
        if "get_equipment_status" not in h._handler_registry:
            return False, "get_equipment_status missing from handler registry"
        if "get_equipment_status" not in h._tool_def_registry:
            return False, "get_equipment_status missing from tool def registry"
        return True, f"Registries built: {len(h._handler_registry)} handlers, {len(h._tool_def_registry)} defs"
    except Exception as e:
        return False, f"Handler registry check failed: {e}"


def check_missing_required_args_returns_structured_error() -> Tuple[bool, str]:
    """Missing required arg returns MISSING_REQUIRED_ARGS structured error, never reaches handler."""
    try:
        import asyncio
        from agent_commercial.tools.handlers.base import BMSToolHandler
        h = BMSToolHandler()

        async def _run():
            return await h.execute("get_equipment_status", {})

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, _run()).result(timeout=10)
        except RuntimeError:
            result = asyncio.run(_run())

        if "error" not in result:
            return False, f"Missing required arg did not return error: {result}"
        err = result["error"]
        if not isinstance(err, dict):
            return False, f"error is not a dict (still stringified): {err!r}"
        if err.get("type") != "MISSING_REQUIRED_ARGS":
            return False, f"Wrong error type: {err.get('type')} (expected MISSING_REQUIRED_ARGS)"
        if "missing_fields" not in err:
            return False, "error dict missing 'missing_fields' key"
        return True, f"MISSING_REQUIRED_ARGS error returned correctly: {err['missing_fields']}"
    except Exception as e:
        return False, f"Required arg validation check failed: {e}"


def check_t1_queries_not_fast_path_shortcut() -> Tuple[bool, str]:
    """T1 lookup path no longer returns __FAST_PATH_ROUTING__ — routes through node."""
    with open(_REPO_ROOT / "arvis_core" / "swarm" / "queen.py", "r") as f:
        content = f.read()
    if "__FAST_PATH_ROUTING__" in content:
        return False, "queen.py still contains __FAST_PATH_ROUTING__ shortcut — T0.4 fix not applied"
    if "_pick_lookup_node" not in content:
        return False, "queen.py missing _pick_lookup_node — T1 forced-tool routing not implemented"
    return True, "T1 lookup path routes through _pick_lookup_node (no fast-path shortcut)"


def check_no_structured_error_stringified() -> Tuple[bool, str]:
    """Structured error dicts are NOT stringified before reaching LLM — [TOOL_ERROR:] prefix preserved."""
    with open(_REPO_ROOT / "arvis_core" / "swarm" / "node.py", "r") as f:
        content = f.read()
    if "[TOOL_ERROR:" not in content:
        return False, "node.py missing [TOOL_ERROR:TYPE] prefix — T0.3 fix not applied"
    if "RECOVERY:" not in content:
        return False, "node.py missing RECOVERY: hint line in error serialization"
    return True, "Structured errors use [TOOL_ERROR:TYPE] prefix with RECOVERY hint"


def check_plan_tool_cache_exists() -> Tuple[bool, str]:
    """InvestigationPlan has cross-node tool cache (cache_tool_result / get_cached_tool_result)."""
    try:
        from arvis_core.plan import InvestigationPlan, Budget
        plan = InvestigationPlan(query="test", budget=Budget())
        if not hasattr(plan, "cache_tool_result"):
            return False, "InvestigationPlan missing cache_tool_result method"
        if not hasattr(plan, "get_cached_tool_result"):
            return False, "InvestigationPlan missing get_cached_tool_result method"
        # Functional test
        plan.cache_tool_result("test:sig", {"cop": 4.2})
        cached = plan.get_cached_tool_result("test:sig")
        if cached != {"cop": 4.2}:
            return False, f"Cache roundtrip failed: {cached}"
        assert plan.get_cached_tool_result("missing") is None
        return True, "InvestigationPlan cross-node tool cache works correctly"
    except Exception as e:
        return False, f"Plan tool cache check failed: {e}"


def check_sync_wrapper_no_nest_asyncio() -> Tuple[bool, str]:
    """sync_wrapper.py does not use nest_asyncio."""
    wrapper_path = _REPO_ROOT / "agent_commercial" / "tools" / "handlers" / "sync_wrapper.py"
    with open(wrapper_path, "r") as f:
        content = f.read()
    if "nest_asyncio" in content:
        return False, "sync_wrapper.py still imports nest_asyncio — T0.6 fix not applied"
    if "ThreadPoolExecutor" not in content:
        return False, "sync_wrapper.py missing ThreadPoolExecutor fallback"
    return True, "sync_wrapper.py uses ThreadPoolExecutor (no nest_asyncio)"


def check_ml_lineage_schema() -> Tuple[bool, str]:
    """Evidence dataclass has ML lineage fields."""
    try:
        from arvis_core.evidence import Evidence
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(Evidence)}
        required = {"is_ml_fallback", "model_id", "model_version", "algorithm",
                    "confidence_bounds", "drift_score", "training_window"}
        missing = required - field_names
        if missing:
            return False, f"Evidence missing ML lineage fields: {missing}"
        # Verify types: is_ml_fallback must default False, model_id must default None
        ev = Evidence(source_tool="test", raw_payload={})
        assert ev.is_ml_fallback is False, "is_ml_fallback default must be False"
        assert ev.model_id is None, "model_id default must be None"
        assert ev.confidence_bounds is None, "confidence_bounds default must be None"
        return True, "Evidence has all ML lineage fields with correct defaults"
    except Exception as e:
        return False, f"ML lineage schema check failed: {e}"


def check_plan_persistence_roundtrip() -> Tuple[bool, str]:
    """InvestigationPlan save→load roundtrip preserves all fields."""
    import tempfile, os
    from pathlib import Path
    from arvis_core.plan import InvestigationPlan, Budget, TaskStatus
    from arvis_core.evidence import Evidence

    plan = InvestigationPlan(query="roundtrip test", budget=Budget(max_tool_calls=10))
    t = plan.add_task(goal="Test task", tool_hint="get_equipment_status", expected_outcome="data")
    t.mark_active()
    plan.register_call("test:sig:abc")
    plan.cache_tool_result("test:sig:abc", {"cop": 5.1})
    ev = Evidence.from_tool_result("get_equipment_status", {"cop": 5.1, "status": "ok"}, node_name="TestNode", task_id=t.id)
    plan.evidence.add(ev)
    t.mark_complete(ev.id)
    plan.record_span(task_id=t.id, node_name="TestNode", action="tool_call:get_equipment_status", tool_name="get_equipment_status")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = Path(f.name)

    try:
        plan.save(tmp_path)
        loaded = InvestigationPlan.load(tmp_path)
    finally:
        os.unlink(tmp_path)

    if loaded.id != plan.id:
        return False, f"id mismatch: {loaded.id} != {plan.id}"
    if loaded.query != plan.query:
        return False, f"query mismatch: {loaded.query!r}"
    if loaded.budget.max_tool_calls != 10:
        return False, f"budget.max_tool_calls not preserved: {loaded.budget.max_tool_calls}"
    if len(loaded.tasks) != 1 or loaded.tasks[0].status != TaskStatus.COMPLETE:
        return False, f"task not preserved: {loaded.tasks}"
    if len(loaded.evidence) != 1:
        return False, f"evidence count mismatch: {len(loaded.evidence)}"
    ev_loaded = loaded.evidence.get(ev.id)
    if ev_loaded is None or ev_loaded.source_tool != "get_equipment_status":
        return False, f"evidence not found or wrong tool: {ev_loaded}"
    if "test:sig:abc" not in loaded._shared_call_sigs:
        return False, "shared_call_sigs not preserved"
    if loaded._tool_cache.get("test:sig:abc") != {"cop": 5.1}:
        return False, f"tool_cache not preserved: {loaded._tool_cache}"
    if len(loaded.audit_trail) != 1:
        return False, f"audit_trail not preserved: {len(loaded.audit_trail)} spans"
    return True, "InvestigationPlan save→load roundtrip preserved all fields"


def check_abstention_fires_on_all_fallback() -> Tuple[bool, str]:
    """Abstention gate fires when all evidence is ML fallback (ml_fallback_ratio=1.0)."""
    import re

    path = _REPO_ROOT / "agent_commercial" / "bms_llm_agent.py"
    with open(path, "r") as f:
        content = f.read()

    # Verify abstention gate treats is_ml_fallback=True as drift_score=1.0
    if "is_ml_fallback" not in content:
        return False, "bms_llm_agent.py missing is_ml_fallback check in abstention gate"

    # Verify the fallback ratio gate exists
    if "ml_fallback_ratio" not in content:
        return False, "bms_llm_agent.py missing ml_fallback_ratio check"

    # Verify threshold is >= 0.5
    ratio_match = re.search(r'ml_fallback_ratio\s*[>]=?\s*([\d.]+)', content)
    if not ratio_match:
        return False, "ml_fallback_ratio threshold not found"
    threshold = float(ratio_match.group(1))
    if threshold > 0.5:
        return False, f"ml_fallback_ratio threshold too high: {threshold} (should be <=0.5)"

    return True, f"Abstention gate fires on ml_fallback_ratio >= {threshold} with is_ml_fallback drift=1.0"


def check_tool_cache_prevents_duplicate_expensive_calls() -> Tuple[bool, str]:
    """Cross-node tool cache: get_cached_tool_result returns cached value on hit."""
    from arvis_core.plan import InvestigationPlan, Budget
    plan = InvestigationPlan(query="cache test", budget=Budget())

    sig = "get_energy_consumption:{}"
    plan.cache_tool_result(sig, {"total_kwh": 1234.5})
    plan.register_call(sig)

    # Verify: duplicate call check fires
    if not plan.is_duplicate_call(sig):
        return False, "is_duplicate_call should return True after register_call"

    # Verify: cache hit returns correct result
    cached = plan.get_cached_tool_result(sig)
    if cached != {"total_kwh": 1234.5}:
        return False, f"Cache hit returned wrong value: {cached}"

    # Verify: missing sig returns None
    if plan.get_cached_tool_result("nonexistent") is not None:
        return False, "Cache miss should return None"

    return True, "Cross-node tool cache dedup + cache-hit verified"


def check_h8_fires_on_all_t3_not_just_safety_keywords() -> Tuple[bool, str]:
    """H8 self-consistency fires on ALL T3 proposals, not just safety keyword queries."""
    path = _REPO_ROOT / "arvis_core" / "swarm" / "queen.py"
    with open(path, "r") as f:
        content = f.read()

    # Must NOT gate H8 behind _SAFETY_KEYWORDS_RE check
    import re
    # Find the H8 block and check it's unconditional inside the T3 BFT path
    h8_block = re.search(
        r'H8.*?self_consistency_check',
        content, re.DOTALL | re.IGNORECASE
    )
    if not h8_block:
        return False, "H8 self-consistency block not found in queen.py"

    # The H8 call must NOT be preceded by an _SAFETY_KEYWORDS_RE.search guard on the same call
    surrounding = content[max(0, h8_block.start() - 200): h8_block.end() + 50]
    if "_SAFETY_KEYWORDS_RE.search(query)" in surrounding:
        return False, "H8 still gated behind _SAFETY_KEYWORDS_RE.search(query)"

    return True, "H8 self-consistency fires unconditionally on all T3 proposals"


# ── Runner ───────────────────────────────────────────────────────────────────

ALL_CHECKS = [
    check_no_hardcoded_confidence,
    check_no_auto_pass_validator,
    check_read_only_enforcement,
    check_grounding_guard_isolation,
    check_evidence_ledger_exists,
    check_investigation_plan_exists,
    check_physics_verifier_exists,
    check_truth_validator_blocking,
    check_no_tolerance_in_grounding,
    # Behavioral runtime checks
    check_grounding_guard_blocks_ungrounded,
    check_read_only_enforcement_runtime,
    check_plan_tasks_populated,
    check_task_lifecycle_in_bft_path,
    # WS-M7: ML CI checks
    check_no_numeric_confidence_in_fallback,
    check_ml_lineage_schema,
    # Tool-Calling Moat: T0-T1 CI checks
    check_tool_contracts_have_response_schema,
    check_tool_registry_built,
    check_missing_required_args_returns_structured_error,
    check_t1_queries_not_fast_path_shortcut,
    check_no_structured_error_stringified,
    check_plan_tool_cache_exists,
    check_sync_wrapper_no_nest_asyncio,
    # A3: Behavioral CI checks
    check_plan_persistence_roundtrip,
    check_abstention_fires_on_all_fallback,
    check_tool_cache_prevents_duplicate_expensive_calls,
    check_h8_fires_on_all_t3_not_just_safety_keywords,
]


def run_ci_gate() -> int:
    """Run all CI gate checks. Returns exit code (0=pass, 1=fail)."""
    print("=" * 60)
    print("ARVIS CI GATE — Hardening Verification")
    print("=" * 60)

    passed = 0
    failed = 0
    results: List[Tuple[str, bool, str]] = []

    for check_fn in ALL_CHECKS:
        name = check_fn.__doc__ or check_fn.__name__
        try:
            ok, msg = check_fn()
        except Exception as e:
            ok, msg = False, f"Exception: {e}"

        status = "PASS" if ok else "FAIL"
        results.append((name.strip(), ok, msg))

        if ok:
            passed += 1
        else:
            failed += 1

        print(f"  [{status}] {name.strip()}")
        if not ok:
            print(f"         → {msg}")

    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(ALL_CHECKS)} checks")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_ci_gate())
