"""
Integration Test: RAG Retrieval (Hybrid)
========================================

Tests HybridRAG + KnowledgeBase integration.
"""

import pytest

from agent_advisory.hybrid_rag import HybridRAGRouter, TreeKnowledgeBase
from agent_advisory.knowledge_base import TechnicalKnowledgeBase

from tests.mocks import MockKnowledgeBase


class TestRAGRetrieval:
    """Test hybrid RAG retrieval."""
    
    @pytest.fixture
    def tree_kb(self):
        """Tree knowledge base."""
        return TreeKnowledgeBase(persist_directory="/tmp/test_tree_kb")
    
    @pytest.fixture
    def vector_kb(self):
        """Mock vector knowledge base."""
        return MockKnowledgeBase()
    
    @pytest.fixture
    def hybrid_rag(self, tree_kb, vector_kb):
        """Hybrid RAG router."""
        return HybridRAGRouter(
            vector_kb=vector_kb,
            tree_kb=tree_kb,
        )
    
    @pytest.mark.asyncio
    async def test_hybrid_retrieval_chooses_strategy(self, hybrid_rag):
        """Router should choose appropriate strategy."""
        result = await hybrid_rag.retrieve(
            query="What is the cooling capacity?",
            limit=5,
        )
        
        assert "strategy" in result
        assert result["strategy"] in ["tree", "vector", "hybrid"]
    
    @pytest.mark.asyncio
    async def test_tree_search_for_procedures(self, hybrid_rag, tree_kb):
        """Tree search should find procedures."""
        # Add document tree
        tree_kb.add_document_tree(
            source="test-manual.pdf",
            doc_name="Chiller Manual",
            tree_structure=[
                {
                    "title": "Startup Procedure",
                    "summary": "Steps to start the chiller",
                    "text": "1. Check oil level 2. Open valves 3. Start pump",
                }
            ],
        )
        
        result = await hybrid_rag.retrieve(
            query="How do I start the chiller?",
            limit=5,
        )
        
        assert result["strategy"] in ["tree", "hybrid"]
        assert len(result["tree_results"]) > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
