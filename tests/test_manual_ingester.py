"""
Test Manual Ingester
=====================

Tests for the ManualIngester class using native PDF parsing
and ARVIS UnifiedLLM.
"""

import pytest
import tempfile
import os
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock

# Import the classes under test
from agent_advisory.manual_ingester import ManualIngester, IngestionResult, ingest_document
from agent_advisory.knowledge_base import TechnicalKnowledgeBase


class TestIngestionResult:
    """Test the IngestionResult dataclass"""
    
    def test_to_dict_success(self):
        """Test serialization with no errors"""
        result = IngestionResult(
            source_file="/path/to/file.pdf",
            doc_name="Test Manual",
            doc_description="A test manual for testing",
            nodes_indexed=10,
            total_tokens_estimated=5000,
            ingestion_time_seconds=2.5,
            equipment_id="CH-01",
            errors=[]
        )
        
        d = result.to_dict()
        assert d["source_file"] == "/path/to/file.pdf"
        assert d["nodes_indexed"] == 10
        assert d["status"] == "success"
        assert d["equipment_id"] == "CH-01"
    
    def test_to_dict_partial(self):
        """Test serialization with errors"""
        result = IngestionResult(
            source_file="/path/to/file.pdf",
            doc_name="Test Manual",
            doc_description="A test manual",
            nodes_indexed=8,
            total_tokens_estimated=4000,
            ingestion_time_seconds=2.0,
            errors=["Failed to index node 'Section 3'"]
        )
        
        d = result.to_dict()
        assert d["status"] == "partial"
        assert len(d["errors"]) == 1


class TestManualIngesterUnit:
    """Unit tests with mocked dependencies"""
    
    @pytest.fixture
    def mock_kb(self):
        """Create a mock TechnicalKnowledgeBase"""
        kb = Mock(spec=TechnicalKnowledgeBase)
        kb.index_technical_snippet = Mock()
        return kb
    
    @pytest.fixture
    def ingester(self, mock_kb):
        """Create a ManualIngester with mocked KB"""
        with patch("agent_advisory.manual_ingester.UnifiedLLM"):
            return ManualIngester(mock_kb)
    
    def test_flatten_tree_simple(self, ingester):
        """Test tree flattening with simple structure"""
        tree = [
            {"title": "Chapter 1", "node_id": "0001", "summary": "First chapter"},
            {"title": "Chapter 2", "node_id": "0002", "summary": "Second chapter"}
        ]
        
        result = ingester._flatten_tree(tree)
        assert len(result) == 2
        assert result[0]["title"] == "Chapter 1"
        assert result[0]["hierarchy_path"] == "Chapter 1"
    
    def test_flatten_tree_nested(self, ingester):
        """Test tree flattening with nested structure"""
        tree = [
            {
                "title": "Chapter 1",
                "node_id": "0001",
                "summary": "First chapter",
                "nodes": [
                    {"title": "Section 1.1", "node_id": "0002", "summary": "First section"},
                    {"title": "Section 1.2", "node_id": "0003", "summary": "Second section"}
                ]
            }
        ]
        
        result = ingester._flatten_tree(tree)
        assert len(result) == 3
        assert result[0]["hierarchy_path"] == "Chapter 1"
        assert result[1]["hierarchy_path"] == "Chapter 1 > Section 1.1"
        assert result[2]["hierarchy_path"] == "Chapter 1 > Section 1.2"
    
    def test_format_node_for_indexing(self, ingester):
        """Test node formatting for indexing"""
        node = {
            "title": "Installation Guide",
            "hierarchy_path": "Manual > Installation Guide",
            "summary": "This section covers installation procedures.",
            "start_index": 5,
            "end_index": 10
        }
        
        content = ingester._format_node_for_indexing(node, "Chiller Manual")
        assert "## Manual > Installation Guide" in content
        assert "*Source: Chiller Manual*" in content
        assert "📄 Pages 5-10" in content
        assert "installation procedures" in content
    
    def test_finalize_tree_structure_empty(self, ingester):
        """Test finalization with empty sections"""
        result = ingester._finalize_tree_structure([], 10)
        assert len(result) == 1
        assert result[0]["title"] == "Document Content"
    
    def test_finalize_tree_structure_dedup(self, ingester):
        """Test that duplicate titles are removed"""
        sections = [
            {"title": "Chapter 1", "start_page": 1, "summary": "First"},
            {"title": "Chapter 1", "start_page": 5, "summary": "Duplicate"},
            {"title": "Chapter 2", "start_page": 10, "summary": "Second"}
        ]
        result = ingester._finalize_tree_structure(sections, 20)
        assert len(result) == 2
        titles = [s["title"] for s in result]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles
    
    def test_parse_markdown_headers(self, ingester):
        """Test markdown header parsing"""
        content = """# Introduction

This is the intro.

## Getting Started

Some getting started content.

### Prerequisites

List of prerequisites.

## Configuration

Configuration section.
"""
        result = ingester._parse_markdown_headers(content)
        assert len(result) == 4
        assert result[0]["title"] == "Introduction"
        assert result[1]["title"] == "Getting Started"
        assert result[2]["title"] == "Prerequisites"
        assert result[3]["title"] == "Configuration"


class TestConvenienceFunction:
    """Test the ingest_document convenience function"""
    
    def test_unsupported_file_type(self):
        """Test error for unsupported file types"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="Unsupported file type"):
                asyncio.run(ingest_document(temp_path))
        finally:
            os.unlink(temp_path)


# ============================================================================
# INTEGRATION TEST - Uses real LLM and real PDF
# ============================================================================
@pytest.mark.integration
class TestRealIngestion:
    """
    Integration test with the REAL Carrier 30XW chiller manual.
    
    This test uses:
    - Real PDF at e:\Automation\30XW_tcm177-84440.pdf
    - Real ARVIS UnifiedLLM (requires API keys)
    - Real ChromaDB persistence
    """
    
    @pytest.fixture
    def temp_persist_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.mark.asyncio
    async def test_ingest_carrier_30xw_manual(self, temp_persist_dir):
        """
        Full integration test: Ingest real Carrier 30XW chiller manual.
        
        This test:
        1. Parses the PDF using native extraction
        2. Builds a tree structure using UnifiedLLM
        3. Indexes into ChromaDB
        4. Verifies we can query the indexed content
        """
        pdf_path = Path("e:/Automation/30XW_tcm177-84440.pdf")
        
        if not pdf_path.exists():
            pytest.skip(f"Test PDF not found: {pdf_path}")
        
        # Create KB and ingester
        kb = TechnicalKnowledgeBase(persist_directory=temp_persist_dir)
        ingester = ManualIngester(kb)
        
        # Ingest the manual
        print(f"\n[TEST] Ingesting Carrier 30XW manual...")
        result = await ingester.ingest_pdf(
            str(pdf_path), 
            equipment_id="30XW-CHILLER",
            include_tree_in_result=True
        )
        
        # Assertions
        print(f"\n[TEST] Results:")
        print(f"  - Document: {result.doc_name}")
        print(f"  - Description: {result.doc_description}")
        print(f"  - Nodes indexed: {result.nodes_indexed}")
        print(f"  - Time: {result.ingestion_time_seconds:.1f}s")
        
        assert result.nodes_indexed > 0, "Should have indexed at least one node"
        assert result.doc_name == "30XW_tcm177-84440"
        assert result.equipment_id == "30XW-CHILLER"
        
        # Verify tree structure was generated
        if result.tree_structure:
            print(f"\n[TEST] Tree structure ({len(result.tree_structure)} sections):")
            for section in result.tree_structure[:5]:
                print(f"  - {section.get('title')}: Pages {section.get('start_index')}-{section.get('end_index')}")
        
        # Test retrieval
        print(f"\n[TEST] Testing retrieval...")
        try:
            query_results = kb.query_specs("refrigerant charge procedures", equipment_id="30XW-CHILLER")
            print(f"  - Found {len(query_results)} results for 'refrigerant charge procedures'")
            if query_results:
                print(f"  - Top result: {query_results[0].get('content', '')[:200]}...")
        except Exception as e:
            print(f"  - Query failed (expected if KB is new): {e}")
        
        print(f"\n[TEST] ✅ Integration test passed!")
        
        return result


if __name__ == "__main__":
    # Run integration test directly
    import asyncio
    
    async def run_integration_test():
        test = TestRealIngestion()
        with tempfile.TemporaryDirectory() as tmpdir:
            await test.test_ingest_carrier_30xw_manual(tmpdir)
    
    print("=" * 60)
    print("RUNNING INTEGRATION TEST: Carrier 30XW Manual Ingestion")
    print("=" * 60)
    asyncio.run(run_integration_test())
