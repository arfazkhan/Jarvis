"""
Context Graph
-------------
Models relationships between users, devices, rooms, and routines.
Uses a NetworkX graph to allow flexible querying of context.
"""

import json
import time
import math
import networkx as nx
from pathlib import Path
from typing import List, Dict, Any, Optional

from config.settings import get_config

CONFIG = get_config("cognitive")
CONTEXT_CONFIG = CONFIG.get("context_graph", {})
STORAGE_PATH = Path(CONTEXT_CONFIG.get("storage_path", "data/cognitive/context_graph.json"))


class ContextGraph:
    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self.storage_path = STORAGE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_graph()

    def _load_graph(self):
        """Load graph from JSON storage"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    self.graph = nx.node_link_graph(data)
                print(f"[ContextGraph] Loaded graph with {self.graph.number_of_nodes()} nodes.")
            except Exception as e:
                print(f"[ContextGraph] Error loading graph: {e}. Starting fresh.")
                self.graph = nx.MultiDiGraph()
        else:
            self._init_default_graph()

    def _init_default_graph(self):
        """Initialize with some basic structure if empty"""
        self.graph.add_node("home", type="location")
        self._save_graph()

    def add_node(self, node_id: str, node_type: str, attributes: Dict[str, Any] = None):
        """Add or update a node"""
        attrs = attributes or {}
        attrs["type"] = node_type
        attrs["updated_at"] = time.time()
        self.graph.add_node(node_id, **attrs)
        self._save_graph()

    def add_edge(self, source: str, target: str, relation: str, ttl: int = None, attributes: Dict[str, Any] = None):
        """
        Add a relationship between nodes.
        ttl: Time-to-live in seconds (optional).
        """
        if not self.graph.has_node(source):
            self.graph.add_node(source, type="unknown")
        if not self.graph.has_node(target):
            self.graph.add_node(target, type="unknown")
            
        attrs = attributes or {}
        attrs["relation"] = relation
        attrs["updated_at"] = time.time()
        
        if ttl:
            attrs["expiration"] = time.time() + ttl
        
        # Remove existing edge of same relation type before adding (to avoid duplicates)
        existing_keys = [
            k for k, v in self.graph.get_edge_data(source, target, default={}).items()
            if v.get("relation") == relation
        ]
        for key in existing_keys:
            self.graph.remove_edge(source, target, key=key)
            
        self.graph.add_edge(source, target, **attrs)
        self._save_graph()

    def cleanup_expired_edges(self):
        """Remove edges that have expired"""
        current_time = time.time()
        edges_to_remove = []
        
        for u, v, key, data in self.graph.edges(data=True, keys=True):
            expiration = data.get("expiration")
            if expiration and current_time > expiration:
                edges_to_remove.append((u, v, key))
                
        if edges_to_remove:
            self.graph.remove_edges_from(edges_to_remove)
            print(f"[ContextGraph] Removed {len(edges_to_remove)} expired edges")
            self._save_graph()

    def get_context(self, subject_id: str, depth: int = 1) -> Dict[str, Any]:
        """
        Retrieve context around a node (neighbors up to 'depth').
        Returns a subgraph representation.
        """
        if subject_id not in self.graph:
            return {}

        # Get subgraph
        nodes = {subject_id}
        current_layer = {subject_id}
        
        for _ in range(depth):
            next_layer = set()
            for node in current_layer:
                neighbors = list(self.graph.neighbors(node)) + list(self.graph.predecessors(node))
                next_layer.update(neighbors)
            nodes.update(next_layer)
            current_layer = next_layer
            
        subgraph = self.graph.subgraph(nodes)
        return nx.node_link_data(subgraph)

    def get_nodes_by_type(self, node_type: str) -> List[Dict[str, Any]]:
        """Find all nodes of a specific type"""
        results = []
        for node, attrs in self.graph.nodes(data=True):
            if attrs.get("type") == node_type:
                item = attrs.copy()
                item["id"] = node
                results.append(item)
        return results

    def compute_hyperbolic_distance(self, u_coord: List[float], v_coord: List[float]) -> float:
        """
        Computes the Poincaré ball hyperbolic distance between two coordinates.
        This provides Ruflow's native understanding of hierarchical BMS topology.
        Formula: arcosh(1 + 2 * ||u - v||^2 / ((1 - ||u||^2)(1 - ||v||^2)))
        """
        def norm_sq(coord):
            return sum(x*x for x in coord)
            
        def dist_sq(c1, c2):
            return sum((x-y)**2 for x, y in zip(c1, c2))
            
        n_u = norm_sq(u_coord)
        n_v = norm_sq(v_coord)
        d_sq = dist_sq(u_coord, v_coord)
        
        # Prevent division by zero or log of negative
        if n_u >= 1.0 or n_v >= 1.0:
            return float('inf')
            
        delta = 2 * d_sq / ((1 - n_u) * (1 - n_v))
        return math.acosh(1 + delta)

    def calculate_topology_distance(self, node_a: str, node_b: str) -> float:
        """
        Calculates the topological distance between two nodes in the BMS hierarchy
        using simulated Hyperbolic Embeddings.
        """
        if not self.graph.has_node(node_a) or not self.graph.has_node(node_b):
            return float('inf')
            
        # For Phase 1, we approximate hyperbolic tree distance via shortest path
        # weighted by hierarchy depth (Root -> Building -> Floor -> Zone -> Equip -> Sensor)
        try:
            return nx.shortest_path_length(self.graph, node_a, node_b)
        except nx.NetworkXNoPath:
            return float('inf')

    def _save_graph(self):
        """Persist graph to disk"""
        data = nx.node_link_data(self.graph)
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def clear(self):
        """Reset graph"""
        self.graph = nx.MultiDiGraph()
        self._init_default_graph()
