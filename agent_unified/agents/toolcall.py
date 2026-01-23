"""
ARVIS Tool Call Agent (Production-Ready)
==========================================

Enhanced agent with:
- Structured tracing with correlation IDs
- Parallel tool execution
- Better error handling
- Execution metrics
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import Field

from agent_unified.schema import AgentState, Message, ToolCall, ToolChoice, Function
from agent_unified.tools.base import ToolResult
from agent_unified.tools.collection import ToolCollection
from agent_unified.llm import UnifiedLLM
from .react import ARVISReActAgent


logger = logging.getLogger("arvis.unified.toolcall")


class ExecutionTrace(Dict):
    """Trace of a single tool execution."""
    pass


class AgentMetrics:
    """Runtime metrics for the agent."""
    
    def __init__(self):
        self.total_steps = 0
        self.total_tool_calls = 0
        self.successful_tool_calls = 0
        self.failed_tool_calls = 0
        self.total_execution_time_ms = 0
        self.llm_calls = 0
        self.llm_tokens_used = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_steps": self.total_steps,
            "total_tool_calls": self.total_tool_calls,
            "successful_tool_calls": self.successful_tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "total_execution_time_ms": self.total_execution_time_ms,
            "llm_calls": self.llm_calls,
            "success_rate": self.successful_tool_calls / max(1, self.total_tool_calls)
        }


class ARVISToolAgent(ARVISReActAgent):
    """
    Production-ready agent with tool calling capabilities.
    
    Features:
    - Structured tracing with correlation IDs
    - Parallel tool execution
    - Execution metrics
    - Enhanced error handling
    """
    
    # LLM client
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    
    # Tools
    available_tools: ToolCollection = Field(default_factory=ToolCollection)
    tool_choices: ToolChoice = Field(default=ToolChoice.AUTO)
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])
    
    # Current pending tool calls
    tool_calls: List[ToolCall] = Field(default_factory=list)
    
    # Execution settings
    parallel_tool_calls: bool = Field(default=True, description="Execute tools in parallel")
    max_observe: int = Field(default=10000, description="Max chars in tool observation")
    
    # Tracing
    execution_traces: List[ExecutionTrace] = Field(default_factory=list)
    _correlation_id: Optional[str] = None
    _step_start_time: float = 0
    _metrics: AgentMetrics = None
    
    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self._metrics = AgentMetrics()
    
    async def think(self) -> bool:
        """
        Generate tool calls via LLM with tracing.
        
        Returns:
            True if tool calls were generated
        """
        self._step_start_time = time.time()
        self._correlation_id = str(uuid.uuid4())[:8]
        
        logger.info(f"[{self.name}:{self._correlation_id}] Thinking (step {self.current_step})...")
        
        # Build messages for LLM
        messages = [msg.to_dict() for msg in self.memory.messages]
        
        # Add next step prompt if present
        if self.next_step_prompt:
            messages.append({"role": "user", "content": self.next_step_prompt})
        
        # Get system messages
        system_msgs = None
        if self.system_prompt:
            system_msgs = [{"role": "system", "content": self.system_prompt}]
        
        try:
            # Call LLM with tools
            llm_start = time.time()
            response = await self.llm.ask_tool(
                messages=messages,
                system_msgs=system_msgs,
                tools=self.available_tools.to_params() if len(self.available_tools) > 0 else None,
                tool_choice=self.tool_choices.value
            )
            llm_time_ms = int((time.time() - llm_start) * 1000)
            self._metrics.llm_calls += 1
            
            # Check for tool calls in response
            if hasattr(response, 'tool_calls') and response.tool_calls:
                self.tool_calls = [
                    ToolCall(
                        id=tc.id,
                        function=Function(
                            name=tc.function.name,
                            arguments=tc.function.arguments
                        )
                    )
                    for tc in response.tool_calls
                ]
                
                # Store assistant message with tool calls
                self.memory.add_message(
                    Message.from_tool_calls(response.tool_calls, response.content or "")
                )
                
                logger.info(
                    f"[{self.name}:{self._correlation_id}] Generated {len(self.tool_calls)} tool calls "
                    f"in {llm_time_ms}ms: {[tc.function.name for tc in self.tool_calls]}"
                )
                
                # Record trace
                self.execution_traces.append({
                    "type": "think",
                    "correlation_id": self._correlation_id,
                    "step": self.current_step,
                    "tool_calls": [tc.function.name for tc in self.tool_calls],
                    "llm_time_ms": llm_time_ms
                })
                
                return True
            
            # No tool calls - store text response
            if hasattr(response, 'content') and response.content:
                self.update_memory("assistant", response.content)
                logger.info(f"[{self.name}:{self._correlation_id}] Text response (no tools)")
            
            return False
            
        except Exception as e:
            logger.error(f"[{self.name}:{self._correlation_id}] Error in think(): {e}")
            self.update_memory("assistant", f"Error generating response: {str(e)}")
            
            self.execution_traces.append({
                "type": "think_error",
                "correlation_id": self._correlation_id,
                "step": self.current_step,
                "error": str(e)
            })
            
            return False
    
    async def act(self) -> str:
        """
        Execute pending tool calls with parallel/sequential support.
        
        Returns:
            String describing execution results
        """
        if not self.tool_calls:
            return "No tool calls to execute"
        
        logger.info(
            f"[{self.name}:{self._correlation_id}] Executing {len(self.tool_calls)} tool calls "
            f"(parallel={self.parallel_tool_calls})"
        )
        
        self._metrics.total_steps += 1
        
        if self.parallel_tool_calls and len(self.tool_calls) > 1:
            results = await self._execute_parallel()
        else:
            results = await self._execute_sequential()
        
        # Clear pending calls
        self.tool_calls = []
        
        # Calculate step time
        step_time_ms = int((time.time() - self._step_start_time) * 1000)
        
        # Build result summary
        summary_parts = []
        for name, result in results:
            status = "✓" if result.success else "✗"
            output = str(result)[:100]
            summary_parts.append(f"{status} {name}: {output}")
            
            if result.success:
                self._metrics.successful_tool_calls += 1
            else:
                self._metrics.failed_tool_calls += 1
        
        self._metrics.total_execution_time_ms += step_time_ms
        
        logger.info(
            f"[{self.name}:{self._correlation_id}] Step completed in {step_time_ms}ms "
            f"({len([r for _, r in results if r.success])}/{len(results)} successful)"
        )
        
        return "\n".join(summary_parts)
    
    async def _execute_parallel(self) -> List[tuple]:
        """Execute tool calls in parallel."""
        
        async def execute_one(tc: ToolCall) -> tuple:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                logger.error(f"[{self.name}:{self._correlation_id}] Invalid JSON for {name}: {e}")
                args = {}
            
            result = await self._execute_tool(name, tc.id, **args)
            return (name, result)
        
        tasks = [execute_one(tc) for tc in self.tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any exceptions
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                name = self.tool_calls[i].function.name
                processed.append((name, ToolResult(error=str(result))))
            else:
                processed.append(result)
        
        return processed
    
    async def _execute_sequential(self) -> List[tuple]:
        """Execute tool calls sequentially."""
        results = []
        
        for tc in self.tool_calls:
            name = tc.function.name
            
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError as e:
                logger.error(f"[{self.name}:{self._correlation_id}] Invalid JSON for {name}: {e}")
                args = {}
            
            result = await self._execute_tool(name, tc.id, **args)
            results.append((name, result))
            
            # Handle special tools
            if self._is_special_tool(name):
                await self._handle_special_tool(name, result)
        
        return results
    
    async def _execute_tool(self, name: str, tool_call_id: str, **kwargs) -> ToolResult:
        """
        Execute a single tool with tracing.
        
        Args:
            name: Tool name
            tool_call_id: Tool call ID for result tracking
            **kwargs: Tool arguments
            
        Returns:
            ToolResult from execution
        """
        start_time = time.time()
        self._metrics.total_tool_calls += 1
        
        logger.info(f"[{self.name}:{self._correlation_id}] Executing tool: {name}")
        
        try:
            result = await self.available_tools.execute(name, **kwargs)
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Truncate if too long
            result_str = str(result)
            if len(result_str) > self.max_observe:
                result_str = result_str[:self.max_observe] + "... (truncated)"
            
            # Store tool result in memory
            self.memory.add_message(
                Message.tool_message(
                    content=result_str,
                    tool_call_id=tool_call_id,
                    name=name
                )
            )
            
            # Record trace
            self.execution_traces.append({
                "type": "tool_execution",
                "correlation_id": self._correlation_id,
                "step": self.current_step,
                "tool": name,
                "success": result.success,
                "execution_time_ms": execution_time_ms,
                "cached": getattr(result, 'cached', False)
            })
            
            return result
            
        except Exception as e:
            error_msg = f"Tool execution error: {str(e)}"
            logger.error(f"[{self.name}:{self._correlation_id}] {error_msg}")
            
            self.memory.add_message(
                Message.tool_message(
                    content=error_msg,
                    tool_call_id=tool_call_id,
                    name=name
                )
            )
            
            self.execution_traces.append({
                "type": "tool_error",
                "correlation_id": self._correlation_id,
                "step": self.current_step,
                "tool": name,
                "error": str(e)
            })
            
            return ToolResult(error=error_msg)
    
    def _is_special_tool(self, name: str) -> bool:
        """Check if tool is special (triggers state change)."""
        return name in self.special_tool_names
    
    async def _handle_special_tool(self, name: str, result: Any) -> None:
        """Handle special tool execution."""
        if name == "terminate":
            logger.info(f"[{self.name}:{self._correlation_id}] Terminate called - finishing execution")
            self.state = AgentState.FINISHED
    
    async def run(self, request: Optional[str] = None) -> str:
        """Run the agent with full lifecycle management."""
        run_id = str(uuid.uuid4())[:8]
        logger.info(f"[{self.name}:{run_id}] Starting run")
        
        try:
            result = await super().run(request)
            
            logger.info(
                f"[{self.name}:{run_id}] Run completed: {self._metrics.total_steps} steps, "
                f"{self._metrics.total_tool_calls} tool calls, "
                f"{self._metrics.total_execution_time_ms}ms total"
            )
            
            return result
        finally:
            await self.cleanup()
    
    async def cleanup(self) -> None:
        """Clean up tool resources."""
        await self.available_tools.cleanup()
        logger.info(f"[{self.name}] Cleanup complete")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get agent execution metrics."""
        return self._metrics.to_dict()
    
    def get_traces(self) -> List[ExecutionTrace]:
        """Get execution traces."""
        return self.execution_traces
    
    def clear_traces(self):
        """Clear execution traces."""
        self.execution_traces = []
    
    async def health_check(self) -> Dict[str, Any]:
        """Check agent and tool health."""
        tool_health = await self.available_tools.health_check()
        
        return {
            "agent": self.name,
            "state": self.state.value,
            "healthy": tool_health.get("collection_healthy", False),
            "metrics": self._metrics.to_dict(),
            "tools": tool_health
        }
