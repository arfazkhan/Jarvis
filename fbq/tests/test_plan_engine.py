"""Hermetic plan-engine tests — instantiation, dependency scheduling, slip recompute,
next-task triggers, working days, cycle detection. No DB, no LLM, fast."""
import json
import time
from pathlib import Path

import pytest

from fbq.models import PlanTask, PlanTemplate
from fbq.plan_engine import (instantiate, mark_done, milestone_progress, overdue_tasks,
                             recompute, topo_order)

SEED = Path(__file__).parent.parent / "seeds" / "phase3_manufacturing.json"


def _template() -> PlanTemplate:
    return PlanTemplate.from_dict(json.loads(SEED.read_text(encoding="utf-8")))


def test_instantiate_computes_dependency_ordered_dates():
    plan = instantiate(_template(), "prj1", "3BHK Kitchen", "2026-08-03")
    by = {t.task_id: t for t in plan.tasks}
    # roots start on the project start date
    assert by["material_po"].start == "2026-08-03"
    assert by["site_prep"].start == "2026-08-03"
    # a dependent task starts strictly after ALL its deps end
    fc = by["factory_carcass"]
    for dep in fc.depends_on:
        assert fc.start > by[dep].end
    # delivery waits for the LATER of qc_factory / painting_base
    dv = by["delivery"]
    assert dv.start > max(by["qc_factory"].end, by["painting_base"].end)
    # every task got dates
    assert all(t.start and t.end for t in plan.tasks)


def test_duration_and_customization():
    plan = instantiate(_template(), "prj2", "Villa", "2026-08-03",
                       customize={"durations": {"factory_carcass": 12},
                                  "owners": {"delivery": "Own Fleet"},
                                  "remove": ["appliances"]})
    by = {t.task_id: t for t in plan.tasks}
    fc = by["factory_carcass"]
    assert (len([1])) and fc.duration_days == 12
    # end - start = duration - 1 (calendar mode)
    from datetime import date
    assert (date.fromisoformat(fc.end) - date.fromisoformat(fc.start)).days == 11
    assert by["delivery"].owner_role == "Own Fleet"
    assert "appliances" not in by
    # deep_clean depended on appliances — dep pruned, still schedules
    assert by["deep_clean"].start


def test_slip_recompute_shifts_downstream_only():
    plan = instantiate(_template(), "prj3", "Flat", "2026-08-03")
    by = {t.task_id: t for t in plan.tasks}
    # freeze upstream site works as done ON TIME (no shift from them)
    for tid in ("site_prep", "false_ceiling", "electrical_roughin", "painting_base",
                "client_material_signoff", "material_po"):
        by[tid].status = "done"
        by[tid].actual_end = by[tid].end
    # factory_carcass finishes 4 days LATE
    late_end = "2026-08-20"
    assert late_end > by["factory_carcass"].end
    shifts, _ = mark_done(plan, "factory_carcass", late_end)
    shifted_ids = {s["task_id"] for s in shifts}
    # qc waits on carcass → must shift; roots/done tasks must NOT
    assert "qc_factory" in shifted_ids
    assert "site_prep" not in shifted_ids and "material_po" not in shifted_ids
    # every shift carries the alert payload fields
    s = next(s for s in shifts if s["task_id"] == "qc_factory")
    assert s["old_end"] < s["new_end"] and s["delta_days"] > 0 and s["owner_role"]


def test_early_finish_pulls_schedule_in():
    plan = instantiate(_template(), "prj4", "Flat", "2026-08-03")
    by = {t.task_id: t for t in plan.tasks}
    early = "2026-08-05"
    assert early < by["factory_carcass"].end
    mark_done(plan, "factory_carcass", early)
    # qc still waits on shutters (unchanged), so it should NOT move earlier than shutters allow
    assert by["qc_factory"].start > by["factory_shutters"].end


def test_next_task_trigger_fires_only_when_all_deps_done():
    plan = instantiate(_template(), "prj5", "Flat", "2026-08-03")
    _, nxt = mark_done(plan, "factory_carcass", "2026-08-14")
    assert all(t.task_id != "qc_factory" for t in nxt)      # shutters not done yet
    _, nxt = mark_done(plan, "factory_shutters", "2026-08-16")
    assert any(t.task_id == "qc_factory" for t in nxt)      # now unblocked (F15)


def test_working_days_skip_weekends():
    t = PlanTemplate(template_id="w", name="w", phase="manufacturing_execution",
                     tasks=[PlanTask("a", "A", duration_days=3),
                            PlanTask("b", "B", duration_days=2, depends_on=["a"])])
    # 2026-08-07 is a Friday → A spans Fri, Mon, Tue; B starts Wed
    plan = instantiate(t, "prjW", "W", "2026-08-07", working_days_only=True)
    by = {x.task_id: x for x in plan.tasks}
    assert by["a"].start == "2026-08-07" and by["a"].end == "2026-08-11"
    assert by["b"].start == "2026-08-12"


def test_cycle_detection_raises():
    tasks = [PlanTask("a", "A", depends_on=["b"]), PlanTask("b", "B", depends_on=["a"])]
    with pytest.raises(ValueError, match="cycle"):
        topo_order(tasks)


def test_overdue_and_milestones():
    plan = instantiate(_template(), "prj6", "Flat", "2026-08-03")
    od = overdue_tasks(plan, "2026-09-30")
    assert od and all(t.status != "done" for t in od)
    ms = milestone_progress(plan)
    prod = next(m for m in ms if m["milestone"] == "Production")
    assert prod["total"] >= 3 and prod["pct"] == 0.0
    mark_done(plan, "material_po", "2026-08-04")
    ms = milestone_progress(plan)
    start = next(m for m in ms if m["milestone"] == "Production start")
    assert start["done"] == 1


def test_58_task_recompute_under_budget():
    # PRD: date recompute <500ms. Build a 60-task chain + random cross-deps.
    tasks = [PlanTask(f"t{i}", f"T{i}", duration_days=2,
                      depends_on=([f"t{i-1}"] if i else []) + ([f"t{i-7}"] if i >= 7 else []))
             for i in range(60)]
    t = PlanTemplate(template_id="big", name="big", phase="manufacturing_execution", tasks=tasks)
    plan = instantiate(t, "big", "big", "2026-08-03")
    t0 = time.perf_counter()
    plan.task("t5").status = "done"; plan.task("t5").actual_end = "2026-09-01"
    recompute(plan)
    assert (time.perf_counter() - t0) < 0.5
