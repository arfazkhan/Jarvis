"""
ARVIS Planning Tool
===================

Tool for creating and managing execution plans.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


class PlanningTool(BaseTool):
    """
    Tool for creating and managing execution plans.
    
    Provides functionality to:
    - Create plans with steps
    - Update plans and steps
    - Track step status
    - Mark steps complete
    """
    
    name: str = "planning"
    description: str = "Create and manage execution plans for complex multi-step tasks. Use to break down problems and track progress."
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["create", "update", "list", "get", "mark_step", "delete", "set_active"],
                "description": "Operation to perform on plans"
            },
            "plan_id": {
                "type": "string",
                "description": "Unique identifier for the plan"
            },
            "title": {
                "type": "string",
                "description": "Title for the plan (used with create/update)"
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of step descriptions (used with create/update)"
            },
            "step_index": {
                "type": "integer",
                "description": "Index of step to update (0-based)"
            },
            "step_status": {
                "type": "string",
                "enum": ["not_started", "in_progress", "completed", "blocked"],
                "description": "New status for the step"
            },
            "step_notes": {
                "type": "string",
                "description": "Notes to add to the step"
            }
        },
        "required": ["command"]
    }
    
    # Internal storage for plans
    plans: Dict[str, Dict] = Field(default_factory=dict)
    active_plan_id: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(
        self,
        command: str,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        step_index: Optional[int] = None,
        step_status: Optional[str] = None,
        step_notes: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Execute planning command"""
        
        handlers = {
            "create": self._create_plan,
            "update": self._update_plan,
            "list": self._list_plans,
            "get": self._get_plan,
            "mark_step": self._mark_step,
            "delete": self._delete_plan,
            "set_active": self._set_active_plan
        }
        
        handler = handlers.get(command)
        if not handler:
            return self.fail_response(f"Unknown command: {command}")
        
        return await handler(
            plan_id=plan_id,
            title=title,
            steps=steps,
            step_index=step_index,
            step_status=step_status,
            step_notes=step_notes
        )
    
    async def _create_plan(
        self,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """Create a new plan"""
        if not plan_id:
            import time
            plan_id = f"plan_{int(time.time())}"
        
        if plan_id in self.plans:
            return self.fail_response(f"Plan '{plan_id}' already exists")
        
        if not steps:
            return self.fail_response("Steps are required to create a plan")
        
        self.plans[plan_id] = {
            "plan_id": plan_id,
            "title": title or "Untitled Plan",
            "steps": [
                {
                    "index": i,
                    "text": step,
                    "status": "not_started",
                    "notes": ""
                }
                for i, step in enumerate(steps)
            ],
            "created_at": self._now(),
            "updated_at": self._now()
        }
        
        self.active_plan_id = plan_id
        
        return self.success_response({
            "status": "created",
            "plan_id": plan_id,
            "title": title or "Untitled Plan",
            "step_count": len(steps)
        })
    
    async def _update_plan(
        self,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        **kwargs
    ) -> ToolResult:
        """Update an existing plan"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        
        if title:
            plan["title"] = title
        
        if steps:
            # Preserve status for existing steps where possible
            old_statuses = {s["text"]: s["status"] for s in plan["steps"]}
            plan["steps"] = [
                {
                    "index": i,
                    "text": step,
                    "status": old_statuses.get(step, "not_started"),
                    "notes": ""
                }
                for i, step in enumerate(steps)
            ]
        
        plan["updated_at"] = self._now()
        
        return self.success_response({
            "status": "updated",
            "plan_id": plan_id,
            "step_count": len(plan["steps"])
        })
    
    async def _list_plans(self, **kwargs) -> ToolResult:
        """List all plans"""
        plans_summary = [
            {
                "plan_id": pid,
                "title": p["title"],
                "step_count": len(p["steps"]),
                "completed_count": sum(1 for s in p["steps"] if s["status"] == "completed"),
                "is_active": pid == self.active_plan_id
            }
            for pid, p in self.plans.items()
        ]
        
        return self.success_response({
            "plans": plans_summary,
            "total_count": len(plans_summary),
            "active_plan_id": self.active_plan_id
        })
    
    async def _get_plan(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Get details of a specific plan"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        
        return self.success_response({
            "plan": plan,
            "progress": self._format_progress(plan)
        })
    
    async def _mark_step(
        self,
        plan_id: Optional[str] = None,
        step_index: Optional[int] = None,
        step_status: Optional[str] = None,
        step_notes: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Mark a step with status and optional notes"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        if step_index is None:
            return self.fail_response("step_index is required")
        
        plan = self.plans[plan_id]
        
        if step_index < 0 or step_index >= len(plan["steps"]):
            return self.fail_response(f"Invalid step_index: {step_index}")
        
        step = plan["steps"][step_index]
        
        if step_status:
            step["status"] = step_status
        
        if step_notes:
            step["notes"] = step_notes
        
        plan["updated_at"] = self._now()
        
        return self.success_response({
            "status": "step_updated",
            "plan_id": plan_id,
            "step_index": step_index,
            "step_status": step["status"],
            "progress": self._format_progress(plan)
        })
    
    async def _delete_plan(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Delete a plan"""
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        del self.plans[plan_id]
        
        if self.active_plan_id == plan_id:
            self.active_plan_id = None
        
        return self.success_response({"status": "deleted", "plan_id": plan_id})
    
    async def _set_active_plan(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Set a plan as the active plan"""
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        self.active_plan_id = plan_id
        
        return self.success_response({
            "status": "active_plan_set",
            "plan_id": plan_id
        })
    
    def _format_progress(self, plan: Dict) -> str:
        """Format plan progress as a string"""
        symbols = {
            "not_started": "○",
            "in_progress": "◐",
            "completed": "●",
            "blocked": "✗"
        }
        
        lines = [f"**{plan['title']}**"]
        for step in plan["steps"]:
            symbol = symbols.get(step["status"], "?")
            lines.append(f"  {symbol} {step['index']+1}. {step['text']}")
            if step["notes"]:
                lines.append(f"     → {step['notes'][:50]}...")
        
        completed = sum(1 for s in plan["steps"] if s["status"] == "completed")
        total = len(plan["steps"])
        lines.append(f"\nProgress: {completed}/{total} steps completed")
        
        return "\n".join(lines)
    
    def _now(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_next_pending_step(self, plan_id: Optional[str] = None) -> Optional[Dict]:
        """Get the next step that needs to be executed"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return None
        
        for step in self.plans[plan_id]["steps"]:
            if step["status"] in ["not_started", "in_progress"]:
                return step
        
        return None
