
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.knowledge_base import TechnicalKnowledgeBase

def reset_kb():
    kb = TechnicalKnowledgeBase()
    target_source = "30XW_tcm177-84440.pdf"
    print(f"Attempting to delete documents with source='{target_source}'...")
    
    # Check bounds before
    # Chroma get is limited but we can just count
    try:
        kb.collection.delete(where={"source": target_source})
        print("Deletion command sent.")
    except Exception as e:
        print(f"Error deleting: {e}")

    # Verify
    results = kb.collection.get(where={"source": target_source})
    count = len(results['ids']) if results and 'ids' in results else 0
    print(f"Remaining documents for {target_source}: {count}")

if __name__ == "__main__":
    reset_kb()
