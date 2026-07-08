"""
fbq plan model — the typed objects the plan engine schedules and the agent writes to.

A PlanTemplate is the vendor's reusable process map (e.g. Phase 3 Manufacturing &
Execution, 58 tasks / 14 milestones). Instantiating it for a client project stamps real
dates via the dependency scheduler (plan_engine). Every mutable write carries provenance
(who/when/source-message) per the PRD's read-first trust rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TASK_STATUSES = ("pending", "in_progress", "done", "blocked")


@dataclass
class PlanTask:
    task_id: str
    name: str
    duration_days: int = 1
    depends_on: List[str] = field(default_factory=list)
    owner_role: str = ""                 # Factory, QC, Electrician, Client, …
    milestone: str = ""
    client_owned: bool = False           # F27: client-task chasing
    # instance state (empty on the template; stamped on instantiation / by writes)
    status: str = "pending"
    start: str = ""                      # planned, ISO date — computed by the scheduler
    end: str = ""                        # planned, ISO date — computed by the scheduler
    actual_end: str = ""                 # set when done
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "name": self.name, "duration_days": self.duration_days,
                "depends_on": list(self.depends_on), "owner_role": self.owner_role,
                "milestone": self.milestone, "client_owned": self.client_owned,
                "status": self.status, "start": self.start, "end": self.end,
                "actual_end": self.actual_end, "notes": self.notes}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanTask":
        return cls(task_id=str(d["task_id"]), name=str(d.get("name", "")),
                   duration_days=max(1, int(d.get("duration_days", 1))),
                   depends_on=[str(x) for x in d.get("depends_on", [])],
                   owner_role=str(d.get("owner_role", "")),
                   milestone=str(d.get("milestone", "")),
                   client_owned=bool(d.get("client_owned", False)),
                   status=str(d.get("status", "pending")),
                   start=str(d.get("start", "")), end=str(d.get("end", "")),
                   actual_end=str(d.get("actual_end", "")), notes=str(d.get("notes", "")))


@dataclass
class PlanTemplate:
    template_id: str
    name: str
    phase: str                            # planning | design | manufacturing_execution | handover
    tasks: List[PlanTask] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"template_id": self.template_id, "name": self.name, "phase": self.phase,
                "tasks": [t.to_dict() for t in self.tasks]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanTemplate":
        return cls(template_id=str(d["template_id"]), name=str(d.get("name", "")),
                   phase=str(d.get("phase", "")),
                   tasks=[PlanTask.from_dict(t) for t in d.get("tasks", [])])


@dataclass
class ProjectPlan:
    project_id: str
    name: str
    phase: str
    start_date: str                       # ISO
    working_days_only: bool = False       # PRD OQ: calendar vs working days — configurable
    tasks: List[PlanTask] = field(default_factory=list)

    def task(self, task_id: str) -> Optional[PlanTask]:
        return next((t for t in self.tasks if t.task_id == task_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {"project_id": self.project_id, "name": self.name, "phase": self.phase,
                "start_date": self.start_date, "working_days_only": self.working_days_only,
                "tasks": [t.to_dict() for t in self.tasks]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProjectPlan":
        return cls(project_id=str(d["project_id"]), name=str(d.get("name", "")),
                   phase=str(d.get("phase", "")), start_date=str(d.get("start_date", "")),
                   working_days_only=bool(d.get("working_days_only", False)),
                   tasks=[PlanTask.from_dict(t) for t in d.get("tasks", [])])
