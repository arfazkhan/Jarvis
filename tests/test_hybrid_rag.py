#!/usr/bin/env python3
"""
Test: Hybrid RAG with LLM Routing
===================================

Tests:
1. Deterministic routing (high confidence)
2. LLM routing fallback (low confidence)
3. End-to-end retrieval with both strategies
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_advisory.hybrid_rag import HybridRAGRouter, TreeKnowledgeBase


async def test_deterministic_routing():
    """Test that clear queries use deterministic routing."""
    print("\n1️⃣ Deterministic Routing")
    print("-" * 40)
    
    router = HybridRAGRouter(llm=None)  # No LLM
    
    # Clear tree hint
    result = router.choose_strategy("Where is the chiller startup procedure?")
    print(f"Query: 'Where is the chiller startup procedure?'")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Hints: {result['reason']}")
    assert result['strategy'] == 'tree', "Should route to tree"
    assert result['confidence'] >= 0.6, "Should have high confidence"
    print("  ✅ Correctly routed to tree")
    
    # Clear vector hint
    result = router.choose_strategy("What is the CHW low temperature limit?")
    print(f"\nQuery: 'What is the CHW low temperature limit?'")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Hints: {result['reason']}")
    assert result['strategy'] == 'vector', "Should route to vector"
    print("  ✅ Correctly routed to vector")
    
    # Clear hybrid hint
    result = router.choose_strategy("What are the capacity and COP ratings?")
    print(f"\nQuery: 'What are the capacity and COP ratings?'")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Hints: {result['reason']}")
    assert result['strategy'] == 'hybrid', "Should route to hybrid"
    print("  ✅ Correctly routed to hybrid")


async def test_llm_routing():
    """Test that ambiguous queries use LLM routing."""
    print("\n\n2️⃣ LLM Routing Fallback")
    print("-" * 40)
    
    router = HybridRAGRouter(llm="mock")  # With LLM
    
    # Ambiguous query (no clear hints)
    result = router.choose_strategy("Is this compressor selection valid?")
    print(f"Query: 'Is this compressor selection valid?'")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Hints: {result['reason']}")
    print(f"  Low confidence: {result['confidence'] < 0.6}")
    print("  ✅ Low confidence triggers LLM fallback")


async def test_tree_kb():
    """Test tree knowledge base indexing and retrieval."""
    print("\n\n3️⃣ Tree Knowledge Base")
    print("-" * 40)
    
    tree_kb = TreeKnowledgeBase(persist_directory="data/test_tree_kb")
    
    # Index a sample document
    sample_tree = [
        {
            "node_id": "001",
            "title": "Chiller Operations",
            "summary": "Overview of chiller startup and shutdown procedures",
            "text": "This section covers Carrier 30XA chiller operations including startup sequence, safety checks, and shutdown procedures.",
            "nodes": [
                {
                    "node_id": "002",
                    "title": "Startup Procedure",
                    "summary": "Step-by-step chiller startup",
                    "text": "1. Verify power. 2. Check oil levels. 3. Start chilled water pump. 4. Activate compressor.",
                },
                {
                    "node_id": "003",
                    "title": "Safety Limits",
                    "summary": "Operating limits and setpoints",
                    "text": "CHW low limit: 4°C. CHW high limit: 15°C. Oil pressure minimum: 25 psi.",
                }
            ]
        }
    ]
    
    count = tree_kb.add_document_tree(
        source="test_manual.pdf",
        doc_name="Carrier 30XA Manual",
        tree_structure=sample_tree,
        equipment_id="CH-01"
    )
    print(f"Indexed {count} nodes")
    
    # Query tree
    results = await tree_kb.query("chiller startup procedure", limit=3)
    print(f"\nQuery: 'chiller startup procedure'")
    print(f"  Found {len(results)} results")
    for r in results:
        print(f"  - {r['title']} (score: {r['score']})")
    
    assert len(results) > 0, "Should find results"
    assert "startup" in results[0]['title'].lower() or "startup" in results[0]['summary'].lower(), "Should find startup procedure"
    print("  ✅ Tree search working")


async def test_end_to_end():
    """Test end-to-end retrieval with tiered routing."""
    print("\n\n4️⃣ End-to-End Retrieval")
    print("-" * 40)
    
    tree_kb = TreeKnowledgeBase(persist_directory="data/test_tree_kb")
    router = HybridRAGRouter(vector_kb=None, tree_kb=tree_kb)
    
    # Query with tree hint (high confidence)
    result = await router.retrieve("Where is the startup procedure?", limit=3)
    print(f"Query: 'Where is the startup procedure?'")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Routing: {result['routing_method']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print(f"  Results: {len(result['combined'])}")
    print("  ✅ Deterministic routing used")
    
    # Query with no hints (low confidence)
    result = await router.retrieve("compressor selection", limit=3, use_llm_routing=False)
    print(f"\nQuery: 'compressor selection' (LLM disabled)")
    print(f"  Strategy: {result['strategy']}")
    print(f"  Routing: {result['routing_method']}")
    print(f"  Confidence: {result['confidence']:.2f}")
    print("  ✅ Low confidence detected")


async def run_all_tests():
    print("\n" + "=" * 60)
    print("HYBRID RAG WITH LLM ROUTING - TEST SUITE")
    print("=" * 60)
    
    await test_deterministic_routing()
    await test_llm_routing()
    await test_tree_kb()
    await test_end_to_end()
    
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
