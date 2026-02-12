
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.manual_ingester import ManualIngester
from agent_unified.llm import UnifiedLLM

async def debug_ingestion():
    print("Initializing LLM...")
    import os
    os.environ["LLM_PROVIDER"] = "groq"
    
    # Mock KB to avoid DB writes
    class MockKB:
        def index_technical_snippet(self, content, **kwargs):
            # print(f"Indexing snippet len: {len(content)}")
            pass
            
    ingester = ManualIngester(knowledge_base=MockKB())
    
    pdf_path = r"e:\Automation\30XW_tcm177-84440.pdf"
    print(f"Ingesting {pdf_path}...")
    
    # We want to inspect the nodes BEFORE indexing, but ingest_manual does everything.
    # We can inspect the returned result? 
    # The result has node count but not content.
    # However, ingest_manual calls _format_node_for_indexing which we modified.
    
    # Let's subclass to intercept
    class DebugIngester(ManualIngester):
        def _format_node_for_indexing(self, node, doc_name):
            content = super()._format_node_for_indexing(node, doc_name)
            if "<table_data>" in content:
                print(f"\n[DEBUG] Found table data in node '{node.get('title')}'!")
                print(f"Content preview: {content[:100]}...")
            elif "Page 6" in content:
                print(f"\n[DEBUG] Page 6 node content (len {len(content)}):")
                print(content[:500])
                print("..." + content[-200:])
            return content

    ingester = DebugIngester(knowledge_base=MockKB())
    
    await ingester.ingest_pdf(pdf_path)

if __name__ == "__main__":
    asyncio.run(debug_ingestion())
