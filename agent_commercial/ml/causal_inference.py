"""
Causal Inference Engine
=======================

Bayesian Network-based causal inference for event correlation.

Uses:
- Structure learning from alarm history (PC algorithm)
- Belief propagation for inference
- Equipment topology as prior knowledge

Custom for BMS:
- Equipment hierarchy graph (Chiller → CHW → AHU → VAV)
- Temporal causality (A before B = A possibly causes B)
- Physical causality rules (upstream failures cascade downstream)

Usage:
    >>> engine = CausalInferenceEngine()
    >>> engine.learn_structure(alarm_history)
    >>> root_cause = engine.infer_cause([alarm1, alarm2, alarm3])
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np

logger = logging.getLogger("arvis.ml.causal")

# Try importing pgmpy
try:
    from pgmpy.models import BayesianNetwork
    from pgmpy.estimators import PC, BayesianEstimator
    from pgmpy.inference import VariableElimination
    from pgmpy.factors.discrete import TabularCPD
    PGMPY_AVAILABLE = True
except ImportError:
    PGMPY_AVAILABLE = False
    logger.warning("pgmpy not installed. Run: pip install pgmpy")


# =============================================================================
# Standard BMS equipment hierarchy
# MOVED TO agent_commercial/graph.py
# Using BMSGraph class for topology management

# Common fault cascade patterns
FAULT_CASCADES = {
    # Chiller trip → multiple effects
    ("chiller", "trip"): [
        ("chw_pump", "no_flow", 0.9),
        ("ahu", "high_sat", 0.8),
        ("vav", "zone_hot", 0.7),
    ],
    # Pump failure
    ("chw_pump", "fault"): [
        ("ahu", "high_sat", 0.85),
        ("vav", "zone_hot", 0.7),
    ],
    # AHU failure
    ("ahu", "fault"): [
        ("vav", "no_airflow", 0.9),
        ("vav", "zone_hot", 0.7),
    ],
    # Filter clog
    ("ahu", "high_filter_dp"): [
        ("ahu", "low_airflow", 0.8),
        ("vav", "zone_hot", 0.5),
    ],
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class CausalNode:
    """A node in the causal graph"""
    equipment_id: str
    equipment_type: str
    fault_type: str
    timestamp: datetime
    probability: float = 0.0
    is_root_cause: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "equipment_type": self.equipment_type,
            "fault_type": self.fault_type,
            "timestamp": self.timestamp.isoformat(),
            "probability": round(self.probability, 3),
            "is_root_cause": self.is_root_cause,
        }


@dataclass
class CausalChain:
    """A causal chain from root cause to effects"""
    root_cause: CausalNode
    effects: List[CausalNode]
    confidence: float
    explanation: str
    cascade_path: List[str]  # Equipment IDs in order
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause": self.root_cause.to_dict(),
            "effects": [e.to_dict() for e in self.effects],
            "confidence": round(self.confidence, 3),
            "explanation": self.explanation,
            "cascade_path": self.cascade_path,
        }


# =============================================================================
# CAUSAL INFERENCE ENGINE
# =============================================================================

class CausalInferenceEngine:
    """
    Bayesian Network-based causal inference for alarm correlation.
    
    Learns causal structure from alarm history and uses it to
    identify root causes when multiple alarms fire.
    """
    
    def __init__(self):
        # Bayesian Network model (type annotation is string to avoid NameError when pgmpy absent)
        self.bn_model: Optional["BayesianNetwork"] = None
        self.inference_engine = None
        
        # Equipment topology graph (Managed by BMSGraph)
        from agent_commercial.graph import BMSGraph
        self.graph = BMSGraph()
        
        # Learned edge weights (strength of causal relationships)
        self.edge_weights: Dict[Tuple[str, str], float] = {}
        
        # Alarm history for learning
        self.alarm_history: List[Dict[str, Any]] = []
        
        # self._init_topology() - No longer needed, graph initialized internally
        
        self.is_trained = False
        
        logger.info("CausalInferenceEngine initialized")

    # _init_topology removed as it is now handled by BMSGraph
    
    def add_alarm(self, alarm: Dict[str, Any]) -> None:
        """Add an alarm to history for structure learning."""
        self.alarm_history.append({
            "equipment_id": alarm.get("equipment_id", ""),
            "equipment_type": self._get_equipment_type(alarm.get("equipment_id", "")),
            "fault_type": alarm.get("fault_type", alarm.get("alarm_type", "")),
            "timestamp": alarm.get("timestamp", datetime.now()),
            "severity": alarm.get("severity", "medium"),
        })
    
    def _get_equipment_type(self, equipment_id: str) -> str:
        """Extract equipment type from ID (e.g., 'CH-01' → 'chiller')."""
        prefixes = {
            "CH": "chiller",
            "AHU": "ahu",
            "VAV": "vav",
            "FCU": "fcu",
            "CHW": "chw_pump",
            "CT": "cooling_tower",
            "BLR": "boiler",
            "HW": "hw_pump",
        }
        
        for prefix, eq_type in prefixes.items():
            if equipment_id.upper().startswith(prefix):
                return eq_type
        
        return "unknown"
    
    def learn_structure(self, 
                        alarm_history: Optional[List[Dict[str, Any]]] = None,
                        min_support: float = 0.05) -> Dict[str, Any]:
        """
        Learn causal structure from alarm history.
        
        Uses:
        1. Temporal precedence (earlier alarms may cause later ones)
        2. Equipment topology (upstream affects downstream)
        3. Co-occurrence patterns (frequent pairs)
        
        Args:
            alarm_history: List of alarm dictionaries
            min_support: Minimum co-occurrence frequency
            
        Returns:
            Learning metrics
        """
        if alarm_history:
            for alarm in alarm_history:
                self.add_alarm(alarm)
        
        if len(self.alarm_history) < 10:
            logger.warning("Insufficient alarm history for structure learning")
            return {"status": "failed", "error": "insufficient_data"}
        
        # ─────────────────────────────────────────────────────────────────
        # 1. Find temporal co-occurrences
        # ─────────────────────────────────────────────────────────────────
        co_occurrences = defaultdict(int)
        
        # Group alarms by time windows (5 minutes)
        sorted_alarms = sorted(self.alarm_history, key=lambda x: x["timestamp"])
        
        for i, alarm_a in enumerate(sorted_alarms):
            for j in range(i + 1, len(sorted_alarms)):
                alarm_b = sorted_alarms[j]
                
                time_diff = (alarm_b["timestamp"] - alarm_a["timestamp"]).total_seconds()
                
                if time_diff > 300:  # More than 5 minutes apart
                    break
                
                # A potentially causes B (temporal precedence)
                key = (alarm_a["equipment_type"], alarm_b["equipment_type"])
                co_occurrences[key] += 1
        
        # ─────────────────────────────────────────────────────────────────
        # 2. Filter by support and topology
        # ─────────────────────────────────────────────────────────────────
        n_windows = len(sorted_alarms)
        
        for (eq_a, eq_b), count in co_occurrences.items():
            support = count / n_windows
            
            if support >= min_support:
                # Check if topology supports this relationship
                # Use BMSGraph to check topological connection
                downstream = self.graph.get_downstream(eq_a)
                topology_weight = 1.0 if eq_b in downstream else 0.5
                
                self.edge_weights[(eq_a, eq_b)] = support * topology_weight
        
        # ─────────────────────────────────────────────────────────────────
        # 3. Build Bayesian Network (if pgmpy available)
        # ─────────────────────────────────────────────────────────────────
        if PGMPY_AVAILABLE and len(self.edge_weights) > 0:
            try:
                # Create edges from learned weights (threshold = 0.1)
                edges = [(a, b) for (a, b), w in self.edge_weights.items() if w > 0.1]
                
                if edges:
                    self.bn_model = BayesianNetwork(edges)
                    
                    # Add CPDs based on observed probabilities
                    self._estimate_cpds()
                    
                    self.inference_engine = VariableElimination(self.bn_model)
                    self.is_trained = True
                    
                    logger.info(f"Bayesian Network learned with {len(edges)} edges")
                    
            except Exception as e:
                logger.warning(f"BN learning failed: {e}")
        
        return {
            "status": "trained" if self.is_trained else "partial",
            "samples": len(self.alarm_history),
            "edges_learned": len(self.edge_weights),
            "strongest_edges": sorted(
                self.edge_weights.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:5],
        }
    
    def _estimate_cpds(self) -> None:
        """Estimate Conditional Probability Distributions."""
        if not PGMPY_AVAILABLE or self.bn_model is None:
            return
        
        # Simple binary CPDs (0 = no fault, 1 = fault)
        for node in self.bn_model.nodes():
            parents = list(self.bn_model.get_parents(node))
            
            if not parents:
                # Root node: use marginal probability
                p_fault = 0.1  # Default 10% fault rate
                cpd = TabularCPD(
                    variable=node,
                    variable_card=2,
                    values=[[1 - p_fault], [p_fault]],
                )
            else:
                # Child node: depends on parents
                n_parents = len(parents)
                n_combinations = 2 ** n_parents
                
                # Probability of fault increases with parent faults
                values = []
                for i in range(n_combinations):
                    parent_states = [(i >> j) & 1 for j in range(n_parents)]
                    n_parent_faults = sum(parent_states)
                    
                    # P(fault | parents) increases with parent faults
                    p_fault = 0.1 + 0.3 * n_parent_faults
                    values.append([1 - p_fault, p_fault])
                
                cpd = TabularCPD(
                    variable=node,
                    variable_card=2,
                    values=np.array(values).T.tolist(),
                    evidence=parents,
                    evidence_card=[2] * n_parents,
                )
            
            try:
                self.bn_model.add_cpds(cpd)
            except Exception:
                pass  # Skip if CPD already exists
    
    def infer_cause(self, 
                    observed_faults: List[Dict[str, Any]],
                    time_window_minutes: int = 30) -> CausalChain:
        """
        Infer the most likely root cause from observed faults.
        
        Args:
            observed_faults: List of fault dictionaries with equipment_id, fault_type, timestamp
            time_window_minutes: Time window for causality
            
        Returns:
            CausalChain with root cause and explanation
        """
        if not observed_faults:
            return self._empty_chain()
        
        # Convert to CausalNodes
        nodes = []
        for fault in observed_faults:
            eq_type = self._get_equipment_type(fault.get("equipment_id", ""))
            nodes.append(CausalNode(
                equipment_id=fault.get("equipment_id", ""),
                equipment_type=eq_type,
                fault_type=fault.get("fault_type", ""),
                timestamp=fault.get("timestamp", datetime.now()),
            ))
        
        # Sort by timestamp (earliest first)
        nodes.sort(key=lambda n: n.timestamp)
        
        # ─────────────────────────────────────────────────────────────────
        # Method 1: Temporal precedence (earliest is likely root cause)
        # ─────────────────────────────────────────────────────────────────
        earliest = nodes[0]
        earliest.probability = 0.5
        
        # ─────────────────────────────────────────────────────────────────
        # Method 2: Topology-based (upstream equipment is root cause)
        # ─────────────────────────────────────────────────────────────────
        upstream_candidate = None
        for node in nodes:
            # Is this equipment upstream of others?
            downstream_types = set(self.graph.get_downstream(node.equipment_type))
            observed_types = {n.equipment_type for n in nodes if n != node}
            
            if downstream_types & observed_types:
                # This node is upstream of some observed faults
                if upstream_candidate is None:
                    upstream_candidate = node
                    upstream_candidate.probability = 0.7
        
        # ─────────────────────────────────────────────────────────────────
        # Method 3: Bayesian inference (if trained)
        # ─────────────────────────────────────────────────────────────────
        bn_candidate = None
        if self.is_trained and self.inference_engine:
            try:
                # Set evidence (observed faults)
                evidence = {}
                for node in nodes:
                    if node.equipment_type in self.bn_model.nodes():
                        evidence[node.equipment_type] = 1  # Fault observed
                
                if evidence:
                    # Query for most likely root cause
                    all_types = set(n.equipment_type for n in nodes)
                    
                    for eq_type in self.bn_model.nodes():
                        if eq_type not in evidence:
                            # Query P(eq_type | evidence)
                            try:
                                result = self.inference_engine.query(
                                    variables=[eq_type],
                                    evidence=evidence,
                                )
                                p_fault = result.values[1]
                                
                                if p_fault > 0.6:
                                    # This might be the hidden root cause
                                    bn_candidate = next(
                                        (n for n in nodes if n.equipment_type == eq_type),
                                        None
                                    )
                                    if bn_candidate:
                                        bn_candidate.probability = float(p_fault)
                            except Exception:
                                pass
                                
            except Exception as e:
                logger.debug(f"BN inference failed: {e}")
        
        # ─────────────────────────────────────────────────────────────────
        # Combine methods and select root cause
        # ─────────────────────────────────────────────────────────────────
        candidates = [n for n in [earliest, upstream_candidate, bn_candidate] if n is not None]
        
        if not candidates:
            return self._empty_chain()
        
        # Select highest probability
        root_cause = max(candidates, key=lambda n: n.probability)
        root_cause.is_root_cause = True
        
        # Build cascade path
        effects = [n for n in nodes if n != root_cause]
        cascade_path = [root_cause.equipment_id] + [e.equipment_id for e in effects]
        
        # Generate explanation
        explanation = self._generate_explanation(root_cause, effects)
        
        return CausalChain(
            root_cause=root_cause,
            effects=effects,
            confidence=root_cause.probability,
            explanation=explanation,
            cascade_path=cascade_path,
        )
    
    def _empty_chain(self) -> CausalChain:
        """Return empty causal chain."""
        return CausalChain(
            root_cause=CausalNode("", "", "", datetime.now()),
            effects=[],
            confidence=0.0,
            explanation="No faults to analyze",
            cascade_path=[],
        )
    
    def _generate_explanation(self, 
                              root: CausalNode, 
                              effects: List[CausalNode]) -> str:
        """Generate human-readable explanation of causal chain."""
        if not root.equipment_id:
            return "Unable to determine root cause"
        
        explanation = f"{root.equipment_id} ({root.fault_type}) is the likely root cause"
        
        if effects:
            effect_ids = ", ".join(e.equipment_id for e in effects[:3])
            explanation += f", causing cascaded effects on {effect_ids}"
        
        # Check if this matches a known pattern
        key = (root.equipment_type, root.fault_type.lower())
        if key in FAULT_CASCADES:
            expected = FAULT_CASCADES[key]
            explanation += f". This matches known cascade pattern."
        
        return explanation
    
    def get_cascade_prediction(self, 
                               fault: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Predict what downstream effects might occur from this fault.
        
        Args:
            fault: Initial fault dictionary
            
        Returns:
            List of predicted downstream effects
        """
        eq_type = self._get_equipment_type(fault.get("equipment_id", ""))
        fault_type = fault.get("fault_type", "").lower()
        
        predictions = []
        
        # Check known cascades
        key = (eq_type, fault_type)
        if key in FAULT_CASCADES:
            for child_type, child_fault, prob in FAULT_CASCADES[key]:
                predictions.append({
                    "equipment_type": child_type,
                    "predicted_fault": child_fault,
                    "probability": prob,
                    "time_to_manifest_minutes": 5,
                })
        
        # Also check learned edges
        for (parent, child), weight in self.edge_weights.items():
            if parent == eq_type and weight > 0.3:
                predictions.append({
                    "equipment_type": child,
                    "predicted_fault": "cascaded_effect",
                    "probability": weight,
                    "time_to_manifest_minutes": 10,
                })
        
        return sorted(predictions, key=lambda x: x["probability"], reverse=True)


    # =========================================================================
    # MODEL PERSISTENCE (ModelRegistry Integration)
    # =========================================================================

    def save_model(self, metrics: Optional[Dict] = None) -> Optional[str]:
        """Save learned causal structure to ModelRegistry."""
        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state = {
            "edge_weights": {f"{k[0]}::{k[1]}": v for k, v in self.edge_weights.items()},
            "learned_edges_count": len(self.edge_weights),
        }
        save_metrics = metrics or {"edges": len(self.edge_weights)}

        version = registry.save_model("causal_inference", model_state, save_metrics)
        logger.info(f"Causal model saved: causal_inference/{version}")
        return version

    def load_model(self) -> bool:
        """Load learned causal structure from ModelRegistry."""
        from agent_commercial.ml.model_registry import get_model_registry
        registry = get_model_registry()

        model_state, metadata = registry.load_model("causal_inference")
        if model_state is None:
            return False

        raw_edges = model_state.get("edge_weights", {})
        self.edge_weights = {}
        for key_str, weight in raw_edges.items():
            parts = key_str.split("::")
            if len(parts) == 2:
                self.edge_weights[(parts[0], parts[1])] = weight

        logger.info(f"Causal model loaded: {len(self.edge_weights)} edges")
        return True

    async def retrain(self, alarm_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Retrain from alarm history for RetrainScheduler integration."""
        if not alarm_history:
            logger.warning("No alarm history provided for causal retrain")
            return {"status": "skipped", "reason": "no_data"}

        self.learn_structure(alarm_history)
        self.save_model({"edges": len(self.edge_weights), "samples": len(alarm_history)})
        return {"status": "success", "edges_learned": len(self.edge_weights)}


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_causal_instance: Optional[CausalInferenceEngine] = None


def get_causal_engine() -> "CausalInferenceEngine":
    """Get or create causal engine with model loading."""
    global _causal_instance
    if _causal_instance is None:
        _causal_instance = CausalInferenceEngine()
        _causal_instance.load_model()
    return _causal_instance


def analyze_cascade(
    alarm_ids: List[str],
    alarms: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Analyze alarm cascade to find root cause - LLM tool handler.
    """
    engine = get_causal_engine()
    chain = engine.infer_cause(alarms)

    return {
        "root_cause": chain.root_cause.to_dict(),
        "cascade_path": chain.cascade_path,
        "confidence": chain.confidence,
        "explanation": chain.explanation,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Causal Inference Engine Test")
    print("=" * 60)
    
    engine = CausalInferenceEngine()
    
    # Simulate a cascade scenario
    now = datetime.now()
    
    alarms = [
        {
            "equipment_id": "CH-01",
            "fault_type": "trip",
            "timestamp": now - timedelta(minutes=10),
        },
        {
            "equipment_id": "AHU-01",
            "fault_type": "high_sat",
            "timestamp": now - timedelta(minutes=7),
        },
        {
            "equipment_id": "AHU-02",
            "fault_type": "high_sat",
            "timestamp": now - timedelta(minutes=6),
        },
        {
            "equipment_id": "VAV-B3-01",
            "fault_type": "zone_hot",
            "timestamp": now - timedelta(minutes=3),
        },
    ]
    
    # Infer root cause
    chain = engine.infer_cause(alarms)
    
    print(f"\nRoot Cause: {chain.root_cause.equipment_id}")
    print(f"Confidence: {chain.confidence:.1%}")
    print(f"Explanation: {chain.explanation}")
    print(f"Cascade Path: {' → '.join(chain.cascade_path)}")
    
    # Predict future effects
    predictions = engine.get_cascade_prediction({
        "equipment_id": "CH-01",
        "fault_type": "trip",
    })
    
    print(f"\nPredicted downstream effects:")
    for pred in predictions:
        print(f"  - {pred['equipment_type']}: {pred['predicted_fault']} "
              f"(P={pred['probability']:.0%})")
