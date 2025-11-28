"""
Mission Executor v2
-------------------
Orchestrates mission execution using ActionRouter and specialized executors.
Supports persistence, cancellation, and restart recovery.
"""

import asyncio
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field, asdict

from agent.event_bus.event_bus import EventBus
from agent_plan.plan_graph import PlanGraph
from agent_mission.base.mission_step import MissionStep, StepType, StepStatus
from agent_mission.mission_store import MissionStore
from agent_mission.base.mission import Mission, MissionStatus
from agent_mission.mission_planner import MissionPlanner
from agent_plan.action_router import ActionRouter
from agent_plan.safety_validator import SafetyValidator

@dataclass
class MissionRuntimeState:
    """Runtime state of a mission execution"""
    mission_id: str
    current_layer_index: int = 0
    step_status: Dict[str, str] = field(default_factory=dict)  # step_id -> status
    step_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    started_ts: float = field(default_factory=time.time)
    last_update_ts: float = field(default_factory=time.time)
    cancelled: bool = False
    paused: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MissionRuntimeState':
        return cls(**data)

class MissionExecutor:
    def __init__(self, 
                 event_bus: EventBus, 
                 store: MissionStore, 
                 planner: MissionPlanner, 
                 action_router: ActionRouter,
                 safety_validator: Optional[SafetyValidator] = None):
        self.event_bus = event_bus
        self.store = store
        self.planner = planner
        self.action_router = action_router
        self.safety_validator = safety_validator
        
        # In-memory cache of active runtime states
        self.active_states: Dict[str, MissionRuntimeState] = {}
        
        # Subscribe to events
        self.event_bus.subscribe("mission_started", self._handle_mission_started)
        
    async def start_execution(self, mission_id: str, plan: PlanGraph):
        """
        Start executing a mission from scratch.
        """
        mission = self.store.load_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")
            
        print(f"🚀 Starting execution for mission {mission_id}")
        
        # Initialize runtime state
        state = MissionRuntimeState(mission_id=mission_id)
        
        # Initialize all steps to PENDING
        layers = plan.get_execution_layers()
        for layer in layers:
            for node in layer:
                state.step_status[node.id] = StepStatus.PENDING.value
                
        self.active_states[mission_id] = state
        
        # Update mission status
        mission.status = MissionStatus.EXECUTING
        mission.runtime_state = state.to_dict()
        self.store.save_mission(mission)
        
        self.event_bus.publish({
            "type": "mission_execution_started",
            "source": "mission_executor",
            "payload": {"mission_id": mission_id}
        })
        
        # Start the execution loop
        self._run_async(self._execution_loop(mission_id, plan))

    async def resume_execution(self, mission_id: str):
        """
        Resume execution of an existing mission (e.g. after restart).
        """
        mission = self.store.load_mission(mission_id)
        if not mission or not mission.runtime_state:
            print(f"⚠️ Cannot resume mission {mission_id}: No runtime state found")
            return
            
        print(f"🔄 Resuming mission {mission_id}")
        
        # Restore state
        state = MissionRuntimeState.from_dict(mission.runtime_state)
        self.active_states[mission_id] = state
        
        # Rebuild plan (since we don't serialize the PlanGraph object itself, just the DAG dict)
        # Assuming mission.plan contains the DAG structure needed to rebuild PlanGraph
        # For now, we might need to regenerate it or assume it's consistent
        # In a real system, we'd serialize the plan graph or rebuild it deterministically
        if not mission.plan:
             print(f"⚠️ Cannot resume mission {mission_id}: No plan found")
             return
             
        # Reconstruct PlanGraph from stored plan dict
        # This assumes MissionPlanner has a method to rebuild from dict, or we just use the dict
        # For this implementation, let's assume we can get the plan from the planner using context
        # NOTE: This is a simplification. Ideally we persist the exact plan.
        plan = self.planner.generate_plan(mission.mission_type, mission.context)
        
        # Start loop
        self._run_async(self._execution_loop(mission_id, plan))

    async def _execution_loop(self, mission_id: str, plan: PlanGraph):
        """
        Main execution loop. Advances layers until completion or failure.
        """
        try:
            while True:
                state = self.active_states.get(mission_id)
                if not state:
                    print(f"⚠️ Execution loop stopped: State lost for {mission_id}")
                    break
                
                if state.cancelled:
                    print(f"🛑 Mission {mission_id} cancelled")
                    await self._finalize_mission(mission_id, MissionStatus.FAILED, "Cancelled")
                    break
                    
                if state.paused:
                    await asyncio.sleep(1)
                    continue
                
                # Get current layer
                layers = plan.get_execution_layers()
                if state.current_layer_index >= len(layers):
                    print(f"✅ Mission {mission_id} all layers completed")
                    await self._finalize_mission(mission_id, MissionStatus.COMPLETED)
                    break
                
                current_layer = layers[state.current_layer_index]
                print(f"📍 Executing Layer {state.current_layer_index + 1}/{len(layers)}")
                
                # Execute layer
                success, error = await self._execute_layer(mission_id, current_layer, state)
                
                if success:
                    state.current_layer_index += 1
                    self._persist_state(mission_id)
                else:
                    print(f"❌ Layer execution failed for {mission_id}: {error}")
                    await self._finalize_mission(mission_id, MissionStatus.FAILED, f"Layer execution failed: {error}")
                    break
                    
        except Exception as e:
            print(f"❌ Execution loop error for {mission_id}: {e}")
            import traceback
            traceback.print_exc()
            await self._finalize_mission(mission_id, MissionStatus.FAILED, str(e))

    async def _execute_layer(self, mission_id: str, layer: List[Any], state: MissionRuntimeState) -> Any:
        """
        Execute a single layer of steps in parallel.
        Returns: (success: bool, error: Optional[str])
        """
        tasks = []
        
        # 1. Filter steps that are already done (in case of resume)
        pending_nodes = []
        for node in layer:
            status = state.step_status.get(node.id, StepStatus.PENDING.value)
            if status == StepStatus.SUCCESS.value:
                continue
            pending_nodes.append(node)
            
        if not pending_nodes:
            return True, None # Layer already done
            
        # 2. Validate Safety
        if self.safety_validator:
            # Convert nodes to actions for validation
            actions = [{"type": node.action, "params": node.params} for node in pending_nodes]
            if not self.safety_validator.validate_layer(actions):
                print(f"⚠️ Safety validation failed for layer in {mission_id}")
                return False, "Safety validation failed"

        # 3. Create tasks
        context = self._build_context(mission_id)
        
        for node in pending_nodes:
            step = MissionStep(
                step_id=node.id,
                step_type=StepType(node.action), # Assuming node.action matches StepType values
                parameters=node.params,
                timeout=node.params.get("timeout", 60),
                retry_count=node.params.get("retry_count", 2)
            )
            tasks.append(self._execute_single_step(step, context, state))
            
        # 4. Run parallel
        if not tasks:
            return True, None
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 5. Check results
        layer_success = True
        first_error = None
        
        for result in results:
            if isinstance(result, Exception):
                layer_success = False
                first_error = str(result)
            elif isinstance(result, tuple):
                success, error = result
                if not success:
                    layer_success = False
                    first_error = error
            elif isinstance(result, bool) and not result:
                # Should not happen with updated _execute_single_step but for safety
                layer_success = False
                first_error = "Step returned False"
                
        return layer_success, first_error

    async def _execute_single_step(self, step: MissionStep, context: Any, state: MissionRuntimeState) -> Any:
        """
        Execute a single step with retries via ActionRouter.
        Returns: (success: bool, error: Optional[str])
        """
        print(f"  ▶️ Executing step: {step.step_id} ({step.step_type.value})")
        
        state.step_status[step.step_id] = StepStatus.RUNNING.value
        self._persist_state(context.metadata.get("mission_id"))
        
        self.event_bus.publish({
            "type": "mission_step_started",
            "payload": {"mission_id": context.metadata.get("mission_id"), "step_id": step.step_id}
        })
        
        last_error = None
        
        for attempt in range(step.retry_count + 1):
            if attempt > 0:
                print(f"  🔄 Retrying step {step.step_id} (Attempt {attempt + 1}/{step.retry_count + 1})")
                state.step_status[step.step_id] = StepStatus.RETRYING.value
                self._persist_state(context.metadata.get("mission_id"))
                await asyncio.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s, 8s...
                
            try:
                # Execute via Router
                result = self.action_router.execute(step, context)
                
                # Update state
                state.step_status[step.step_id] = StepStatus.SUCCESS.value
                state.step_outputs[step.step_id] = result
                
                self.event_bus.publish({
                    "type": "mission_step_completed",
                    "payload": {"mission_id": context.metadata.get("mission_id"), "step_id": step.step_id, "result": result}
                })
                print(f"  ✅ Step {step.step_id} success")
                return True, None
                
            except Exception as e:
                last_error = str(e)
                print(f"  ❌ Step {step.step_id} failed: {e}")
                
        # If we get here, all retries failed
        state.step_status[step.step_id] = StepStatus.FAILED.value
        
        self.event_bus.publish({
            "type": "mission_step_failed",
            "payload": {"mission_id": context.metadata.get("mission_id"), "step_id": step.step_id, "error": last_error}
        })
        return False, last_error

    def cancel_mission(self, mission_id: str):
        """Cancel a mission"""
        if mission_id in self.active_states:
            self.active_states[mission_id].cancelled = True
            self._persist_state(mission_id)
            print(f"🛑 Cancelled mission {mission_id}")

    def pause_mission(self, mission_id: str):
        """Pause a mission"""
        if mission_id in self.active_states:
            self.active_states[mission_id].paused = True
            self._persist_state(mission_id)
            print(f"⏸️ Paused mission {mission_id}")

    def resume_mission(self, mission_id: str):
        """Resume a paused mission"""
        if mission_id in self.active_states:
            self.active_states[mission_id].paused = False
            self._persist_state(mission_id)
            print(f"▶️ Resumed mission {mission_id}")

    def _persist_state(self, mission_id: str):
        """Save runtime state to MissionStore"""
        state = self.active_states.get(mission_id)
        if state:
            mission = self.store.load_mission(mission_id)
            if mission:
                mission.runtime_state = state.to_dict()
                mission.status = MissionStatus.EXECUTING # Ensure status is correct
                self.store.save_mission(mission)

    async def _finalize_mission(self, mission_id: str, status: MissionStatus, error: Optional[str] = None):
        """Clean up and save final status"""
        mission = self.store.load_mission(mission_id)
        if mission:
            mission.status = status
            if error:
                mission.history.append({"event": "failed", "error": error, "ts": time.time()})
            else:
                mission.history.append({"event": "completed", "ts": time.time()})
            
            # Clear runtime state on completion/failure to avoid resume loops?
            # Or keep it for debugging? Let's keep it but mark completed.
            if mission_id in self.active_states:
                mission.runtime_state = self.active_states[mission_id].to_dict()
            
            self.store.save_mission(mission)
            
        # Remove from active memory
        if mission_id in self.active_states:
            del self.active_states[mission_id]
            
        event_type = "mission_execution_completed" if status == MissionStatus.COMPLETED else "mission_execution_failed"
        self.event_bus.publish({
            "type": event_type,
            "payload": {"mission_id": mission_id, "error": error}
        })

    def _build_context(self, mission_id: str):
        """Build execution context"""
        from agent_mission.base.mission_context import MissionContext
        # In a real app, we'd load this from the mission object
        ctx = MissionContext(user_id="default")
        ctx.metadata["mission_id"] = mission_id
        return ctx

    def _handle_mission_started(self, event: Dict[str, Any]):
        """Handle mission_started event"""
        payload = event.get("payload", {})
        mission_id = payload.get("mission_id")
        if mission_id:
            # We need to fetch the plan somehow. 
            # Ideally the event payload has it, or we generate it.
            # For now, we assume _prepare_and_execute logic handles generation if needed
            # But here we just trigger the start if the plan exists in the mission
            self._run_async(self._prepare_and_execute(mission_id))

    async def _prepare_and_execute(self, mission_id: str):
        """Generate plan and start execution"""
        mission = self.store.load_mission(mission_id)
        if not mission:
            return
            
        # Generate plan if missing
        plan = None
        if not mission.plan:
             print(f"📋 Generating plan for {mission.mission_type}...")
             plan = self.planner.generate_plan(mission.mission_type, mission.context)
             mission.plan = plan.to_dict() # Save plan structure
             self.store.save_mission(mission)
        else:
             # Rebuild PlanGraph from dict
             # This assumes we have a way to do that. 
             # For now, let's regenerate for simplicity in this MVP
             plan = self.planner.generate_plan(mission.mission_type, mission.context)

        await self.start_execution(mission_id, plan)

    def _run_async(self, coro):
        """Helper to run coroutine"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running loop
            pass
