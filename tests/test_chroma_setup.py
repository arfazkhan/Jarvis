"""
Test ChromaDB Setup for PreferenceStore
"""
import sys
import os
import logging

# Configure logging to see info/debug
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, ".")

from agent.memory.preference_store import PreferenceStore

def test_chroma():
    print("-" * 50)
    print("Testing PreferenceStore ChromaDB Initialization")
    print("-" * 50)
    
    persist_dir = "./data/test_chroma_db"
    
    try:
        # Initialize store
        store = PreferenceStore(persist_dir=persist_dir)
        
        # Check internals
        if store._client:
            print("✅ ChromaDB Client initialized")
        else:
            print("❌ ChromaDB Client is None")
            
        if store._collection:
            print(f"✅ ChromaDB Collection initialized (Count: {store._collection.count()})")
        else:
            print("❌ ChromaDB Collection is None")
            
        if store._fallback_mode:
            print("⚠️ Store is in FALLBACK MODE (JSON)")
        else:
            print("🎉 Store is in CHROMA MODE (Vector DB)")
            
        # Test add/search (Verify embeddings work)
        print("\nTesting Semantic Search...")
        store.add("I like blue light", key="test_pref", context="test")
        
        # Search with semantic query
        results = store.search("what color light do I like?", limit=1)
        
        if results:
            print(f"✅ Search found: {results[0]['content']} (Score: {results[0]['score']:.4f})")
        else:
            print("❌ Search returned no results")
            
    except Exception as e:
        print(f"❌ Exception during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_chroma()
