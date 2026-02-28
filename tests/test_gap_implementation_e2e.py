"""
End-to-End Verification for ARVIS Strategic Gaps
================================================

Tests:
1. BMSGraph topology integration (Gap 1)
2. Trust Boundaries in System Prompt (Gap 3)
3. Causal Inference using Graph (Gap 1 & 2 foundations)
"""

import unittest
import logging
from datetime import datetime, timedelta
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_commercial.graph import BMSGraph
from agent_commercial.ml.causal_inference import CausalInferenceEngine
from agent_commercial.prompt_builder import get_ops_system_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_e2e")

class TestGapImplementation(unittest.TestCase):
    
    def test_01_graph_topology(self):
        """Verify BMSGraph correctly models the equipment hierarchy."""
        logger.info("TEST 1: Verifying BMSGraph Topology...")
        graph = BMSGraph()
        
        # Check Chiller -> AHU connection
        downstream = graph.get_downstream("chiller")
        self.assertIn("ahu", downstream, "Chiller should feed AHU (type-level)")
        
        # Check AHU -> VAV connection
        downstream_ahu = graph.get_downstream("ahu")
        self.assertIn("vav", downstream_ahu, "AHU should feed VAV")
        
        # Check Upstream
        upstream_vav = graph.get_upstream("vav")
        self.assertIn("ahu", upstream_vav, "VAV parent should be AHU")
        
        logger.info("✅ Graph Topology Verified")

    def test_02_trust_boundaries(self):
        """Verify System Prompt contains the new Constitution/Trust Boundaries."""
        logger.info("TEST 2: Verifying Trust Boundaries in Prompt...")
        prompt = get_ops_system_prompt()
        
        # Gap 3: Explicit Refusals
        self.assertIn("Trust & Safety Boundaries", prompt)
        self.assertIn("**NEVER** write to BACnet points directly", prompt)
        self.assertIn("Safety (Fire/Life) > Comfort > Efficiency > Cost", prompt)
        
        logger.info("✅ Constitution Layer Verified in System Prompt")

    def test_03_causal_inference_via_graph(self):
        """Verify CausalInferenceEngine uses BMSGraph to solve a cascade."""
        logger.info("TEST 3: Verifying Causal Inference with Graph...")
        engine = CausalInferenceEngine()
        
        # Verify it has the graph instance
        self.assertIsInstance(engine.graph, BMSGraph)
        
        # Scenario: Chiller Trip causing High Temp downstream
        now = datetime.now()
        alarms = [
            # Downstream effect (happened later)
            {
                "equipment_id": "AHU-01",
                "fault_type": "high_sat",
                "timestamp": now
            },
            # Upstream root cause (happened earlier)
            {
                "equipment_id": "CH-01",  # Chiller
                "fault_type": "trip",
                "timestamp": now - timedelta(minutes=10)
            }
        ]
        
        # Run inference
        chain = engine.infer_cause(alarms)
        
        logger.info(f"Inferred Root Cause: {chain.root_cause.equipment_id}")
        logger.info(f"Explanation: {chain.explanation}")
        
        # Assertions
        # 1. Root cause should be Chiller (CH-01)
        self.assertEqual(chain.root_cause.equipment_id, "CH-01")
        
        # 2. Confidence should be high due to Topology (Method 2 in inference)
        # Note: Previous hardcoded dict logic is replaced by graph.get_downstream
        self.assertTrue(chain.confidence > 0.5, "Confidence should be high due to topological link")
        
        logger.info("✅ Causal Inference correctly used Graph Topology")

if __name__ == "__main__":
    unittest.main()
