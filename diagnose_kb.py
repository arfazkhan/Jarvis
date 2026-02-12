import asyncio
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.knowledge_base import TechnicalKnowledgeBase

async def diagnose():
    # Use the KB from the test
    kb = TechnicalKnowledgeBase(persist_directory="data/test_agentic_kb")
    
    print("Searching for 'Performance Data'...")
    results = await kb.query_specs("Performance Data 30XW-P", limit=5)
    
    for i, r in enumerate(results):
        meta = r.get("metadata", {})
        content = r.get("content", "")
        print(f"\n--- Result {i+1} ---")
        print(f"Source: {meta.get('source')}, Page: {meta.get('equipment_id')} - {meta.get('manual_type')}")
        print(f"Content Length: {len(content)}")
        print(f"Metadata Keys: {list(meta.keys())}")
        
        t_json = meta.get("table_data_json")
        if t_json:
            try:
                tables = json.loads(t_json)
                print(f"Table Data Found: {len(tables)} tables")
                for j, t in enumerate(tables):
                    print(f"  Table {j+1}: {len(t.get('rows', []))} rows")
            except Exception as e:
                print(f"  Table Data Error: {e}")
        else:
            print("  Table Data Missing!")

if __name__ == "__main__":
    asyncio.run(diagnose())
