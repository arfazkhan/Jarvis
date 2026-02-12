
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.knowledge_base import TechnicalKnowledgeBase

def reset():
    print("Initializing Knowledge Base...")
    kb = TechnicalKnowledgeBase(persist_directory="data/test_agentic_kb")
    
    # Check all sources first
    all_data = kb.collection.get()
    sources = set()
    for m in all_data['metadatas']:
        if m and 'source' in m:
            sources.add(m['source'])
            
    print(f"Current sources in KB: {sources}")
    
    target_source = "30XW_tcm177-84440.pdf"
    targets_to_delete = [s for s in sources if target_source in s]
    
    if not targets_to_delete:
        print(f"No documents found for {target_source}")
        return

    print(f"Deleting documents for sources: {targets_to_delete}")
    for s in targets_to_delete:
        kb.collection.delete(where={"source": s})
        
    print("Deletion complete.")
    
    # Verify
    check = kb.collection.get(where={"source": targets_to_delete[0]})
    print(f"Remaining documents for {targets_to_delete[0]}: {len(check['ids'])}")

if __name__ == "__main__":
    reset()
