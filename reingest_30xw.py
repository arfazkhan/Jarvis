import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.manual_ingester import ManualIngester
from agent_advisory.knowledge_base import TechnicalKnowledgeBase

async def main():
    kb = TechnicalKnowledgeBase(persist_directory="data/test_agentic_kb")
    ingester = ManualIngester(kb)
    
    pdf_path = "30XW_tcm177-84440.pdf"
    if not Path(pdf_path).exists():
        print(f"Error: {pdf_path} not found.")
        return

    print(f"Ingesting {pdf_path}...")
    result = await ingester.ingest_pdf(pdf_path, equipment_id="30XW-CHILLER")
    print(f"Ingestion complete: {result.nodes_indexed} nodes.")

if __name__ == "__main__":
    asyncio.run(main())
