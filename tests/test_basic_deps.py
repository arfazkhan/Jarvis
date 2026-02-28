
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import time
print("Importing numpy...")
start = time.time()
import numpy as np
print(f"Numpy imported in {time.time() - start:.2f}s")

print("Importing pandas...")
start = time.time()
import pandas as pd
print(f"Pandas imported in {time.time() - start:.2f}s")

try:
    print("Importing agent_unified.llm...")
    start = time.time()
    from agent_unified.llm import UnifiedLLM
    print(f"UnifiedLLM imported in {time.time() - start:.2f}s")
except ImportError:
    print("UnifiedLLM not available")
except Exception as e:
    print(f"UnifiedLLM import failed with: {e}")
