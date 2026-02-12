from typing import Optional, Any
from agent_unified.tools.base import BaseTool, ToolResult

class AnalyzeEnergy(BaseTool):
    """Analyze energy usage"""
    name: str = "analyze_energy"
    description: str = "Analyze energy consumption for a specific period."
    parameters: dict = {
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": ["today", "yesterday", "this_week", "this_month"]}
        }
    }
    
    energy_analyzer: Optional[Any] = None
    
    async def execute(self, period: str = "today") -> ToolResult:
        if not self.energy_analyzer:
            return self.fail_response("Energy analyzer not available")
            
        report = self.energy_analyzer.analyze(period=period)
        return self.success_response(report)

class GetWastePatterns(BaseTool):
    """Get energy waste patterns"""
    name: str = "get_energy_anomalies"
    description: str = "Get detected energy waste patterns and anomalies."
    
    energy_analyzer: Optional[Any] = None
    
    async def execute(self) -> ToolResult:
        if not self.energy_analyzer:
            return self.fail_response("Energy analyzer not available")
            
        anomalies = self.energy_analyzer.detect_anomalies()
        return self.success_response(anomalies)
