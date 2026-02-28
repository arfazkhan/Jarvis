
import sys
from pathlib import Path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("Attempting to import OmegaTestRunner...")
try:
    from tests.omega_stress_test.omega_test_runner import OmegaTestRunner
    print("Successfully imported OmegaTestRunner.")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
