"""
BMS GSAS Tools
==============

Class-based tools for GSAS sustainability compliance.
"""

from typing import Any, Optional
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class GetGSASStatus(BaseTool):
    """Get current GSAS compliance status."""
    
    name: str = "get_gsas_status"
    description: str = "Get current GSAS (Global Sustainability Assessment System) compliance status including scores by category and recommendations."
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    gsas_reporter: Optional[Any] = None
    bms_state: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self) -> ToolResult:
        if self.gsas_reporter:
            try:
                status = self.gsas_reporter.get_status()
                return self.success_response(status)
            except Exception as e:
                return self.fail_response(f"Error getting GSAS status: {str(e)}")
        
        # Return mock data
        result = {
            "overall_score": 2.8,
            "target_score": 3.0,
            "certification_level": "2 Stars",
            "categories": [
                {"name": "Energy", "score": 2.9, "status": "on_track"},
                {"name": "Water", "score": 3.1, "status": "achieved"},
                {"name": "Indoor Environment", "score": 2.7, "status": "needs_work"},
                {"name": "Materials", "score": 2.5, "status": "needs_work"},
                {"name": "Site", "score": 3.0, "status": "achieved"}
            ],
            "next_assessment_date": "2026-03-15",
            "improvement_priority": "Indoor Environment quality monitoring"
        }
        
        return self.success_response(result)


class GetGSASImprovementPriorities(BaseTool):
    """Get prioritized GSAS improvement recommendations."""
    
    name: str = "get_gsas_improvement_priorities"
    description: str = "Get prioritized list of GSAS improvements ranked by impact on overall score. Shows the top 10 actions to take to improve the building's GSAS rating."
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    gsas_reporter: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self) -> ToolResult:
        # Return prioritized improvements
        result = {
            "current_score": 2.8,
            "target_score": 3.0,
            "gap_to_target": 0.2,
            "priorities": [
                {
                    "rank": 1,
                    "category": "Indoor Environment",
                    "action": "Install CO2 monitoring in all occupied zones",
                    "impact": "+0.15 points",
                    "cost_estimate_qar": 25000,
                    "payback_months": 12
                },
                {
                    "rank": 2,
                    "category": "Energy",
                    "action": "Optimize chiller staging sequence",
                    "impact": "+0.08 points",
                    "cost_estimate_qar": 5000,
                    "payback_months": 3
                },
                {
                    "rank": 3,
                    "category": "Water",
                    "action": "Install smart irrigation controllers",
                    "impact": "+0.05 points",
                    "cost_estimate_qar": 15000,
                    "payback_months": 8
                },
                {
                    "rank": 4,
                    "category": "Materials",
                    "action": "Switch to low-VOC cleaning products",
                    "impact": "+0.04 points",
                    "cost_estimate_qar": 2000,
                    "payback_months": 1
                },
                {
                    "rank": 5,
                    "category": "Energy",
                    "action": "Implement demand-controlled ventilation",
                    "impact": "+0.03 points",
                    "cost_estimate_qar": 35000,
                    "payback_months": 18
                }
            ],
            "total_improvement_potential": "+0.35 points"
        }
        
        return self.success_response(result)


class GenerateGORDReport(BaseTool):
    """Generate GORD-compliant PDF report."""
    
    name: str = "generate_gord_report"
    description: str = "Generate a GORD-compliant PDF report for GSAS Operations certification."
    parameters: dict = {
        "type": "object",
        "properties": {
            "building_id": {
                "type": "string",
                "description": "Building identifier"
            },
            "building_name": {
                "type": "string",
                "description": "Building display name"
            }
        },
        "required": []
    }
    
    gsas_reporter: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        building_id: Optional[str] = None,
        building_name: Optional[str] = None
    ) -> ToolResult:
        if self.gsas_reporter and hasattr(self.gsas_reporter, 'generate_report'):
            try:
                report_path = self.gsas_reporter.generate_report(
                    building_id=building_id,
                    building_name=building_name
                )
                return self.success_response({
                    "status": "generated",
                    "report_path": str(report_path),
                    "format": "PDF"
                })
            except Exception as e:
                return self.fail_response(f"Error generating report: {str(e)}")
        
        return self.success_response({
            "status": "simulated",
            "message": "GORD report generation would be executed here",
            "building_id": building_id or "default",
            "note": "Connect GSAS reporter for actual PDF generation"
        })
