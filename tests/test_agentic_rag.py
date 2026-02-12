"""
Test: Agentic RAG vs Traditional RAG
=====================================

Demonstrates the difference between:
- Traditional: one-shot retrieve → generate
- Agentic: LLM-controlled iterative retrieval with tool calling

Uses the same 30XW chiller manual for fair comparison.
"""

import asyncio
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_advisory.manual_ingester import ManualIngester, IngestionResult
from agent_advisory.knowledge_base import TechnicalKnowledgeBase
from agent_advisory.agentic_rag import AgenticRAG
from agent_unified.llm import UnifiedLLM


# Test queries
TEST_QUERIES = [
    "What is the cooling capacity and COP for the 30XW chiller models?",
    "What type of compressors are used in the 30XW and what are their features?",
    "What are the evaporator and condenser water flow rates for the 30XW?",
]


async def main():
    print("=" * 70)
    print("AGENTIC RAG TEST")
    print("=" * 70)
    
    # Initialize LLM
    llm = UnifiedLLM()
    
    # Initialize & ingest
    kb = TechnicalKnowledgeBase(persist_directory="data/test_agentic_kb")
    
    manual_path = Path("30XW_tcm177-84440.pdf")
    if not manual_path.exists():
        print(f"❌ Manual not found: {manual_path}")
        return
    
    print("\n📄 Ingesting 30XW manual...")
    ingester = ManualIngester(knowledge_base=kb)
    result: IngestionResult = await ingester.ingest_pdf(
        str(manual_path),
        equipment_id="30XW-CHILLER"
    )
    print(f"✅ Ingested: {result.nodes_indexed} nodes in {result.ingestion_time_seconds:.1f}s")
    
    # Test agentic RAG
    print("\n" + "=" * 70)
    print("AGENTIC RAG RESPONSES")
    print("=" * 70)
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n{'─' * 60}")
        print(f"🔍 Query {i}: {query}")
        print(f"{'─' * 60}")
        
        start = time.time()
        
        try:
            agent = AgenticRAG(knowledge_base=kb, llm=llm)
            result = await agent.query(query)
            elapsed = time.time() - start
            
            print(f"\n   📊 Summary: {result['iterations']} iterations | {result['confidence']} confidence | {elapsed:.1f}s")
            print(f"   📚 Sources: {result['sources']}")
            print(f"\n   💬 ANSWER: {result['answer'][:500]}")
            
        except Exception as e:
            elapsed = time.time() - start
            print(f"\n   ❌ Error ({elapsed:.1f}s): {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
