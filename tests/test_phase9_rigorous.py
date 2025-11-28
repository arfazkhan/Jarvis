import unittest
import asyncio
import tempfile
import shutil
import time
from unittest.mock import MagicMock, patch
from agent.event_bus.event_bus import EventBus
from agent_mission.mission_executor import MissionExecutor, MissionRuntimeState
from agent_mission.mission_store import MissionStore
from agent_mission.mission_planner import MissionPlanner
from agent_plan.action_router import ActionRouter
from agent_mission.base.mission import Mission, MissionStatus
from agent_plan.plan_graph import PlanGraph, PlanNode
from agent_mission.base.mission_step import StepStatus

class TestPhase9Rigorous(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.store = MissionStore(storage_path=self.temp_dir)
        self.planner = MagicMock(spec=MissionPlanner)
        self.action_router = MagicMock(spec=ActionRouter)
        
        self.executor = MissionExecutor(
            self.event_bus, 
            self.store, 
            self.planner, 
            self.action_router
        )
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    async def test_retry_logic(self):
        print("\n[Test] Retry Logic")
        
        # Setup: Action fails twice then succeeds
        # Since execute is called in an async function but might not be async itself in the mock,
        # we need to be careful. ActionRouter.execute is synchronous in the real code?
        # Let's check ActionRouter. It calls executor.execute which might be async?
        # In the real code: result = self.action_router.execute(step, context)
        # ActionRouter.execute returns the result of specific executor.execute.
        # Executors like DeviceExecutor are synchronous in my implementation?
        # Let's check DeviceExecutor. Yes, it returns dict.
        # So ActionRouter.execute is synchronous.
        
        self.action_router.execute.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            {"status": "success"}
        ]
        
        mission = Mission(mission_id="retry_mission", mission_type="test", status=MissionStatus.INIT)
        self.store.save_mission(mission)
        
        plan = PlanGraph()
        node = PlanNode(node_id="step1", action="action", params={"retry_count": 3})
        plan.add_node(node)
        
        # Execute
        await self.executor.start_execution("retry_mission", plan)
        
        # Wait for completion
        for _ in range(100): # Wait longer due to backoff (1+2+4 = 7s minimum)
            await asyncio.sleep(0.1)
            m = self.store.load_mission("retry_mission")
            if m.status in [MissionStatus.COMPLETED, MissionStatus.FAILED]:
                break
                
        final_mission = self.store.load_mission("retry_mission")
        self.assertEqual(final_mission.status, MissionStatus.COMPLETED)
        self.assertEqual(self.action_router.execute.call_count, 3)
        print("✅ Retry logic verified")

    async def test_recovery_from_crash(self):
        print("\n[Test] Recovery from Crash")
        
        # 1. Start mission and pause it mid-execution
        mission = Mission(mission_id="crash_mission", mission_type="test", status=MissionStatus.INIT)
        self.store.save_mission(mission)
        
        plan = PlanGraph()
        # Layer 1
        plan.add_node(PlanNode(node_id="s1", action="action", params={}))
        # Layer 2
        plan.add_node(PlanNode(node_id="s2", action="action", params={}, depends_on=["s1"]))
        
        # Mock planner to return this plan on resume
        self.planner.generate_plan.return_value = plan
        
        # Reset router mock to ensure success
        self.action_router.execute.side_effect = None
        self.action_router.execute.return_value = {"status": "success"}
        
        # Manually create state as if s1 finished and we crashed before s2
        state = MissionRuntimeState(mission_id="crash_mission")
        state.step_status["s1"] = StepStatus.SUCCESS.value
        state.current_layer_index = 1 # Ready for layer 2 (s2)
        
        mission.status = MissionStatus.EXECUTING
        mission.runtime_state = state.to_dict()
        mission.plan = plan.to_dict()
        self.store.save_mission(mission)
        
        # 2. Create NEW executor (simulating restart)
        new_executor = MissionExecutor(
            self.event_bus, 
            self.store, 
            self.planner, 
            self.action_router
        )
        
        # 3. Resume
        await new_executor.resume_execution("crash_mission")
        
        # Wait for completion
        for _ in range(100):
            await asyncio.sleep(0.1)
            try:
                m = self.store.load_mission("crash_mission")
                if m.status == MissionStatus.COMPLETED:
                    break
            except Exception as e:
                print(f"Store read error: {e}")
                continue
                
        final_mission = self.store.load_mission("crash_mission")
        self.assertEqual(final_mission.status, MissionStatus.COMPLETED)
        
        # Verify s1 was NOT executed again, but s2 WAS
        # We can't easily check s1 call count on new executor's router since it's a new mock
        # But we can check that s2 was executed.
        # Actually, let's check the router call count. 
        # Since we passed the SAME mock object to the new executor (self.action_router), 
        # we can check its call count.
        # It should be called ONCE (for s2). s1 was already done.
        # NOTE: If retry logic test ran before this, call_count is higher.
        # We should reset mock in setUp or check increment.
        # But since we use IsolatedAsyncioTestCase, setUp is called per test? 
        # Yes, setUp creates new mocks.
        self.assertEqual(self.action_router.execute.call_count, 1)
        print("✅ Recovery verified")

    async def test_cancellation(self):
        print("\n[Test] Cancellation")
        
        mission = Mission(mission_id="cancel_mission", mission_type="test", status=MissionStatus.INIT)
        self.store.save_mission(mission)
        
        plan = PlanGraph()
        plan.add_node(PlanNode(node_id="s1", action="action", params={"timeout": 5}))
        
        # Make step take a long time
        # ActionRouter.execute is synchronous, so we can't await inside it easily if it's not async.
        # But MissionExecutor calls it synchronously: result = self.action_router.execute(step, context)
        # If we want to simulate a long running step, we need to block? No, that blocks the loop.
        # If ActionRouter.execute is sync, it blocks.
        # Real executors (DeviceExecutor) are sync.
        # So MissionExecutor._execute_single_step blocks during router execution?
        # Yes, unless router returns a coroutine.
        # My implementation of _execute_single_step:
        # result = self.action_router.execute(step, context) -> SYNC call.
        # So if I put a sleep there, it blocks the whole loop.
        # To test cancellation, we need the loop to yield.
        # But if the step is blocking, we can't cancel it until it returns!
        # This is a design limitation of sync executors.
        # However, we can simulate cancellation happening *between* steps or if the step itself checks for cancellation (it doesn't).
        # Or if we have multiple steps.
        # Let's test cancellation *between* layers or steps.
        
        # Redefine plan to have 2 steps in sequence
        plan = PlanGraph()
        plan.add_node(PlanNode(node_id="s1", action="action", params={}))
        plan.add_node(PlanNode(node_id="s2", action="action", params={}, depends_on=["s1"]))
        
        # Mock execute to be fast
        self.action_router.execute.return_value = {"status": "success"}
        
        # We need to inject cancellation *after* s1 but *before* s2.
        # We can use a side_effect that cancels the mission when s1 runs.
        
        def cancel_side_effect(step, context):
            if step.step_id == "s1":
                self.executor.cancel_mission("cancel_mission")
            return {"status": "success"}
            
        self.action_router.execute.side_effect = cancel_side_effect
        
        # Start
        await self.executor.start_execution("cancel_mission", plan)
        
        # Wait
        await asyncio.sleep(0.5)
        
        final_mission = self.store.load_mission("cancel_mission")
        # It should be FAILED (Cancelled) or at least not COMPLETED if s2 didn't run.
        # Wait, if s1 cancels, the loop checks state.cancelled at the top.
        # So s1 finishes, loop continues, checks cancelled, breaks.
        # s2 should NOT run.
        
        self.assertEqual(self.action_router.execute.call_count, 1) # Only s1
        self.assertEqual(final_mission.status, MissionStatus.FAILED)
        print("✅ Cancellation verified")

if __name__ == "__main__":
    unittest.main()
