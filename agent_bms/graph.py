"""
BMS Graph Topology
==================

First-class graph object for building topology. 
Replaces implicit dictionaries with explicit nodes and edges.

Supports:
- Upstream/Downstream traversal
- Path scoring based on historical outcomes
- Explainability
"""

from typing import Dict, List, Set, Optional, Tuple
import logging
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger("arvis.bms.graph")

@dataclass
class GraphEdge:
    source: str
    target: str
    relation_type: str = "feeds"  # feeds, controls, powers
    weight: float = 1.0


class BMSGraph:
    """
    Explicit graph representation of the building equipment topology.
    """
    
    def __init__(self):
        self._adj: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._rev_adj: Dict[str, List[GraphEdge]] = defaultdict(list)
        self._nodes: Set[str] = set()
        
        # Load default hierarchy
        self._init_default_hierarchy()
        
        # Connection to pattern store for outcome-aware scoring
        from agent_bms.learning.operator_patterns import get_pattern_store
        self.pattern_store = get_pattern_store()

    def _init_default_hierarchy(self):
        """Initialize with standard equipment ontology."""
        # Standard BMS equipment hierarchy
        # Parent -> Child means parent failure affects child
        hierarchy = {
            # Chilled Water System
            "chiller": ["chw_pump", "ahu"],
            "chw_pump": ["ahu"],
            "cooling_tower": ["chiller"],
            "condenser_pump": ["cooling_tower"],
            
            # Air Handling
            "ahu": ["vav", "fcu"],
            "vav": ["room"],
            "fcu": ["room"],
            
            # Hot Water System
            "boiler": ["hw_pump", "ahu"],
            "hw_pump": ["ahu"],
            
            # Electrical
            "main_breaker": ["panel", "chiller", "ahu"],
            "panel": ["vav", "fcu", "lighting"],
        }
        
        for parent, children in hierarchy.items():
            for child in children:
                self.add_edge(parent, child, "feeds")

    def add_edge(self, source: str, target: str, relation: str = "feeds", weight: float = 1.0):
        """Add a directed edge to the graph."""
        self._nodes.add(source)
        self._nodes.add(target)
        
        edge = GraphEdge(source, target, relation, weight)
        self._adj[source].append(edge)
        
        rev_edge = GraphEdge(target, source, relation, weight)
        self._rev_adj[target].append(rev_edge)

    def get_downstream(self, node: str) -> List[str]:
        """Get nodes immediately downstream (affected by this node)."""
        return [e.target for e in self._adj.get(node, [])]

    def get_upstream(self, node: str) -> List[str]:
        """Get nodes immediately upstream (that affect this node)."""
        return [e.target for e in self._rev_adj.get(node, [])]

    def get_all_upstream(self, node: str, visited: Set[str] = None) -> Set[str]:
        """Get all upstream nodes recursively."""
        if visited is None:
            visited = set()
        
        parents = self.get_upstream(node)
        for p in parents:
            if p not in visited:
                visited.add(p)
                self.get_all_upstream(p, visited)
        
        return visited

    def score_path(self, path: List[str]) -> float:
        """
        Score a causal path based on historical outcomes.
        
        # Logic:
        # - Base score: 1.0
        # - Bonus: If nodes in path have high successful query counts (+0.1 to +0.5)
        # - Penalty: If nodes have high 'ignored' alarm counts (implied if success rate is low)
        """
        score = 1.0
        
        if not self.pattern_store:
            return score
            
        # Check success rate of the root cause (most important node)
        root_node = path[0]
        stats = self.pattern_store.get_equipment_stats(root_node)
        
        # Bias: 
        # success_rate 0.8 -> +0.3
        # success_rate 0.2 -> -0.3
        rate = stats.get("success_rate", 0.5)
        count = stats.get("count", 0)
        
        if count > 0:
            bias = (rate - 0.5)  # Range -0.5 to +0.5
            score += bias
            
        return score

    def visualize(self) -> str:
        """Return Mermaid JS graph definition."""
        lines = ["graph TD"]
        for src, edges in self._adj.items():
            for edge in edges:
                lines.append(f"    {src} --> {edge.target}")
        return "\n".join(lines)
