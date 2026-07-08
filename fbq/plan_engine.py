"""
C9 — plan/workflow engine: template instantiation, dependency scheduling, date recompute.

Deterministic and pure (no DB, no LLM) — the same discipline as arvisx.checklist_forms.
The scheduler is a forward pass in topological order:

  start(task) = project start (no deps) | next day after the latest effective end of its deps
  end(task)   = start + duration - 1 (calendar), or the duration-th working day

"Effective end" of a dependency = actual_end when done, else its planned end — so a task
finishing LATE pushes successors, and finishing EARLY pulls them in, on the next recompute.
DONE / IN-PROGRESS tasks are never rescheduled (the past is frozen); only pending tasks move.
`recompute` returns the shift list (old→new dates per task) — that is the payload for the
F14 dependency-impact alert ("these 4 tasks moved, owners notified"). `mark_done` returns the
newly-unblocked successors — the F15 next-task trigger. A 58-task plan recomputes in well
under the PRD's 500ms budget (it's O(V+E) date arithmetic).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from fbq.models import PlanTask, PlanTemplate, ProjectPlan


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


def _iso(d: date) -> str:
    return d.isoformat()


def _next_day(d: date, working_only: bool) -> date:
    d = d + timedelta(days=1)
    while working_only and d.weekday() >= 5:      # Sat=5 Sun=6
        d += timedelta(days=1)
    return d


def _add_duration(start: date, duration_days: int, working_only: bool) -> date:
    """End date = the duration-th (working) day counting the start day itself."""
    d, counted = start, 1
    while counted < max(1, duration_days):
        d = _next_day(d, working_only)
        counted += 1
    return d


def _align(d: date, working_only: bool) -> date:
    while working_only and d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def topo_order(tasks: List[PlanTask]) -> List[PlanTask]:
    """Kahn topological sort; raises ValueError on a dependency cycle or unknown dep."""
    by_id = {t.task_id: t for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in by_id:
                raise ValueError(f"task '{t.task_id}' depends on unknown task '{dep}'")
    indeg = {t.task_id: len(t.depends_on) for t in tasks}
    succ: Dict[str, List[str]] = {t.task_id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            succ[dep].append(t.task_id)
    queue = [tid for tid, n in indeg.items() if n == 0]
    out: List[PlanTask] = []
    while queue:
        tid = queue.pop(0)
        out.append(by_id[tid])
        for s in succ[tid]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(out) != len(tasks):
        cyc = [tid for tid, n in indeg.items() if n > 0]
        raise ValueError(f"dependency cycle involving: {', '.join(sorted(cyc))}")
    return out


def _effective_end(t: PlanTask) -> str:
    return t.actual_end if (t.status == "done" and t.actual_end) else t.end


def schedule(plan: ProjectPlan) -> ProjectPlan:
    """Forward-pass (re)schedule of all PENDING tasks in place. Done/in-progress keep their
    dates; pending tasks move to the earliest slot their dependencies allow."""
    order = topo_order(plan.tasks)
    by_id = {t.task_id: t for t in plan.tasks}
    w = plan.working_days_only
    for t in order:
        if t.status in ("done", "in_progress") and t.start:
            continue                                   # the past is frozen
        if t.depends_on:
            dep_ends = [_effective_end(by_id[d]) for d in t.depends_on]
            dep_ends = [e for e in dep_ends if e]
            start = _next_day(max(_d(e) for e in dep_ends), w) if dep_ends else _align(_d(plan.start_date), w)
        else:
            start = _align(_d(plan.start_date), w)
        t.start = _iso(start)
        t.end = _iso(_add_duration(start, t.duration_days, w))
    return plan


def instantiate(template: PlanTemplate, project_id: str, name: str, start_date: str,
                working_days_only: bool = False,
                customize: Optional[Dict] = None) -> ProjectPlan:
    """Template → client project plan with computed dates. `customize` (all optional):
    {"remove": [task_ids], "durations": {task_id: days}, "owners": {task_id: role},
     "add": [PlanTask dicts]} — the F11 per-client customization contract."""
    c = customize or {}
    removed = set(c.get("remove", []))
    tasks = [PlanTask.from_dict(t.to_dict()) for t in template.tasks if t.task_id not in removed]
    for t in tasks:
        t.depends_on = [d for d in t.depends_on if d not in removed]
        if t.task_id in c.get("durations", {}):
            t.duration_days = max(1, int(c["durations"][t.task_id]))
        if t.task_id in c.get("owners", {}):
            t.owner_role = str(c["owners"][t.task_id])
    for d in c.get("add", []):
        tasks.append(PlanTask.from_dict(d))
    plan = ProjectPlan(project_id=project_id, name=name, phase=template.phase,
                       start_date=start_date, working_days_only=working_days_only, tasks=tasks)
    return schedule(plan)


def recompute(plan: ProjectPlan) -> List[Dict]:
    """Re-run the scheduler and return the SHIFT LIST — every pending task whose dates moved:
    [{task_id, name, owner_role, old_start, new_start, old_end, new_end, delta_days}].
    Feed this to the F14 dependency-impact alert (grouped message to shifted-task owners)."""
    before = {t.task_id: (t.start, t.end) for t in plan.tasks}
    schedule(plan)
    shifts: List[Dict] = []
    for t in plan.tasks:
        old_start, old_end = before.get(t.task_id, ("", ""))
        if (old_start, old_end) != (t.start, t.end) and old_end and t.end:
            shifts.append({"task_id": t.task_id, "name": t.name, "owner_role": t.owner_role,
                           "old_start": old_start, "new_start": t.start,
                           "old_end": old_end, "new_end": t.end,
                           "delta_days": (_d(t.end) - _d(old_end)).days})
    return shifts


def mark_done(plan: ProjectPlan, task_id: str, on_date: str) -> Tuple[List[Dict], List[PlanTask]]:
    """Complete a task (F7 write-back). Returns (shifts, next_tasks):
    shifts = downstream date moves (F14); next_tasks = successors now fully unblocked
    (F15 next-task trigger → notify their owners)."""
    t = plan.task(task_id)
    if t is None:
        raise ValueError(f"unknown task '{task_id}'")
    t.status = "done"
    t.actual_end = on_date
    shifts = recompute(plan)
    by_id = {x.task_id: x for x in plan.tasks}
    next_tasks = [x for x in plan.tasks
                  if x.status == "pending" and task_id in x.depends_on
                  and all(by_id[d].status == "done" for d in x.depends_on)]
    return shifts, next_tasks


def overdue_tasks(plan: ProjectPlan, today: str) -> List[PlanTask]:
    """Planned end passed, not done — feeds reminders (F8) and slippage tracking (F17)."""
    return [t for t in plan.tasks
            if t.status not in ("done",) and t.end and t.end < today]


def milestone_progress(plan: ProjectPlan) -> List[Dict]:
    """Per-milestone done/total + % — feeds F16 milestone notices."""
    ms: Dict[str, Dict] = {}
    for t in plan.tasks:
        m = t.milestone or "(no milestone)"
        e = ms.setdefault(m, {"milestone": m, "total": 0, "done": 0})
        e["total"] += 1
        e["done"] += 1 if t.status == "done" else 0
    out = list(ms.values())
    for e in out:
        e["pct"] = round(100.0 * e["done"] / e["total"], 0) if e["total"] else 0.0
    return out
