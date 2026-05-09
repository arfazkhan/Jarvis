import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mocks import MockGSASReporter
import inspect

sig = inspect.signature(MockGSASReporter.__init__)
print(f"MockGSASReporter.__init__ signature: {sig}")
