"""
ARVIS Planning Tool (Production-Ready)
=======================================

Tool for creating and managing execution plans with:
- Step dependencies (DAG support)
- Persistence (JSON file storage)
- Status tracking with timestamps
- Rollback support
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import Field

from agent_unified.tools.base import BaseTool, ToolResult


logger = logging.getLogger("arvis.unified.planning")


class PlanStep:
    """Represents a single step in an execution plan"""
    
    def __init__(
        self,
        index: int,
        text: str,
        status: str = "not_started",
        depends_on: Optional[List[int]] = None,
        notes: str = "",
        result: str = "",
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 3
    ):
        self.index = index
        self.text = text
        self.status = status  # not_started, in_progress, completed, failed, blocked, skipped
        self.depends_on = depends_on or []
        self.notes = notes
        self.result = result
        self.started_at = started_at
        self.completed_at = completed_at
        self.retry_count = retry_count
        self.max_retries = max_retries
    
    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "text": self.text,
            "status": self.status,
            "depends_on": self.depends_on,
            "notes": self.notes,
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PlanStep":
        return cls(**data)
    
    def can_execute(self, completed_steps: Set[int]) -> bool:
        """Check if all dependencies are satisfied"""
        return all(dep in completed_steps for dep in self.depends_on)
    
    def is_terminal(self) -> bool:
        """Check if step is in a terminal state"""
        return self.status in ["completed", "failed", "skipped"]


class ExecutionPlan:
    """Represents a complete execution plan with DAG support"""
    
    def __init__(
        self,
        plan_id: str,
        title: str,
        steps: List[PlanStep],
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        status: str = "pending",  # pending, running, completed, failed, cancelled
        original_request: str = "",
        metadata: Optional[Dict] = None
    ):
        self.plan_id = plan_id
        self.title = title
        self.steps = steps
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or self.created_at
        self.status = status
        self.original_request = original_request
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "original_request": self.original_request,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionPlan":
        steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            plan_id=data["plan_id"],
            title=data["title"],
            steps=steps,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            status=data.get("status", "pending"),
            original_request=data.get("original_request", ""),
            metadata=data.get("metadata", {})
        )
    
    def get_completed_step_indices(self) -> Set[int]:
        """Get indices of all completed steps"""
        return {s.index for s in self.steps if s.status == "completed"}
    
    def get_next_executable_steps(self) -> List[PlanStep]:
        """Get all steps that can be executed now (dependencies satisfied)"""
        completed = self.get_completed_step_indices()
        return [
            s for s in self.steps 
            if s.status == "not_started" and s.can_execute(completed)
        ]
    
    def get_progress(self) -> Dict:
        """Get progress statistics"""
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == "completed")
        failed = sum(1 for s in self.steps if s.status == "failed")
        in_progress = sum(1 for s in self.steps if s.status == "in_progress")
        blocked = sum(1 for s in self.steps if s.status == "blocked")
        
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "blocked": blocked,
            "not_started": total - completed - failed - in_progress - blocked,
            "percentage": round((completed / total) * 100, 1) if total > 0 else 0
        }
    
    def validate_dependencies(self) -> List[str]:
        """Validate DAG - check for cycles and invalid references"""
        errors = []
        step_indices = {s.index for s in self.steps}
        
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_indices:
                    errors.append(f"Step {step.index} depends on non-existent step {dep}")
                if dep == step.index:
                    errors.append(f"Step {step.index} cannot depend on itself")
                if dep > step.index:
                    errors.append(f"Step {step.index} has forward dependency on step {dep}")
        
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()
        
        def has_cycle(idx: int) -> bool:
            visited.add(idx)
            rec_stack.add(idx)
            
            step = next((s for s in self.steps if s.index == idx), None)
            if step:
                for dep in step.depends_on:
                    if dep not in visited:
                        if has_cycle(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(idx)
            return False
        
        for step in self.steps:
            if step.index not in visited:
                if has_cycle(step.index):
                    errors.append("Circular dependency detected in plan")
                    break
        
        return errors


class PlanningTool(BaseTool):
    """
    Production-ready planning tool with:
    - Step dependencies (DAG)
    - Persistence to JSON
    - Rollback support
    - Retry logic
    """
    
    name: str = "planning"
    description: str = "Create and manage execution plans with dependencies, persistence, and rollback support."
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": [
                    "create", "update", "list", "get", "mark_step", 
                    "delete", "set_active", "replan", "rollback",
                    "get_executable", "validate"
                ],
                "description": "Operation to perform"
            },
            "plan_id": {
                "type": "string",
                "description": "Plan identifier"
            },
            "title": {
                "type": "string",
                "description": "Plan title"
            },
            "steps": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "integer"}
                                }
                            },
                            "required": ["text"]
                        }
                    ]
                },
                "description": "Steps - can be strings or objects with dependencies"
            },
            "step_index": {
                "type": "integer",
                "description": "Step index (0-based)"
            },
            "step_status": {
                "type": "string",
                "enum": ["not_started", "in_progress", "completed", "failed", "blocked", "skipped"],
                "description": "Step status"
            },
            "step_notes": {
                "type": "string",
                "description": "Notes for the step"
            },
            "step_result": {
                "type": "string",
                "description": "Result/output of step execution"
            },
            "rollback_to": {
                "type": "integer",
                "description": "Step index to rollback to"
            }
        },
        "required": ["command"]
    }
    
    # Storage
    plans: Dict[str, ExecutionPlan] = Field(default_factory=dict)
    active_plan_id: Optional[str] = None
    storage_path: Optional[Path] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, storage_dir: Optional[str] = None, **data):
        super().__init__(**data)
        if storage_dir:
            self.storage_path = Path(storage_dir)
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self._load_plans()
    
    def _load_plans(self):
        """Load plans from storage"""
        if not self.storage_path:
            return
        
        plans_file = self.storage_path / "plans.json"
        if plans_file.exists():
            try:
                with open(plans_file, "r") as f:
                    data = json.load(f)
                    for plan_data in data.get("plans", []):
                        plan = ExecutionPlan.from_dict(plan_data)
                        self.plans[plan.plan_id] = plan
                    self.active_plan_id = data.get("active_plan_id")
                logger.info(f"Loaded {len(self.plans)} plans from storage")
            except Exception as e:
                logger.error(f"Failed to load plans: {e}")
    
    def _save_plans(self):
        """Save plans to storage"""
        if not self.storage_path:
            return
        
        try:
            plans_file = self.storage_path / "plans.json"
            data = {
                "plans": [p.to_dict() for p in self.plans.values()],
                "active_plan_id": self.active_plan_id,
                "saved_at": datetime.now().isoformat()
            }
            with open(plans_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save plans: {e}")
    
    async def execute(
        self,
        command: str,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List] = None,
        step_index: Optional[int] = None,
        step_status: Optional[str] = None,
        step_notes: Optional[str] = None,
        step_result: Optional[str] = None,
        rollback_to: Optional[int] = None,
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
            "set_active": self._set_active_plan,
            "replan": self._replan,
            "rollback": self._rollback,
            "get_executable": self._get_executable_steps,
            "validate": self._validate_plan
        }
        
        handler = handlers.get(command)
        if not handler:
            return self.fail_response(f"Unknown command: {command}")
        
        result = await handler(
            plan_id=plan_id,
            title=title,
            steps=steps,
            step_index=step_index,
            step_status=step_status,
            step_notes=step_notes,
            step_result=step_result,
            rollback_to=rollback_to
        )
        
        # Auto-save after mutations
        if command in ["create", "update", "mark_step", "delete", "replan", "rollback"]:
            self._save_plans()
        
        return result
    
    async def _create_plan(
        self,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List] = None,
        **kwargs
    ) -> ToolResult:
        """Create a new plan with optional dependencies"""
        if not plan_id:
            plan_id = f"plan_{int(time.time())}"
        
        if plan_id in self.plans:
            return self.fail_response(f"Plan '{plan_id}' already exists")
        
        if not steps:
            return self.fail_response("Steps are required")
        
        # Parse steps - support both string and object format
        plan_steps = []
        for i, step in enumerate(steps):
            if isinstance(step, str):
                plan_steps.append(PlanStep(index=i, text=step))
            elif isinstance(step, dict):
                plan_steps.append(PlanStep(
                    index=i,
                    text=step.get("text", ""),
                    depends_on=step.get("depends_on", [])
                ))
        
        plan = ExecutionPlan(
            plan_id=plan_id,
            title=title or "Untitled Plan",
            steps=plan_steps
        )
        
        # Validate dependencies
        errors = plan.validate_dependencies()
        if errors:
            return self.fail_response(f"Invalid plan: {'; '.join(errors)}")
        
        self.plans[plan_id] = plan
        self.active_plan_id = plan_id
        
        return self.success_response({
            "status": "created",
            "plan_id": plan_id,
            "title": plan.title,
            "step_count": len(plan_steps),
            "has_dependencies": any(s.depends_on for s in plan_steps)
        })
    
    async def _update_plan(
        self,
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List] = None,
        **kwargs
    ) -> ToolResult:
        """Update an existing plan"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        
        if title:
            plan.title = title
        
        if steps:
            # Preserve status for matching steps
            old_status = {s.text: (s.status, s.result) for s in plan.steps}
            
            new_steps = []
            for i, step in enumerate(steps):
                if isinstance(step, str):
                    status, result = old_status.get(step, ("not_started", ""))
                    new_steps.append(PlanStep(index=i, text=step, status=status, result=result))
                elif isinstance(step, dict):
                    text = step.get("text", "")
                    status, result = old_status.get(text, ("not_started", ""))
                    new_steps.append(PlanStep(
                        index=i,
                        text=text,
                        depends_on=step.get("depends_on", []),
                        status=status,
                        result=result
                    ))
            
            plan.steps = new_steps
            
            errors = plan.validate_dependencies()
            if errors:
                return self.fail_response(f"Invalid update: {'; '.join(errors)}")
        
        plan.updated_at = datetime.now().isoformat()
        
        return self.success_response({
            "status": "updated",
            "plan_id": plan_id,
            "step_count": len(plan.steps)
        })
    
    async def _list_plans(self, **kwargs) -> ToolResult:
        """List all plans with progress"""
        plans_summary = []
        for pid, plan in self.plans.items():
            progress = plan.get_progress()
            plans_summary.append({
                "plan_id": pid,
                "title": plan.title,
                "status": plan.status,
                "progress": f"{progress['completed']}/{progress['total']}",
                "percentage": progress["percentage"],
                "is_active": pid == self.active_plan_id
            })
        
        return self.success_response({
            "plans": plans_summary,
            "total_count": len(plans_summary),
            "active_plan_id": self.active_plan_id
        })
    
    async def _get_plan(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Get detailed plan info"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        
        return self.success_response({
            "plan": plan.to_dict(),
            "progress": plan.get_progress(),
            "formatted": self._format_plan(plan)
        })
    
    async def _mark_step(
        self,
        plan_id: Optional[str] = None,
        step_index: Optional[int] = None,
        step_status: Optional[str] = None,
        step_notes: Optional[str] = None,
        step_result: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Mark step with status, notes, and result"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        if step_index is None:
            return self.fail_response("step_index is required")
        
        plan = self.plans[plan_id]
        
        if step_index < 0 or step_index >= len(plan.steps):
            return self.fail_response(f"Invalid step_index: {step_index}")
        
        step = plan.steps[step_index]
        now = datetime.now().isoformat()
        
        # Handle status transitions
        if step_status:
            if step_status == "in_progress" and step.status == "not_started":
                step.started_at = now
            elif step_status in ["completed", "failed"]:
                step.completed_at = now
            elif step_status == "failed":
                step.retry_count += 1
            
            step.status = step_status
        
        if step_notes:
            step.notes = step_notes
        
        if step_result:
            step.result = step_result
        
        plan.updated_at = now
        
        # Update plan status based on steps
        progress = plan.get_progress()
        if progress["failed"] > 0 and plan.status != "failed":
            plan.status = "running"  # Keep running, may replan
        elif progress["completed"] == progress["total"]:
            plan.status = "completed"
        elif progress["in_progress"] > 0 or progress["completed"] > 0:
            plan.status = "running"
        
        # Check for blocked steps (dependencies on failed steps)
        failed_indices = {s.index for s in plan.steps if s.status == "failed"}
        for s in plan.steps:
            if s.status == "not_started" and any(d in failed_indices for d in s.depends_on):
                s.status = "blocked"
        
        return self.success_response({
            "status": "step_updated",
            "plan_id": plan_id,
            "step_index": step_index,
            "step_status": step.status,
            "progress": progress,
            "formatted": self._format_plan(plan)
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
        """Set active plan"""
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        self.active_plan_id = plan_id
        
        return self.success_response({"status": "active_plan_set", "plan_id": plan_id})
    
    async def _replan(
        self,
        plan_id: Optional[str] = None,
        steps: Optional[List] = None,
        **kwargs
    ) -> ToolResult:
        """Replan from failed step - replace remaining steps"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        if not steps:
            return self.fail_response("New steps required for replan")
        
        plan = self.plans[plan_id]
        
        # Find first failed/blocked step
        failed_idx = next(
            (s.index for s in plan.steps if s.status in ["failed", "blocked"]),
            None
        )
        
        if failed_idx is None:
            return self.fail_response("No failed steps to replan from")
        
        # Keep completed steps, replace the rest
        completed_steps = [s for s in plan.steps if s.status == "completed"]
        
        # Add new steps starting from failed index
        for i, step in enumerate(steps):
            idx = failed_idx + i
            if isinstance(step, str):
                completed_steps.append(PlanStep(index=idx, text=step))
            elif isinstance(step, dict):
                completed_steps.append(PlanStep(
                    index=idx,
                    text=step.get("text", ""),
                    depends_on=step.get("depends_on", [])
                ))
        
        # Re-index
        for i, step in enumerate(completed_steps):
            step.index = i
        
        plan.steps = completed_steps
        plan.status = "running"
        plan.updated_at = datetime.now().isoformat()
        plan.metadata["replan_count"] = plan.metadata.get("replan_count", 0) + 1
        
        return self.success_response({
            "status": "replanned",
            "plan_id": plan_id,
            "kept_steps": failed_idx,
            "new_steps": len(steps),
            "total_steps": len(plan.steps)
        })
    
    async def _rollback(
        self,
        plan_id: Optional[str] = None,
        rollback_to: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        """Rollback to a specific step - reset all subsequent steps"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        if rollback_to is None:
            return self.fail_response("rollback_to step index required")
        
        plan = self.plans[plan_id]
        
        if rollback_to < 0 or rollback_to >= len(plan.steps):
            return self.fail_response(f"Invalid rollback_to: {rollback_to}")
        
        # Reset all steps after rollback point
        reset_count = 0
        for step in plan.steps:
            if step.index > rollback_to:
                step.status = "not_started"
                step.result = ""
                step.notes = ""
                step.started_at = None
                step.completed_at = None
                reset_count += 1
        
        plan.status = "running"
        plan.updated_at = datetime.now().isoformat()
        plan.metadata["rollback_count"] = plan.metadata.get("rollback_count", 0) + 1
        
        return self.success_response({
            "status": "rolled_back",
            "plan_id": plan_id,
            "rollback_to": rollback_to,
            "steps_reset": reset_count
        })
    
    async def _get_executable_steps(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Get all steps that can be executed now (parallel execution support)"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        executable = plan.get_next_executable_steps()
        
        return self.success_response({
            "executable_steps": [s.to_dict() for s in executable],
            "count": len(executable),
            "can_parallelize": len(executable) > 1
        })
    
    async def _validate_plan(self, plan_id: Optional[str] = None, **kwargs) -> ToolResult:
        """Validate plan dependencies"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return self.fail_response(f"Plan '{plan_id}' not found")
        
        plan = self.plans[plan_id]
        errors = plan.validate_dependencies()
        
        return self.success_response({
            "valid": len(errors) == 0,
            "errors": errors
        })
    
    def _format_plan(self, plan: ExecutionPlan) -> str:
        """Format plan for display"""
        symbols = {
            "not_started": "○",
            "in_progress": "◐",
            "completed": "●",
            "failed": "✗",
            "blocked": "⊘",
            "skipped": "◌"
        }
        
        lines = [f"**{plan.title}** ({plan.status})"]
        
        for step in plan.steps:
            symbol = symbols.get(step.status, "?")
            deps = f" [depends: {step.depends_on}]" if step.depends_on else ""
            lines.append(f"  {symbol} {step.index + 1}. {step.text}{deps}")
            if step.notes:
                lines.append(f"     📝 {step.notes[:50]}...")
            if step.result and step.status == "completed":
                lines.append(f"     ✓ {step.result[:50]}...")
            if step.status == "failed" and step.retry_count > 0:
                lines.append(f"     ⚠ Retries: {step.retry_count}/{step.max_retries}")
        
        progress = plan.get_progress()
        lines.append(f"\nProgress: {progress['completed']}/{progress['total']} ({progress['percentage']}%)")
        
        return "\n".join(lines)
    
    def get_next_pending_step(self, plan_id: Optional[str] = None) -> Optional[Dict]:
        """Get next step for sequential execution"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return None
        
        plan = self.plans[plan_id]
        executable = plan.get_next_executable_steps()
        
        if executable:
            return executable[0].to_dict()
        return None
    
    def get_parallel_steps(self, plan_id: Optional[str] = None) -> List[Dict]:
        """Get all steps that can run in parallel"""
        plan_id = plan_id or self.active_plan_id
        if not plan_id or plan_id not in self.plans:
            return []
        
        plan = self.plans[plan_id]
        return [s.to_dict() for s in plan.get_next_executable_steps()]
