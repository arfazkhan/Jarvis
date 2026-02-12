"""
Equipment Topology Graph
========================

Provides equipment topology awareness for graph pre-filtering and validation.
Uses NetworkX for efficient graph operations.

Key capabilities:
1. Build graph from BMS equipment relationships
2. Get equipment neighborhood (upstream/downstream)
3. Validate action paths across equipment
"""

import logging
from typing import Dict, Any, List, Set, Optional
from dataclasses import dataclass

logger = logging.getLogger("arvis.advisory.equipment_graph")

# Lazy import NetworkX
_nx = None

def _ensure_networkx():
    """Lazy import NetworkX"""
    global _nx
    if _nx is None:
        try:
            import networkx as nx
            _nx = nx
        except ImportError:
            logger.warning("NetworkX not installed. Run: pip install networkx")
    return _nx


@dataclass
class EquipmentNode:
    """Equipment node in the topology graph"""
    equipment_id: str
    equipment_type: str
    name: str
    location: str = ""
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class EquipmentGraph:
    """
    BMS equipment topology graph for pre-filtering and validation.
    
    Equipment relationships:
    - Chiller → AHU (supplies cooling)
    - AHU → VAV (supplies air)
    - Boiler → AHU (supplies heating)
    - Pump → Chiller/AHU (circulates water)
    
    Example graph:
    ```
    CHILLER-01 ──supplies──> AHU-01 ──supplies──> VAV-01
                                    ──supplies──> VAV-02
                ──supplies──> AHU-02 ──supplies──> VAV-03
    ```
    """
    
    def __init__(self):
        nx = _ensure_networkx()
        if nx:
            self.graph = nx.DiGraph()
        else:
            self.graph = None
            self._fallback_edges = {}  # Simple dict fallback
        self._equipment_cache: Dict[str, EquipmentNode] = {}
        logger.info("EquipmentGraph initialized")
    
    def add_equipment(
        self,
        equipment_id: str,
        equipment_type: str,
        name: str,
        location: str = "",
        parent_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """Add equipment node to the graph"""
        node = EquipmentNode(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            name=name,
            location=location,
            parent_id=parent_id,
            metadata=metadata or {}
        )
        self._equipment_cache[equipment_id] = node
        
        if self.graph is not None:
            self.graph.add_node(
                equipment_id,
                type=equipment_type,
                name=name,
                location=location
            )
            
            # Add edge from parent if specified
            if parent_id and parent_id in self._equipment_cache:
                self.graph.add_edge(
                    parent_id, 
                    equipment_id,
                    relationship="supplies"
                )
        else:
            # Fallback without NetworkX
            if parent_id:
                if parent_id not in self._fallback_edges:
                    self._fallback_edges[parent_id] = []
                self._fallback_edges[parent_id].append(equipment_id)
    
    def add_relationship(
        self,
        from_id: str,
        to_id: str,
        relationship: str = "supplies"
    ) -> None:
        """Add a relationship edge between equipment"""
        if self.graph is not None:
            self.graph.add_edge(from_id, to_id, relationship=relationship)
        else:
            if from_id not in self._fallback_edges:
                self._fallback_edges[from_id] = []
            self._fallback_edges[from_id].append(to_id)
    
    def build_from_equipment_list(self, equipment_list: List[Dict[str, Any]]) -> None:
        """
        Build graph from BMS equipment list.
        
        Each equipment dict should have:
        - equipment_id
        - equipment_type
        - name
        - location (optional)
        - parent_equipment_id (optional)
        """
        # First pass: add all nodes
        for eq in equipment_list:
            self.add_equipment(
                equipment_id=eq.get("equipment_id"),
                equipment_type=eq.get("equipment_type", "unknown"),
                name=eq.get("name", ""),
                location=eq.get("location", ""),
                parent_id=eq.get("parent_equipment_id"),
                metadata=eq.get("metadata", {})
            )
        
        # Second pass: add edges for parent relationships
        for eq in equipment_list:
            parent_id = eq.get("parent_equipment_id")
            if parent_id and parent_id in self._equipment_cache:
                self.add_relationship(
                    from_id=parent_id,
                    to_id=eq["equipment_id"],
                    relationship="supplies"
                )
        
        logger.info(f"Built equipment graph with {len(self._equipment_cache)} nodes")
    
    def get_neighborhood(self, equipment_id: str, depth: int = 2) -> Set[str]:
        """
        Get equipment IDs within N hops (upstream + downstream).
        
        Args:
            equipment_id: Starting equipment
            depth: Number of hops in each direction
            
        Returns:
            Set of equipment IDs in the neighborhood
        """
        if equipment_id not in self._equipment_cache:
            return {equipment_id}
        
        neighborhood = {equipment_id}
        
        if self.graph is not None:
            nx = _ensure_networkx()
            
            # Get descendants (downstream)
            try:
                descendants = nx.descendants_at_distance(self.graph, equipment_id, 1)
                for d in range(2, depth + 1):
                    descendants |= nx.descendants_at_distance(self.graph, equipment_id, d)
                neighborhood |= descendants
            except nx.NetworkXError:
                pass
            
            # Get ancestors (upstream)
            try:
                ancestors = nx.ancestors(self.graph, equipment_id)
                neighborhood |= ancestors
            except nx.NetworkXError:
                pass
        else:
            # Fallback: simple traversal
            neighborhood |= self._get_downstream_fallback(equipment_id, depth)
            neighborhood |= self._get_upstream_fallback(equipment_id)
        
        return neighborhood
    
    def get_upstream(self, equipment_id: str) -> List[str]:
        """
        Get parent equipment chain (e.g., VAV → AHU → Chiller).
        
        Returns list ordered from immediate parent to root.
        """
        if equipment_id not in self._equipment_cache:
            return []
        
        upstream = []
        
        if self.graph is not None:
            nx = _ensure_networkx()
            try:
                # Get all predecessors
                predecessors = list(nx.ancestors(self.graph, equipment_id))
                
                # Sort by distance from equipment_id
                for pred in predecessors:
                    try:
                        path = nx.shortest_path(self.graph, pred, equipment_id)
                        upstream.append((pred, len(path)))
                    except nx.NetworkXNoPath:
                        pass
                
                # Sort by distance (closest first)
                upstream.sort(key=lambda x: x[1])
                return [u[0] for u in upstream]
            except nx.NetworkXError:
                return []
        else:
            return list(self._get_upstream_fallback(equipment_id))
    
    def get_downstream(self, equipment_id: str) -> List[str]:
        """
        Get child equipment (e.g., Chiller → [AHU-01, AHU-02]).
        
        Returns list of immediate children.
        """
        if equipment_id not in self._equipment_cache:
            return []
        
        if self.graph is not None:
            return list(self.graph.successors(equipment_id))
        else:
            return self._fallback_edges.get(equipment_id, [])
    
    def validate_path(self, from_id: str, to_id: str) -> bool:
        """
        Check if path between equipment is valid (connected).
        
        Returns True if there's a path in either direction.
        """
        if self.graph is not None:
            nx = _ensure_networkx()
            try:
                return nx.has_path(self.graph, from_id, to_id) or \
                       nx.has_path(self.graph, to_id, from_id)
            except nx.NetworkXError:
                return False
        else:
            # Fallback: check if they're in each other's neighborhood
            neighborhood = self.get_neighborhood(from_id, depth=5)
            return to_id in neighborhood
    
    def get_equipment_type(self, equipment_id: str) -> str:
        """Get equipment type for an ID"""
        node = self._equipment_cache.get(equipment_id)
        return node.equipment_type if node else "unknown"
    
    def get_subgraph_for_context(self, equipment_id: str, depth: int = 2) -> Dict[str, Any]:
        """
        Get subgraph data for LLM prompt context.
        
        Returns structured dictionary describing the equipment neighborhood.
        """
        neighborhood = self.get_neighborhood(equipment_id, depth)
        upstream = self.get_upstream(equipment_id)
        downstream = self.get_downstream(equipment_id)
        
        nodes = []
        for eq_id in neighborhood:
            node = self._equipment_cache.get(eq_id)
            if node:
                nodes.append({
                    "id": eq_id,
                    "type": node.equipment_type,
                    "name": node.name,
                    "location": node.location
                })
        
        return {
            "focus_equipment": equipment_id,
            "focus_type": self.get_equipment_type(equipment_id),
            "upstream_chain": upstream,
            "downstream_children": downstream,
            "neighborhood": list(neighborhood),
            "nodes": nodes
        }
    
    def _get_downstream_fallback(self, equipment_id: str, depth: int) -> Set[str]:
        """Fallback downstream traversal without NetworkX"""
        result = set()
        current = [equipment_id]
        for _ in range(depth):
            next_level = []
            for eq_id in current:
                children = self._fallback_edges.get(eq_id, [])
                next_level.extend(children)
                result.update(children)
            current = next_level
        return result
    
    def _get_upstream_fallback(self, equipment_id: str) -> Set[str]:
        """Fallback upstream traversal without NetworkX"""
        result = set()
        for parent_id, children in self._fallback_edges.items():
            if equipment_id in children:
                result.add(parent_id)
                result.update(self._get_upstream_fallback(parent_id))
        return result
    
    def __len__(self) -> int:
        return len(self._equipment_cache)
    
    def __contains__(self, equipment_id: str) -> bool:
        return equipment_id in self._equipment_cache


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def create_sample_graph() -> EquipmentGraph:
    """Create a sample equipment graph for testing"""
    graph = EquipmentGraph()
    
    # Add chillers
    graph.add_equipment("CHILLER-01", "chiller", "Chiller 1", "Mechanical Room")
    graph.add_equipment("CHILLER-02", "chiller", "Chiller 2", "Mechanical Room")
    
    # Add AHUs (children of chillers)
    graph.add_equipment("AHU-01", "ahu", "AHU 1", "Floor 1", parent_id="CHILLER-01")
    graph.add_equipment("AHU-02", "ahu", "AHU 2", "Floor 2", parent_id="CHILLER-01")
    graph.add_equipment("AHU-03", "ahu", "AHU 3", "Floor 3", parent_id="CHILLER-02")
    
    # Add relationships
    graph.add_relationship("CHILLER-01", "AHU-01", "supplies")
    graph.add_relationship("CHILLER-01", "AHU-02", "supplies")
    graph.add_relationship("CHILLER-02", "AHU-03", "supplies")
    
    # Add VAVs (children of AHUs)
    for i in range(1, 4):
        for j in range(1, 4):
            vav_id = f"VAV-{i:02d}-{j:02d}"
            ahu_id = f"AHU-{i:02d}"
            graph.add_equipment(vav_id, "vav", f"VAV {i}-{j}", f"Floor {i} Zone {j}", parent_id=ahu_id)
            graph.add_relationship(ahu_id, vav_id, "supplies")
    
    return graph
