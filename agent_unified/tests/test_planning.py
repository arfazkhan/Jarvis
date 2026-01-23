"""
Tests for ARVIS Planning System (Production-Ready)
===================================================

Tests for PlanningTool and PlanningFlow with:
- DAG dependencies
- Persistence
- Replanning
- Parallel execution
"""

import asyncio
import json
import tempfile
from pathlib import Path
import pytest

from agent_unified.tools.planning import PlanningTool, PlanStep, ExecutionPlan
from agent_unified.flows.planning import PlanningFlow, ExecutionResult


class TestPlanStep:
    """Tests for PlanStep class"""
    
    def test_create_simple_step(self):
        step = PlanStep(index=0, text="Test step")
        assert step.index == 0
        assert step.text == "Test step"
        assert step.status == "not_started"
        assert step.depends_on == []
    
    def test_step_with_dependencies(self):
        step = PlanStep(index=2, text="Step 3", depends_on=[0, 1])
        assert step.depends_on == [0, 1]
    
    def test_can_execute_no_deps(self):
        step = PlanStep(index=0, text="First step")
        assert step.can_execute(set()) is True
    
    def test_can_execute_with_deps(self):
        step = PlanStep(index=2, text="Third step", depends_on=[0, 1])
        assert step.can_execute({0}) is False
        assert step.can_execute({0, 1}) is True
        assert step.can_execute({0, 1, 3}) is True
    
    def test_serialization(self):
        step = PlanStep(
            index=1, 
            text="Test", 
            status="completed",
            depends_on=[0],
            notes="Some notes"
        )
        data = step.to_dict()
        restored = PlanStep.from_dict(data)
        assert restored.index == 1
        assert restored.text == "Test"
        assert restored.status == "completed"
        assert restored.depends_on == [0]


class TestExecutionPlan:
    """Tests for ExecutionPlan class"""
    
    def test_create_plan(self):
        steps = [
            PlanStep(0, "Step 1"),
            PlanStep(1, "Step 2", depends_on=[0]),
            PlanStep(2, "Step 3", depends_on=[0]),
        ]
        plan = ExecutionPlan("test_plan", "Test Plan", steps)
        
        assert plan.plan_id == "test_plan"
        assert len(plan.steps) == 3
    
    def test_get_executable_steps(self):
        steps = [
            PlanStep(0, "Step 1"),
            PlanStep(1, "Step 2", depends_on=[0]),
            PlanStep(2, "Step 3"),  # Independent
        ]
        plan = ExecutionPlan("test", "Test", steps)
        
        # Initially, steps 0 and 2 can execute (no deps)
        executable = plan.get_next_executable_steps()
        indices = [s.index for s in executable]
        assert 0 in indices
        assert 2 in indices
        assert 1 not in indices
    
    def test_executable_after_completion(self):
        steps = [
            PlanStep(0, "Step 1", status="completed"),
            PlanStep(1, "Step 2", depends_on=[0]),
            PlanStep(2, "Step 3", depends_on=[1]),
        ]
        plan = ExecutionPlan("test", "Test", steps)
        
        # Step 0 completed, step 1 should be executable
        executable = plan.get_next_executable_steps()
        assert len(executable) == 1
        assert executable[0].index == 1
    
    def test_progress(self):
        steps = [
            PlanStep(0, "Step 1", status="completed"),
            PlanStep(1, "Step 2", status="in_progress"),
            PlanStep(2, "Step 3"),
        ]
        plan = ExecutionPlan("test", "Test", steps)
        
        progress = plan.get_progress()
        assert progress["total"] == 3
        assert progress["completed"] == 1
        assert progress["in_progress"] == 1
        assert progress["not_started"] == 1
        assert progress["percentage"] == pytest.approx(33.3, 0.1)
    
    def test_validate_dependencies_valid(self):
        steps = [
            PlanStep(0, "First"),
            PlanStep(1, "Second", depends_on=[0]),
        ]
        plan = ExecutionPlan("test", "Test", steps)
        errors = plan.validate_dependencies()
        assert len(errors) == 0
    
    def test_validate_dependencies_self_reference(self):
        steps = [
            PlanStep(0, "Self ref", depends_on=[0]),
        ]
        plan = ExecutionPlan("test", "Test", steps)
        errors = plan.validate_dependencies()
        assert any("cannot depend on itself" in e for e in errors)
    
    def test_validate_dependencies_invalid_ref(self):
        steps = [
            PlanStep(0, "First", depends_on=[5]),
        ]
        plan = ExecutionPlan("test", "Test", steps)
        errors = plan.validate_dependencies()
        assert any("non-existent" in e for e in errors)


class TestPlanningTool:
    """Tests for PlanningTool"""
    
    @pytest.fixture
    def tool(self):
        return PlanningTool()
    
    @pytest.mark.asyncio
    async def test_create_simple_plan(self, tool):
        result = await tool.execute(
            command="create",
            plan_id="test_plan",
            title="Test Plan",
            steps=["Step 1", "Step 2", "Step 3"]
        )
        
        assert result.error is None
        data = json.loads(result.output)
        assert data["status"] == "created"
        assert data["step_count"] == 3
    
    @pytest.mark.asyncio
    async def test_create_plan_with_deps(self, tool):
        result = await tool.execute(
            command="create",
            plan_id="dep_plan",
            title="Plan with Dependencies",
            steps=[
                {"text": "First step", "depends_on": []},
                {"text": "Second step", "depends_on": [0]},
                {"text": "Parallel step", "depends_on": [0]},
                {"text": "Final step", "depends_on": [1, 2]},
            ]
        )
        
        assert result.error is None
        data = json.loads(result.output)
        assert data["has_dependencies"] is True
    
    @pytest.mark.asyncio
    async def test_get_executable_steps(self, tool):
        await tool.execute(
            command="create",
            plan_id="exec_test",
            steps=[
                {"text": "A", "depends_on": []},
                {"text": "B", "depends_on": [0]},
                {"text": "C", "depends_on": []},
            ]
        )
        
        result = await tool.execute(command="get_executable", plan_id="exec_test")
        data = json.loads(result.output)
        
        # Steps A and C should be executable (no deps)
        assert data["count"] == 2
        assert data["can_parallelize"] is True
    
    @pytest.mark.asyncio
    async def test_mark_step_completed(self, tool):
        await tool.execute(
            command="create",
            plan_id="mark_test",
            steps=["Step 1", "Step 2"]
        )
        
        result = await tool.execute(
            command="mark_step",
            plan_id="mark_test",
            step_index=0,
            step_status="completed",
            step_result="Success!"
        )
        
        assert result.error is None
        data = json.loads(result.output)
        assert data["progress"]["completed"] == 1
    
    @pytest.mark.asyncio
    async def test_rollback(self, tool):
        await tool.execute(
            command="create",
            plan_id="rollback_test",
            steps=["Step 1", "Step 2", "Step 3"]
        )
        
        # Complete first two steps
        await tool.execute(command="mark_step", plan_id="rollback_test", 
                          step_index=0, step_status="completed")
        await tool.execute(command="mark_step", plan_id="rollback_test", 
                          step_index=1, step_status="completed")
        
        # Rollback to step 0
        result = await tool.execute(
            command="rollback",
            plan_id="rollback_test",
            rollback_to=0
        )
        
        data = json.loads(result.output)
        assert data["steps_reset"] == 2
    
    @pytest.mark.asyncio
    async def test_replan(self, tool):
        await tool.execute(
            command="create",
            plan_id="replan_test",
            steps=["Step 1", "Step 2", "Step 3"]
        )
        
        # Complete step 1, fail step 2
        await tool.execute(command="mark_step", plan_id="replan_test",
                          step_index=0, step_status="completed")
        await tool.execute(command="mark_step", plan_id="replan_test",
                          step_index=1, step_status="failed")
        
        # Replan with new steps
        result = await tool.execute(
            command="replan",
            plan_id="replan_test",
            steps=["Recovery step", "New approach", "Verify"]
        )
        
        data = json.loads(result.output)
        assert data["status"] == "replanned"
        assert data["kept_steps"] == 1
        assert data["new_steps"] == 3


class TestPlanningToolPersistence:
    """Tests for PlanningTool persistence"""
    
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and save
            tool1 = PlanningTool(storage_dir=tmpdir)
            await tool1.execute(
                command="create",
                plan_id="persist_test",
                title="Persistence Test",
                steps=["Step 1", "Step 2"]
            )
            await tool1.execute(
                command="mark_step",
                plan_id="persist_test",
                step_index=0,
                step_status="completed"
            )
            
            # Load in new instance
            tool2 = PlanningTool(storage_dir=tmpdir)
            
            result = await tool2.execute(command="get", plan_id="persist_test")
            data = json.loads(result.output)
            
            assert data["plan"]["title"] == "Persistence Test"
            assert data["progress"]["completed"] == 1


class TestExecutionResult:
    """Tests for ExecutionResult class"""
    
    def test_create_success(self):
        result = ExecutionResult(
            step_index=0,
            step_text="Test step",
            success=True,
            result="Done",
            duration_ms=100
        )
        
        assert result.success is True
        assert result.duration_ms == 100
    
    def test_serialization(self):
        result = ExecutionResult(
            step_index=1,
            step_text="Step",
            success=False,
            error="Failed",
            retries=2
        )
        
        data = result.to_dict()
        assert data["step_index"] == 1
        assert data["success"] is False
        assert data["retries"] == 2


# Run tests with: pytest tests/test_planning.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
