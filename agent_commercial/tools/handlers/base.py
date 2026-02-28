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
        graph_rag=None
    ):
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
        
        # Phase 1: Advisory System Components (fallback/direct use)
        if advisor:
            self.tracker = advisor.tracker
            self.preference_learner = advisor.preference_learner
        else:
            self.tracker = recommendation_tracker
            self.preference_learner = preference_learner
    
    def _sanitize_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Hard type enforcement for tool arguments to prevent LLM type hallucinations."""
        if not args:
            return args
            
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
    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a BMS tool and return result with observability."""
        import time
        start_time = time.perf_counter()
        
        # 1. Hard Type Enforcement
        args = self._sanitize_args(tool_name, args)
        
        # Route to handler method dynamically
        handler_name = f"_handle_{tool_name}"
        handler = getattr(self, handler_name, None)
        
        result = {}
        success = False
        error_msg = None
        
        if not handler:
            error_msg = f"Unknown tool: {tool_name}"
            result = {
                "error": {
                    "type": "UNKNOWN_TOOL",
                    "message": error_msg,
                    "recovery_hint": "Check BMS tool documentation for available operations."
                }
            }
        else:
            try:
                result = await handler(args)
                if isinstance(result, dict) and "error" in result:
                    error_msg = str(result["error"])
                    # Wrap simple string errors in structured format
                    if isinstance(result["error"], str):
                        result["error"] = {
                            "type": "EXECUTION_ERROR",
                            "message": result["error"],
                            "recovery_hint": "Verify arguments and equipment status before retrying."
                        }
                else:
                    success = True
            except Exception as e:
                logger.exception(f"[ToolHandler] Error executing {tool_name}: {e}")
                error_msg = str(e)
                result = {
                    "error": {
                        "type": "CRITICAL_FAILURE",
                        "message": error_msg,
                        "recovery_hint": "Internal system error. Check logs or try a different approach."
                    }
                }
        
        # 2. Observability Logging
        duration_ms = (time.perf_counter() - start_time) * 1000
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
