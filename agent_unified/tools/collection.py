from typing import Dict, List, Optional, Tuple, Any
from .base import BaseTool, ToolResult

class ToolCollection:
    """Collection of tools available to an agent"""
    
    def __init__(self, *tools: BaseTool):
        self.tools: List[BaseTool] = list(tools)
        self.tool_map: Dict[str, BaseTool] = {t.name: t for t in tools}
    
    def add_tools(self, *tools: BaseTool):
        self.tools.extend(tools)
        self.tool_map.update({t.name: t for t in tools})
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self.tool_map.get(name)
    
    async def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(error=f"Tool not found: {name}")
            
        return await tool.execute(**kwargs)
    
    def to_params(self) -> List[Dict]:
        return [tool.to_param() for tool in self.tools]
