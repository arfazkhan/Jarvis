"""
Mission Executor
----------------
Executes DAG plans with parallel execution, retries, timeouts, and scene integration.
"""

import asyncio
import time
from typing import Dict, Optional, List, Any
from agent.event_bus.event_bus import EventBus
from agent_plan.plan_graph import PlanGraph
from agent_mission.base.mission_step import MissionStep, StepType, StepStatus
from agent_mission.mission_store import MissionStore
from agent_mission.base.mission import Mission, MissionStatus
from agent_mission.mission_planner import MissionPlanner

class MissionExecutor:
    def __init__(self, event_bus: EventBus, store: MissionStore, planner: MissionPlanner, scene_engine=None):
        self.event_bus = event_bus
        self.store = store
        self.planner = planner
        self.scene_engine = scene_engine
        self.active_executions: Dict[str, bool] = {}  # mission_id -> is_running
        
        # Subscribe to events
        self.event_bus.subscribe("mission_started", self._handle_mission_started)
        
    async def execute_mission(self, mission_id: str, plan: PlanGraph):
        """
        Execute a mission's DAG plan with parallel layer execution.
        
        Args:
            mission_id: Mission identifier
            plan: PlanGraph to execute
        """
        mission = self.store.load_mission(mission_id)
        if not mission:
            raise ValueError(f"Mission not found: {mission_id}")
        
        # Mark as running
        self.active_executions[mission_id] = True
        mission.status = MissionStatus.EXECUTING
        self.store.save_mission(mission)
        
        try:
            # Get execution layers (topologically sorted)
            layers = plan.get_execution_layers()
            
            print(f"🚀 Executing mission {mission_id}: {len(layers)} layers")
            
            # Execute each layer in sequence
            for layer_idx, layer in enumerate(layers):
                if not self.active_executions.get(mission_id, False):
                    print(f"⚠️ Mission {mission_id} cancelled")
                    break
                
                print(f"📍 Layer {layer_idx + 1}/{len(layers)}: {len(layer)} steps")
                
                # Execute all steps in layer concurrently
                tasks = []
                for node in layer:
                    # node is already a PlanNode object from get_execution_layers()
                    tasks.append(self._execute_step(mission_id, node, mission))
                
                # Wait for all steps in layer to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Check for failures
                for idx, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(f"❌ Step failed: {layer[idx]} - {result}")
                        raise result
                
            # Mission completed successfully
            mission.status = MissionStatus.MONITORING
            self.store.save_mission(mission)
            
            self.event_bus.publish({
                "type": "mission_execution_completed",
                "source": "mission_executor",
                "payload": {"mission_id": mission_id}
            })
            
            print(f"✅ Mission {mission_id} execution completed")
            
        except Exception as e:
            mission.status = MissionStatus.FAILED
            mission.history.append({
                "event": "execution_failed",
                "error": str(e),
                "ts": time.time()
            })
            self.store.save_mission(mission)
            
            self.event_bus.publish({
                "type": "mission_execution_failed",
                "source": "mission_executor",
                "payload": {
                    "mission_id": mission_id,
                    "error": str(e)
                }
            })
            
            print(f"❌ Mission {mission_id} failed: {e}")
            raise
        finally:
            self.active_executions[mission_id] = False
    def _handle_mission_started(self, event: Dict[str, Any]):
        """Handle mission_started event by generating plan and executing"""
        payload = event.get("payload", {})
        mission_id = payload.get("mission_id")
        
        if not mission_id:
            return
            
        print(f"⚡ MissionExecutor received start event for {mission_id}")
        
        # Run in background task
        self._run_async(self._prepare_and_execute(mission_id))

    def _run_async(self, coro):
        """Helper to run coroutine in background"""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running loop, spawn a thread
            def run_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(coro)
                loop.close()
            
            import threading
            t = threading.Thread(target=run_in_thread, daemon=True)
            t.start()
        
    async def _prepare_and_execute(self, mission_id: str):
        """Generate plan and execute mission"""
        try:
            mission = self.store.load_mission(mission_id)
            if not mission:
                print(f"❌ Mission not found: {mission_id}")
                return
                
            # Generate plan
            print(f"📋 Generating plan for {mission.mission_type}...")
            plan = self.planner.generate_plan(mission.mission_type, mission.context)
            
            # Execute
            await self.execute_mission(mission_id, plan)
            
        except Exception as e:
            print(f"❌ Failed to prepare/execute mission {mission_id}: {e}")
            import traceback
            traceback.print_exc()
    async def _execute_step(self, mission_id: str, node, mission: Mission) -> Dict:
        """
        Execute a single mission step with timeout and retry logic.
        
        Args:
            mission_id: Mission identifier
            node: PlanNode from PlanGraph
            mission: Mission object
        
        Returns:
            Step execution result
        """
        # Extract step info from node
        step_id = node.id
        action = node.action  # Step type as string
        params = node.params
        
        # Determine timeout (default 60s)
        timeout = params.get("timeout", 60)
        retry_count = params.get("retry_count", 2)
        
        print(f"  ▶️ Executing step: {step_id} (type: {action})")
        
        # Publish step started event
        self.event_bus.publish({
            "type": "mission_step_started",
            "source": "mission_executor",
            "payload": {
                "mission_id": mission_id,
                "step_id": step_id,
                "action": action
            }
        })
        
        # Execute with retry logic
        last_error = None
        for attempt in range(retry_count + 1):
            try:
                # Execute based on step type
                result = await asyncio.wait_for(
                    self._execute_step_by_type(mission_id, step_id, action, params, mission),
                    timeout=timeout
                )
                
                # Success
                self.event_bus.publish({
                    "type": "mission_step_completed",
                    "source": "mission_executor",
                    "payload": {
                        "mission_id": mission_id,
                        "step_id": step_id,
                        "result": result
                    }
                })
                
                print(f"  ✅ Step completed: {step_id}")
                return result
                
            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout}s"
                print(f"  ⏱️ Step {step_id} timeout (attempt {attempt + 1}/{retry_count + 1})")
                
            except Exception as e:
                last_error = str(e)
                print(f"  ⚠️ Step {step_id} error: {e} (attempt {attempt + 1}/{retry_count + 1})")
            
            # Wait before retry
            if attempt < retry_count:
                await asyncio.sleep(1)
        
        # All retries failed
        raise RuntimeError(f"Step {step_id} failed after {retry_count + 1} attempts: {last_error}")
    
    async def _execute_step_by_type(self, mission_id: str, step_id: str, action: str, params: Dict, mission: Mission) -> Dict:
        """
        Execute step based on its type.
        
        Args:
            mission_id: Mission identifier
            step_id: Step identifier
            action: Step type (collection, scene, automation, monitoring, action)
            params: Step parameters
            mission: Mission object
        
        Returns:
            Execution result
        """
        if action == "collection":
            # Data collection step
            # TODO: Integrate with data collection services
            return await self._execute_collection(step_id, params, mission)
        
        elif action == "scene":
            # Scene generation/application step
            return await self._execute_scene(step_id, params, mission)
        
        elif action == "automation":
            # Automation scheduling step
            return await self._execute_automation(step_id, params, mission)
        
        elif action == "monitoring":
            # Monitoring step (continuous or one-time)
            return await self._execute_monitoring(step_id, params, mission)
        
        elif action == "action":
            # Direct device action
            return await self._execute_action(step_id, params, mission)
        
        else:
            raise ValueError(f"Unknown step type: {action}")
    
    async def _execute_collection(self, step_id: str, params: Dict, mission: Mission) -> Dict:
        """Execute data collection step"""
        # Placeholder for data collection
        # In production, this would:
        # 1. Query sensor history from Phase 4
        # 2. Compute statistics
        # 3. Store in mission context
        
        print(f"    📊 Collecting data: {params.get('data_types', [])}")
        await asyncio.sleep(0.1)  # Simulate work
        
        return {
            "status": "success",
            "data_collected": params.get("data_types", [])
        }
    
    async def _execute_scene(self, step_id: str, params: Dict, mission: Mission) -> Dict:
        """Execute scene generation/application step"""
        scene_name = params.get("scene_name", "unknown")
        
        if self.scene_engine:
            # Use Phase 2 SceneEngine
            try:
                # Generate or retrieve scene
                scene_params = {k: v for k, v in params.items() if k != "scene_name"}
                
                # TODO: scene_engine.generate_scene(scene_name, scene_params)
                print(f"    🎬 Creating scene: {scene_name} with params {scene_params}")
                await asyncio.sleep(0.1)
                
                return {
                    "status": "success",
                    "scene_id": scene_name,
                    "scene_params": scene_params
                }
            except Exception as e:
                raise RuntimeError(f"Scene creation failed: {e}")
        else:
            # Fallback: log scene parameters
            print(f"    🎬 Scene step (no SceneEngine): {scene_name}")
            return {
                "status": "success_no_engine",
                "scene_name": scene_name,
                "params": params
            }
    
    async def _execute_automation(self, step_id: str, params: Dict, mission: Mission) -> Dict:
        """Execute automation scheduling step"""
        trigger_time = params.get("trigger_time", "unknown")
        scene_id = params.get("scene_id", None)
        
        print(f"    ⏰ Scheduling automation: trigger={trigger_time}, scene={scene_id}")
        
        # TODO: Integrate with automation scheduler (APScheduler or similar)
        # For now, just log the schedule
        await asyncio.sleep(0.1)
        
        return {
            "status": "success",
            "scheduled": True,
            "trigger_time": trigger_time,
            "scene_id": scene_id
        }
    
    async def _execute_monitoring(self, step_id: str, params: Dict, mission: Mission) -> Dict:
        """Execute monitoring step"""
        metrics = params.get("metrics", [])
        continuous = params.get("continuous", False)
        
        print(f"    📈 Monitoring: metrics={metrics}, continuous={continuous}")
        
        # TODO: Set up monitoring hooks
        # For continuous monitoring, this would:
        # 1. Subscribe to sensor events
        # 2. Compute metrics on each update
        # 3. Trigger MissionMonitor.evaluate_mission()
        
        await asyncio.sleep(0.1)
        
        return {
            "status": "success",
            "monitoring_active": True,
            "metrics": metrics,
            "continuous": continuous
        }
    
    async def _execute_action(self, step_id: str, params: Dict, mission: Mission) -> Dict:
        """Execute direct device action"""
        device_list = params.get("device_list", [])
        action = params.get("action", "unknown")
        
        print(f"    🔌 Device action: {action} on {device_list}")
        
        # TODO: Integrate with device controller
        # This would call agent.devices or VirtualMatterController
        await asyncio.sleep(0.1)
        
        return {
            "status": "success",
            "devices_affected": device_list,
            "action": action
        }
    
    def cancel_mission(self, mission_id: str):
        """Cancel an active mission execution"""
        if mission_id in self.active_executions:
            self.active_executions[mission_id] = False
            print(f"🛑 Mission {mission_id} cancellation requested")
