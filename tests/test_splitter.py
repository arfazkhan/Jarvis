
import sys
import os
sys.path.insert(0, os.getcwd())
from agent_home.voice.vibevoice_engine import SentenceSplitter

def test_splitter():
    splitter = SentenceSplitter()
    
    print("Test 1: Simple chunks")
    chunks = ["Hello world.", " How are ", "you? I am fine."]
    expected = ["Hello world.", "How are you?", "I am fine."]
    
    results = []
    print(f"Input chunks: {chunks}")
    for chunk in chunks:
        for s in splitter.feed(chunk):
            results.append(s)
    
    for s in splitter.flush():
        results.append(s)
        
    print(f"Results: {results}")
    assert results == expected, f"Expected {expected}, got {results}"
    print("✅ Test 1 Passed")

    print("\nTest 2: Abbreviations")
    splitter = SentenceSplitter()
    chunks = ["Dr. Smith went to the ", "hospital. He is ok."]
    expected = ["Dr. Smith went to the hospital.", "He is ok."]
    
    results = []
    for chunk in chunks:
        for s in splitter.feed(chunk):
            results.append(s)
    for s in splitter.flush():
        results.append(s)
        
    print(f"Results: {results}")
    assert results == expected, f"Expected {expected}, got {results}"
    print("✅ Test 2 Passed")

if __name__ == "__main__":
    test_splitter()
