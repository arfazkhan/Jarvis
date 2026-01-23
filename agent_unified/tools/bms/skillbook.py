"""
BMS Skillbook Tools
===================

Class-based tools for building institutional memory.
"""

from typing import Any, Dict, Optional, List
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class QuerySkillbook(BaseTool):
    """Query building institutional memory."""
    
    name: str = "query_skillbook"
    description: str = "Query the building's institutional memory (Skillbook). Returns learned knowledge about equipment quirks, patterns, past optimizations, and contractor notes."
    parameters: dict = {
        "type": "object",
        "properties": {
            "building_id": {
                "type": "string",
                "description": "Building identifier (default: current building)"
            },
            "context": {
                "type": "object",
                "description": "Current context for relevance matching"
            },
            "skill_type": {
                "type": "string",
                "enum": ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note", "schedule", "threshold"],
                "description": "Filter by skill type"
            },
            "equipment_id": {
                "type": "string",
                "description": "Filter by equipment"
            }
        },
        "required": []
    }
    
    skillbook: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        building_id: Optional[str] = None,
        context: Optional[Dict] = None,
        skill_type: Optional[str] = None,
        equipment_id: Optional[str] = None
    ) -> ToolResult:
        if not self.skillbook:
            # Return mock data
            result = {
                "skills": [
                    {
                        "type": "equipment_quirk",
                        "title": "CH-02 high ambient startup issue",
                        "description": "CH-02 trips if started when outdoor temp > 35°C. Wait for evening or pre-cool.",
                        "confidence": 0.85,
                        "times_verified": 3
                    },
                    {
                        "type": "pattern",
                        "title": "Friday low occupancy",
                        "description": "Friday occupancy typically 15% of normal weekday. Consider setback mode.",
                        "confidence": 0.92,
                        "times_verified": 12
                    }
                ],
                "total_found": 2
            }
            return self.success_response(result)
        
        try:
            skills = self.skillbook.query_skills(
                building_id=building_id,
                skill_type=skill_type,
                equipment_id=equipment_id,
                context=context
            )
            return self.success_response({"skills": skills, "total_found": len(skills)})
        except Exception as e:
            return self.fail_response(f"Error querying skillbook: {str(e)}")


class AddToSkillbook(BaseTool):
    """Record new learning in building skillbook."""
    
    name: str = "add_to_skillbook"
    description: str = "Record a new learning in the building's Skillbook. Use when discovering equipment quirks, confirming optimization results, or noting contractor performance."
    parameters: dict = {
        "type": "object",
        "properties": {
            "skill_type": {
                "type": "string",
                "enum": ["equipment_quirk", "pattern", "optimization", "failure", "contractor_note"],
                "description": "Type of knowledge being recorded"
            },
            "title": {
                "type": "string",
                "description": "Short title for the skill"
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the learning"
            },
            "building_id": {
                "type": "string",
                "description": "Building identifier"
            },
            "equipment_id": {
                "type": "string",
                "description": "Related equipment (optional)"
            },
            "zone_id": {
                "type": "string",
                "description": "Related zone (optional)"
            },
            "evidence": {
                "type": "object",
                "description": "Supporting data"
            }
        },
        "required": ["skill_type", "title", "description"]
    }
    
    skillbook: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        skill_type: str,
        title: str,
        description: str,
        building_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        evidence: Optional[Dict] = None
    ) -> ToolResult:
        if not self.skillbook:
            return self.success_response({
                "status": "simulated",
                "skill_added": {
                    "type": skill_type,
                    "title": title,
                    "description": description[:100] + "...",
                    "initial_confidence": 0.5
                },
                "message": "Skill would be recorded. Connect skillbook for persistence."
            })
        
        try:
            skill_id = self.skillbook.add_skill(
                skill_type=skill_type,
                title=title,
                description=description,
                building_id=building_id,
                equipment_id=equipment_id,
                zone_id=zone_id,
                evidence=evidence
            )
            return self.success_response({
                "status": "added",
                "skill_id": skill_id,
                "title": title
            })
        except Exception as e:
            return self.fail_response(f"Error adding skill: {str(e)}")


class FindSimilarSkills(BaseTool):
    """Use semantic search to find relevant skills."""
    
    name: str = "find_similar_skills"
    description: str = "Use semantic embeddings to find relevant building skills from the Skillbook. Matches based on meaning not just keywords."
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Description of the situation or problem"
            },
            "building_id": {
                "type": "string",
                "description": "Building identifier"
            },
            "equipment_id": {
                "type": "string",
                "description": "Related equipment (optional)"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5
            }
        },
        "required": ["query"]
    }
    
    skillbook: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        query: str,
        building_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        top_k: int = 5
    ) -> ToolResult:
        if not self.skillbook:
            return self.success_response({
                "query": query,
                "similar_skills": [
                    {"title": "Related equipment issue", "similarity": 0.85, "type": "equipment_quirk"},
                    {"title": "Past optimization success", "similarity": 0.72, "type": "optimization"}
                ],
                "note": "Connect skillbook for semantic search"
            })
        
        try:
            results = self.skillbook.semantic_search(
                query=query,
                building_id=building_id,
                equipment_id=equipment_id,
                top_k=top_k
            )
            return self.success_response({"query": query, "similar_skills": results})
        except Exception as e:
            return self.fail_response(f"Error searching skills: {str(e)}")
