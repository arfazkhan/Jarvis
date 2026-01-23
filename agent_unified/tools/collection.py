"""
ARVIS Tool Collection (Production-Ready)
==========================================

Enhanced tool collection with:
- Parallel tool execution
- Tool lifecycle management
- Health monitoring
- Aggregated metrics
"""

import asyncio
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Set

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, ToolMetrics


logger = logging.getLogger("arvis.unified.collection")


class CollectionMetrics(BaseModel):
    """Aggregated metrics for the tool collection."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_execution_time_ms: int = 0
    tools_with_errors: Set[str] = Field(default_factory=set)
    
    class Config:
        arbitrary_types_allowed = True


class ToolCollection:
    """
    Production-ready collection of tools with parallel execution support.
    
    Features:
    - Parallel tool execution with asyncio.gather
    - Tool lifecycle management (init, cleanup)
    - Health monitoring
    - Aggregated metrics
    - Tool grouping
    """
    
    def __init__(self, *tools: BaseTool):
        """
        Initialize collection with tools.
        
        Args:
            *tools: Variable number of BaseTool instances
        """
        self._tools: Dict[str, BaseTool] = {}
        self._tool_groups: Dict[str, List[str]] = {}
        self._metrics = CollectionMetrics()
        
        for tool in tools:
            self.add(tool)
    
    def add(self, tool: BaseTool, group: Optional[str] = None) -> None:
        """
        Add a tool to the collection.
        
        Args:
            tool: Tool instance to add
            group: Optional group name for organization
        """
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")
        
        self._tools[tool.name] = tool
        
        if group:
            if group not in self._tool_groups:
                self._tool_groups[group] = []
            self._tool_groups[group].append(tool.name)
        
        logger.debug(f"Added tool: {tool.name}")
    
    def remove(self, name: str) -> Optional[BaseTool]:
        """
        Remove a tool from the collection.
        
        Args:
            name: Tool name to remove
            
        Returns:
            Removed tool or None if not found
        """
        tool = self._tools.pop(name, None)
        
        # Remove from groups
        for group_tools in self._tool_groups.values():
            if name in group_tools:
                group_tools.remove(name)
        
        return tool
    
    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def __getitem__(self, name: str) -> BaseTool:
        """Get a tool by name with bracket notation."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]
    
    def __contains__(self, name: str) -> bool:
        """Check if tool exists in collection."""
        return name in self._tools
    
    def __len__(self) -> int:
        """Get number of tools in collection."""
        return len(self._tools)
    
    def __iter__(self) -> Iterator[BaseTool]:
        """Iterate over tools."""
        return iter(self._tools.values())
    
    @property
    def names(self) -> List[str]:
        """Get all tool names."""
        return list(self._tools.keys())
    
    def get_by_group(self, group: str) -> List[BaseTool]:
        """Get all tools in a group."""
        names = self._tool_groups.get(group, [])
        return [self._tools[n] for n in names if n in self._tools]
    
    async def execute(self, name: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name.
        
        Args:
            name: Tool name
            **kwargs: Tool arguments
            
        Returns:
            ToolResult from execution
        """
        if name not in self._tools:
            return ToolResult(error=f"Tool not found: {name}")
        
        start_time = time.time()
        
        try:
            result = await self._tools[name](**kwargs)
            
            # Update collection metrics
            self._metrics.total_calls += 1
            self._metrics.total_execution_time_ms += int((time.time() - start_time) * 1000)
            
            if result.success:
                self._metrics.successful_calls += 1
            else:
                self._metrics.failed_calls += 1
                self._metrics.tools_with_errors.add(name)
            
            return result
            
        except Exception as e:
            logger.error(f"Tool execution error for {name}: {e}")
            self._metrics.total_calls += 1
            self._metrics.failed_calls += 1
            self._metrics.tools_with_errors.add(name)
            return ToolResult(error=f"Execution failed: {str(e)}")
    
    async def execute_parallel(
        self,
        calls: List[Dict[str, Any]],
        fail_fast: bool = False
    ) -> List[ToolResult]:
        """
        Execute multiple tool calls in parallel.
        
        Args:
            calls: List of {"name": str, "args": dict} objects
            fail_fast: If True, cancel remaining on first failure
            
        Returns:
            List of ToolResults in same order as calls
        """
        if not calls:
            return []
        
        logger.info(f"Executing {len(calls)} tools in parallel")
        
        async def execute_one(call: Dict[str, Any]) -> ToolResult:
            name = call.get("name", "")
            args = call.get("args", {})
            return await self.execute(name, **args)
        
        tasks = [execute_one(call) for call in calls]
        
        if fail_fast:
            # Use gather with return_exceptions=False to fail fast
            try:
                results = await asyncio.gather(*tasks)
                return results
            except Exception as e:
                # Cancel remaining tasks
                for task in tasks:
                    if not task.done():
                        task.cancel()
                return [ToolResult(error=f"Parallel execution failed: {str(e)}")]
        else:
            # Execute all, collect results including exceptions
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Convert exceptions to ToolResults
            return [
                r if isinstance(r, ToolResult) else ToolResult(error=str(r))
                for r in results
            ]
    
    async def execute_sequential(
        self,
        calls: List[Dict[str, Any]],
        stop_on_error: bool = False
    ) -> List[ToolResult]:
        """
        Execute multiple tool calls sequentially.
        
        Args:
            calls: List of {"name": str, "args": dict} objects
            stop_on_error: If True, stop on first error
            
        Returns:
            List of ToolResults
        """
        results = []
        
        for call in calls:
            name = call.get("name", "")
            args = call.get("args", {})
            
            result = await self.execute(name, **args)
            results.append(result)
            
            if stop_on_error and not result.success:
                break
        
        return results
    
    def to_params(self) -> List[dict]:
        """Convert all tools to OpenAI function calling format."""
        return [tool.to_param() for tool in self._tools.values()]
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of all tools.
        
        Returns:
            Health status for collection and each tool
        """
        tool_health = {}
        
        for name, tool in self._tools.items():
            try:
                tool_health[name] = await tool.health_check()
            except Exception as e:
                tool_health[name] = {"healthy": False, "error": str(e)}
        
        healthy_count = sum(1 for h in tool_health.values() if h.get("healthy", False))
        
        return {
            "collection_healthy": healthy_count == len(self._tools),
            "total_tools": len(self._tools),
            "healthy_tools": healthy_count,
            "unhealthy_tools": len(self._tools) - healthy_count,
            "tools_with_errors": list(self._metrics.tools_with_errors),
            "metrics": {
                "total_calls": self._metrics.total_calls,
                "successful_calls": self._metrics.successful_calls,
                "failed_calls": self._metrics.failed_calls,
                "total_execution_time_ms": self._metrics.total_execution_time_ms
            },
            "tool_details": tool_health
        }
    
    def get_metrics(self) -> Dict[str, ToolMetrics]:
        """Get metrics for all tools."""
        return {name: tool.get_metrics() for name, tool in self._tools.items()}
    
    def clear_all_caches(self):
        """Clear caches for all tools."""
        for tool in self._tools.values():
            tool.clear_cache()
    
    async def cleanup(self):
        """Clean up all tool resources."""
        for tool in self._tools.values():
            if hasattr(tool, 'cleanup'):
                try:
                    await tool.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up tool {tool.name}: {e}")
    
    def summary(self) -> str:
        """Get a summary of the collection."""
        lines = [f"ToolCollection ({len(self._tools)} tools)"]
        
        if self._tool_groups:
            for group, names in self._tool_groups.items():
                lines.append(f"  {group}: {len(names)} tools")
        else:
            for name in self._tools:
                lines.append(f"  - {name}")
        
        return "\n".join(lines)
