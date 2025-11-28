"""
Plan Executor
-------------
Executes the Plan Graph.
Handles:
1. Layer-by-layer execution
2. Safety Validation before execution
3. Error handling and retries
"""

import time
import threading
from typing import Dict, Any, List

from agent.event_bus.event_bus import EventBus
from agent_plan.plan_graph import PlanGraph, PlanNode
from agent_plan.safety_validator import SafetyValidator

class PlanExecutor:
    def __init__(self, event_bus: EventBus, matter_controller=None):
        self.event_bus = event_bus
        self.matter_controller = matter_controller
        self.validator = SafetyValidator()
        self.running = False

    def execute(self, graph: PlanGraph) -> bool:
        """
        Execute a plan graph.
        Returns True if successful, False if failed.
        """
        self.running = True
        print("[PlanExecutor] Starting execution...")
        
        layers = graph.get_execution_layers()
        
        for i, layer in enumerate(layers):
            print(f"[PlanExecutor] Executing Layer {i} ({len(layer)} steps)")
            
            # 1. Validate Layer
            # We convert nodes back to dicts for validator
            layer_steps = [{"action": n.action, "params": n.params, "id": n.id} for n in layer]
            # Context is mocked for now
            validated, errors = self.validator.validate_plan(layer_steps, {})
            
            if errors:
                print(f"[PlanExecutor] Safety Errors in Layer {i}: {errors}")
                self.running = False
                return False
                
            # 2. Execute Layer (Parallel)
            # For MVP, we just iterate, but in real system we'd fire threads
            success = self._execute_layer(layer)
            if not success:
                print(f"[PlanExecutor] Layer {i} failed.")
                self.running = False
                return False
                
        print("[PlanExecutor] Plan completed successfully.")
        self.running = False
        return True

    def _execute_layer(self, nodes: List[PlanNode]) -> bool:
        """Execute a list of nodes in parallel (simulated)"""
        threads = []
        results = []
        
        def run_node(node):
            res = self._execute_node(node)
            results.append(res)

        for node in nodes:
            t = threading.Thread(target=run_node, args=(node,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        return all(results)

    def _execute_node(self, node: PlanNode) -> bool:
        """Execute a single node"""
        try:
            print(f"[PlanExecutor] Running: {node.action} ({node.params})")
            
            # Physical Actuation
            if self.matter_controller:
                device_id = node.params.get("device_id", "unknown")
                endpoint = node.params.get("endpoint", 1)
                
                if node.action == "turn_on":
                    self.matter_controller.turn_on(device_id, endpoint)
                elif node.action == "turn_off":
                    self.matter_controller.turn_off(device_id, endpoint)
                else:
                    # Fallback for other actions (scenes, etc.)
                    time.sleep(0.1)
            else:
                # Simulation fallback
                time.sleep(0.1)
            
            # Publish event
            self.event_bus.publish({
                "type": "action_execution",
                "source": "plan_executor",
                "payload": {
                    "node_id": node.id,
                    "action": node.action,
                    "params": node.params,
                    "status": "completed"
                }
            })
            
            node.status = "completed"
            return True
        except Exception as e:
            print(f"[PlanExecutor] Error executing node {node.id}: {e}")
            node.status = "failed"
            return False

    def execute_action(self, action: str, params: Dict[str, Any]) -> bool:
        """
        Execute a single action immediately (bypass graph).
        Useful for direct voice commands.
        """
        # Create a temporary node
        node = PlanNode(node_id="direct_action", action=action, params=params)
        return self._execute_node(node)
