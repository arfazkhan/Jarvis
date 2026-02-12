from typing import Optional, Any
from agent_unified.tools.base import BaseTool, ToolResult

class GetGSASStatus(BaseTool):
    """Get GSAS status"""
    name: str = "get_gsas_status"
    description: str = "Get current GSAS sustainability compliance status."
    
    bms_state: Optional[Any] = None
    
    async def execute(self) -> ToolResult:
        if not self.bms_state or not hasattr(self.bms_state, 'gsas_reporter'):
            return self.fail_response("GSAS reporter not available")
            
        status = self.bms_state.gsas_reporter.get_status()
        return self.success_response(status)
