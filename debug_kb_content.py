
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agent_advisory.knowledge_base import TechnicalKnowledgeBase

def debug_kb():
    kb = TechnicalKnowledgeBase()
    print(f"Listing all sources in KB...")
    
    # Get all metadata
    all_data = kb.collection.get()
    if not all_data or not all_data['metadatas']:
        print("KB is empty.")
        return

    sources = set()
    for m in all_data['metadatas']:
        if m and 'source' in m:
            sources.add(m['source'])
            
    print(f"Unique sources found: {sources}")
    
    # If target exists, try fetching
    target_source = "30XW_tcm177-84440.pdf"
    # Try finding close match
    match = None
    for s in sources:
        if target_source in s:
            match = s
            break
            
    if match:
        print(f"\nFetching documents for match='{match}'...")
        results = kb.collection.get(where={"source": match})
        
        print(f"Found {len(results['documents'])} documents.")
        
        for i, doc in enumerate(results['documents']):
            meta = results['metadatas'][i]
            content = doc
            
            # Check for page 6
            if "Page 6" in content or "page 6" in content.lower():
                print(f"\n--- Document {i} (Page 6 Candidate) ---")
                print(f"Metadata: {meta}")
                print(f"Has <table_data>: {'<table_data' in content}")
                print(f"Content Preview: {content[:500]}...")
                if '<table_data' in content:
                    print(f"Table Tag: {content[content.find('<table_data'):content.find('>', content.find('<table_data'))+1]}")
                else:
                    print(f"WARNING: No <table_data> tag found in this chunk. Content len: {len(content)}")
    else:
        print(f"Target {target_source} not found in sources.")

if __name__ == "__main__":
    debug_kb()
