"""
ARVIS Tool Collection
====================

Container for managing multiple tools available to an agent.
"""

from typing import Dict, List, Optional, Tuple

from .base import BaseTool, ToolResult


class ToolCollection:
    """
    Collection of tools available to an agent.
    
    Provides:
    - Tool registration and lookup
    - Batch parameter conversion for LLM
    - Tool execution by name
    """
    
    def __init__(self, *tools: BaseTool):
        """
        Initialize with tools.
        
        Args:
            *tools: Variable number of BaseTool instances
        """
        self.tools: Tuple[BaseTool, ...] = tools
        self.tool_map: Dict[str, BaseTool] = {t.name: t for t in tools}
    
    def add_tools(self, *tools: BaseTool) -> None:
        """Add more tools to the collection"""
        self.tools = self.tools + tools
        self.tool_map.update({t.name: t for t in tools})
    
    def remove_tool(self, name: str) -> Optional[BaseTool]:
        """Remove a tool by name"""
        tool = self.tool_map.pop(name, None)
        if tool:
            self.tools = tuple(t for t in self.tools if t.name != name)
        return tool
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name"""
        return self.tool_map.get(name)
    
    def has_tool(self, name: str) -> bool:
        """Check if a tool exists"""
        return name in self.tool_map
    
    async def execute(self, name: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name.
        
        Args:
            name: Tool name
            **kwargs: Tool parameters
            
        Returns:
            ToolResult from tool execution
        """
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(error=f"Tool not found: {name}")
        
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(error=f"Tool execution error: {str(e)}")
    
    def to_params(self) -> List[Dict]:
        """
        Convert all tools to OpenAI function calling format.
        
        Returns:
            List of tool parameter dicts
        """
        return [tool.to_param() for tool in self.tools]
    
    def get_tool_names(self) -> List[str]:
        """Get list of all tool names"""
        return list(self.tool_map.keys())
    
    def __len__(self) -> int:
        return len(self.tools)
    
    def __iter__(self):
        return iter(self.tools)
    
    def __contains__(self, name: str) -> bool:
        return name in self.tool_map
