import pytest
import sys
import os
import time
from datetime import datetime

def run_tests():
    """
    Run the comprehensive test suite for the Home Automation Agent.
    Includes core components and all new phases (13-19).
    """
    print("🚀 Starting Comprehensive System Verification...")
    print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run all tests in the tests/ directory
    # -v: verbose
    # --tb=short: shorter traceback
    # -p no:warnings: suppress warnings to keep output clean
    args = ["-v", "--tb=short", "-p", "no:warnings", "tests/"]
    
    print(f"🧪 Running ALL tests in tests/ directory...")
    result = pytest.main(args)
    
    print("\n" + "="*50)
    if result == 0:
        print("✅ ALL SYSTEMS GO! Comprehensive verification passed.")
    else:
        print("❌ SYSTEM VERIFICATION FAILED. Please check the logs above.")
    print("="*50)
    
    return result

if __name__ == "__main__":
    sys.exit(run_tests())
