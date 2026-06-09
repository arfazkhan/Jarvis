"""
Base BMS Tool Handler
=====================

Core handler class with dependency injection and tool routing.
"""

import asyncio
import functools
import logging
from typing import Dict, Any, Optional, Callable

from agent_advisory.explainer import DetailLevel
from agent_commercial.bms_data_model import EquipmentType, AlarmSeverity, AlarmState, EquipmentStatus

# Import mixins for inheritance
from agent_commercial.tools.handlers.equipment import EquipmentHandlerMixin
from agent_commercial.tools.handlers.alarms import AlarmHandlerMixin
from agent_commercial.tools.handlers.energy import EnergyHandlerMixin
from agent_commercial.tools.handlers.maintenance import MaintenanceHandlerMixin
from agent_commercial.tools.handlers.gsas import GSASHandlerMixin
from agent_commercial.tools.handlers.advisory import AdvisoryHandlerMixin
from agent_commercial.tools.handlers.ml import MLHandlerMixin
from agent_commercial.tools.handlers.sovereign import SovereignHandlerMixin

logger = logging.getLogger("arvis.bms.tools")


_TRANSIENT_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError, TimeoutError)

_MAX_RETRIES = 2
_BACKOFF_BASE = 0.3

# T3.1: Per-tool cost classification. Budget governor deducts _TOOL_COST_UNITS per call.
_TOOL_COST_MAP: Dict[str, str] = {
    # ML tools — expensive (model inference + DB)
    "forecast_energy": "expensive",
    "analyze_root_cause": "expensive",
    "simulate_with_uncertainty": "expensive",
    "detect_equipment_faults": "medium",
    "benchmark_building_ml": "medium",
    "find_similar_skills": "cheap",
    # Energy analytics
    "get_energy_consumption": "medium",
    "get_energy_anomalies": "medium",
    "check_cost_impact": "medium",
    "get_burn_rate": "cheap",
    "find_ghost_spaces": "medium",
    "estimate_zone_occupancy": "cheap",
    "get_virtual_sensor_reading": "cheap",
    # Equipment — mostly cheap DB reads
    "get_equipment_status": "cheap",
    "get_calibration_status": "cheap",
    "list_equipment": "cheap",
    "get_equipment_health": "cheap",
    "get_point_history": "medium",
    "get_equipment_specs": "cheap",
    "get_dashboard_overview": "cheap",
    "hybrid_search_knowledge": "medium",
    # Alarms
    "get_active_alarms": "cheap",
    "explain_alarm": "cheap",
    "analyze_cascade": "medium",
    # Maintenance
    "predict_maintenance": "medium",
    "verify_maintenance_work": "cheap",
    # GSAS — report generation expensive
    "generate_gord_report": "expensive",
    "simulate_gsas_impact": "medium",
    # Advisory
    "get_advisory_recommendations": "medium",
    "generate_briefing": "expensive",
    # Sovereign
    "query_skillbook": "cheap",
    "compare_to_fleet": "medium",
    "correlate_events": "medium",
}
_TOOL_COST_UNITS: Dict[str, int] = {"cheap": 1, "medium": 5, "expensive": 20}


def tool_timeout(seconds: int):
    """Decorator to add timeout to tool handlers."""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            try:
                return await asyncio.wait_for(func(self, *args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                return {"error": f"Tool {func.__name__} timed out after {seconds}s"}
        return wrapper
    return decorator


class BMSToolHandler(
    EquipmentHandlerMixin,
    AlarmHandlerMixin,
    EnergyHandlerMixin,
    MaintenanceHandlerMixin,
    GSASHandlerMixin,
    AdvisoryHandlerMixin,
    MLHandlerMixin,
    SovereignHandlerMixin
):
    """
    Handler for BMS tools, to be integrated with the main ToolExecutor.

    Example integration:
        >>> handler = BMSToolHandler(bms_state, alarm_engine, energy_analyzer, pm_engine)
        >>> result = await handler.execute("get_equipment_status", {"equipment_id": "AHU-01"})
    """

    def __init__(
        self,
        bms_state=None,
        alarm_engine=None,
        energy_analyzer=None,
        predictive_engine=None,
        # Phase 1: Advisory components
        recommendation_tracker=None,
        preference_learner=None,
        advisor=None,  # Phase 2: Full Advisor
        # Phase 3: Proactive Components
        goal_generator=None,
        briefing_scheduler=None,
        feedback_loop=None,
        # Phase 5: World Models & Explanations
        explainer=None,
        world_model=None,
        trust_calibrator=None,
        online_learner=None,
        # Phase 7 & 8: Grounding
        knowledge_base=None,
        graph_rag=None,
        hybrid_rag=None,
        gsas_reporter=None,
        # Mem-8: Unified memory façade
        memory_orchestrator=None,
    ):
        # GroundingGuard — tracks every tool result so the response layer
        # can verify cited numbers have real provenance.
        from agent_commercial.grounding_guard import GroundingGuard
        self.grounding_guard = GroundingGuard()

        self.bms_state = bms_state
        self.alarm_engine = alarm_engine
        self.energy_analyzer = energy_analyzer
        self.predictive_engine = predictive_engine
        self.recommendation_tracker = recommendation_tracker
        self.preference_learner = preference_learner
        self.advisor = advisor
        self.goal_generator = goal_generator
        self.briefing_scheduler = briefing_scheduler
        self.feedback_loop = feedback_loop
        self.explainer = explainer
        self.world_model = world_model

        # Phase 6
        self.online_learner = online_learner
        self.trust_calibrator = trust_calibrator

        # Phase 7 & 8
        self.knowledge_base = knowledge_base
        self.graph_rag = graph_rag
        self.hybrid_rag = hybrid_rag
        self.gsas_reporter = gsas_reporter

        # Mem-8: Unified memory façade
        self.memory_orchestrator = memory_orchestrator

        # Phase 1: Advisory System Components (fallback/direct use)
        if advisor:
            self.tracker = advisor.tracker
            self.preference_learner = advisor.preference_learner
        else:
            self.tracker = recommendation_tracker
            self.preference_learner = preference_learner

        # T0.5: Build handler + tool-def registries from mixin get_handlers()
        self._handler_registry: Dict[str, Callable] = {}
        self._tool_def_registry: Dict[str, Dict] = {}
        self._build_registries()
    
    def _build_registries(self) -> None:
        """Populate _handler_registry and _tool_def_registry from all mixins."""
        # Handler registry: mixin.get_handlers() -> {tool_name: method}
        seen = set()
        for cls in type(self).__mro__:
            if cls is BMSToolHandler or cls is object:
                continue
            if "get_handlers" in cls.__dict__ and cls not in seen:
                seen.add(cls)
                try:
                    self._handler_registry.update(cls.get_handlers(self))
                except Exception:
                    pass

        # Tool def registry: built from the canonical definitions package
        try:
            from agent_commercial.tools.definitions import get_all_tools
            for tool_def in get_all_tools():
                name = tool_def.get("name")
                if name:
                    self._tool_def_registry[name] = tool_def
        except Exception:
            pass

    def _validate_required_args(self, tool_name: str, args: Dict, tool_def: Dict) -> Optional[Dict]:
        """Return MISSING_REQUIRED_ARGS error dict if required fields absent, else None."""
        required = tool_def.get("parameters", {}).get("required", [])
        missing = [f for f in required if f not in args or args[f] is None]
        if not missing:
            return None
        return {
            "error": {
                "type": "MISSING_REQUIRED_ARGS",
                "message": f"Tool '{tool_name}' missing required args: {missing}",
                "missing_fields": missing,
                "recovery_hint": f"Provide values for: {', '.join(missing)}",
            }
        }

    def _validate_output(self, tool_name: str, result: Dict, tool_def: Dict) -> Dict:
        """Enforce schema compliance on tool output.

        Behaviour:
          - If result is not a dict, wraps it in an error dict with all schema keys backfilled.
          - If schema keys are missing, backfills them with type-safe defaults and records
            a _schema_violation entry.  This runs even on error responses so that callers
            can always destructure result[key] without KeyError.
          - Pure-error dicts (containing *only* an 'error' key) are exempt to avoid
            polluting clean error signals with phantom zeros.
        """
        schema = tool_def.get("response_schema")
        if not schema:
            return result

        # Non-dict result — wrap safely
        if not isinstance(result, dict):
            logger.error(
                f"[ToolHandler] {tool_name} returned non-dict ({type(result).__name__}); "
                "wrapping in schema-compliant error response."
            )
            result = {"error": f"Tool returned non-dict result: {type(result).__name__}"}

        try:
            properties = schema.get("properties", {})

            # Exempt: pure single-key error dicts (avoids polluting clean error signals)
            is_pure_error = set(result.keys()) <= {"error"}

            missing_keys = [k for k in properties if k not in result and not is_pure_error]
            if missing_keys:
                result["_schema_violation"] = {
                    "missing_keys": missing_keys,
                    "tool": tool_name,
                }
                logger.error(
                    f"[ToolHandler] SCHEMA VIOLATION — {tool_name} missing keys: {missing_keys}. "
                    "Backfilling with type-safe defaults. Fix the handler to eliminate this."
                )

                # Backfill missing keys with type-safe schema-compliant defaults
                for k in missing_keys:
                    prop_def = properties.get(k, {})
                    if not isinstance(prop_def, dict):
                        result[k] = None
                        continue
                    prop_type = prop_def.get("type")
                    if prop_type == "array":
                        result[k] = []
                    elif prop_type == "object":
                        result[k] = {}
                    elif prop_type == "string":
                        result[k] = ""
                    elif prop_type in ("number", "integer"):
                        result[k] = 0
                    elif prop_type == "boolean":
                        result[k] = False
                    else:
                        result[k] = None
        except Exception as e:
            logger.error(f"[ToolHandler] Output validation/backfilling failed: {e}")
        return result

    def _sanitize_args(self, tool_name: str, args: Any) -> Dict[str, Any]:
        """Hard type enforcement for tool arguments to prevent LLM type hallucinations."""
        if not isinstance(args, dict):
            return {}
            
        # Integer fields
        int_fields = {"limit", "top_k", "forecast_hours", "time_window_minutes", "minutes", "window_days", "system_depth"}
        # Float/Number fields
        float_fields = {"current_value", "proposed_value", "confidence_level", "impact", "current_temp", "target_temp", "total_kw"}
        
        sanitized = args.copy()
        for key, value in sanitized.items():
            if key in int_fields:
                try:
                    sanitized[key] = int(float(str(value)))  # Handle "5" or "5.0"
                except (ValueError, TypeError):
                    logger.warning(f"[ToolHandler] Failed to cast {key}='{value}' to int")
            elif key in float_fields:
                try:
                    sanitized[key] = float(str(value))
                except (ValueError, TypeError):
                    logger.warning(f"[ToolHandler] Failed to cast {key}='{value}' to float")
                    
        return sanitized

    @tool_timeout(seconds=5)
    async def execute(self, tool_name: str, args: Dict[str, Any], plan=None, task_id: str = "", node_name: str = "") -> Dict[str, Any]:
        """Execute a BMS tool and return result with observability."""
        import time
        start_time = time.perf_counter()

        # 1. Hard Type Enforcement & Safety
        if args is None:
            args = {}
        args = self._sanitize_args(tool_name, args)

        # T0.5: resolve handler + tool def from registry (fallback to getattr for unlisted tools)
        tool_def = self._tool_def_registry.get(tool_name, {})
        handler = self._handler_registry.get(tool_name) or getattr(self, f"_handle_{tool_name}", None)

        result = {}
        success = False
        error_msg = None

        if not handler:
            error_msg = f"Unknown tool: {tool_name}"
            result = {
                "error": {
                    "type": "UNKNOWN_TOOL",
                    "message": error_msg,
                    "recovery_hint": "Check BMS tool documentation for available operations.",
                }
            }
        else:
            # T0.1: Required arg validation — fail fast before reaching handler
            validation_error = self._validate_required_args(tool_name, args, tool_def)
            if validation_error is not None:
                return validation_error

            # Retry with exponential backoff for transient failures
            last_exception = None
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    result = await handler(args)
                    if isinstance(result, dict) and "error" in result:
                        error_msg = str(result["error"])
                        if isinstance(result["error"], str):
                            result["error"] = {
                                "type": "EXECUTION_ERROR",
                                "message": result["error"],
                                "recovery_hint": "Verify arguments and equipment status before retrying.",
                            }
                    else:
                        success = True
                    last_exception = None
                    break
                except _TRANSIENT_ERRORS as e:
                    last_exception = e
                    if attempt < _MAX_RETRIES:
                        wait = _BACKOFF_BASE * (2 ** attempt)
                        logger.warning(f"[ToolHandler] {tool_name} transient error (attempt {attempt+1}): {e}. Retrying in {wait:.1f}s.")
                        await asyncio.sleep(wait)
                    else:
                        logger.error(f"[ToolHandler] {tool_name} failed after {_MAX_RETRIES+1} attempts: {e}")
                except Exception as e:
                    last_exception = e
                    break

            if last_exception is not None:
                logger.exception(f"[ToolHandler] Error executing {tool_name}: {last_exception}")
                error_msg = str(last_exception)
                result = {
                    "error": {
                        "type": "CRITICAL_FAILURE",
                        "message": error_msg,
                        "recovery_hint": "Internal system error. Check logs or try a different approach.",
                    }
                }

            # T0.2: Output schema validation (non-blocking — injects _schema_violation flag)
            if success and tool_def:
                result = self._validate_output(tool_name, result, tool_def)
        
        # T1.1+T1.2: Write Evidence + Span into InvestigationPlan at tool boundary
        if plan is not None and isinstance(result, dict):
            try:
                from arvis_core.evidence import Evidence
                ev = Evidence.from_tool_result(tool_name, result, node_name=node_name, task_id=task_id)
                plan.evidence.add(ev)
                if not result.get("error") and task_id:
                    for _t in plan.tasks:
                        if _t.id == task_id:
                            _t.evidence_ids.append(ev.id)
                            break
                duration_ms = (time.perf_counter() - start_time) * 1000
                _cost_class = _TOOL_COST_MAP.get(tool_name, "cheap")
                _cost_units = _TOOL_COST_UNITS[_cost_class]
                plan.record_span(
                    task_id=task_id,
                    node_name=node_name,
                    action=f"tool_call:{tool_name}",
                    tool_name=tool_name,
                    tool_args=args,
                    evidence_id=ev.id,
                    duration_ms=duration_ms,
                )
                # Budget charged once per tool invocation (not per retry attempt — retries are internal implementation detail)
                plan.budget.record_tool_call(cost_usd=_cost_units * 0.001)
            except Exception as _plan_err:
                logger.debug(f"[ToolHandler] Plan evidence write failed (non-fatal): {_plan_err}")

        # 2. Register result with GroundingGuard — tracks provenance of all numbers
        #    Uses per-request contextvar for concurrency isolation
        try:
            from agent_commercial.grounding_guard import get_active_guard
            _guard = get_active_guard() or self.grounding_guard
            _guard.register_tool_result(tool_name, result)
        except Exception as _gg_err:
            logger.debug(f"[GroundingGuard] register failed (non-fatal): {_gg_err}")

        # 3. Observability Logging
        duration_ms = (time.perf_counter() - start_time) * 1000

        # 4. GLASS BOX: Broadcast tool execution to frontend
        try:
            from agent_commercial.api.sse_broadcaster import SSEBroadcaster
            import asyncio
            try:
                _loop = asyncio.get_running_loop()
            except RuntimeError:
                _loop = None
            if _loop is not None and tool_name not in ("task_boundary",):
                _loop.create_task(SSEBroadcaster().broadcast("tool_use", {
                    "tool": tool_name,
                    "args": args,
                    "success": success,
                    "duration_ms": round(duration_ms, 2)
                }))
        except Exception as e:
            logger.debug(f"[ToolHandler] Failed to broadcast tool_use: {e}")
            
        if self.knowledge_base and hasattr(self.knowledge_base, "log_tool_usage"):
            try:
                await self.knowledge_base.log_tool_usage(
                    tool_name=tool_name,
                    args=args,
                    success=success,
                    duration_ms=duration_ms,
                    error=error_msg
                )
            except Exception as le:
                logger.error(f"Failed to log tool usage: {le}")
                
        return result

    async def _handle_task_boundary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle technical execution of task boundary - simply returns args for Agent interception."""
        return args
