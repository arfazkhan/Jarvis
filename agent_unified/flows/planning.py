"""
ARVIS Planning Flow
===================

Flow for executing multi-step plans with agent coordination.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import Field

from agent_unified.llm import UnifiedLLM
from agent_unified.tools.planning import PlanningTool
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

Output ONLY a numbered list of steps, one per line. Example:
1. First step description
2. Second step description
3. Third step description

Steps:"""


class PlanningFlow(BaseFlow):
    """
    Planning flow for executing complex multi-step tasks.
    
    This flow:
    1. Creates an initial plan from user request
    2. Executes each step using the appropriate agent
    3. Tracks progress and updates step status
    4. Handles failures and replanning if needed
    """
    
    llm: UnifiedLLM = Field(default_factory=UnifiedLLM)
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)
    agents: Dict[str, Any] = Field(default_factory=dict)
    primary_agent: str = "arvis"
    
    # Execution settings
    max_steps: int = Field(default=20, description="Max steps to execute")
    auto_create_plan: bool = Field(default=True, description="Auto-create plan from request")
    
    # Current state
    current_plan_id: Optional[str] = None
    execution_log: List[Dict] = Field(default_factory=list)
    
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
        logger.info(f"[PlanningFlow] Starting execution for: {input_text[:100]}...")
        
        try:
            # Step 1: Create plan
            if self.auto_create_plan:
                plan_result = await self._create_plan_from_request(input_text)
                if not plan_result:
                    return "Failed to create execution plan"
                self.current_plan_id = plan_result["plan_id"]
            
            # Step 2: Execute plan steps
            execution_results = await self._execute_plan()
            
            # Step 3: Generate summary
            summary = await self._generate_summary(input_text, execution_results)
            
            return summary
            
        except Exception as e:
            logger.error(f"[PlanningFlow] Execution error: {e}")
            return f"Plan execution failed: {str(e)}"
    
    async def _create_plan_from_request(self, request: str) -> Optional[Dict]:
        """Create a plan from user request using LLM"""
        logger.info("[PlanningFlow] Generating plan from request...")
        
        try:
            # Use LLM to generate plan steps
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
            
            # Parse steps from response
            steps = self._parse_steps(response.content)
            
            if not steps:
                logger.warning("[PlanningFlow] No steps parsed from LLM response")
                return None
            
            # Create plan using planning tool
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
    
    def _parse_steps(self, text: str) -> List[str]:
        """Parse numbered steps from LLM response"""
        if not text:
            return []
        
        steps = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Remove numbering (1., 2., etc.)
            import re
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
            
            if cleaned and len(cleaned) > 3:
                steps.append(cleaned)
        
        return steps[:15]  # Limit to 15 steps
    
    async def _execute_plan(self) -> List[Dict]:
        """Execute all steps in the current plan"""
        if not self.current_plan_id:
            return []
        
        results = []
        step_count = 0
        
        while step_count < self.max_steps:
            # Get next pending step
            next_step = self.planning_tool.get_next_pending_step(self.current_plan_id)
            
            if not next_step:
                logger.info("[PlanningFlow] All steps completed")
                break
            
            step_count += 1
            step_idx = next_step["index"]
            step_text = next_step["text"]
            
            logger.info(f"[PlanningFlow] Executing step {step_idx + 1}: {step_text[:50]}...")
            
            # Mark step in progress
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.current_plan_id,
                step_index=step_idx,
                step_status="in_progress"
            )
            
            # Execute step using agent
            step_result = await self._execute_step(step_text)
            
            # Mark step completed
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.current_plan_id,
                step_index=step_idx,
                step_status="completed" if step_result["success"] else "blocked",
                step_notes=step_result["result"][:200] if step_result["result"] else ""
            )
            
            results.append({
                "step_index": step_idx,
                "step_text": step_text,
                "success": step_result["success"],
                "result": step_result["result"]
            })
            
            self.execution_log.append({
                "step_index": step_idx,
                "timestamp": time.time(),
                "result": step_result
            })
        
        return results
    
    async def _execute_step(self, step_text: str) -> Dict:
        """Execute a single step using the primary agent"""
        agent = self.get_agent()
        
        if not agent:
            return {
                "success": False,
                "result": "No agent available for execution"
            }
        
        try:
            # Run the agent with the step as input
            result = await agent.run(step_text)
            
            return {
                "success": True,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"[PlanningFlow] Step execution error: {e}")
            return {
                "success": False,
                "result": str(e)
            }
    
    async def _generate_summary(self, original_request: str, results: List[Dict]) -> str:
        """Generate execution summary"""
        completed = sum(1 for r in results if r["success"])
        total = len(results)
        
        # Get final plan state
        plan_result = await self.planning_tool.execute(
            command="get",
            plan_id=self.current_plan_id
        )
        
        summary_parts = [
            f"## Execution Summary",
            f"",
            f"**Request:** {original_request[:100]}...",
            f"**Steps Completed:** {completed}/{total}",
            f"",
        ]
        
        if plan_result.output:
            try:
                import json
                plan_data = json.loads(plan_result.output)
                if "progress" in plan_data:
                    summary_parts.append("### Plan Progress")
                    summary_parts.append(plan_data["progress"])
                    summary_parts.append("")
            except Exception:
                pass
        
        summary_parts.append("### Step Results")
        for r in results:
            status = "✅" if r["success"] else "❌"
            summary_parts.append(f"{status} **Step {r['step_index'] + 1}:** {r['step_text'][:50]}...")
            if r["result"]:
                summary_parts.append(f"   → {r['result'][:100]}...")
        
        return "\n".join(summary_parts)
    
    def get_current_plan(self) -> Optional[Dict]:
        """Get the current plan details"""
        if not self.current_plan_id:
            return None
        return self.planning_tool.plans.get(self.current_plan_id)
    
    def get_execution_log(self) -> List[Dict]:
        """Get the execution log"""
        return self.execution_log
