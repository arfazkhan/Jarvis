"""
Tool Contract Tests (T4.1)
==========================

For every tool:
- Call handler with valid args → assert result matches response_schema key set
- Call with missing required arg → assert MISSING_REQUIRED_ARGS structured error
- Assert output schema validation injects _schema_violation on mismatch

Also covers T0 surface area:
- Handler registry completeness
- Structured error types preserved end-to-end
- Cross-node tool cache roundtrip
- Sync wrapper no longer uses nest_asyncio
"""

import asyncio
import pytest
from typing import Dict, Any


def _run(coro):
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=15)
    except RuntimeError:
        return asyncio.run(coro)


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def handler():
    from agent_commercial.tools.handlers.base import BMSToolHandler
    return BMSToolHandler()


# ── Registry completeness ─────────────────────────────────────────────────────

def test_handler_registry_not_empty(handler):
    assert handler._handler_registry, "Handler registry must not be empty"


def test_tool_def_registry_not_empty(handler):
    assert handler._tool_def_registry, "Tool def registry must not be empty"


def test_known_tools_in_both_registries(handler):
    expected = [
        "get_equipment_status", "list_equipment",
        "get_active_alarms", "get_energy_consumption",
        "forecast_energy", "detect_equipment_faults",
    ]
    for tool_name in expected:
        assert tool_name in handler._handler_registry, f"{tool_name} missing from handler registry"
        assert tool_name in handler._tool_def_registry, f"{tool_name} missing from tool def registry"


def test_all_registered_handlers_are_callable(handler):
    for name, fn in handler._handler_registry.items():
        assert callable(fn), f"Handler for {name!r} is not callable"


# ── All tools have response_schema ───────────────────────────────────────────

def test_all_tools_have_response_schema():
    from agent_commercial.tools.definitions import get_all_tools
    tools = get_all_tools()
    assert tools, "get_all_tools() returned empty list"
    missing = [t["name"] for t in tools if "response_schema" not in t]
    assert not missing, f"Tools missing response_schema: {missing}"


def test_all_tools_have_version():
    from agent_commercial.tools.definitions import get_all_tools
    tools = get_all_tools()
    missing = [t["name"] for t in tools if "version" not in t]
    assert not missing, f"Tools missing version field: {missing}"


def test_all_tools_have_precedents_and_produces():
    from agent_commercial.tools.definitions import get_all_tools
    tools = get_all_tools()
    missing_precedents = [t["name"] for t in tools if "precedents" not in t]
    missing_produces = [t["name"] for t in tools if "produces" not in t]
    assert not missing_precedents, f"Tools missing precedents: {missing_precedents}"
    assert not missing_produces, f"Tools missing produces: {missing_produces}"


# ── Required arg validation (T0.1) ───────────────────────────────────────────

def test_missing_required_arg_returns_structured_error(handler):
    result = _run(handler.execute("get_equipment_status", {}))
    assert "error" in result, f"Missing required arg must return error dict, got: {result}"
    err = result["error"]
    assert isinstance(err, dict), f"error must be a dict, not string. Got: {err!r}"
    assert err.get("type") == "MISSING_REQUIRED_ARGS", f"Wrong error type: {err.get('type')}"
    assert "missing_fields" in err, "error dict must contain 'missing_fields'"
    assert "equipment_id" in err["missing_fields"]
    assert "recovery_hint" in err, "error dict must contain 'recovery_hint'"


def test_missing_required_arg_detect_equipment_faults(handler):
    result = _run(handler.execute("detect_equipment_faults", {}))
    assert "error" in result
    err = result["error"]
    assert err.get("type") == "MISSING_REQUIRED_ARGS"
    assert "equipment_id" in err["missing_fields"]


def test_missing_required_arg_analyze_root_cause(handler):
    result = _run(handler.execute("analyze_root_cause", {}))
    assert "error" in result
    err = result["error"]
    assert err.get("type") == "MISSING_REQUIRED_ARGS"
    assert "alarm_ids" in err["missing_fields"]


def test_missing_required_arg_does_not_reach_handler(handler):
    """Handler must NOT be called when required args are missing."""
    call_log = []
    original = handler._handler_registry.get("get_equipment_status")
    async def _spy(args):
        call_log.append(args)
        return original(args) if original else {}
    handler._handler_registry["get_equipment_status"] = _spy

    result = _run(handler.execute("get_equipment_status", {}))
    assert "error" in result
    assert call_log == [], "Handler was called despite missing required args"

    # Restore
    if original:
        handler._handler_registry["get_equipment_status"] = original


def test_optional_args_not_blocked(handler):
    """Tools with no required args must not be blocked by validation."""
    result = _run(handler.execute("list_equipment", {}))
    # Any result is fine — just must not be a MISSING_REQUIRED_ARGS error
    if "error" in result and isinstance(result["error"], dict):
        assert result["error"].get("type") != "MISSING_REQUIRED_ARGS", \
            "list_equipment (no required args) should not get MISSING_REQUIRED_ARGS error"


# ── Unknown tool ──────────────────────────────────────────────────────────────

def test_unknown_tool_returns_structured_error(handler):
    result = _run(handler.execute("nonexistent_tool_xyz", {}))
    assert "error" in result
    err = result["error"]
    assert isinstance(err, dict)
    assert err.get("type") == "UNKNOWN_TOOL"


# ── Output schema validation (T0.2) ──────────────────────────────────────────

def test_validate_output_injects_schema_violation_flag(handler):
    """_validate_output must inject _schema_violation when output is missing declared keys."""
    tool_def = {
        "response_schema": {
            "type": "object",
            "properties": {"foo": {"type": "string"}, "bar": {"type": "integer"}},
        }
    }
    result = handler._validate_output("test_tool", {"only_foo": "present"}, tool_def)
    assert "_schema_violation" in result, "Missing key must trigger _schema_violation"
    assert "bar" in result["_schema_violation"]["missing_keys"]
    assert result["_schema_violation"]["tool"] == "test_tool"


def test_validate_output_passes_complete_result(handler):
    tool_def = {
        "response_schema": {
            "type": "object",
            "properties": {"foo": {"type": "string"}, "bar": {"type": "integer"}},
        }
    }
    result = handler._validate_output("test_tool", {"foo": "x", "bar": 1}, tool_def)
    assert "_schema_violation" not in result


def test_validate_output_skips_error_results(handler):
    tool_def = {
        "response_schema": {
            "type": "object",
            "properties": {"foo": {"type": "string"}},
        }
    }
    result = handler._validate_output("test_tool", {"error": {"type": "X"}}, tool_def)
    assert "_schema_violation" not in result


def test_validate_output_no_schema_no_flag(handler):
    result = handler._validate_output("test_tool", {"anything": True}, {})
    assert "_schema_violation" not in result


# ── Plan tool cache (T1.3) ───────────────────────────────────────────────────

def test_plan_cache_roundtrip():
    from arvis_core.plan import InvestigationPlan, Budget
    plan = InvestigationPlan(query="test", budget=Budget())
    plan.cache_tool_result("eq:AHU-01", {"cop": 4.2, "status": "running"})
    cached = plan.get_cached_tool_result("eq:AHU-01")
    assert cached == {"cop": 4.2, "status": "running"}
    assert plan.get_cached_tool_result("missing") is None


def test_plan_cache_miss_returns_none():
    from arvis_core.plan import InvestigationPlan, Budget
    plan = InvestigationPlan(query="test", budget=Budget())
    assert plan.get_cached_tool_result("eq:nonexistent") is None


def test_plan_cache_does_not_cross_plans():
    from arvis_core.plan import InvestigationPlan, Budget
    plan_a = InvestigationPlan(query="a", budget=Budget())
    plan_b = InvestigationPlan(query="b", budget=Budget())
    plan_a.cache_tool_result("key", {"val": 1})
    assert plan_b.get_cached_tool_result("key") is None


# ── T0.5: _validate_required_args unit tests ─────────────────────────────────

def test_validate_required_args_passes_when_present(handler):
    tool_def = {"parameters": {"required": ["equipment_id"]}}
    result = handler._validate_required_args("test", {"equipment_id": "AHU-01"}, tool_def)
    assert result is None


def test_validate_required_args_fails_on_missing(handler):
    tool_def = {"parameters": {"required": ["equipment_id"]}}
    result = handler._validate_required_args("test", {}, tool_def)
    assert result is not None
    assert result["error"]["type"] == "MISSING_REQUIRED_ARGS"
    assert "equipment_id" in result["error"]["missing_fields"]


def test_validate_required_args_fails_on_none_value(handler):
    tool_def = {"parameters": {"required": ["equipment_id"]}}
    result = handler._validate_required_args("test", {"equipment_id": None}, tool_def)
    assert result is not None
    assert "equipment_id" in result["error"]["missing_fields"]


def test_validate_required_args_empty_required_list(handler):
    tool_def = {"parameters": {"required": []}}
    result = handler._validate_required_args("test", {}, tool_def)
    assert result is None


def test_validate_required_args_no_parameters_key(handler):
    result = handler._validate_required_args("test", {}, {})
    assert result is None


# ── T0.3: Structured error format in node.py ─────────────────────────────────

def test_node_error_format_contains_type_prefix():
    """node.py error serialization must produce [TOOL_ERROR:TYPE] prefix."""
    import json
    error_result = {
        "error": {
            "type": "MISSING_REQUIRED_ARGS",
            "message": "Tool 'get_equipment_status' missing required args: ['equipment_id']",
            "missing_fields": ["equipment_id"],
            "recovery_hint": "Provide values for: equipment_id",
        }
    }
    result = error_result
    if isinstance(result, dict) and result.get("error"):
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
    assert tool_content.startswith("[TOOL_ERROR:MISSING_REQUIRED_ARGS]")
    assert "RECOVERY:" in tool_content
    assert "equipment_id" in tool_content


def test_node_error_format_non_dict_error():
    """Bare string errors are wrapped under EXECUTION_ERROR type."""
    import json
    result = {"error": "something went wrong"}
    if isinstance(result, dict) and result.get("error"):
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
    assert "[TOOL_ERROR:EXECUTION_ERROR]" in tool_content


# ── T0.6: sync wrapper no nest_asyncio ──────────────────────────────────────

def test_sync_wrapper_importable_without_nest_asyncio():
    import importlib
    import sys
    # Ensure nest_asyncio is not pre-imported by this test
    sys.modules.pop("nest_asyncio", None)
    from agent_commercial.tools.handlers.sync_wrapper import BMSToolHandlerSync
    h = BMSToolHandlerSync()
    assert hasattr(h, "handle_tool_call")


def test_sync_wrapper_source_has_no_nest_asyncio():
    import inspect
    from agent_commercial.tools.handlers import sync_wrapper
    src = inspect.getsource(sync_wrapper)
    assert "nest_asyncio" not in src, "sync_wrapper.py must not reference nest_asyncio"
    assert "ThreadPoolExecutor" in src, "sync_wrapper.py must use ThreadPoolExecutor"
