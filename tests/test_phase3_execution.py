import unittest
import time
from arvis_core.event_bus.event_bus import EventBus
from agent_plan.plan_graph import PlanGraph, PlanNode
from agent_plan.plan_executor import PlanExecutor

class TestPhase3Execution(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self.executor = PlanExecutor(self.bus)

    def test_plan_execution_success(self):
        """Verify successful execution of a DAG plan"""
        print("\n[Test] Plan Execution Success")
        
        # Create Graph
        # A -> B
        # A -> C
        # B, C -> D
        graph = PlanGraph()
        
        node_a = PlanNode("A", "turn_on", {"device": "light_1"})
        node_b = PlanNode("B", "dim", {"device": "light_1"}, depends_on=["A"])
        node_c = PlanNode("C", "turn_on", {"device": "fan_1"}, depends_on=["A"])
        node_d = PlanNode("D", "notify", {"msg": "done"}, depends_on=["B", "C"])
        
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_node(node_c)
        graph.add_node(node_d)
        
        # Capture events
        events = []
        self.bus.subscribe("action_execution", lambda e: events.append(e))
        
        # Execute
        success = self.executor.execute(graph)
        
        ids = [e["payload"]["node_id"] for e in events]
        print(f"Captured IDs: {ids}")
        
        self.assertTrue(success)
        self.assertEqual(len(events), 4)
        
        # Verify Order (A must be first, D must be last)
        self.assertEqual(ids[0], "A")
        self.assertEqual(ids[-1], "D")
        print("✅ DAG executed in correct topological order")

    def test_safety_conflict(self):
        """Verify SafetyValidator catches conflicts"""
        print("\n[Test] Safety Conflict")
        
        graph = PlanGraph()
        # Two nodes targeting same device in same layer (conceptually, though validator checks per layer)
        # Actually, my validator checks for duplicates in the *list* passed to it.
        # If A and B are in same layer, they are passed together.
        
        node_a = PlanNode("A", "turn_on", {"device": "tv"})
        node_b = PlanNode("B", "turn_off", {"device": "tv"}) # Conflict!
        
        graph.add_node(node_a)
        graph.add_node(node_b)
        
        # Execute
        success = self.executor.execute(graph)
        
        self.assertFalse(success)
        print("✅ SafetyValidator caught conflict")

if __name__ == "__main__":
    unittest.main()
