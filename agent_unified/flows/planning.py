"""
ARVIS Planning Flow (Production-Ready)
=======================================

Flow for executing multi-step plans with:
- Parallel step execution
- Replanning on failure
- Retry logic
- Comprehensive execution tracking
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import Field

from agent_unified.llm import UnifiedLLM
from agent_unified.tools.planning import PlanningTool, ExecutionPlan
from agent_unified.prompts.planning import PLANNING_SYSTEM_PROMPT
from .base import BaseFlow


logger = logging.getLogger("arvis.unified.flow.planning")


PLAN_GENERATION_PROMPT = """You are a planning expert. Create a step-by-step plan to accomplish the following task.

Task: {task}

Requirements:
1. Break down the task into clear, actionable steps
2. Each step should be specific and achievable
3. Order steps logically by dependencies
4. Include verification steps where appropriate
5. Keep the plan concise (5-10 steps typically)
6. If steps can run in parallel, note the dependencies

Output format - JSON array of steps:
[
  {{"text": "First step description", "depends_on": []}},
  {{"text": "Second step that requires first", "depends_on": [0]}},
  {{"text": "Third step independent of second", "depends_on": [0]}},
  {{"text": "Fourth step requiring both 2 and 3", "depends_on": [1, 2]}}
]

Important:
- depends_on uses 0-based indices
- Steps with same dependencies can run in parallel
- Empty depends_on means step can start immediately

Plan:"""


REPLAN_PROMPT = """The following step failed during plan execution. Create new steps to recover and complete the task.

Original Task: {task}

Completed Steps:
{completed_steps}

Failed Step: {failed_step}
Error: {error}

Create new steps to:
1. Handle or work around the failure
2. Complete the remaining objectives

Output as JSON array (same format as before):
[{{"text": "Recovery step", "depends_on": []}}, ...]

New Steps:"""


class ExecutionResult:
    """Result of executing a single step"""
    
    def __init__(
        self,
        step_index: int,
        step_text: str,
        success: bool,
        result: str = "",
        error: str = "",
        duration_ms: int = 0,
        retries: int = 0
    ):
        self.step_index = step_index
        self.step_text = step_text
        self.success = success
        self.result = result
        self.error = error
        self.duration_ms = duration_ms
        self.retries = retries
    
    def to_dict(self) -> Dict:
        return {
            "step_index": self.step_index,
            "step_text": self.step_text,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "retries": self.retries
        }


class PlanningFlow(BaseFlow):
    """
    Production-ready planning flow with:
    - Parallel step execution
    - Replanning on failure
    - Retry logic with backoff
    - Comprehensive execution tracking
    """
    
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)
    agents: Dict[str, Any] = Field(default_factory=dict)
    primary_agent: str = "arvis"
    
    # Execution settings
    max_steps: int = Field(default=30, description="Max total steps to execute")
    max_retries: int = Field(default=3, description="Max retries per step")
    retry_delay_ms: int = Field(default=1000, description="Initial retry delay")
    enable_parallel: bool = Field(default=True, description="Enable parallel execution")
    enable_replan: bool = Field(default=True, description="Enable replanning on failure")
    max_replans: int = Field(default=2, description="Max replanning attempts")
    
    # Current state
    current_plan_id: Optional[str] = None
    execution_results: List[ExecutionResult] = Field(default_factory=list)
    replan_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    async def execute(self, input_text: str) -> str:
        """
        Execute the planning flow.
        
        Args:
            input_text: User request to plan and execute
            
        Returns:
            Summary of execution results
        """
        self.started_at = datetime.now().isoformat()
        self.execution_results = []
        self.replan_count = 0
        
        logger.info(f"[PlanningFlow] Starting execution for: {input_text[:100]}...")
        
        try:
            # Step 1: Create plan
            plan_result = await self._create_plan_from_request(input_text)
            if not plan_result:
                return "Failed to create execution plan"
            self.current_plan_id = plan_result["plan_id"]
            
            # Step 2: Execute plan
            await self._execute_plan_loop(input_text)
            
            # Step 3: Generate summary
            self.completed_at = datetime.now().isoformat()
            summary = await self._generate_summary(input_text)
            
            return summary
            
        except Exception as e:
            logger.error(f"[PlanningFlow] Execution error: {e}")
            self.completed_at = datetime.now().isoformat()
            return f"Plan execution failed: {str(e)}"
    
    async def _create_plan_from_request(self, request: str) -> Optional[Dict]:
        """Create a plan with dependencies from user request"""
        logger.info("[PlanningFlow] Generating plan from request...")
        
        try:
            response = await self.llm.ask(
                messages=[{
                    "role": "user",
                    "content": PLAN_GENERATION_PROMPT.format(task=request)
                }],
                system_msgs=[{
                    "role": "system",
                    "content": PLANNING_SYSTEM_PROMPT
                }]
            )
            
            steps = self._parse_steps_json(response.content)
            
            if not steps:
                # Fallback to simple parsing
                steps = self._parse_steps_simple(response.content)
            
            if not steps:
                logger.warning("[PlanningFlow] No steps parsed from LLM response")
                return None
            
            result = await self.planning_tool.execute(
                command="create",
                plan_id=f"plan_{int(time.time())}",
                title=request[:80],
                steps=steps
            )
            
            if result.error:
                logger.error(f"[PlanningFlow] Plan creation failed: {result.error}")
                return None
            
            logger.info(f"[PlanningFlow] Created plan with {len(steps)} steps")
            return {"plan_id": self.planning_tool.active_plan_id, "steps": steps}
            
        except Exception as e:
            logger.error(f"[PlanningFlow] Plan creation error: {e}")
            return None
    
    def _parse_steps_json(self, text: str) -> List[Dict]:
        """Parse JSON formatted steps"""
        import json
        import re
        
        # Try to find JSON array in the response
        json_match = re.search(r'\[[\s\S]*\]', text)
        if not json_match:
            return []
        
        try:
            steps = json.loads(json_match.group())
            if isinstance(steps, list):
                return [
                    s if isinstance(s, dict) else {"text": str(s), "depends_on": []}
                    for s in steps
                ]
        except json.JSONDecodeError:
            pass
        
        return []
    
    def _parse_steps_simple(self, text: str) -> List[str]:
        """Fallback: parse numbered steps as strings"""
        import re
        
        steps = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
            if cleaned and len(cleaned) > 3:
                steps.append(cleaned)
        
        return steps[:15]
    
    async def _execute_plan_loop(self, original_request: str):
        """Main execution loop with parallel execution and replanning"""
        total_executed = 0
        
        while total_executed < self.max_steps:
            # Get executable steps
            result = await self.planning_tool.execute(
                command="get_executable",
                plan_id=self.current_plan_id
            )
            
            if result.error:
                break
            
            import json
            data = json.loads(result.output)
            executable = data.get("executable_steps", [])
            
            if not executable:
                # Check if we're done or stuck
                plan = self.planning_tool.plans.get(self.current_plan_id)
                if plan and plan.status == "completed":
                    logger.info("[PlanningFlow] Plan completed successfully")
                    break
                
                # Check for failures that need replanning
                has_blocked = any(s.status == "blocked" for s in plan.steps)
                if has_blocked and self.enable_replan and self.replan_count < self.max_replans:
                    success = await self._attempt_replan(original_request)
                    if success:
                        continue
                
                logger.info("[PlanningFlow] No more executable steps")
                break
            
            # Execute steps (parallel or sequential)
            if self.enable_parallel and len(executable) > 1:
                results = await self._execute_parallel(executable)
            else:
                results = await self._execute_sequential(executable)
            
            total_executed += len(results)
            self.execution_results.extend(results)
            
            # Check for failures
            failures = [r for r in results if not r.success]
            if failures and self.enable_replan and self.replan_count < self.max_replans:
                await self._attempt_replan(original_request)
    
    async def _execute_parallel(self, steps: List[Dict]) -> List[ExecutionResult]:
        """Execute multiple steps in parallel"""
        logger.info(f"[PlanningFlow] Executing {len(steps)} steps in parallel")
        
        tasks = [self._execute_step_with_retry(s) for s in steps]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        execution_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                execution_results.append(ExecutionResult(
                    step_index=steps[i]["index"],
                    step_text=steps[i]["text"],
                    success=False,
                    error=str(result)
                ))
            else:
                execution_results.append(result)
        
        return execution_results
    
    async def _execute_sequential(self, steps: List[Dict]) -> List[ExecutionResult]:
        """Execute steps one by one"""
        results = []
        for step in steps:
            result = await self._execute_step_with_retry(step)
            results.append(result)
            
            # Stop on failure in sequential mode
            if not result.success:
                break
        
        return results
    
    async def _execute_step_with_retry(self, step: Dict) -> ExecutionResult:
        """Execute a step with retry logic"""
        step_idx = step["index"]
        step_text = step["text"]
        
        logger.info(f"[PlanningFlow] Executing step {step_idx + 1}: {step_text[:50]}...")
        
        # Mark in progress
        await self.planning_tool.execute(
            command="mark_step",
            plan_id=self.current_plan_id,
            step_index=step_idx,
            step_status="in_progress"
        )
        
        retries = 0
        last_error = ""
        start_time = time.time()
        
        while retries <= self.max_retries:
            try:
                agent = self.get_agent()
                if not agent:
                    raise RuntimeError("No agent available")
                
                result = await agent.run(step_text)
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Mark completed
                await self.planning_tool.execute(
                    command="mark_step",
                    plan_id=self.current_plan_id,
                    step_index=step_idx,
                    step_status="completed",
                    step_result=result[:500] if result else ""
                )
                
                return ExecutionResult(
                    step_index=step_idx,
                    step_text=step_text,
                    success=True,
                    result=result or "",
                    duration_ms=duration_ms,
                    retries=retries
                )
                
            except Exception as e:
                last_error = str(e)
                retries += 1
                logger.warning(f"[PlanningFlow] Step {step_idx + 1} failed (attempt {retries}): {e}")
                
                if retries <= self.max_retries:
                    delay = self.retry_delay_ms * (2 ** (retries - 1)) / 1000
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        duration_ms = int((time.time() - start_time) * 1000)
        
        await self.planning_tool.execute(
            command="mark_step",
            plan_id=self.current_plan_id,
            step_index=step_idx,
            step_status="failed",
            step_notes=f"Failed after {retries} retries: {last_error[:200]}"
        )
        
        return ExecutionResult(
            step_index=step_idx,
            step_text=step_text,
            success=False,
            error=last_error,
            duration_ms=duration_ms,
            retries=retries
        )
    
    async def _attempt_replan(self, original_request: str) -> bool:
        """Attempt to replan from a failed step"""
        self.replan_count += 1
        logger.info(f"[PlanningFlow] Attempting replan ({self.replan_count}/{self.max_replans})")
        
        plan = self.planning_tool.plans.get(self.current_plan_id)
        if not plan:
            return False
        
        # Find failed step
        failed_step = next((s for s in plan.steps if s.status == "failed"), None)
        if not failed_step:
            return False
        
        # Build context
        completed_steps = "\n".join([
            f"✓ {s.index + 1}. {s.text}: {s.result[:100]}"
            for s in plan.steps if s.status == "completed"
        ])
        
        try:
            response = await self.llm.ask(
                messages=[{
                    "role": "user",
                    "content": REPLAN_PROMPT.format(
                        task=original_request,
                        completed_steps=completed_steps or "None",
                        failed_step=f"{failed_step.index + 1}. {failed_step.text}",
                        error=failed_step.notes or "Unknown error"
                    )
                }],
                system_msgs=[{
                    "role": "system",
                    "content": PLANNING_SYSTEM_PROMPT
                }]
            )
            
            new_steps = self._parse_steps_json(response.content)
            if not new_steps:
                new_steps = self._parse_steps_simple(response.content)
            
            if not new_steps:
                logger.warning("[PlanningFlow] Failed to generate new steps for replan")
                return False
            
            result = await self.planning_tool.execute(
                command="replan",
                plan_id=self.current_plan_id,
                steps=new_steps
            )
            
            if result.error:
                logger.error(f"[PlanningFlow] Replan failed: {result.error}")
                return False
            
            logger.info(f"[PlanningFlow] Replanned with {len(new_steps)} new steps")
            return True
            
        except Exception as e:
            logger.error(f"[PlanningFlow] Replan error: {e}")
            return False
    
    async def _generate_summary(self, original_request: str) -> str:
        """Generate comprehensive execution summary"""
        plan = self.planning_tool.plans.get(self.current_plan_id)
        progress = plan.get_progress() if plan else {}
        
        success_count = sum(1 for r in self.execution_results if r.success)
        total_count = len(self.execution_results)
        total_duration = sum(r.duration_ms for r in self.execution_results)
        
        status_emoji = "✅" if progress.get("percentage", 0) == 100 else "⚠️"
        
        summary = [
            f"## {status_emoji} Execution Summary",
            "",
            f"**Request:** {original_request[:100]}{'...' if len(original_request) > 100 else ''}",
            f"**Duration:** {total_duration / 1000:.1f}s",
            f"**Steps Executed:** {success_count}/{total_count} successful",
            f"**Replanning Attempts:** {self.replan_count}",
            "",
        ]
        
        if plan:
            result = await self.planning_tool.execute(
                command="get",
                plan_id=self.current_plan_id
            )
            import json
            data = json.loads(result.output)
            summary.append("### Plan Progress")
            summary.append(data.get("formatted", ""))
            summary.append("")
        
        summary.append("### Step Results")
        for r in self.execution_results:
            status = "✅" if r.success else "❌"
            retry_info = f" (retries: {r.retries})" if r.retries > 0 else ""
            summary.append(f"{status} **Step {r.step_index + 1}:** {r.step_text[:50]}...{retry_info}")
            if r.result:
                summary.append(f"   → {r.result[:100]}...")
            if r.error:
                summary.append(f"   ⚠ Error: {r.error[:100]}...")
        
        return "\n".join(summary)
    
    def get_current_plan(self) -> Optional[Dict]:
        """Get current plan details"""
        if not self.current_plan_id:
            return None
        plan = self.planning_tool.plans.get(self.current_plan_id)
        return plan.to_dict() if plan else None
    
    def get_execution_results(self) -> List[Dict]:
        """Get all execution results"""
        return [r.to_dict() for r in self.execution_results]
