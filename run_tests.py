import pytest
import sys

# Redirect stdout/stderr to a file
with open("test_result.txt", "w", encoding="utf-8") as f:
    sys.stdout = f
    sys.stderr = f
    
    # Run tests
    exit_code = pytest.main(["tests/test_core_complete.py", "tests/test_llm_resilience.py", "-v"])
    
    print(f"\nExit Code: {exit_code}")
