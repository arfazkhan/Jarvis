"""
Plan Graph Engine
-----------------
Manages the execution dependency graph (DAG).
Converts a list of steps into a graph and provides execution layers.
"""

import networkx as nx
from typing import List, Dict, Any, Set

class PlanNode:
    def __init__(self, node_id: str, action: str, params: Dict[str, Any], depends_on: List[str] = None):
        self.id = node_id
        self.action = action
        self.params = params
        self.depends_on = depends_on or []
        self.status = "pending" # pending, running, completed, failed

    def __repr__(self):
        return f"Node({self.id}, {self.action})"

class PlanGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, PlanNode] = {}

    def add_node(self, node: PlanNode):
        """Add a node to the graph"""
        self.nodes[node.id] = node
        self.graph.add_node(node.id)
        for dep_id in node.depends_on:
            self.graph.add_edge(dep_id, node.id)

    def build_from_sequence(self, steps: List[Dict[str, Any]]):
        """
        Build a linear graph from a list of steps.
        Assumes step[i] depends on step[i-1].
        """
        prev_id = None
        for i, step in enumerate(steps):
            node_id = f"step_{i}"
            action = step.get("action")
            params = step.get("params", {})
            
            depends_on = [prev_id] if prev_id else []
            
            node = PlanNode(node_id, action, params, depends_on)
            self.add_node(node)
            prev_id = node_id

    def get_execution_layers(self) -> List[List[PlanNode]]:
        """
        Return layers of nodes that can be executed in parallel.
        Layer 0: No dependencies.
        Layer 1: Depends only on Layer 0.
        ...
        """
        if not self.nodes:
            return []
            
        try:
            # Topological generation
            layers = []
            for generation in nx.topological_generations(self.graph):
                layer_nodes = [self.nodes[node_id] for node_id in generation]
                layers.append(layer_nodes)
            return layers
        except nx.NetworkXUnfeasible:
            print("[PlanGraph] Error: Cycle detected in plan!")
            return []

    def get_node(self, node_id: str) -> PlanNode:
        return self.nodes.get(node_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dict"""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "action": n.action,
                    "params": n.params,
                    "depends_on": n.depends_on
                }
                for n in self.nodes.values()
            ]
        }
