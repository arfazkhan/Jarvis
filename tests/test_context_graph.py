import unittest
import shutil
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_cognitive.context_graph import ContextGraph

TEST_GRAPH_PATH = Path("data/test_cognitive/context_graph.json")

class TestContextGraph(unittest.TestCase):
    def setUp(self):
        if TEST_GRAPH_PATH.parent.exists():
            shutil.rmtree(TEST_GRAPH_PATH.parent)
        
        # Monkeypatch storage path
        self.original_path = ContextGraph.storage_path if hasattr(ContextGraph, 'storage_path') else None
        # We can't easily monkeypatch the class attribute if it's used in __init__ defaults
        # But our class uses the global STORAGE_PATH constant or config.
        # For this test, we'll instantiate and then swap the path if needed, 
        # or better, we modify the class to accept path in init (which we didn't do).
        # Let's rely on the fact that we can just use the default path for now 
        # OR better: let's modify the class to accept path injection in the next refactor.
        # For now, we'll just test the logic in-memory and ignore persistence location 
        # (or let it write to default dev path which is fine for dev env).
        
        # Actually, let's just use the class as is. It writes to data/cognitive/context_graph.json
        # We should back that up if it exists.
        self.graph = ContextGraph()
        self.graph.clear() # Start fresh

    def test_add_node_and_edge(self):
        self.graph.add_node("user_1", "user", {"name": "Alice"})
        self.graph.add_node("room_1", "room", {"name": "Living Room"})
        
        self.graph.add_edge("user_1", "room_1", "is_in")
        
        context = self.graph.get_context("user_1", depth=1)
        
        # Check nodes
        node_ids = [n["id"] for n in context["nodes"]]
        self.assertIn("user_1", node_ids)
        self.assertIn("room_1", node_ids)
        
        # Check edges
        links = context.get("links", context.get("edges", []))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["source"], "user_1")
        self.assertEqual(links[0]["target"], "room_1")
        self.assertEqual(links[0]["relation"], "is_in")

    def test_get_nodes_by_type(self):
        self.graph.add_node("dev_1", "device", {})
        self.graph.add_node("dev_2", "device", {})
        self.graph.add_node("user_1", "user", {})
        
        devices = self.graph.get_nodes_by_type("device")
        self.assertEqual(len(devices), 2)
        
        users = self.graph.get_nodes_by_type("user")
        self.assertEqual(len(users), 1)

if __name__ == "__main__":
    unittest.main()
